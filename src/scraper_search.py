"""
Amazon 关键词搜索抓取模块 — 指定选品功能的核心数据源。

用户提供关键词 → 抓取 Amazon 搜索结果页 → 返回 Top N 产品列表。

抓取策略：
    - 复用 utils.py 的 User-Agent 池和解析函数
    - 搜索结果页 CSS 选择器与 Best Sellers 页不同，单独维护
    - 请求间隔 2-4 秒随机延迟
    - 检测 503/验证码返回失败，不使用 Mock 数据

输出字段：
    title, price, rating, num_reviews, rank, url, asin, category
"""

from __future__ import annotations

import re
import random
import time
from datetime import datetime, timezone
from typing import Optional

import requests
from bs4 import BeautifulSoup

from .utils import USER_AGENTS, is_blocked, parse_price, parse_rating, parse_review_count


# 地区域名映射
_REGION_DOMAINS = {
    "us": "amazon.com",
    "uk": "amazon.co.uk",
    "jp": "amazon.co.jp",
    "de": "amazon.de",
}


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
            price = parse_price(text)
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
            rating = parse_rating(elem.get_text(strip=True))
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
            count = parse_review_count(text)
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

def _scrape_amazon_search(keyword: str, max_results: int = 20, region: str = "us") -> list[dict]:
    """
    真实抓取 Amazon 搜索结果页。

    Args:
        keyword:     搜索关键词
        max_results: 最多返回产品数
        region:      地区代码（us/uk/jp/de）

    Returns:
        解析后的产品列表

    Raises:
        requests.RequestException: 网络错误
        RuntimeError: 被反爬拦截
    """
    encoded_kw = keyword.replace(" ", "+")
    domain = _REGION_DOMAINS.get(region, "amazon.com")
    url = f"https://www.{domain}/s?k={encoded_kw}"

    headers = {
        "User-Agent": random.choice(USER_AGENTS),
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
    if is_blocked(resp.text):
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

def search_amazon(keyword: str, max_results: int = 20, region: str = "us") -> dict:
    """
    在 Amazon 搜索指定关键词，返回产品列表。

    Args:
        keyword:     搜索关键词（英文，如 "portable blender"）
        max_results: 最多返回产品数，默认 20
        region:      地区代码（us/uk/jp/de），默认 "us"

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
        products = _scrape_amazon_search(keyword, max_results, region=region)
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
