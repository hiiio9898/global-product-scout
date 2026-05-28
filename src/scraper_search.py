"""
Amazon 关键词搜索抓取模块 — 指定选品功能的核心数据源。

用户提供关键词 → 抓取 Amazon 搜索结果页 → 返回 Top N 产品列表。

抓取策略：
    - 复用 scraper.py 的 User-Agent 池和请求头模板
    - 搜索结果页 CSS 选择器与 Best Sellers 页不同，单独维护
    - 请求间隔 2-4 秒随机延迟
    - 检测 503/验证码返回失败，不使用 Mock 数据

输出字段：
    title, price, rating, num_reviews, rank, url, asin, category
"""

import os
import re
import random
import time
from datetime import datetime, timezone
from typing import Optional

import requests
from bs4 import BeautifulSoup

# ============================================================
# User-Agent 池（与 scraper.py 保持一致）
# ============================================================

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) "
    "Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
]

# ============================================================
# 反爬检测关键词
# ============================================================

_BLOCK_PATTERNS = [
    "captcha",
    "robot",
    "automated access",
    "blocked",
    "请输入图中的字符",
    "Type the characters you see below",
]


def _is_blocked(html: str) -> bool:
    """检测返回页面是否为验证码/拦截页。"""
    html_lower = html.lower()
    return any(pat in html_lower for pat in _BLOCK_PATTERNS)


# ============================================================
# 货币解析（复用 scraper.py 逻辑）
# ============================================================

def _parse_price(text: str) -> Optional[float]:
    """从价格文本中提取 USD 金额，支持多币种换算。"""
    if not text:
        return None
    text = text.strip()

    CURRENCY_TO_USD = {
        "USD": 1.0, "$": 1.0,
        "HKD": 1 / 7.83, "HK$": 1 / 7.83,
        "SGD": 1 / 1.34, "S$": 1 / 1.34,
        "CNY": 1 / 7.24, "¥": 1 / 7.24, "RMB": 1 / 7.24,
        "EUR": 1.08, "€": 1.08,
        "GBP": 1.27, "£": 1.27,
    }

    matched_currency = None
    for code in sorted(CURRENCY_TO_USD, key=len, reverse=True):
        if text.startswith(code) or f" {code}" in text:
            matched_currency = code
            break

    rate = CURRENCY_TO_USD.get(matched_currency, 1.0)
    match = re.search(r'[\d,]+\.?\d*', text)
    if match:
        value = float(match.group().replace(',', ''))
        return round(value * rate, 2)
    return None


def _parse_rating(text: str) -> Optional[float]:
    """从评分文本中提取浮点数。"""
    if not text:
        return None
    match = re.search(r'(\d+\.?\d*)', text)
    if match:
        return float(match.group(1))
    return None


def _parse_review_count(text: str) -> int:
    """从评论数文本中提取整数。"""
    if not text:
        return 0
    cleaned = re.sub(r'[^\d,]', '', text)
    if cleaned:
        return int(cleaned.replace(',', ''))
    return 0


# ============================================================
# 搜索结果页解析（与 Best Sellers 页面结构不同）
# ============================================================

def _extract_search_title(card) -> str:
    """
    从 Amazon 搜索结果卡片中提取标题。

    搜索结果页结构（2026 年）：
        div[data-component-type="s-search-result"]
          └─ h2 a span                     ← 标准标题
          └─ h2 a                          ← 备选（直接取链接文本）
    """
    selectors = [
        'h2 a span',                           # 标准搜索结果标题
        'h2 a',                                # 备选：链接本身
        'a.a-link-normal span.a-size-base-plus',  # 通用中等标题
        'span[data-component-type="s-product-image"] img',  # 图片 alt
    ]
    for sel in selectors:
        elem = card.select_one(sel)
        if elem:
            # 特殊处理 img alt
            if elem.name == 'img':
                text = elem.get('alt', '').strip()
            else:
                text = elem.get_text(strip=True)
            if text and len(text) > 3:
                return text
    return ""


def _extract_search_price(card) -> Optional[float]:
    """
    从 Amazon 搜索结果卡片中提取价格。

    搜索结果页价格结构：
        span.a-price > span.a-offscreen  ← 隐藏文本 "$29.99"
        span.a-price[data-a-size="xl"]   ← 大号价格
    """
    selectors = [
        'span.a-price span.a-offscreen',       # 最可靠：隐藏文本
        '.a-price .a-offscreen',               # 变体
        'span.a-price:not([data-a-size]) span',  # 无尺寸属性的价格
        'span._cDEzb_p13n-sc-price_3mJ9Z',     # 动态类名
    ]
    for sel in selectors:
        elem = card.select_one(sel)
        if elem:
            text = elem.get_text(strip=True)
            price = _parse_price(text)
            if price and price > 0:
                return price
    return None


def _extract_search_rating(card) -> Optional[float]:
    """从搜索结果卡片中提取评分。"""
    selectors = [
        'i.a-icon-star-small span.a-icon-alt',
        '.a-icon-star .a-icon-alt',
        'span.a-icon-alt',
    ]
    for sel in selectors:
        elem = card.select_one(sel)
        if elem:
            rating = _parse_rating(elem.get_text(strip=True))
            if rating and 1.0 <= rating <= 5.0:
                return rating
    # 全文正则兜底
    card_text = card.get_text()
    m = re.search(r'(\d+\.?\d*)\s*(?:out\s+of\s+5|stars?)', card_text, re.I)
    if m:
        val = float(m.group(1))
        if 1.0 <= val <= 5.0:
            return val
    return None


def _extract_search_reviews(card) -> int:
    """从搜索结果卡片中提取评论数。"""
    # 搜索结果页中评论数通常在评分旁边的链接里
    selectors = [
        'a[href*="customerReviews"] span',
        'span.a-size-base.s-underline-text',
        'span.a-size-small',
    ]
    for sel in selectors:
        for elem in card.select(sel):
            text = elem.get_text(strip=True)
            if any(kw in text.lower() for kw in ('rating', 'stars', 'out of')):
                continue
            count = _parse_review_count(text)
            if count > 0:
                return count
    # 全文正则兜底
    card_text = card.get_text()
    m = re.search(r'([\d,]+)\s*(?:ratings?|reviews?)', card_text, re.I)
    if m:
        try:
            return int(m.group(1).replace(',', ''))
        except ValueError:
            pass
    return 0


def _extract_search_url(card) -> str:
    """从搜索结果卡片中提取产品详情页 URL。"""
    # 优先取标题链接
    link = card.select_one('h2 a')
    if link and link.get('href'):
        href = link['href']
        if href.startswith('/'):
            return f"https://www.amazon.com{href}"
        return href
    # 备选：取图片链接
    img_link = card.select_one('a.a-link-normal[href*="/dp/"]')
    if img_link and img_link.get('href'):
        href = img_link['href']
        if href.startswith('/'):
            return f"https://www.amazon.com{href}"
        return href
    return ""


def _extract_asin_from_url(url: str) -> str:
    """从 Amazon URL 中提取 ASIN 编号。"""
    m = re.search(r'/dp/([A-Z0-9]{10})', url)
    if m:
        return m.group(1)
    m = re.search(r'/gp/product/([A-Z0-9]{10})', url)
    if m:
        return m.group(1)
    return ""


def _parse_search_card(card, rank: int, keyword: str) -> Optional[dict]:
    """
    解析单个搜索结果卡片，返回产品 dict。
    找不到标题时返回 None。
    """
    title = _extract_search_title(card)
    if not title:
        return None

    url = _extract_search_url(card)
    asin = card.get("data-asin", "").strip()
    if not asin and url:
        asin = _extract_asin_from_url(url)

    price = _extract_search_price(card)
    rating = _extract_search_rating(card)
    num_reviews = _extract_search_reviews(card)

    return {
        "title": title,
        "asin": asin,
        "price": price if price is not None else 0.0,
        "rating": rating if rating is not None else 0.0,
        "num_reviews": num_reviews,
        "rank": rank,
        "url": url,
        "category": keyword,  # 搜索关键词作为类目标签
    }


# ============================================================
# 真实抓取引擎
# ============================================================

def _scrape_amazon_search(keyword: str, max_results: int = 20) -> list[dict]:
    """
    真实抓取 Amazon US 站搜索结果页。

    Args:
        keyword:     搜索关键词
        max_results: 最多返回产品数

    Returns:
        解析后的产品列表

    Raises:
        requests.RequestException: 网络错误
        RuntimeError: 被反爬拦截
    """
    encoded_kw = keyword.replace(" ", "+")
    url = f"https://www.amazon.com/s?k={encoded_kw}"

    headers = {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Cache-Control": "max-age=0",
    }

    session = requests.Session()
    session.headers.update(headers)

    # 随机延迟 2-4 秒
    delay = random.uniform(2.0, 4.0)
    time.sleep(delay)

    resp = session.get(url, timeout=30)
    print(f"[scraper_search] HTTP {resp.status_code} | URL: {url}")
    resp.raise_for_status()

    # 检测拦截
    if _is_blocked(resp.text):
        raise RuntimeError("被 Amazon 反爬拦截，收到验证码或登录页面")

    soup = BeautifulSoup(resp.text, "html.parser")

    # 搜索结果页产品卡片选择器
    card_selectors = [
        'div[data-component-type="s-search-result"]',   # 标准搜索结果
        'div[data-asin][data-component-type]',           # 带 ASIN 的通用卡片
        '.s-result-item[data-asin]',                     # 旧版搜索结果
    ]

    cards = []
    for sel in card_selectors:
        cards = soup.select(sel)
        if cards:
            break

    if not cards:
        # 可能页面结构变动或关键词无结果
        print(f"[scraper_search] 未找到产品卡片，尝试的选择器: {card_selectors}")
        return []

    # 解析每个卡片
    products = []
    rank = 1
    for card in cards:
        # 跳过广告卡片（通常没有 data-asin 或标记为广告）
        if not card.get("data-asin"):
            continue
        # 跳过 "Sponsored" 广告
        sponsored = card.select_one('span.puis-label-popover-default')
        if sponsored and 'Sponsored' in sponsored.get_text():
            continue

        product = _parse_search_card(card, rank, keyword)
        if product:
            products.append(product)
            rank += 1
            if rank > max_results:
                break

    return products


# ============================================================
# 公开 API
# ============================================================

def search_amazon(keyword: str, max_results: int = 20) -> dict:
    """
    在 Amazon US 站搜索指定关键词，返回产品列表。

    抓取失败时返回 success=False + 错误信息，不使用 Mock 数据。

    Args:
        keyword:     搜索关键词（英文，如 "portable blender"）
        max_results: 最多返回产品数，默认 20

    Returns:
        {
            "success": bool,
            "keyword": str,
            "results": list[dict],
            "total_found": int,
            "source": str,              # "live" | "none"
            "scrape_time": str,
            "error": str | None,
        }
    """
    keyword = keyword.strip()
    if not keyword:
        return {
            "success": False,
            "keyword": keyword,
            "results": [],
            "total_found": 0,
            "source": "none",
            "scrape_time": "",
            "error": "搜索关键词不能为空",
        }

    scrape_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    try:
        products = _scrape_amazon_search(keyword, max_results)
        if products:
            return {
                "success": True,
                "keyword": keyword,
                "results": products,
                "total_found": len(products),
                "source": "live",
                "scrape_time": scrape_time,
                "error": None,
            }
        else:
            return {
                "success": False,
                "keyword": keyword,
                "results": [],
                "total_found": 0,
                "source": "none",
                "scrape_time": scrape_time,
                "error": "未搜索到相关产品，请尝试更换关键词",
            }
    except requests.RequestException as e:
        return {
            "success": False,
            "keyword": keyword,
            "results": [],
            "total_found": 0,
            "source": "none",
            "scrape_time": scrape_time,
            "error": f"网络请求失败：{e}",
        }
    except RuntimeError as e:
        return {
            "success": False,
            "keyword": keyword,
            "results": [],
            "total_found": 0,
            "source": "none",
            "scrape_time": scrape_time,
            "error": f"Amazon 反爬拦截：{e}",
        }
    except Exception as e:
        return {
            "success": False,
            "keyword": keyword,
            "results": [],
            "total_found": 0,
            "source": "none",
            "scrape_time": scrape_time,
            "error": f"搜索失败：{e}",
        }
