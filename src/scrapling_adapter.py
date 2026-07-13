"""
Scrapling 适配层 — 统一抓取接口 + 自动降级策略。

封装 Scrapling 三层抓取器（Fetcher / StealthyFetcher / DynamicFetcher），
对外暴露统一的 fetch_page() 接口，所有平台 scraper 共用此模块。

策略：
    - fetcher_first（默认）：Fetcher 优先，被拦截自动降级 StealthyFetcher
    - stealth_only：直接用 StealthyFetcher（用于 1688 等强反爬站点）
    - dynamic_only：用 DynamicFetcher（JS 渲染页面）

使用方式：
    from src.scrapling_adapter import fetch_page
    response = fetch_page("https://example.com")
    titles = response.css("h1")
"""

from __future__ import annotations

import os
import sys
import subprocess
from typing import Optional

from .utils import is_blocked, get_logger

_logger = get_logger(__name__)


# ============================================================
# 配置
# ============================================================

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ADAPTIVE_DB = os.path.join(_PROJECT_ROOT, "data", "adaptive_elements.db")


# ============================================================
# 浏览器自动安装（Streamlit Cloud 首次启动引导）
# ============================================================

def _patchright_chromium_ready() -> bool:
    """
    精确检测 patchright 期望版本的 chromium 可执行文件是否真实存在。

    patchright 与 playwright 版本号不同（如 patchright 要 chromium-1217，
    playwright 可能装了 chromium-1223），只看缓存目录任意 chromium-* 会误判。
    这里取 patchright 自己的 executable_path 并验证文件存在。
    """
    try:
        from patchright.sync_api import sync_playwright
        p = sync_playwright().start()
        try:
            exe = p.chromium.executable_path
        finally:
            p.stop()
        return bool(exe) and os.path.exists(exe)
    except Exception as e:
        return False


def ensure_browser_installed() -> bool:
    """
    确保 patchright chromium 已安装。

    Streamlit Cloud 默认不装 patchright 的浏览器（packages.txt 的 apt chromium 无效），
    首次启动时自动 `python -m patchright install chromium`，并用标记文件避免重复安装。

    Returns:
        True 表示浏览器已就绪（已安装或本次安装成功）
    """
    marker = os.path.join(_PROJECT_ROOT, "data", ".patchright_browser_ok")

    # 快速路径：标记存在则跳过
    if os.path.exists(marker):
        return True

    # 精确检查：patchright 期望的 chromium 可执行文件是否真实存在
    # （不能用"任意 chromium-* 目录"判断——playwright 和 patchright 版本号不同，
    #   如 playwright 装了 chromium-1223 但 patchright 要 chromium-1217，会误判）
    if _patchright_chromium_ready():
        try:
            os.makedirs(os.path.dirname(marker), exist_ok=True)
            with open(marker, "w", encoding="utf-8") as f:
                f.write("ok")
        except Exception as e:
            pass
        return True

    # 未安装或版本不匹配 → best-effort 安装（下载 ~150MB，可能耗时 1-2 分钟）
    _logger.info("[bootstrap] patchright chromium 缺失或版本不匹配，正在安装 …")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "patchright", "install", "chromium"],
            capture_output=True, timeout=180, text=True,
        )
        if result.returncode == 0:
            try:
                os.makedirs(os.path.dirname(marker), exist_ok=True)
                with open(marker, "w", encoding="utf-8") as f:
                    f.write("ok")
            except Exception as e:
                pass
            _logger.info("[bootstrap] chromium 安装完成")
            return True
        _logger.error(f"[bootstrap] chromium 安装失败 rc={result.returncode}: {result.stderr[:200]}")
        return False
    except Exception as e:
        _logger.info(f"[bootstrap] chromium 安装异常: {e}")
        return False


def _get_config() -> dict:
    """读取 Scrapling 配置。"""
    try:
        from .config import get_scrapling_config
        return get_scrapling_config()
    except (ImportError, AttributeError):
        return {
            "proxy": None,
            "browser_timeout": 30000,
            "adaptive_db": _ADAPTIVE_DB,
            "strategy": "fetcher_first",
        }


# ============================================================
# 核心接口
# ============================================================

def fetch_page(
    url: str,
    stealth: bool = False,
    adaptive: bool = True,
    proxy: Optional[str] = None,
    wait_selector: Optional[str] = None,
    wait_seconds: float = 5.0,
) -> object:
    """
    抓取页面，返回 Scrapling Response 对象。

    策略：stealth=False 时先用 Fetcher（快速），被拦截则自动升级 StealthyFetcher。
          stealth=True 时直接用 StealthyFetcher。

    Args:
        url:            目标 URL
        stealth:        是否直接使用 StealthyFetcher
        adaptive:       是否启用自适应元素追踪
        proxy:          代理地址（可选）
        wait_selector:  等待的 CSS 选择器（仅 StealthyFetcher 有效）
        wait_seconds:   等待秒数（仅 StealthyFetcher 有效）

    Returns:
        Scrapling Response 对象，支持 .css() / .xpath() / .text / .status

    Raises:
        RuntimeError: 所有抓取方式均失败时
    """
    cfg = _get_config()
    proxy = proxy or cfg.get("proxy")
    strategy = cfg.get("strategy", "fetcher_first")

    if stealth or strategy == "stealth_only":
        return _fetch_stealth(url, proxy=proxy, adaptive=adaptive,
                              wait_selector=wait_selector, wait_seconds=wait_seconds)

    if strategy == "dynamic_only":
        return _fetch_dynamic(url, proxy=proxy, wait_selector=wait_selector,
                              wait_seconds=wait_seconds)

    # fetcher_first 策略：先用 Fetcher，被拦截降级 StealthyFetcher
    return _fetch_with_fallback(url, proxy=proxy, adaptive=adaptive,
                                wait_selector=wait_selector, wait_seconds=wait_seconds)


def _fetch_with_fallback(
    url: str,
    proxy: Optional[str] = None,
    adaptive: bool = True,
    wait_selector: Optional[str] = None,
    wait_seconds: float = 5.0,
) -> object:
    """Fetcher 优先 + StealthyFetcher 兜底。浏览器缺失时回退重试 Fetcher。"""
    import time
    import random
    from scrapling import Fetcher

    def _try_fetcher():
        fetcher_args = {}
        if adaptive:
            fetcher_args["adaptive"] = True
        if proxy:
            fetcher_args["proxy"] = proxy
        f = Fetcher(**fetcher_args) if fetcher_args else Fetcher()
        resp = f.get(url)
        if resp.status == 200 and not is_blocked(str(resp.text)):
            return resp
        return None

    # 第一层：Fetcher（快速，curl_cffi TLS 指纹模拟）
    try:
        resp = _try_fetcher()
        if resp is not None:
            return resp
        _logger.warning("[scrapling] Fetcher 被拦截，降级到 StealthyFetcher")
    except Exception as e:
        _logger.warning(f"[scrapling] Fetcher 失败: {e}，降级到 StealthyFetcher")

    # 第二层：StealthyFetcher（Patchright 反检测浏览器）
    # 触发前确保浏览器已安装（首次会自动下载，标记文件避免重复）
    ensure_browser_installed()
    try:
        return _fetch_stealth(url, proxy=proxy, adaptive=adaptive,
                              wait_selector=wait_selector, wait_seconds=wait_seconds)
    except RuntimeError as e:
        # 浏览器仍未安装（自动安装失败）→ 回退重试 Fetcher 几次（Amazon 拦截常是临时的）
        if "浏览器未安装" in str(e) or "Executable doesn't exist" in str(e):
            _logger.error("[scrapling] 浏览器仍不可用，回退重试 Fetcher（间隔退避）…")
            last_err = e
            for attempt in range(3):
                time.sleep(random.uniform(3.0, 6.0))
                try:
                    resp = _try_fetcher()
                    if resp is not None:
                        return resp
                    _logger.warning(f"[scrapling] Fetcher 重试 {attempt+1}/3 仍被拦截")
                except Exception as retry_err:
                    last_err = retry_err
                    _logger.info(f"[scrapling] Fetcher 重试 {attempt+1}/3 异常: {retry_err}")
            raise RuntimeError(
                "抓取失败：Fetcher 被 Amazon 拦截，且浏览器组件不可用无法降级。"
                "请稍后重试（浏览器可能正在后台安装）。"
            ) from last_err
        raise


def _fetch_stealth(
    url: str,
    proxy: Optional[str] = None,
    adaptive: bool = True,
    wait_selector: Optional[str] = None,
    wait_seconds: float = 5.0,
) -> object:
    """使用 StealthyFetcher 抓取。"""
    try:
        from scrapling import StealthyFetcher
    except ImportError as e:
        raise RuntimeError(f"StealthyFetcher 不可用: {e}")

    fetcher_args = {}
    if adaptive:
        fetcher_args["adaptive"] = True
    if proxy:
        fetcher_args["proxy"] = proxy

    f = StealthyFetcher(**fetcher_args) if fetcher_args else StealthyFetcher()

    extra_args = {}
    if wait_selector:
        extra_args["wait_selector"] = wait_selector
    if wait_seconds:
        extra_args["wait_seconds"] = wait_seconds

    try:
        resp = f.fetch(url, **extra_args)
        return resp
    except Exception as e:
        # 浏览器未安装等环境问题，给出明确提示而非原始栈
        err_msg = str(e)
        if "Executable doesn't exist" in err_msg or "install" in err_msg.lower():
            raise RuntimeError(
                "StealthyFetcher 浏览器未安装。请运行: patchright install 或 python -m playwright install chromium"
            ) from e
        raise


def _fetch_dynamic(
    url: str,
    proxy: Optional[str] = None,
    wait_selector: Optional[str] = None,
    wait_seconds: float = 5.0,
) -> object:
    """使用 DynamicFetcher 抓取。"""
    from scrapling import DynamicFetcher

    fetcher_args = {}
    if proxy:
        fetcher_args["proxy"] = proxy

    f = DynamicFetcher(**fetcher_args) if fetcher_args else DynamicFetcher()

    extra_args = {}
    if wait_selector:
        extra_args["wait_selector"] = wait_selector
    if wait_seconds:
        extra_args["wait_seconds"] = wait_seconds

    resp = f.fetch(url, **extra_args)
    return resp
