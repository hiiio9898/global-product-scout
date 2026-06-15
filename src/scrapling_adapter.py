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
from typing import Optional

from .utils import is_blocked

# ============================================================
# 配置
# ============================================================

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ADAPTIVE_DB = os.path.join(_PROJECT_ROOT, "data", "adaptive_elements.db")


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
    """Fetcher 优先 + StealthyFetcher 兜底。"""
    # 第一层：Fetcher（快速，curl_cffi TLS 指纹模拟）
    try:
        from scrapling import Fetcher
        fetcher_args = {}
        if adaptive:
            fetcher_args["adaptive"] = True
        if proxy:
            fetcher_args["proxy"] = proxy

        f = Fetcher(**fetcher_args) if fetcher_args else Fetcher()
        resp = f.get(url)

        # 检查是否被拦截
        if resp.status == 200 and not is_blocked(str(resp.text)):
            return resp

        print(f"[scrapling] Fetcher 被拦截 (status={resp.status})，降级到 StealthyFetcher")
    except Exception as e:
        print(f"[scrapling] Fetcher 失败: {e}，降级到 StealthyFetcher")

    # 第二层：StealthyFetcher（Patchright 反检测浏览器）
    return _fetch_stealth(url, proxy=proxy, adaptive=adaptive,
                          wait_selector=wait_selector, wait_seconds=wait_seconds)


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
