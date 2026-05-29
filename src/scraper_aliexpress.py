"""
AliExpress 数据抓取模块 — 速卖通热销产品抓取 + 本地缓存。

两层数据获取策略（按优先级）：
    1. 实时抓取 — requests + BeautifulSoup 抓取 AliExpress 热销/搜索页面
    2. 本地缓存 — 上次成功抓取的结果保存为 JSON，抓取失败时复用

抓取策略：
    - 真实浏览器 User-Agent，模拟正常用户访问
    - 每次请求间隔 1.5-2.5 秒
    - 多套 CSS 选择器兜底，适应 AliExpress 页面结构变动
    - 遇验证码自动降级，不反复重试

输出字段：
    title, price, rating, num_reviews, url, image, orders
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

# 地区语言映射
_REGION_LANG = {
    "us": "en_US",
    "eu": "en_US",
    "ru": "ru_RU",
}


def _get_cache_file(region: str = "us") -> str:
    """返回按地区区分的缓存文件路径。"""
    return os.path.join(_CACHE_DIR, f"aliexpress_best_sellers_{region}.json")


# ============================================================
# 非实体商品关键词过滤
# ============================================================

_SKIP_KEYWORDS = [
    "virtual", "gift card", "coupon", "top up", "recharge",
    "digital code", "download", "subscription", "membership",
]


def _is_physical_product(title: str) -> bool:
    """检查标题是否看起来像实体商品。"""
    title_lower = title.lower()
    for kw in _SKIP_KEYWORDS:
        if kw in title_lower:
            return False
    return True


# ============================================================
# 缓存读写
# ============================================================

def _load_cache(region: str = "us") -> Optional[list[dict]]:
    """读取本地缓存的 JSON 数据。"""
    cache_file = _get_cache_file(region)
    try:
        if os.path.exists(cache_file):
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and len(data) > 0:
                # 检查缓存时效
                mtime = os.path.getmtime(cache_file)
                if time.time() - mtime < _CACHE_TTL:
                    return data
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _save_cache(products: list[dict], region: str = "us") -> None:
    """将抓取结果保存为本地 JSON 缓存。"""
    os.makedirs(_CACHE_DIR, exist_ok=True)
    cache_file = _get_cache_file(region)
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)


def _get_cache_timestamp(region: str = "us") -> Optional[str]:
    """获取缓存文件的最后修改时间。"""
    cache_file = _get_cache_file(region)
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
    """从产品卡片中提取标题，多层选择器兜底。"""
    selectors = [
        "h3.manhattan--title--2i-6M a",
        "h3.manhattan--title--2i-6M",
        "div.product-title a",
        "h1.product-title-text",
        "[class*='title'] a",
        "a[class*='title']",
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
        "span.manhattan--price--2i-6M",
        "div.product-price span[class*='price-current']",
        "span[class*='price-current']",
        "span[class*='price']",
        "div.product-price",
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
    """从产品卡片中提取评分。"""
    selectors = [
        "span.manhattan--rating--2i-6M",
        "span.rating-value",
        "[class*='rating'] span",
        "span[class*='star']",
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
    """从产品卡片中提取评论/销量数。"""
    selectors = [
        "span.manhattan--trade--2i-6M",
        "span[class*='trade']",
        "span[class*='orders']",
        "span[class*='sold']",
    ]
    for sel in selectors:
        elem = card.select_one(sel)
        if elem:
            text = elem.get_text(strip=True)
            # 提取数字："1,234 sold" → 1234
            nums = re.findall(r"[\d,]+", text)
            if nums:
                try:
                    return int(nums[0].replace(",", ""))
                except ValueError:
                    pass
    return 0


def _extract_url(card) -> str:
    """从产品卡片中提取产品链接。"""
    selectors = [
        "a[href*='item']",
        "a[href*='product']",
        "a[href*='aliexpress']",
    ]
    for sel in selectors:
        elem = card.select_one(sel)
        if elem:
            href = elem.get("href", "")
            if href:
                if href.startswith("//"):
                    href = "https:" + href
                elif href.startswith("/"):
                    href = "https://www.aliexpress.com" + href
                return href
    return ""


def _extract_image(card) -> str:
    """从产品卡片中提取产品图片 URL。"""
    img = card.select_one("img")
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
    if not title or not _is_physical_product(title):
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
# 真实抓取 — AliExpress 热销页面
# ============================================================

def _scrape_aliexpress_best_sellers(region: str = "us") -> list[dict]:
    """
    真实抓取 AliExpress 热销产品。

    Args:
        region: 地区代码（us/eu/ru）

    Raises:
        requests.RequestException: 网络错误
        RuntimeError: 被反爬拦截
    """
    domain = _REGION_DOMAINS.get(region, "aliexpress.com")

    # AliExpress 搜索排序页面（best-sellers URL 已失效，改用搜索方式）
    url = f"https://www.{domain}/w/wholesale-best-selling.html?SortType=total_orders"

    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": _REGION_LANG.get(region, "en_US") + ",en;q=0.9",
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

    # 请求前等待
    delay = random.uniform(1.5, 2.5)
    time.sleep(delay)

    resp = session.get(url, timeout=30)
    print(f"[scraper_aliexpress] HTTP {resp.status_code} | URL: {url}")
    resp.raise_for_status()

    # 检测拦截
    if is_blocked(resp.text):
        raise RuntimeError("被 AliExpress 反爬拦截，收到验证码页面")

    soup = BeautifulSoup(resp.text, "html.parser")

    # 多套选择器兜底
    card_selectors = [
        "div.manhattan--container--1lP57",       # 新版热销卡片
        "div.product-card",                       # 通用产品卡片
        "div[data-widget-cid]",                   # 带 widget ID 的卡片
        "a[href*='item'] div",                    # 链接内 div
    ]

    cards = []
    for sel in card_selectors:
        cards = soup.select(sel)
        if cards:
            break

    # 如果选择器都未命中，尝试搜索排序方式
    if not cards:
        url = f"https://www.{domain}/w/wholesale-best-selling.html?SortType=total_orders"
        time.sleep(delay)
        resp = session.get(url, timeout=30)
        resp.raise_for_status()

        if is_blocked(resp.text):
            raise RuntimeError("被 AliExpress 反爬拦截")

        soup = BeautifulSoup(resp.text, "html.parser")
        card_selectors = [
            "div.product-card",
            "div[data-widget-cid]",
            "a[href*='item']",
        ]
        for sel in card_selectors:
            cards = soup.select(sel)
            if cards:
                break

    # Selenium 降级：如果 requests 方式失败或被拦截
    if not cards or len(cards) < 3:
        print("[scraper_aliexpress] requests 方式产品不足，尝试 Selenium 降级...")
        try:
            from .selenium_helper import fetch_page_soup
            selenium_url = f"https://www.{domain}/w/wholesale-best-selling.html?SortType=total_orders"
            selenium_soup = fetch_page_soup(selenium_url, wait_seconds=10)
            if selenium_soup:
                # 检查是否是 404 或 CAPTCHA
                page_text = selenium_soup.get_text().lower()
                if "404" in page_text[:200] or "captcha" in page_text:
                    print("[scraper_aliexpress] Selenium 页面为 404 或 CAPTCHA")
                else:
                    for sel in card_selectors:
                        cards = selenium_soup.select(sel)
                        if cards:
                            break
        except Exception as e:
            print(f"[scraper_aliexpress] Selenium 降级也失败: {e}")

    print(f"[scraper_aliexpress] 找到 {len(cards)} 个产品卡片")

    products = []
    for i, card in enumerate(cards[:50], 1):
        product = _parse_product_card(card, i)
        if product:
            products.append(product)

    print(f"[scraper_aliexpress] 解析完成：{len(products)} 个产品")
    return products


# ============================================================
# 真实抓取 — AliExpress 关键词搜索
# ============================================================

def _scrape_aliexpress_search(keyword: str, region: str = "us", max_results: int = 20) -> list[dict]:
    """
    真实抓取 AliExpress 搜索结果。

    Args:
        keyword:     搜索关键词
        region:      地区代码
        max_results: 最多返回产品数
    """
    domain = _REGION_DOMAINS.get(region, "aliexpress.com")
    encoded_kw = keyword.replace(" ", "+")
    url = f"https://www.{domain}/w/wholesale-{encoded_kw}.html?SortType=total_orders"

    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": _REGION_LANG.get(region, "en_US") + ",en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }

    session = requests.Session()
    session.headers.update(headers)

    delay = random.uniform(1.5, 2.5)
    time.sleep(delay)

    resp = session.get(url, timeout=30)
    print(f"[scraper_aliexpress] HTTP {resp.status_code} | URL: {url}")
    resp.raise_for_status()

    if is_blocked(resp.text):
        raise RuntimeError("被 AliExpress 反爬拦截")

    soup = BeautifulSoup(resp.text, "html.parser")

    # 搜索结果卡片选择器
    card_selectors = [
        "div.product-card",
        "div[data-widget-cid]",
        "a[href*='item']",
    ]

    cards = []
    for sel in card_selectors:
        cards = soup.select(sel)
        if cards:
            break

    # Selenium 降级
    if not cards or len(cards) < 3:
        print("[scraper_aliexpress] 搜索 requests 方式产品不足，尝试 Selenium 降级...")
        try:
            from .selenium_helper import fetch_page_soup
            selenium_soup = fetch_page_soup(url, wait_seconds=8)
            if selenium_soup:
                for sel in card_selectors:
                    cards = selenium_soup.select(sel)
                    if cards:
                        break
        except Exception as e:
            print(f"[scraper_aliexpress] 搜索 Selenium 降级也失败：{e}")

    print(f"[scraper_aliexpress] 找到 {len(cards)} 个搜索结果")

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
    获取 AliExpress 热销产品列表（两层降级策略）。

    Args:
        region: 地区代码（us/eu/ru），默认 "us"

    Returns:
        (products, source_info) 元组
    """
    # ---------- 第一层：实时抓取 ----------
    try:
        products = _scrape_aliexpress_best_sellers(region=region)
        if len(products) >= 3:
            _save_cache(products, region=region)
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            return products, {"source": "live", "timestamp": timestamp}
        else:
            print(f"[!] AliExpress 实时抓取仅获得 {len(products)} 个产品，降级到缓存")
    except Exception as e:
        print(f"[!] AliExpress 实时抓取失败: {e}")

    # ---------- 第二层：本地缓存 ----------
    cached = _load_cache(region=region)
    if cached and len(cached) >= 3:
        cache_ts = _get_cache_timestamp(region=region)
        print(f"[*] 使用 AliExpress 本地缓存 ({len(cached)} 个产品)")
        return cached, {"source": "cache", "timestamp": cache_ts or "unknown"}

    # ---------- 均不可用 ----------
    print("[X] AliExpress 实时抓取和本地缓存均不可用")
    return [], {
        "source": "unavailable",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "error": "AliExpress 实时抓取和本地缓存均不可用",
    }


def search_aliexpress(keyword: str, region: str = "us", max_results: int = 20) -> dict:
    """
    在 AliExpress 搜索指定关键词，返回产品列表。

    Args:
        keyword:     搜索关键词
        region:      地区代码（us/eu/ru）
        max_results: 最多返回产品数

    Returns:
        搜索结果字典（与 search_amazon 格式一致）
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
            "error": f"AliExpress 反爬拦截：{e}",
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
