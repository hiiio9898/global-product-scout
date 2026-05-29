"""
工具函数模块 - 提供通用辅助功能。

包含多个模块共享的常量和函数：
- User-Agent 池
- 反爬检测关键词和函数
- 价格/评分/评论数解析
"""

import re
from typing import Optional


# ============================================================
# 真实浏览器 User-Agent 池（模拟 Chrome / Firefox / Edge）
# ============================================================

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
