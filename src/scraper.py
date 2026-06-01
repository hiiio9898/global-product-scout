"""
数据抓取模块 — Amazon Best Sellers 真实抓取 + 本地缓存。

两层数据获取策略（按优先级）：
    1. 实时抓取 — requests + BeautifulSoup 抓取 Amazon Best Sellers 首页
    2. 本地缓存 — 上次成功抓取的结果保存为 JSON，抓取失败时复用

抓取策略：
    - 真实浏览器 User-Agent，模拟正常用户访问
    - 每次请求间隔 2 秒（可通过 SCRAPE_DELAY_SECONDS 配置）
    - 多套 CSS 选择器兜底，适应 Amazon 页面结构变动
    - 遇 503/验证码自动降级，不反复重试加重反爬

输出字段：
    title, price, rating, num_reviews, rank, category
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional

from .config import get_config
from .scrapling_adapter import fetch_page
from .utils import is_blocked, parse_price, parse_rating, parse_review_count

# ============================================================
# 缓存路径常量
# ============================================================

_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "cache",
)
_CACHE_FILE = os.path.join(_CACHE_DIR, "amazon_best_sellers.json")

# 地区域名映射
_REGION_DOMAINS = {
    "us": "amazon.com",
    "uk": "amazon.co.uk",
    "jp": "amazon.co.jp",
    "de": "amazon.de",
}


def _get_cache_file(region: str = "us") -> str:
    """返回按地区区分的缓存文件路径。"""
    return os.path.join(_CACHE_DIR, f"amazon_best_sellers_{region}.json")

# ============================================================
# 非实体商品关键词黑名单（过滤数字订阅/服务类产品）
# ============================================================

_SKIP_KEYWORDS = [
    "subscription", "monthly auto-renewal", "auto-renewal",
    "plan", "service plan", "warranty",
    "extended warranty", "protection plan",
    "gift card", "gift certificate", "e-gift",
    "digital code", "download code", "digital delivery",
    "membership", "renewal",
]


def _is_physical_product(title: str) -> bool:
    """检查标题是否看起来像实体商品（而非数字订阅/服务）。"""
    title_lower = title.lower()
    for kw in _SKIP_KEYWORDS:
        if kw in title_lower:
            return False
    return True


# ============================================================
# 真实浏览器 User-Agent 池（模拟 Chrome / Firefox / Edge）
# ============================================================
# 缓存读写
# ============================================================

def _load_cache(region: str = "us") -> Optional[list[dict]]:
    """读取本地缓存的 JSON 数据，文件不存在或损坏时返回 None。"""
    cache_file = _get_cache_file(region)
    # 兼容旧版缓存文件
    if not os.path.exists(cache_file) and region == "us":
        cache_file = _CACHE_FILE
    try:
        if os.path.exists(cache_file):
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and len(data) > 0:
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
    """获取缓存文件的最后修改时间，格式化为可读字符串。"""
    cache_file = _get_cache_file(region)
    if not os.path.exists(cache_file) and region == "us":
        cache_file = _CACHE_FILE
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
    selectors_text = [
        'div.zg-carousel-general-faceout a.a-link-normal span',
        'div.zg-carousel-general-faceout a.a-link-normal',
        'a.a-link-normal span.a-size-base-plus',
        'h2 a span',
        '.p13n-sc-truncate-desktop-type2',
        '.p13n-sc-truncated',
        'a.a-link-normal span.a-size-medium',
    ]
    for sel in selectors_text:
        elem = card.css(sel).first if card.css(sel) else None
        if elem:
            text = str(elem.text).strip()
            if text and len(text) > 3:
                return text
    # 最后兜底：取 img alt
    img = card.css('img').first if card.css('img') else None
    if img:
        alt = img.attrib.get('alt', '').strip()
        if alt:
            return alt
    return ""


def _extract_price(card) -> Optional[float]:
    """从产品卡片中提取价格，仅使用 CSS 选择器，不依赖不可靠的正则兜底。"""
    selectors = [
        '.a-price .a-offscreen',
        '.a-price span[aria-hidden="true"]',
        '.p13n-sc-price',
        'span.a-color-price',
        'span._cDEzb_p13n-sc-price_3mJ9Z',
    ]
    for sel in selectors:
        elem = card.css(sel).first if card.css(sel) else None
        if elem:
            text = str(elem.text).strip()
            price = parse_price(text)
            if price and price > 0:
                return price
    return None


def _extract_rating(card) -> Optional[float]:
    """从产品卡片中提取用户评分，优先选择器，再全文正则兜底。"""
    selectors = [
        '.a-icon-star .a-icon-alt',
        'i[class*="a-star"] span',
        '.a-icon-alt',
        'span.a-icon-alt',
    ]
    for sel in selectors:
        elem = card.css(sel).first if card.css(sel) else None
        if elem:
            rating = parse_rating(str(elem.text).strip())
            if rating and 1.0 <= rating <= 5.0:
                return rating
    # 全文正则兜底
    card_text = str(card.text)
    rating_match = re.search(r'(\d+\.?\d*)\s*(?:out\s+of\s+5|stars?)', card_text, re.IGNORECASE)
    if rating_match:
        try:
            val = float(rating_match.group(1))
            if 1.0 <= val <= 5.0:
                return val
        except ValueError:
            pass
    return None


def _extract_review_count(card) -> int:
    """从产品卡片中提取评论总数，优先选择器，再全文正则兜底。"""
    selectors = [
        'span.a-size-small',
        'span.a-size-base',
        'a[href*="customerReviews"] span',
    ]
    for sel in selectors:
        for elem in card.css(sel):
            text = str(elem.text).strip()
            if any(kw in text.lower() for kw in ('rating', 'stars')):
                continue
            count = parse_review_count(text)
            if count > 0:
                return count
    # 全文正则兜底
    card_text = str(card.text)
    review_match = re.search(
        r'([\d,]+)\s*(?:ratings?|reviews?)',
        card_text, re.IGNORECASE,
    )
    if review_match:
        try:
            return int(review_match.group(1).replace(',', ''))
        except ValueError:
            pass
    # 最后兜底：从链接文本中提取数字
    for link in card.css('a.a-link-normal'):
        text = str(link.text).strip()
        count = parse_review_count(text)
        if count > 0:
            return count
    return 0


def _parse_product_card(card, rank: int) -> Optional[dict]:
    """解析单个产品卡片，提取所有字段。"""
    title = _extract_title(card)
    if not title:
        return None

    asin = card.attrib.get("data-asin", "").strip() if hasattr(card, 'attrib') else ""

    price = _extract_price(card)
    rating = _extract_rating(card)
    num_reviews = _extract_review_count(card)

    return {
        "title": title,
        "asin": asin,
        "price": price if price is not None else 0.0,
        "rating": rating if rating is not None else 0.0,
        "num_reviews": num_reviews,
        "rank": rank,
        "category": "",
    }


# ============================================================
# 真实抓取引擎
# ============================================================

def _scrape_amazon_best_sellers(region: str = "us") -> list[dict]:
    """
    真实抓取 Amazon Best Sellers 首页（使用 Scrapling）。

    Args:
        region: 地区代码（us/uk/jp/de），决定目标域名

    Raises:
        RuntimeError: 被反爬拦截
        Exception: 网络错误或解析异常
    """
    cfg = get_config()
    delay = cfg["scrape_delay"]

    domain = _REGION_DOMAINS.get(region, "amazon.com")
    url = f"https://www.{domain}/Best-Sellers/zgbs/"

    # 请求前等待，遵守速率限制
    time.sleep(delay)

    resp = fetch_page(url)
    print(f"HTTP 状态码: {resp.status}")

    # 检测是否被拦截
    if is_blocked(str(resp.text)):
        raise RuntimeError("被 Amazon 反爬拦截，收到验证码或登录页面")

    # 定位产品卡片 — 以 div[data-asin] 为主选择器
    all_cards = resp.css('div[data-asin]')
    cards = [c for c in all_cards if c.attrib.get('data-asin', '').strip()] if all_cards else []
    print(f"\n📦 找到 {len(cards)} 个有效 div[data-asin] 卡片")

    products = []
    for i, card in enumerate(cards[:50], 1):
        product = _parse_product_card(card, i)
        if product and product.get("title"):
            if _is_physical_product(product["title"]):
                products.append(product)
            else:
                print(f"  ⏭️ 跳过非实体商品: {product['title'][:50]}")

    print(f"\n📊 解析完成：{len(products)} / {len(cards)} 个卡片成功提取产品")
    return products


# ============================================================
# 公开接口 — 仅真实抓取（调试模式）
# ============================================================

def fetch_amazon_best_sellers(region: str = "us") -> tuple[list[dict], dict]:
    """
    获取 Amazon Best Sellers 产品列表（两层降级策略）。

    Args:
        region: 地区代码（us/uk/jp/de），默认 "us"

    策略：
        1. 实时抓取 → 至少 3 个产品才算成功
        2. 抓取失败或产品不足 → 本地缓存 JSON

    Returns:
        (products, source_info) 元组：
        - products:    产品字典列表
        - source_info: {"source": "live"|"cache"|"unavailable", "timestamp": "...", ...}
    """
    # ---------- 第一层：实时抓取 ----------
    try:
        products = _scrape_amazon_best_sellers(region=region)
        if len(products) >= 3:
            _save_cache(products, region=region)
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            return products, {"source": "live", "timestamp": timestamp}
        else:
            print(f"⚠️ 实时抓取仅获得 {len(products)} 个产品（不足 3 个），降级到缓存")
    except Exception as e:
        print(f"⚠️ 实时抓取失败：{e}")

    # ---------- 第二层：本地缓存 ----------
    cached = _load_cache(region=region)
    if cached and len(cached) >= 3:
        cache_ts = _get_cache_timestamp(region=region)
        print(f"📦 使用本地缓存（{len(cached)} 个产品，缓存时间：{cache_ts}）")
        return cached, {"source": "cache", "timestamp": cache_ts or "unknown"}

    # ---------- 均不可用 ----------
    print("❌ 实时抓取和本地缓存均不可用")
    return [], {"source": "unavailable", "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"), "error": "实时抓取和本地缓存均不可用"}
