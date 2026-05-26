"""
数据抓取模块 — Amazon Best Sellers 真实抓取 + 本地缓存 + 模拟降级。

三层数据获取策略（按优先级）：
    1. 实时抓取 — requests + BeautifulSoup 抓取 Amazon Best Sellers 首页
    2. 本地缓存 — 上次成功抓取的结果保存为 JSON，抓取失败时复用
    3. 模拟数据 — 缓存也不可用时，降级为内置模拟数据确保体验

抓取策略：
    - 真实浏览器 User-Agent，模拟正常用户访问
    - 每次请求间隔 2 秒（可通过 SCRAPE_DELAY_SECONDS 配置）
    - 多套 CSS 选择器兜底，适应 Amazon 页面结构变动
    - 遇 503/验证码自动降级，不反复重试加重反爬

输出字段：
    title, price, rating, num_reviews, rank, category
"""

import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional

import requests
from bs4 import BeautifulSoup

from .config import get_config

# ============================================================
# 缓存路径常量
# ============================================================

_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "cache",
)
_CACHE_FILE = os.path.join(_CACHE_DIR, "amazon_best_sellers.json")

# ============================================================
# 真实浏览器 User-Agent 池（模拟 Chrome / Firefox / Edge）
# ============================================================

_USER_AGENTS = [
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
# 内置模拟数据（终极降级方案）
# ============================================================

def _get_mock_products() -> list[dict]:
    """
    返回精心设计的模拟产品数据，确保无网络时也能完整体验。

    模拟数据模拟了 Amazon Best Sellers 真实榜单特征，涵盖多个热门类目，
    包含逼真的 Listing 标题风格和合理的价格/评分分布。
    """
    return [
        {
            "title": "SoundPro X1 Portable Bluetooth Speaker - IPX7 Waterproof, 24H Playtime, Deep Bass (Black)",
            "price": 25.99,
            "rating": 4.5,
            "num_reviews": 18342,
            "rank": 1,
            "category": "Electronics",
        },
        {
            "title": "ComfortRest Memory Foam Travel Neck Pillow - Ergonomic Design, Washable Cover, Portable with Carry Bag (Gray)",
            "price": 17.99,
            "rating": 4.3,
            "num_reviews": 28760,
            "rank": 2,
            "category": "Home & Kitchen",
        },
        {
            "title": "AquaSteel Stainless Steel Vacuum Insulated Water Bottle 32oz - Double Wall, Keeps Cold 24H/Hot 12H (Gradient Blue)",
            "price": 22.99,
            "rating": 4.7,
            "num_reviews": 56123,
            "rank": 3,
            "category": "Sports & Outdoors",
        },
        {
            "title": "LumiPro LED Desk Lamp with USB Charging Port - 5 Brightness Levels, Touch Control, Eye-Caring, Auto Timer (White)",
            "price": 29.99,
            "rating": 4.6,
            "num_reviews": 15420,
            "rank": 4,
            "category": "Office Products",
        },
        {
            "title": "EcoThreads Organic Cotton T-Shirt Men's Crew Neck 3-Pack - 180GSM Heavyweight, Pre-Shrunk (Black/White/Gray)",
            "price": 34.99,
            "rating": 4.4,
            "num_reviews": 8520,
            "rank": 5,
            "category": "Clothing",
        },
        {
            "title": "PowerMax 26800mAh Fast Charging Portable Charger - USB-C PD 3.0, 22.5W Quick Charge, Dual Output, LED Display (Black)",
            "price": 39.99,
            "rating": 4.6,
            "num_reviews": 32100,
            "rank": 6,
            "category": "Electronics",
        },
        {
            "title": "BambooChef Natural Bamboo Cutting Board 3-Piece Set - Organic, Knife-Friendly, Deep Juice Grooves, Easy Hang Handles",
            "price": 24.99,
            "rating": 4.5,
            "num_reviews": 19200,
            "rank": 7,
            "category": "Home & Kitchen",
        },
    ]


# ============================================================
# 缓存读写
# ============================================================

def _load_cache() -> Optional[list[dict]]:
    """读取本地缓存的 JSON 数据，文件不存在或损坏时返回 None。"""
    try:
        if os.path.exists(_CACHE_FILE):
            with open(_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and len(data) > 0:
                return data
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _save_cache(products: list[dict]) -> None:
    """将抓取结果保存为本地 JSON 缓存。"""
    os.makedirs(_CACHE_DIR, exist_ok=True)
    with open(_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)


def _get_cache_timestamp() -> Optional[str]:
    """获取缓存文件的最后修改时间，格式化为可读字符串。"""
    try:
        if os.path.exists(_CACHE_FILE):
            mtime = os.path.getmtime(_CACHE_FILE)
            dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
            return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except OSError:
        pass
    return None


# ============================================================
# 字段解析辅助函数
# ============================================================

def _parse_price(text: str) -> Optional[float]:
    """从价格文本中提取浮点数，如 '$29.99' → 29.99。"""
    if not text:
        return None
    match = re.search(r'[\d,]+\.?\d*', text)
    if match:
        return float(match.group().replace(',', ''))
    return None


def _parse_rating(text: str) -> Optional[float]:
    """从评分文本中提取浮点数，如 '4.5 out of 5 stars' → 4.5。"""
    if not text:
        return None
    match = re.search(r'(\d+\.?\d*)', text)
    if match:
        return float(match.group(1))
    return None


def _parse_review_count(text: str) -> int:
    """从评论数文本中提取整数，如 '12,345' → 12345。"""
    if not text:
        return 0
    # 清理常见前缀
    cleaned = re.sub(r'[^\d,]', '', text)
    if cleaned:
        return int(cleaned.replace(',', ''))
    return 0


# ============================================================
# HTML 解析 — 产品卡片
# ============================================================

def _extract_title(card) -> str:
    """从产品卡片中提取标题，多层选择器兜底。"""
    selectors = [
        'h2 a span',                          # 标准搜索卡片
        '.p13n-sc-truncate-desktop-type2',     # Best Sellers 截断标题
        '.p13n-sc-truncated',                  # 旧版 Best Sellers
        'a.a-link-normal span.a-size-medium',  # 通用
        'img',                                 # 最后兜底：取 img alt
    ]
    for sel in selectors:
        elem = card.select_one(sel)
        if elem:
            text = elem.get('alt', '') if sel == 'img' else elem.get_text(strip=True)
            if text:
                return text
    return ""


def _extract_price(card) -> Optional[float]:
    """从产品卡片中提取价格。"""
    selectors = [
        '.a-price .a-offscreen',
        '.a-price span[aria-hidden="true"]',
        '.p13n-sc-price',
        'span.a-color-price',
    ]
    for sel in selectors:
        elem = card.select_one(sel)
        if elem:
            text = elem.get_text(strip=True)
            price = _parse_price(text)
            if price and price > 0:
                return price
    return None


def _extract_rating(card) -> Optional[float]:
    """从产品卡片中提取用户评分。"""
    selectors = [
        '.a-icon-star .a-icon-alt',
        '.a-icon-alt',
        'i[class*="star"] span',
        'span.a-icon-alt',
    ]
    for sel in selectors:
        elem = card.select_one(sel)
        if elem:
            rating = _parse_rating(elem.get_text(strip=True))
            if rating and 1.0 <= rating <= 5.0:
                return rating
    return None


def _extract_review_count(card) -> int:
    """从产品卡片中提取评论总数。"""
    selectors = [
        'span.a-size-small',                  # 常见位置
        'span.a-size-base',                   # 备选
        'a[href*="customerReviews"] span',    # 链接内
    ]
    for sel in selectors:
        for elem in card.select(sel):
            text = elem.get_text(strip=True)
            if any(kw in text.lower() for kw in ('rating', 'ratings', 'review', 'stars')):
                continue  # 跳过评分文本，只要评论数
            count = _parse_review_count(text)
            if count > 0:
                return count
    # 如果有 a-link-normal 且文本包含数字，可能是评论链接
    for link in card.select('a.a-link-normal'):
        text = link.get_text(strip=True)
        count = _parse_review_count(text)
        if count > 0:
            return count
    return 0


def _parse_product_card(card, rank: int) -> Optional[dict]:
    """解析单个产品卡片，提取所有字段。返回 None 表示解析失败。"""
    title = _extract_title(card)
    if not title:
        return None

    price = _extract_price(card)
    rating = _extract_rating(card)
    num_reviews = _extract_review_count(card)

    return {
        "title": title,
        "price": price or 0.0,
        "rating": rating or 0.0,
        "num_reviews": num_reviews,
        "rank": rank,
        "category": "",  # Best Sellers 首页跨类目，无统一类目
    }


# ============================================================
# 真实抓取引擎
# ============================================================

def _scrape_amazon_best_sellers() -> list[dict]:
    """
    真实抓取 Amazon Best Sellers 首页（US 站）。

    使用 requests + BeautifulSoup，不加 Selenium。
    设置了真实浏览器 User-Agent、请求间隔 2 秒。
    多套 CSS 选择器兜底以适应页面结构变动。

    Raises:
        requests.RequestException: 网络错误
        Exception: 解析异常（页面结构不匹配、验证码等）
    """
    cfg = get_config()
    url = cfg["amazon_url"]
    delay = cfg["scrape_delay"]

    # 构建真实浏览器请求头
    headers = {
        "User-Agent": _USER_AGENTS[0],
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

    # 请求前等待，遵守速率限制
    time.sleep(delay)

    resp = session.get(url, timeout=30)
    resp.raise_for_status()

    # 检测是否被拦截（验证码/登录页）
    if _is_blocked(resp.text):
        raise RuntimeError("被 Amazon 反爬拦截，收到验证码或登录页面")

    soup = BeautifulSoup(resp.text, "html.parser")

    # 定位产品卡片 — 多套选择器按优先级尝试
    cards = []
    card_selectors = [
        'div[id^="gridItemRoot"]',                        # Best Sellers 网格
        'div[data-component-type="s-product-card"]',       # 搜索卡片格式
        'div.zg-grid-general-faceout',                     # 旧版 Best Sellers
        'div.p13n-grid-content div[id]',                   # 新版网格
    ]
    for sel in card_selectors:
        cards = soup.select(sel)
        if cards:
            break

    if not cards:
        # 最后的兜底：查找所有疑似产品卡片的容器
        cards = soup.select('div[role="listitem"]')

    products = []
    for i, card in enumerate(cards[:50], 1):  # 最多取前 50 个
        product = _parse_product_card(card, i)
        if product and product.get("title") and product.get("price", 0) > 0:
            products.append(product)

    return products


def _is_blocked(html: str) -> bool:
    """检测页面是否被 Amazon 反爬机制拦截。"""
    blocked_keywords = [
        "Type the characters you see",
        "Enter the characters you see",
        "Sorry, we just need to make sure you're not a robot",
        "To discuss automated access to Amazon data",
        "api-services-support@amazon.com",
        "<title>Robot Check</title>",
        "<title>503 - Service Not Available</title>",
    ]
    html_lower = html.lower()
    return any(kw.lower() in html_lower for kw in blocked_keywords)


# ============================================================
# 公开接口 — 三层降级策略
# ============================================================

def fetch_amazon_best_sellers() -> tuple[list[dict], dict]:
    """
    获取 Amazon Best Sellers 产品列表（三层降级）。

    策略：
        1. 实时抓取 → 成功则缓存到本地 JSON
        2. 抓取失败 → 读取上次成功抓取的本地缓存
        3. 缓存也不可用 → 降级为内置模拟数据

    Returns:
        (products, source_info) 元组：
        - products:    产品字典列表
        - source_info: {"source": "live"|"cache"|"mock", "timestamp": "..."}
    """
    # ---- 第 1 层：尝试真实抓取 ----
    try:
        products = _scrape_amazon_best_sellers()
        if products and len(products) >= 3:
            # 抓取成功，写入缓存
            _save_cache(products)
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            return products, {"source": "live", "timestamp": timestamp}
    except Exception:
        # 抓取失败，静默进入下一层
        pass

    # ---- 第 2 层：读取本地缓存 ----
    cached = _load_cache()
    if cached:
        ts = _get_cache_timestamp() or "未知"
        return cached, {"source": "cache", "timestamp": ts}

    # ---- 第 3 层：降级为模拟数据 ----
    return _get_mock_products(), {
        "source": "mock",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }
