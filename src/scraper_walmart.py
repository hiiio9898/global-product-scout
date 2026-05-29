"""
Walmart 数据抓取模块 — 沃尔玛热销产品抓取 + 本地缓存。

两层数据获取策略（按优先级）：
    1. 实时抓取 — requests + BeautifulSoup 抓取 Walmart Best Sellers/搜索页面
    2. 本地缓存 — 上次成功抓取的结果保存为 JSON，抓取失败时复用

抓取策略：
    - 真实浏览器 User-Agent，模拟正常用户访问
    - 每次请求间隔 1.5-2.5 秒
    - 多套 CSS 选择器兜底，适应 Walmart 页面结构变动
    - 遇验证码自动降级，不反复重试

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

# 地区域名映射（Walmart 目前仅支持美国）
_REGION_DOMAINS = {
    "us": "walmart.com",
}


def _get_cache_file(prefix: str, region: str) -> str:
    """返回按地区区分的缓存文件路径。"""
    return os.path.join(_CACHE_DIR, f"walmart_{prefix}_{region}.json")


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
# HTML 解析 — 产品卡片
# ============================================================

def _extract_title(card) -> str:
    """从产品卡片中提取标题。"""
    selectors = [
        "span[data-automation-id='product-title']",
        "a span[data-automation-id]",
        "a[class*='product-title'] span",
        "span[class*='product-title']",
        "[data-automation-id='name']",
        "a[class*='product'] span",
    ]
    for sel in selectors:
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
    selectors = [
        "[data-automation-id='product-price'] div[class*='price']",
        "[data-automation-id='product-price']",
        "span[class*='price']",
        "div[class*='price'] span",
    ]
    for sel in selectors:
        elem = card.select_one(sel)
        if elem:
            text = elem.get_text(strip=True)
            price = parse_price(text)
            if price and price > 0:
                return price
    return None


def _extract_rating(card) -> Optional[float]:
    """提取评分。"""
    selectors = [
        "span[class*='rating']",
        "div[class*='stars']",
        "[data-automation-id='product-rating']",
    ]
    for sel in selectors:
        elem = card.select_one(sel)
        if elem:
            text = elem.get_text(strip=True)
            rating = parse_rating(text)
            if rating and rating > 0:
                return rating
    return None


def _extract_reviews(card) -> int:
    """提取评论数。"""
    selectors = [
        "span[class*='reviews']",
        "[data-automation-id='product-reviews']",
        "span[class*='count']",
    ]
    for sel in selectors:
        elem = card.select_one(sel)
        if elem:
            text = elem.get_text(strip=True)
            nums = re.findall(r"[\d,]+", text)
            if nums:
                try:
                    return int(nums[0].replace(",", ""))
                except ValueError:
                    pass
    return 0


def _extract_url(card) -> str:
    """提取产品链接。"""
    link = card.select_one("a[href*='/ip/']") or card.select_one("a[href]")
    if link:
        href = link.get("href", "")
        if href:
            if href.startswith("/"):
                href = "https://www.walmart.com" + href
            return href
    return ""


def _extract_image(card) -> str:
    """提取图片 URL。"""
    img = card.select_one("img")
    if img:
        src = img.get("src", "") or img.get("data-src", "")
        if src:
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
# 真实抓取 — Walmart Best Sellers
# ============================================================

def _scrape_walmart_best_sellers(region: str = "us") -> list[dict]:
    """
    真实抓取 Walmart Best Sellers / Trending 热销产品。

    Args:
        region: 地区代码（目前仅 us）
    """
    domain = _REGION_DOMAINS.get(region, "walmart.com")

    urls_to_try = [
        f"https://www.{domain}/shop/Best-Sellers",
        f"https://www.{domain}/shop/bestsellers/4045458",
    ]

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
    }

    session = requests.Session()
    session.headers.update(headers)

    for url in urls_to_try:
        try:
            delay = random.uniform(1.5, 2.5)
            time.sleep(delay)

            resp = session.get(url, timeout=30)
            print(f"[scraper_walmart] HTTP {resp.status_code} | URL: {url}")
            resp.raise_for_status()

            if is_blocked(resp.text):
                print(f"[scraper_walmart] 被拦截，尝试下一个 URL")
                continue

            soup = BeautifulSoup(resp.text, "html.parser")

            card_selectors = [
                "[data-item-id]",
                "div[class*='search-result-gridview-item']",
                "div[class*='product-card']",
                "div[data-automation-id='product-tile']",
                "li[class*='Grid-col']",
            ]

            cards = []
            for sel in card_selectors:
                cards = soup.select(sel)
                if cards:
                    break

            if cards:
                print(f"[scraper_walmart] 找到 {len(cards)} 个产品卡片")
                products = []
                for i, card in enumerate(cards[:50], 1):
                    product = _parse_product_card(card, i)
                    if product:
                        products.append(product)
                if products:
                    return products
        except Exception as e:
            print(f"[scraper_walmart] URL {url} 失败: {e}")
            continue

    # 搜索降级
    try:
        url = f"https://www.{domain}/search?q=best+sellers&sort=best_seller"
        delay = random.uniform(1.5, 2.5)
        time.sleep(delay)

        resp = session.get(url, timeout=30)
        resp.raise_for_status()

        if not is_blocked(resp.text):
            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.select("[data-item-id]") or soup.select("div[class*='product-card']")
            if cards:
                products = []
                for i, card in enumerate(cards[:50], 1):
                    product = _parse_product_card(card, i)
                    if product:
                        products.append(product)
                if products:
                    return products
    except Exception as e:
        print(f"[scraper_walmart] 搜索降级也失败: {e}")

    return []


# ============================================================
# 搜索抓取
# ============================================================

def _scrape_walmart_search(keyword: str, region: str = "us", max_results: int = 20) -> list[dict]:
    """
    真实抓取 Walmart 搜索结果。
    """
    domain = _REGION_DOMAINS.get(region, "walmart.com")
    encoded_kw = keyword.replace(" ", "+")
    url = f"https://www.{domain}/search?q={encoded_kw}&sort=best_seller"

    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }

    session = requests.Session()
    session.headers.update(headers)

    delay = random.uniform(1.5, 2.5)
    time.sleep(delay)

    resp = session.get(url, timeout=30)
    print(f"[scraper_walmart] HTTP {resp.status_code} | URL: {url}")
    resp.raise_for_status()

    if is_blocked(resp.text):
        raise RuntimeError("被 Walmart 反爬拦截")

    soup = BeautifulSoup(resp.text, "html.parser")

    cards = soup.select("[data-item-id]") or soup.select("div[class*='product-card']")

    print(f"[scraper_walmart] 找到 {len(cards)} 个搜索结果")

    products = []
    for i, card in enumerate(cards[:max_results], 1):
        product = _parse_product_card(card, i)
        if product:
            products.append(product)

    return products


# ============================================================
# 公开接口
# ============================================================

def fetch_walmart_best_sellers(region: str = "us") -> tuple[list[dict], dict]:
    """
    获取 Walmart 热销产品列表（两层降级策略）。

    Args:
        region: 地区代码（us），默认 "us"

    Returns:
        (products, source_info) 元组
    """
    # ---------- 第一层：实时抓取 ----------
    try:
        products = _scrape_walmart_best_sellers(region=region)
        if len(products) >= 3:
            _save_cache(products, "best_sellers", region)
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            return products, {"source": "live", "timestamp": timestamp}
        else:
            print(f"[!] Walmart 实时抓取仅获得 {len(products)} 个产品，降级到缓存")
    except Exception as e:
        print(f"[!] Walmart 实时抓取失败: {e}")

    # ---------- 第二层：本地缓存 ----------
    cached = _load_cache("best_sellers", region)
    if cached and len(cached) >= 3:
        cache_ts = _get_cache_timestamp("best_sellers", region)
        print(f"[*] 使用 Walmart 本地缓存 ({len(cached)} 个产品)")
        return cached, {"source": "cache", "timestamp": cache_ts or "unknown"}

    # ---------- 均不可用 ----------
    print("[X] Walmart 实时抓取和本地缓存均不可用")
    return [], {
        "source": "unavailable",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "error": "Walmart 实时抓取和本地缓存均不可用",
    }


def search_walmart(keyword: str, region: str = "us", max_results: int = 20) -> dict:
    """
    在 Walmart 搜索指定关键词，返回产品列表。
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
        products = _scrape_walmart_search(keyword, region=region, max_results=max_results)
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
            "error": f"Walmart 反爬拦截: {e}",
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
