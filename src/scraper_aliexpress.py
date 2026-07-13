"""
AliExpress（速卖通）数据抓取模块 — 热销产品抓取 + 本地缓存。

两层数据获取策略（按优先级）：
    1. 实时抓取 — Scrapling StealthyFetcher 抓取 AliExpress 热销页面
    2. 本地缓存 — 上次成功抓取的结果保存为 JSON，抓取失败时复用

抓取策略：
    - AliExpress 是 SPA 架构，需要 StealthyFetcher（浏览器渲染）
    - 每次请求间隔 2-3 秒
    - 遇验证码自动降级到缓存

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

from .scrapling_adapter import fetch_page
from .utils import (
    is_blocked, parse_price, parse_rating,
    load_json_cache, save_json_cache, get_cache_timestamp,
    get_logger,
)

_logger = get_logger(__name__)


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
    "us": "aliexpress.us",
    "eu": "aliexpress.com",
    "ru": "aliexpress.ru",
}


def _get_cache_file(region: str = "us") -> str:
    """获取缓存文件路径。"""
    os.makedirs(_CACHE_DIR, exist_ok=True)
    return os.path.join(_CACHE_DIR, f"aliexpress_best_sellers_{region}.json")


# ============================================================
# HTML 解析
# ============================================================

def _parse_product_card(card, rank: int) -> Optional[dict]:
    """解析单个产品卡片。"""
    try:
        # 标题
        title = ""
        for sel in [
            'h1._18_85 a',
            'a._18_85',
            '.item-title a',
            'h1 a',
            'a[href*="/item/"]',
        ]:
            elem = card.css(sel).first if card.css(sel) else None
            if elem:
                title = str(elem.text).strip()
                if title and len(title) > 3:
                    break
        if not title:
            img = card.css('img').first if card.css('img') else None
            if img:
                title = img.attrib.get('alt', '').strip()
        if not title:
            return None

        # 价格
        price = 0.0
        for sel in [
            '.mGXnE ._12A8D',
            '._12A8D',
            '.item-price',
            'span[class*="price"]',
        ]:
            elem = card.css(sel).first if card.css(sel) else None
            if elem:
                price = parse_price(str(elem.text))
                if price and price > 0:
                    break

        # 评分
        rating = 0.0
        for sel in [
            '.e0PwJ',
            'span[class*="star"]',
            '.item-rating',
        ]:
            elem = card.css(sel).first if card.css(sel) else None
            if elem:
                rating = parse_rating(str(elem.text))
                if rating and rating > 0:
                    break

        # 订单数
        orders = 0
        for sel in [
            '.mGXnE ._12A8D + span',
            'span[class*="sold"]',
            '.item-sold',
        ]:
            elem = card.css(sel).first if card.css(sel) else None
            if elem:
                text = str(elem.text).strip()
                nums = re.findall(r'[\d,]+', text)
                if nums:
                    orders = int(nums[0].replace(',', ''))
                    break

        # URL
        url = ""
        link = card.css('a[href*="/item/"]').first if card.css('a[href*="/item/"]') else None
        if link:
            href = link.attrib.get('href', '')
            if href.startswith('/'):
                url = f"https://www.aliexpress.com{href}"
            elif href.startswith('http'):
                url = href

        # 图片
        image = ""
        img = card.css('img').first if card.css('img') else None
        if img:
            image = img.attrib.get('src', '') or img.attrib.get('data-src', '')

        return {
            "title": title,
            "price": price if price else 0.0,
            "rating": rating if rating else 0.0,
            "num_reviews": orders,
            "rank": rank,
            "category": "",
            "url": url,
            "image": image,
        }
    except Exception as e:
        return None


# ============================================================
# 真实抓取
# ============================================================

def _scrape_aliexpress_best_sellers(region: str = "us", max_products: int = 30) -> list[dict]:
    """真实抓取 AliExpress 热销产品。"""
    domain = _REGION_DOMAINS.get(region, "aliexpress.com")
    url = f"https://www.{domain}/g/best-sellers"

    time.sleep(random.uniform(2.0, 3.0))

    resp = fetch_page(url, stealth=True, wait_seconds=8)
    _logger.info(f"[scraper_aliexpress] HTTP {resp.status} | URL: {url}")

    if resp.status != 200 or is_blocked(str(resp.text)):
        raise RuntimeError(f"被拦截或请求失败 (status={resp.status})")

    # 查找产品卡片
    cards = resp.css('div[class*="product-card"]') or resp.css('div[class*="item-card"]')
    if not cards:
        cards = resp.css('a[href*="/item/"]')

    _logger.info(f"[scraper_aliexpress] 找到 {len(cards)} 个产品卡片")

    products = []
    for i, card in enumerate(cards[:max_products], 1):
        product = _parse_product_card(card, i)
        if product and product.get("title"):
            products.append(product)

    return products


# ============================================================
# 公开接口
# ============================================================

def fetch_aliexpress_best_sellers(region: str = "us", max_products: int = 30) -> tuple[list[dict], dict]:
    """
    获取 AliExpress 热销产品列表（两层降级策略）。

    Args:
        region: 地区代码（us/eu/ru）
        max_products: 最多返回产品数

    Returns:
        (products, source_info) 元组
    """
    # 第一层：实时抓取
    try:
        products = _scrape_aliexpress_best_sellers(region=region, max_products=max_products)
        if len(products) >= 3:
            save_json_cache(products, _get_cache_file(region))
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            return products, {"source": "live", "timestamp": timestamp}
        else:
            _logger.warning(f"⚠️ 实时抓取仅获得 {len(products)} 个产品，降级到缓存")
    except Exception as e:
        _logger.warning(f"⚠️ 实时抓取失败：{e}")

    # 第二层：本地缓存
    cached = load_json_cache(_get_cache_file(region))
    if cached and len(cached) >= 3:
        cache_ts = get_cache_timestamp(_get_cache_file(region))
        _logger.info(f"📦 使用本地缓存（{len(cached)} 个产品）")
        return cached, {"source": "cache", "timestamp": cache_ts or "unknown"}

    # 均不可用
    _logger.error("实时抓取和本地缓存均不可用")
    return [], {"source": "unavailable", "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"), "error": "实时抓取和本地缓存均不可用"}


def search_aliexpress(keyword: str, region: str = "us", max_products: int = 20) -> tuple[list[dict], dict]:
    """关键词搜索 AliExpress 产品。"""
    domain = _REGION_DOMAINS.get(region, "aliexpress.com")
    url = f"https://www.{domain}/w/wholesale-{keyword.replace(' ', '-')}.html"

    time.sleep(random.uniform(2.0, 3.0))

    try:
        resp = fetch_page(url, stealth=True, wait_seconds=8)
        if resp.status != 200 or is_blocked(str(resp.text)):
            return [], {"source": "unavailable", "error": f"请求失败 (status={resp.status})"}

        cards = resp.css('div[class*="product-card"]') or resp.css('a[href*="/item/"]')
        products = []
        for i, card in enumerate(cards[:max_products], 1):
            product = _parse_product_card(card, i)
            if product and product.get("title"):
                products.append(product)

        if products:
            return products, {"source": "live", "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}
        return [], {"source": "unavailable", "error": "未找到产品"}
    except Exception as e:
        return [], {"source": "unavailable", "error": str(e)[:100]}
