"""
AliExpress 数据抓取模块 — 速卖通热销产品抓取 + 本地缓存。

三层数据获取策略（按优先级）：
    1. Selenium + undetected-chromedriver（主要方案）
    2. requests + BeautifulSoup（快速尝试）
    3. 本地缓存（兜底）

抓取策略：
    - 使用 Selenium 绕过 SPA 反爬
    - 自动检测 Chrome 版本
    - 模拟真实浏览器行为（滚动、等待）
    - 24 小时本地缓存

输出字段：
    title, price, rating, num_reviews, url, image, category
"""

from __future__ import annotations

import json
import os
import re
import time
import random
from datetime import datetime, timezone
from typing import Optional

import requests
from bs4 import BeautifulSoup

from .utils import USER_AGENTS, is_blocked, parse_price, parse_rating

# ============================================================
# 缓存配置
# ============================================================

_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "cache",
)
_CACHE_TTL = 24 * 60 * 60  # 24 小时

# 地区域名映射
_REGION_DOMAINS = {
    "us": "aliexpress.com",
    "eu": "aliexpress.com",
    "ru": "aliexpress.ru",
}


def _get_cache_file(prefix: str, region: str) -> str:
    """返回按地区区分的缓存文件路径。"""
    return os.path.join(_CACHE_DIR, f"aliexpress_{prefix}_{region}.json")


# ============================================================
# 缓存读写
# ============================================================

def _load_cache(prefix: str, region: str) -> Optional[list[dict]]:
    """读取本地缓存的 JSON 数据。"""
    cache_file = _get_cache_file(prefix, region)
    try:
        if os.path.exists(cache_file):
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and len(data) > 0:
                mtime = os.path.getmtime(cache_file)
                if time.time() - mtime < _CACHE_TTL:
                    return data
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _save_cache(products: list[dict], prefix: str, region: str) -> None:
    """将抓取结果保存为本地 JSON 缓存。"""
    os.makedirs(_CACHE_DIR, exist_ok=True)
    cache_file = _get_cache_file(prefix, region)
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)


def _get_cache_timestamp(prefix: str, region: str) -> Optional[str]:
    """获取缓存文件的最后修改时间。"""
    cache_file = _get_cache_file(prefix, region)
    try:
        if os.path.exists(cache_file):
            mtime = os.path.getmtime(cache_file)
            dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
            return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except OSError:
        pass
    return None


# ============================================================
# Selenium 抓取
# ============================================================

def _scrape_via_selenium(url: str, wait_seconds: float = 10.0) -> Optional[BeautifulSoup]:
    """
    使用 Selenium 获取页面内容。

    Args:
        url:           目标 URL
        wait_seconds:  页面加载后等待秒数

    Returns:
        BeautifulSoup 对象，失败返回 None
    """
    try:
        from .selenium_helper import fetch_page_soup
        return fetch_page_soup(url, wait_seconds)
    except Exception as e:
        print(f"[scraper_aliexpress] Selenium 抓取失败: {e}")
        return None


# ============================================================
# 产品解析
# ============================================================

# 多层选择器（适应页面结构变化）
_CARD_SELECTORS = [
    "div[class*='SearchProductFeed'] div[class*='item']",
    "div[class*='product-card']",
    "div[class*='item-card']",
    "a[href*='/item/']",
    "div[data-widget-cid]",
    "div[class*='list--gallery'] > div",
]

_TITLE_SELECTORS = [
    "h1[class*='title']",
    "div[class*='title']",
    "a[href*='/item/'] h1",
    "span[class*='title']",
    "div[class*='ProductTitle']",
]

_PRICE_SELECTORS = [
    "div[class*='price'] span",
    "span[class*='price-current']",
    "div[class*='Price'] span",
    "span[class*='Price']",
]


def _extract_title(card) -> str:
    """从产品卡片中提取标题。"""
    for sel in _TITLE_SELECTORS:
        elem = card.select_one(sel)
        if elem:
            text = elem.get_text(strip=True)
            if text and len(text) > 3:
                return text
    # 兜底：img alt
    img = card.select_one("img")
    if img:
        alt = img.get("alt", "").strip()
        if alt and len(alt) > 3:
            return alt
    return ""


def _extract_price(card) -> Optional[float]:
    """从产品卡片中提取价格。"""
    for sel in _PRICE_SELECTORS:
        elem = card.select_one(sel)
        if elem:
            text = elem.get_text(strip=True)
            price = parse_price(text)
            if price and price > 0:
                return price
    # 从整个卡片文本提取价格
    card_text = card.get_text(strip=True)
    price_match = re.search(r'\$[\d,.]+', card_text)
    if price_match:
        try:
            return float(price_match.group(0).replace('$', '').replace(',', ''))
        except ValueError:
            pass
    return None


def _extract_rating(card) -> Optional[float]:
    """提取评分。"""
    rating_elem = card.select_one("span[class*='rating']") or card.select_one("div[class*='star']")
    if rating_elem:
        text = rating_elem.get_text(strip=True)
        rating = parse_rating(text)
        if rating and rating > 0:
            return rating
    return None


def _extract_reviews(card) -> int:
    """提取评论数。"""
    review_elem = card.select_one("span[class*='review']") or card.select_one("span[class*='sold']")
    if review_elem:
        text = review_elem.get_text(strip=True)
        nums = re.findall(r'[\d,]+', text)
        if nums:
            try:
                return int(nums[0].replace(',', ''))
            except ValueError:
                pass
    return 0


def _extract_url(card) -> str:
    """提取产品链接。"""
    link = card.select_one("a[href*='/item/']") or card.select_one("a[href]")
    if link:
        href = link.get("href", "")
        if href:
            if href.startswith("//"):
                href = "https:" + href
            elif href.startswith("/"):
                href = "https://www.aliexpress.com" + href
            return href
    return ""


def _extract_image(card) -> str:
    """提取图片 URL。"""
    img = card.select_one("img[src*='alicdn']") or card.select_one("img")
    if img:
        src = img.get("src", "") or img.get("data-src", "")
        if src:
            if src.startswith("//"):
                src = "https:" + src
            return src
    return ""


def _parse_product_card(card, rank: int) -> Optional[dict]:
    """解析单个产品卡片，返回标准产品字典。"""
    title = _extract_title(card)
    if not title:
        return None

    price = _extract_price(card)
    if not price or price <= 0:
        return None

    return {
        "title": title,
        "price": price,
        "rating": _extract_rating(card),
        "num_reviews": _extract_reviews(card),
        "rank": rank,
        "url": _extract_url(card),
        "image": _extract_image(card),
        "category": "best_sellers",
    }


# ============================================================
# 页面抓取
# ============================================================

def _scrape_aliexpress_best_sellers(region: str = "us") -> list[dict]:
    """
    抓取 AliExpress 热销产品。

    策略：
    1. 使用 Selenium 访问热销页面
    2. 等待页面加载（8-12 秒）
    3. 滚动页面触发懒加载
    4. 提取产品卡片数据
    """
    domain = _REGION_DOMAINS.get(region, "aliexpress.com")

    urls_to_try = [
        f"https://www.{domain}/popular/best-sellers.html",
        f"https://www.{domain}/popular/top-selling.html",
        f"https://www.{domain}/category/0/best-sellers.html",
    ]

    for url in urls_to_try:
        print(f"[scraper_aliexpress] 尝试 URL: {url}")
        soup = _scrape_via_selenium(url, wait_seconds=12)
        if not soup:
            continue

        # 检查是否是有效页面
        page_text = soup.get_text().lower()
        if "404" in page_text[:500] or "captcha" in page_text[:1000]:
            print(f"[scraper_aliexpress] 页面无效（404或验证码）")
            continue

        # 尝试多种选择器
        cards = []
        for sel in _CARD_SELECTORS:
            cards = soup.select(sel)
            if cards and len(cards) >= 3:
                break

        if cards:
            print(f"[scraper_aliexpress] 找到 {len(cards)} 个产品卡片")
            products = []
            for i, card in enumerate(cards[:50], 1):
                product = _parse_product_card(card, i)
                if product:
                    products.append(product)
            if products:
                return products

    # 最终降级：搜索 URL
    search_url = f"https://www.{domain}/w/wholesale-best-selling.html?SortType=total_orders"
    print(f"[scraper_aliexpress] 降级到搜索 URL: {search_url}")
    soup = _scrape_via_selenium(search_url, wait_seconds=12)
    if soup:
        cards = []
        for sel in _CARD_SELECTORS:
            cards = soup.select(sel)
            if cards:
                break
        if cards:
            products = []
            for i, card in enumerate(cards[:50], 1):
                product = _parse_product_card(card, i)
                if product:
                    products.append(product)
            if products:
                return products

    return []


def _scrape_aliexpress_search(keyword: str, region: str = "us", max_results: int = 20) -> list[dict]:
    """
    搜索 AliExpress 产品。

    URL 模式：
    - https://www.aliexpress.com/w/wholesale-{keyword}.html
    - 支持排序参数：SortType=total_orders（按销量）
    """
    domain = _REGION_DOMAINS.get(region, "aliexpress.com")
    encoded_kw = keyword.replace(" ", "+")
    url = f"https://www.{domain}/w/wholesale-{encoded_kw}.html?SortType=total_orders"

    print(f"[scraper_aliexpress] 搜索: {url}")
    soup = _scrape_via_selenium(url, wait_seconds=12)
    if not soup:
        return []

    # 检查是否被拦截
    page_text = soup.get_text().lower()
    if "captcha" in page_text[:1000]:
        print("[scraper_aliexpress] 搜索被验证码拦截")
        return []

    cards = []
    for sel in _CARD_SELECTORS:
        cards = soup.select(sel)
        if cards:
            break

    print(f"[scraper_aliexpress] 搜索找到 {len(cards)} 个结果")

    products = []
    for i, card in enumerate(cards[:max_results], 1):
        product = _parse_product_card(card, i)
        if product:
            products.append(product)

    return products


# ============================================================
# 公开接口
# ============================================================

def fetch_aliexpress_best_sellers(region: str = "us") -> tuple[list[dict], dict]:
    """
    获取 AliExpress 热销产品列表（三层降级策略）。

    Args:
        region: 地区代码（us/eu/ru），默认 "us"

    Returns:
        (products, source_info) 元组
    """
    # ---------- 第一层：Selenium 抓取 ----------
    try:
        products = _scrape_aliexpress_best_sellers(region=region)
        if len(products) >= 3:
            _save_cache(products, "best_sellers", region)
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            return products, {"source": "live", "timestamp": timestamp}
        else:
            print(f"[!] AliExpress 实时抓取仅获得 {len(products)} 个产品，降级到缓存")
    except Exception as e:
        print(f"[!] AliExpress 实时抓取失败: {e}")

    # ---------- 第二层：本地缓存 ----------
    cached = _load_cache("best_sellers", region)
    if cached and len(cached) >= 3:
        cache_ts = _get_cache_timestamp("best_sellers", region)
        print(f"[*] 使用 AliExpress 本地缓存 ({len(cached)} 个产品)")
        return cached, {"source": "cache", "timestamp": cache_ts or "unknown"}

    # ---------- 均不可用 ----------
    print("[X] AliExpress 实时抓取和本地缓存均不可用")
    return [], {
        "source": "unavailable",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "error": "AliExpress 实时抓取和本地缓存均不可用。请确保已安装 Chrome 浏览器。",
    }


def search_aliexpress(keyword: str, region: str = "us", max_results: int = 20) -> dict:
    """
    在 AliExpress 搜索指定关键词，返回产品列表。
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
        products = _scrape_aliexpress_search(keyword, region=region, max_results=max_results)
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
            "error": f"网络请求失败: {e}",
        }
    except RuntimeError as e:
        return {
            "success": False,
            "keyword": keyword,
            "results": [],
            "total_found": 0,
            "source": "none",
            "scrape_time": scrape_time,
            "error": f"AliExpress 反爬拦截: {e}",
        }
    except Exception as e:
        return {
            "success": False,
            "keyword": keyword,
            "results": [],
            "total_found": 0,
            "source": "none",
            "scrape_time": scrape_time,
            "error": f"搜索失败: {e}",
        }
