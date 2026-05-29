"""
Shopee 数据抓取模块 — 虾皮热销产品抓取（API 优先 + HTML 降级）。

两层数据获取策略（按优先级）：
    1. Shopee 公开 API — 获取热销/搜索产品数据（无需 API Key）
    2. HTML 页面抓取 — API 失败时降级方案

抓取策略：
    - 真实浏览器 User-Agent
    - 请求间隔 1.5-2.5 秒
    - 支持 5 个东南亚站点（sg/my/th/vn/ph）
    - VND 特殊价格处理（/100000 转换）

输出字段：
    title, price, rating, num_reviews, url, image, orders, asin
"""

import json
import os
import re
import time
import random
from datetime import datetime, timezone
from typing import Optional

import requests
from bs4 import BeautifulSoup

from .utils import USER_AGENTS, is_blocked

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
    "sg": "shopee.sg",
    "my": "shopee.com.my",
    "th": "shopee.co.th",
    "vn": "shopee.vn",
    "ph": "shopee.ph",
}

# 地区货币映射
_REGION_CURRENCY = {
    "sg": "SGD",
    "my": "MYR",
    "th": "THB",
    "vn": "VND",
    "ph": "PHP",
}


def _get_cache_file(prefix: str, region: str) -> str:
    """返回按地区区分的缓存文件路径。"""
    return os.path.join(_CACHE_DIR, f"shopee_{prefix}_{region}.json")


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
# API 方式抓取
# ============================================================

def _fetch_via_api(domain: str, endpoint: str, region: str) -> list[dict]:
    """
    通过 Shopee 公开 API 获取产品数据。

    Args:
        domain:   域名
        endpoint: API 端点路径
        region:   地区代码

    Returns:
        产品列表
    """
    url = f"https://{domain}/api/v4{endpoint}"

    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "X-Shopee-Language": "en",
        "X-API-SOURCE": "pc",
        "Referer": f"https://{domain}/",
    }

    session = requests.Session()
    session.headers.update(headers)

    delay = random.uniform(1.5, 2.5)
    time.sleep(delay)

    resp = session.get(url, timeout=30)
    print(f"[scraper_shopee] API HTTP {resp.status_code} | URL: {url}")
    resp.raise_for_status()

    data = resp.json()

    # 解析 API 响应
    items = []
    if "data" in data:
        sections = data["data"].get("sections", [])
        for section in sections:
            item_list = section.get("data", {}).get("item", [])
            items.extend(item_list)

    if not items:
        # 尝试其他响应格式
        items = data.get("items", [])
        if not items:
            items = data.get("data", {}).get("items", [])

    products = []
    for i, item in enumerate(items[:50], 1):
        product = _parse_api_product(item, i, domain, region)
        if product:
            products.append(product)

    print(f"[scraper_shopee] API 解析完成：{len(products)} 个产品")
    return products


def _parse_api_product(item: dict, rank: int, domain: str, region: str) -> Optional[dict]:
    """
    解析 Shopee API 返回的单个产品数据。

    Shopee 价格通常乘以 100000 存储。
    """
    name = item.get("name", "")
    if not name:
        return None

    # 价格处理：Shopee API 价格通常需要 /100000
    raw_price = item.get("price", 0) or item.get("price_min", 0)
    if raw_price > 10000:
        price = raw_price / 100000
    else:
        price = raw_price / 100  # 备选：有些版本 /100

    if price <= 0:
        return None

    # 评分处理
    rating_data = item.get("item_rating", {})
    rating = rating_data.get("rating_star", 0)
    rating_count = rating_data.get("rating_count", [0, 0, 0, 0, 0])
    if isinstance(rating_count, list):
        num_reviews = sum(rating_count)
    else:
        num_reviews = rating_count or 0

    # 销量
    historical_sold = item.get("historical_sold", 0) or item.get("sold", 0)

    # 图片
    image = item.get("image", "")
    if image:
        image = f"https://down-{region}.img.susercontent.com/{image}"

    # 产品链接
    shop_id = item.get("shopid", 0)
    item_id = item.get("itemid", 0)
    url = f"https://{domain}/product/{shop_id}-{item_id}"

    return {
        "title": name,
        "price": round(price, 2),
        "rating": round(rating, 1) if rating else 0,
        "num_reviews": num_reviews,
        "rank": rank,
        "url": url,
        "image": image,
        "category": str(item.get("catid", "")),
        "asin": f"{shop_id}-{item_id}",
        "historical_sold": historical_sold,
    }


# ============================================================
# HTML 方式抓取（降级方案）
# ============================================================

def _fetch_via_html(domain: str, region: str) -> list[dict]:
    """
    通过 HTML 页面抓取 Shopee 产品数据（降级方案）。

    Shopee 是 SPA 应用，HTML 中可能不含产品数据。
    尝试从 <script> 标签中的 JSON 数据提取。
    """
    url = f"https://{domain}/top_sold"

    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    session = requests.Session()
    session.headers.update(headers)

    delay = random.uniform(1.5, 2.5)
    time.sleep(delay)

    resp = session.get(url, timeout=30)
    print(f"[scraper_shopee] HTML HTTP {resp.status_code} | URL: {url}")
    resp.raise_for_status()

    if is_blocked(resp.text):
        raise RuntimeError("被 Shopee 反爬拦截")

    soup = BeautifulSoup(resp.text, "html.parser")

    # 尝试从 script 标签提取 JSON 数据
    products = _extract_json_from_scripts(soup, domain, region)

    if not products:
        # 尝试 HTML 选择器
        products = _extract_from_html_elements(soup, domain, region)

    print(f"[scraper_shopee] HTML 解析完成：{len(products)} 个产品")
    return products


def _extract_json_from_scripts(soup, domain: str, region: str) -> list[dict]:
    """从 <script> 标签中提取 JSON 产品数据。"""
    scripts = soup.find_all("script", type="application/json")
    for script in scripts:
        try:
            data = json.loads(script.string)
            # 尝试多种 JSON 结构
            items = (
                data.get("items", []) or
                data.get("data", {}).get("items", []) or
                data.get("props", {}).get("pageProps", {}).get("items", [])
            )
            if items:
                products = []
                for i, item in enumerate(items[:50], 1):
                    product = _parse_api_product(item, i, domain, region)
                    if product:
                        products.append(product)
                if products:
                    return products
        except (json.JSONDecodeError, AttributeError):
            continue
    return []


def _extract_from_html_elements(soup, domain: str, region: str) -> list[dict]:
    """从 HTML 元素中提取产品数据。"""
    # Shopee 产品卡片选择器
    card_selectors = [
        "div.shopee-search-item-result__item",
        "div[data-sqe='item']",
        "a[data-sqe='item']",
        "div.col-xs-2-4",
    ]

    cards = []
    for sel in card_selectors:
        cards = soup.select(sel)
        if cards:
            break

    products = []
    for i, card in enumerate(cards[:50], 1):
        product = _parse_html_card(card, i, domain, region)
        if product:
            products.append(product)

    return products


def _parse_html_card(card, rank: int, domain: str, region: str) -> Optional[dict]:
    """解析 HTML 产品卡片。"""
    # 标题
    title_selectors = [
        "div.ie3A\\+n",
        "div[data-sqe='name']",
        "a[data-sqe='name']",
        "div.shopee-search-item-result__item a",
    ]
    title = ""
    for sel in title_selectors:
        elem = card.select_one(sel)
        if elem:
            title = elem.get_text(strip=True)
            if title and len(title) > 3:
                break

    if not title:
        return None

    # 价格
    price_selectors = [
        "span.ZEgDH9",
        "div[class*='price']",
        "span[class*='price']",
    ]
    price = 0.0
    for sel in price_selectors:
        elem = card.select_one(sel)
        if elem:
            text = elem.get_text(strip=True)
            nums = re.findall(r"[\d,.]+", text)
            if nums:
                try:
                    price = float(nums[0].replace(",", ""))
                    if price > 10000:
                        price = price / 100000
                    break
                except ValueError:
                    pass

    if price <= 0:
        return None

    # 评分
    rating = 0.0
    rating_elem = card.select_one("div[class*='rating']") or card.select_one("span[class*='star']")
    if rating_elem:
        rating_text = rating_elem.get_text(strip=True)
        nums = re.findall(r"[\d.]+", rating_text)
        if nums:
            try:
                rating = float(nums[0])
            except ValueError:
                pass

    # 销量
    num_reviews = 0
    sold_elem = card.select_one("span[class*='sold']") or card.select_one("div[class*='sold']")
    if sold_elem:
        sold_text = sold_elem.get_text(strip=True)
        nums = re.findall(r"[\d,]+", sold_text)
        if nums:
            try:
                num_reviews = int(nums[0].replace(",", ""))
            except ValueError:
                pass

    # 链接
    link = card.select_one("a[href]")
    url = ""
    if link:
        href = link.get("href", "")
        if href:
            if href.startswith("/"):
                url = f"https://{domain}{href}"
            else:
                url = href

    return {
        "title": title,
        "price": round(price, 2),
        "rating": round(rating, 1),
        "num_reviews": num_reviews,
        "rank": rank,
        "url": url,
        "image": "",
        "category": "",
        "asin": "",
    }


# ============================================================
# 搜索抓取
# ============================================================

def _scrape_shopee_search(keyword: str, region: str = "sg", max_results: int = 20) -> list[dict]:
    """
    抓取 Shopee 搜索结果。

    优先 API，失败时降级 HTML。
    """
    domain = _REGION_DOMAINS.get(region, "shopee.sg")
    encoded_kw = keyword.replace(" ", "+")

    # 尝试 API 方式
    try:
        endpoint = f"/search/search_items?keyword={encoded_kw}&limit={max_results}&offset=0&sort_by=sales"
        products = _fetch_via_api(domain, endpoint, region)
        if products:
            return products
    except Exception as e:
        print(f"[scraper_shopee] 搜索 API 失败：{e}")

    # 降级 HTML 方式
    try:
        url = f"https://{domain}/search?keyword={encoded_kw}&sortBy=sales"
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        session = requests.Session()
        session.headers.update(headers)

        delay = random.uniform(1.5, 2.5)
        time.sleep(delay)

        resp = session.get(url, timeout=30)
        resp.raise_for_status()

        if is_blocked(resp.text):
            raise RuntimeError("被 Shopee 反爬拦截")

        soup = BeautifulSoup(resp.text, "html.parser")
        products = _extract_json_from_scripts(soup, domain, region)

        if not products:
            products = _extract_from_html_elements(soup, domain, region)

        return products[:max_results]

    except Exception as e:
        print(f"[scraper_shopee] 搜索 HTML 降级也失败：{e}")
        return []


# ============================================================
# 公开接口
# ============================================================

def fetch_shopee_best_sellers(region: str = "sg") -> tuple[list[dict], dict]:
    """
    获取 Shopee 热销产品列表（API 优先 + HTML 降级 + 缓存）。

    Args:
        region: 地区代码（sg/my/th/vn/ph），默认 "sg"

    Returns:
        (products, source_info) 元组
    """
    domain = _REGION_DOMAINS.get(region, "shopee.sg")

    # ---------- 第一层：API 抓取 ----------
    try:
        endpoint = "/recommend/recommend?limit=50&offset=0&section=top_sold"
        products = _fetch_via_api(domain, endpoint, region)
        if len(products) >= 3:
            _save_cache(products, "best_sellers", region)
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            return products, {"source": "live", "timestamp": timestamp}
    except Exception as e:
        print(f"⚠️ Shopee API 抓取失败：{e}")

    # ---------- 第二层：HTML 降级 ----------
    try:
        products = _fetch_via_html(domain, region)
        if len(products) >= 3:
            _save_cache(products, "best_sellers", region)
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            return products, {"source": "live", "timestamp": timestamp}
    except Exception as e:
        print(f"⚠️ Shopee HTML 抓取也失败：{e}")

    # ---------- 第三层：本地缓存 ----------
    cached = _load_cache("best_sellers", region)
    if cached and len(cached) >= 3:
        cache_ts = _get_cache_timestamp("best_sellers", region)
        print(f"📦 使用 Shopee 本地缓存（{len(cached)} 个产品）")
        return cached, {"source": "cache", "timestamp": cache_ts or "unknown"}

    # ---------- 均不可用 ----------
    print("❌ Shopee 实时抓取和本地缓存均不可用")
    return [], {
        "source": "unavailable",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "error": "Shopee 实时抓取和本地缓存均不可用",
    }


def search_shopee(keyword: str, region: str = "sg", max_results: int = 20) -> dict:
    """
    在 Shopee 搜索指定关键词，返回产品列表。

    Args:
        keyword:     搜索关键词
        region:      地区代码（sg/my/th/vn/ph）
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
        products = _scrape_shopee_search(keyword, region=region, max_results=max_results)
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
            "error": f"Shopee 反爬拦截：{e}",
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
