"""
工具函数模块 - 提供通用辅助功能。

包含多个模块共享的常量和函数：
- User-Agent 池
- 反爬检测关键词和函数
- 价格/评分/评论数解析
- JSON 缓存读写（供各 scraper 模块共用）
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional


# ============================================================
# 真实浏览器 User-Agent 池（模拟 Chrome / Firefox / Edge）
# ============================================================


# ============================================================
# 日志配置 — 统一 logger，各模块通过 get_logger() 获取
# ============================================================

def get_logger(name: str = "scout") -> logging.Logger:
    """
    获取统一配置的 logger。

    首次调用时配置 root logger（控制台输出，INFO 级别），
    后续调用返回带模块前缀的子 logger。
    """
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    return logging.getLogger(name)


USER_AGENTS = [
    # Chrome 125 on Windows 10
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    # Chrome 125 on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    # Firefox 126 on Windows 10
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) "
    "Gecko/20100101 Firefox/126.0",
    # Edge 125 on Windows 10
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
]

# ============================================================
# 反爬检测关键词（合并 Best Sellers + 搜索两种场景）
# ============================================================

BLOCK_PATTERNS = [
    # 通用检测
    "captcha",
    "automated access",
    "blocked",
    "robot check",
    "are you a human",
    # Amazon 精确匹配
    "Type the characters you see",
    "Enter the characters you see",
    "Sorry, we just need to make sure you're not a robot",
    "To discuss automated access to Amazon data",
    "api-services-support@amazon.com",
    "<title>Robot Check</title>",
    "<title>503 - Service Not Available</title>",
    # 中文
    "请输入图中的字符",
]


def is_blocked(html: str) -> bool:
    """检测返回页面是否为验证码/拦截页。"""
    html_lower = html.lower()
    return any(pat.lower() in html_lower for pat in BLOCK_PATTERNS)

# ============================================================
# 类型安全转换
# ============================================================

def safe_float(value, default: float = 0.0) -> float:
    """
    安全转换为 float，失败时返回默认值。

    统一替代各模块中重复的 _safe_float 实现。
    None / 空字符串 / 非数字均返回 default。
    """
    try:
        return float(value) if value is not None else default
    except (ValueError, TypeError):
        return default


def safe_int(value, default: int = 0) -> int:
    """安全转换为 int，失败时返回默认值。"""
    try:
        return int(value) if value is not None else default
    except (ValueError, TypeError):
        return default



# ============================================================
# 货币解析
# ============================================================

# 货币→USD 换算率（基于 2026 年 5 月汇率）
_CURRENCY_TO_USD = {
    "USD": 1.0, "$": 1.0,
    "HKD": 1 / 7.83, "HK$": 1 / 7.83,
    "SGD": 1 / 1.34, "S$": 1 / 1.34,
    "CNY": 1 / 7.24, "¥": 1 / 7.24, "RMB": 1 / 7.24,
    "EUR": 1.08, "€": 1.08,
    "GBP": 1.27, "£": 1.27,
    "AUD": 0.65, "A$": 0.65,
    "JPY": 1 / 150.0, "JPY\xa0": 1 / 150.0,
}


def parse_price(text: str) -> Optional[float]:
    """
    从价格文本中提取 USD 金额。

    支持常见货币符号自动换算为 USD：USD, HKD, SGD, CNY, EUR, GBP, AUD, JPY。
    """
    if not text:
        return None
    text = text.strip()

    # 检测货币代码（长匹配优先，如 HK$ 优先于 $）
    matched_currency = None
    for code in sorted(_CURRENCY_TO_USD, key=len, reverse=True):
        if text.startswith(code) or f" {code}" in text:
            matched_currency = code
            break

    rate = _CURRENCY_TO_USD.get(matched_currency, 1.0)

    # 提取数字
    match = re.search(r'[\d,]+\.?\d*', text)
    if match:
        value = float(match.group().replace(',', ''))
        return round(value * rate, 2)
    return None


def parse_rating(text: str) -> Optional[float]:
    """从评分文本中提取浮点数，如 '4.5 out of 5 stars' → 4.5。"""
    if not text:
        return None
    match = re.search(r'(\d+\.?\d*)', text)
    if match:
        return float(match.group(1))
    return None


def parse_review_count(text: str) -> int:
    """从评论数文本中提取整数，如 '12,345' → 12345。"""
    if not text:
        return 0
    cleaned = re.sub(r'[^\d,]', '', text)
    if cleaned:
        return int(cleaned.replace(',', ''))
    return 0


# ============================================================
# 通用格式化
# ============================================================


def format_number(num: int) -> str:
    """将大数字格式化为易读形式，如 12345 -> "12.3k"。"""
    if num >= 1_000_000:
        return f"{num / 1_000_000:.1f}M"
    if num >= 1_000:
        return f"{num / 1_000:.1f}k"
    return str(num)


# ============================================================
# JSON 缓存读写（供各 scraper 模块共用）
# ============================================================

def load_json_cache(
    cache_file: str,
    max_age_seconds: Optional[int] = None,
) -> Optional[list[dict]]:
    """
    读取本地 JSON 缓存文件。

    Args:
        cache_file:       缓存文件完整路径
        max_age_seconds:  最大有效期（秒），None 表示永不过期

    Returns:
        缓存的产品列表，无效/过期/不存在时返回 None
    """
    try:
        if not os.path.exists(cache_file):
            return None
        if max_age_seconds is not None:
            mtime = os.path.getmtime(cache_file)
            if __import__("time").time() - mtime > max_age_seconds:
                return None
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list) and len(data) > 0:
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return None


def save_json_cache(products: list[dict], cache_file: str) -> None:
    """将产品数据保存为本地 JSON 缓存。"""
    os.makedirs(os.path.dirname(cache_file), exist_ok=True)
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)


def get_cache_timestamp(cache_file: str) -> Optional[str]:
    """获取缓存文件的最后修改时间，格式化为可读字符串。"""
    try:
        if os.path.exists(cache_file):
            mtime = os.path.getmtime(cache_file)
            dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
            return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except OSError:
        pass
    return None


def deduplicate_products(products: list[dict]) -> list[dict]:
    """
    按 ASIN 去重，保留评分最高的变体。

    同一产品可能因不同变体（颜色/尺寸）在搜索结果中出现多次，
    去重后仅保留评分最高的变体，节省 AI 分析配额。

    Args:
        products: 产品字典列表（需包含 asin 和 rating 字段）

    Returns:
        去重后的产品列表
    """
    seen = {}  # asin → (product, rating)
    no_asin = []

    for p in products:
        asin = (p.get("asin") or "").strip()
        if not asin:
            no_asin.append(p)
            continue
        try:
            rating = float(p.get("rating", 0) or 0)
        except (ValueError, TypeError):
            rating = 0.0
        if asin not in seen or rating > seen[asin][1]:
            seen[asin] = (p, rating)

    result = [v[0] for v in seen.values()]
    result.extend(no_asin)
    return result
