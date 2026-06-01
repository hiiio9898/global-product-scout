"""
eBay 数据抓取模块 — eBay 热销产品抓取 + 本地缓存。

两层数据获取策略（按优先级）：
    1. 实时抓取 — requests + BeautifulSoup 抓取 eBay Trending/Best Sellers 页面
    2. 本地缓存 — 上次成功抓取的结果保存为 JSON，抓取失败时复用

抓取策略：
    - 真实浏览器 User-Agent，模拟正常用户访问
    - 每次请求间隔 1.5-2.5 秒
    - 多套 CSS 选择器兜底，适应 eBay 页面结构变动
    - 遇验证码自动降级，不反复重试

输出字段：
    title, price, rating, num_reviews, url, image, shipping
"""

from __future__ import annotations

import json
import os
import re
import time
import random
from datetime import datetime, timezone
from typing import Optional

from .scrapling_adapter import fetch_page
from .utils import is_blocked, parse_price, parse_rating

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
    "us": "ebay.com",
    "uk": "ebay.co.uk",
    "de": "ebay.de",
}

# 地区语言映射
_REGION_LANG = {
    "us": "en-US",
    "uk": "en-GB",
    "de": "de-DE",
}


def _get_cache_file(prefix: str, region: str) -> str:
    """返回按地区区分的缓存文件路径。"""
    return os.path.join(_CACHE_DIR, f"ebay_{prefix}_{region}.json")


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
        "h3",
        "div.s-item__title span",
        "div.s-item__title",
        "h3.s-item__title",
        "a.s-item__link span",
        "div[class*='itemtcard'] h3",
        "h3.texttt",
        "[class*='title']",
    ]
    for sel in selectors:
        elem = card.css(sel).first if card.css(sel) else None
        if elem:
            text = str(elem.text).strip()
            if text and len(text) > 5 and "shop on ebay" not in text.lower():
                return text
    return ""


def _extract_price(card) -> Optional[float]:
    """从产品卡片中提取价格。"""
    all_text = str(card.text).strip()
    price = _extract_first_price_from_text(all_text)
    if price and price > 0:
        return price

    selectors = [
        "span.s-item__price",
        "span.s-item__price span",
        "div.displayprice",
        "span[class*='price']",
    ]
    for sel in selectors:
        elem = card.css(sel).first if card.css(sel) else None
        if elem:
            text = str(elem.text).strip()
            price = _clean_price(text)
            if price and price > 0:
                return price
    return None


def _extract_first_price_from_text(text: str) -> Optional[float]:
    """从文本中提取第一个价格数字。"""
    if not text:
        return None
    # 匹配各种货币格式：$12.99, ￥58,917.00, €15.00, £9.99
    match = re.search(r'[\$￥€£]\s*([\d,]+\.?\d*)', text)
    if match:
        try:
            price_str = match.group(1).replace(",", "")
            price = float(price_str)
            # 日元转换：如果金额 > 1000 且原始符号是 ￥，转为 USD
            if price > 1000 and "￥" in text[:match.start() + 5]:
                price = price / 150.0  # 粗略 JPY -> USD
            return round(price, 2)
        except ValueError:
            pass
    return None


def _clean_price(price_str: str) -> Optional[float]:
    """
    清洗价格字符串，处理各种 eBay 价格格式。
    "$12.99" → 12.99
    "$12.99 to $29.99" → 12.99（取最低价）
    "C $15.00" → 15.00
    "￥58,917.00" → 392.78（JPY 转 USD）
    """
    if not price_str:
        return None

    # 移除货币符号和空格
    cleaned = price_str.strip()

    # 处理区间价：取第一个价格
    if " to " in cleaned.lower():
        cleaned = cleaned.lower().split(" to ")[0].strip()

    # 检测是否是日元
    is_jpy = "￥" in cleaned or "¥" in cleaned
    # 检测是否是欧元
    is_eur = "€" in cleaned

    # 提取数字
    nums = re.findall(r"[\d,.]+", cleaned)
    if nums:
        try:
            price = float(nums[0].replace(",", ""))
            if is_jpy and price > 1000:
                price = price / 150.0  # JPY -> USD 近似
            elif is_eur:
                price = price * 1.08  # EUR -> USD 近似
            return round(price, 2)
        except ValueError:
            pass
    return None


def _extract_shipping(card) -> float:
    """提取运费。"""
    selectors = [
        "span.s-item__shipping",
        "span.s-item__freeXDays",
        "span[class*='shipping']",
    ]
    for sel in selectors:
        elem = card.css(sel).first if card.css(sel) else None
        if elem:
            text = str(elem.text).strip().lower()
            if "free" in text:
                return 0.0
            nums = re.findall(r"[\d,.]+", text)
            if nums:
                try:
                    return float(nums[0].replace(",", ""))
                except ValueError:
                    pass
    return 0.0


def _extract_rating(card) -> float:
    """提取评分（eBay 不总是显示评分）。"""
    selectors = [
        "div.x-star-rating",
        "span[class*='star']",
        "span[class*='rating']",
    ]
    for sel in selectors:
        elem = card.css(sel).first if card.css(sel) else None
        if elem:
            text = str(elem.text).strip()
            rating = parse_rating(text)
            if rating and rating > 0:
                return rating
    return 0.0


def _extract_reviews(card) -> int:
    """提取评论数。"""
    selectors = [
        "span.s-item__reviews-count",
        "span[class*='reviews']",
        "span[class*='sold']",
    ]
    for sel in selectors:
        elem = card.css(sel).first if card.css(sel) else None
        if elem:
            text = str(elem.text).strip()
            nums = re.findall(r"[\d,]+", text)
            if nums:
                try:
                    return int(nums[0].replace(",", ""))
                except ValueError:
                    pass
    return 0


def _extract_url(card) -> str:
    """提取产品链接。"""
    selectors = [
        "a[href*='itm']",
        "a.s-item__link",
        "a[href*='ebay.com/itm']",
        "a[href*='ebay']",
    ]
    for sel in selectors:
        elem = card.css(sel).first if card.css(sel) else None
        if elem:
            href = elem.attrib.get("href", "")
            if href:
                if "?" in href:
                    href = href.split("?")[0]
                if "ebay" in href or href.startswith("/"):
                    return href
    return ""


def _extract_image(card) -> str:
    """提取图片 URL。"""
    img = card.css("img").first if card.css("img") else None
    if img:
        src = img.attrib.get("src", "") or img.attrib.get("data-src", "")
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
        "shipping": _extract_shipping(card),
        "category": "trending",
    }


# ============================================================
# 真实抓取 — eBay Trending 页面
# ============================================================

def _scrape_ebay_best_sellers(region: str = "us") -> list[dict]:
    """
    真实抓取 eBay Trending / Best Sellers 热销产品（使用 Scrapling）。

    Args:
        region: 地区代码（us/uk/de）
    """
    domain = _REGION_DOMAINS.get(region, "ebay.com")

    urls_to_try = [
        f"https://www.{domain}/trending",
        f"https://www.{domain}/b/Best-Sellers/bn_7001234567",
    ]

    for url in urls_to_try:
        try:
            delay = random.uniform(1.5, 2.5)
            time.sleep(delay)

            resp = fetch_page(url)
            print(f"[scraper_ebay] HTTP {resp.status} | URL: {url}")

            if is_blocked(str(resp.text)):
                print("[scraper_ebay] 被拦截，尝试下一个 URL")
                continue

            card_selectors = [
                "article",
                "ul.srp-results li.s-item",
                "div.ebayui-dne-itemtcard",
                "div.s-item__wrapper",
                "li.s-item",
            ]

            cards = []
            for sel in card_selectors:
                cards = resp.css(sel)
                if cards:
                    break

            if cards:
                print(f"[scraper_ebay] 找到 {len(cards)} 个产品卡片")
                products = []
                for i, card in enumerate(cards[:50], 1):
                    product = _parse_product_card(card, i)
                    if product:
                        products.append(product)
                if products:
                    return products

        except Exception as e:
            print(f"[scraper_ebay] URL {url} 失败: {e}")
            continue

    # 降级：搜索排序
    try:
        url = f"https://www.{domain}/sch/i.html?_nkw=best+sellers&_sop=12"
        delay = random.uniform(1.5, 2.5)
        time.sleep(delay)

        resp = fetch_page(url)

        if not is_blocked(str(resp.text)):
            cards = resp.css("ul.srp-results li.s-item") or resp.css("li.s-item") or []
            if cards:
                products = []
                for i, card in enumerate(cards[:50], 1):
                    product = _parse_product_card(card, i)
                    if product:
                        products.append(product)
                if products:
                    return products
    except Exception as e:
        print(f"[scraper_ebay] 搜索排序也失败: {e}")

    return []


# ============================================================
# 真实抓取 — eBay 关键词搜索
# ============================================================

def _scrape_ebay_search(keyword: str, region: str = "us", max_results: int = 20) -> list[dict]:
    """真实抓取 eBay 搜索结果（使用 Scrapling）。"""
    domain = _REGION_DOMAINS.get(region, "ebay.com")
    encoded_kw = keyword.replace(" ", "+")
    url = f"https://www.{domain}/sch/i.html?_nkw={encoded_kw}&_sop=12"

    delay = random.uniform(1.5, 2.5)
    time.sleep(delay)

    resp = fetch_page(url)
    print(f"[scraper_ebay] HTTP {resp.status} | URL: {url}")

    if is_blocked(str(resp.text)):
        raise RuntimeError("被 eBay 反爬拦截")

    cards = resp.css("ul.srp-results li.s-item") or resp.css("li.s-item") or []

    print(f"[scraper_ebay] 找到 {len(cards)} 个搜索结果")

    products = []
    for i, card in enumerate(cards[:max_results], 1):
        product = _parse_product_card(card, i)
        if product:
            products.append(product)

    return products


# ============================================================
# 公开接口
# ============================================================

def fetch_ebay_best_sellers(region: str = "us") -> tuple[list[dict], dict]:
    """
    获取 eBay 热销产品列表（两层降级策略）。

    Args:
        region: 地区代码（us/uk/de），默认 "us"

    Returns:
        (products, source_info) 元组
    """
    # ---------- 第一层：实时抓取（Scrapling 自动 Fetcher→StealthyFetcher 降级） ----------
    try:
        products = _scrape_ebay_best_sellers(region=region)
        if len(products) >= 3:
            _save_cache(products, "best_sellers", region)
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            return products, {"source": "live", "timestamp": timestamp}
        else:
            print(f"[!] eBay 实时抓取仅获得 {len(products)} 个产品，降级到缓存")
    except Exception as e:
        print(f"[!] eBay 实时抓取失败: {e}")

    # ---------- 第二层：本地缓存 ----------
    cached = _load_cache("best_sellers", region)
    if cached and len(cached) >= 3:
        cache_ts = _get_cache_timestamp("best_sellers", region)
        print(f"[*] 使用 eBay 本地缓存 ({len(cached)} 个产品)")
        return cached, {"source": "cache", "timestamp": cache_ts or "unknown"}

    # ---------- 均不可用 ----------
    print("[X] eBay 实时抓取和本地缓存均不可用")
    return [], {
        "source": "unavailable",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "error": "eBay 实时抓取和本地缓存均不可用",
    }


def search_ebay(keyword: str, region: str = "us", max_results: int = 20) -> dict:
    """
    在 eBay 搜索指定关键词，返回产品列表。

    Args:
        keyword:     搜索关键词
        region:      地区代码（us/uk/de）
        max_results: 最多返回产品数

    Returns:
        搜索结果字典
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
        products = _scrape_ebay_search(keyword, region=region, max_results=max_results)
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

    except RuntimeError as e:
        return {
            "success": False,
            "keyword": keyword,
            "results": [],
            "total_found": 0,
            "source": "none",
            "scrape_time": scrape_time,
            "error": f"eBay 反爬拦截：{e}",
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
