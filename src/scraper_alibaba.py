"""
阿里巴巴国际站 (alibaba.com) 数据抓取模块 — B2B 批发产品抓取 + 本地缓存。

两层数据获取策略（按优先级）：
    1. 实时抓取 — requests + BeautifulSoup 抓取 alibaba.com 搜索结果
    2. 本地缓存 — 上次成功抓取的结果保存为 JSON，抓取失败时复用

抓取策略：
    - 真实浏览器 User-Agent，模拟正常用户访问
    - 每次请求间隔 1.5-2.5 秒
    - 多套 CSS 选择器兜底，适应页面结构变动
    - 遇验证码自动降级，不反复重试

输出字段：
    title, price, moq, rating, num_reviews, url, image, category
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
)

# ============================================================
# 缓存配置
# ============================================================

_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "cache",
)
_CACHE_TTL = 24 * 60 * 60  # 24 小时

# 阿里巴巴国际站域名
_DOMAIN = "www.alibaba.com"


def _get_cache_file(prefix: str) -> str:
    """返回缓存文件路径。"""
    return os.path.join(_CACHE_DIR, f"alibaba_{prefix}.json")


# ============================================================
# 缓存读写
# ============================================================

def _load_cache(prefix: str) -> Optional[list[dict]]:
    """读取本地缓存的 JSON 数据。"""
    return load_json_cache(_get_cache_file(prefix), max_age_seconds=_CACHE_TTL)


def _save_cache(products: list[dict], prefix: str) -> None:
    """将抓取结果保存为本地 JSON 缓存。"""
    save_json_cache(products, _get_cache_file(prefix))


def _get_cache_timestamp(prefix: str) -> Optional[str]:
    """获取缓存文件的最后修改时间。"""
    return get_cache_timestamp(_get_cache_file(prefix))


# ============================================================
# 产品解析
# ============================================================

def _extract_title(card) -> str:
    """从产品卡片中提取标题。"""
    selectors = [
        "h2.searchx-product-e-title",
        "h2[class*='title']",
        "a[href*='/product-detail/'] h2",
        "div[class*='title'] h2",
    ]
    for sel in selectors:
        elem = card.css(sel).first if card.css(sel) else None
        if elem:
            text = str(elem.text).strip()
            if text and len(text) > 5:
                return text
    # 从链接文本提取
    link = card.css("a[href*='/product-detail/']").first if card.css("a[href*='/product-detail/']") else None
    if link:
        text = str(link.text).strip()
        if text and len(text) > 10:
            # 清理价格和MOQ信息
            text = re.sub(r'CN¥[\d,.]+.*', '', text).strip()
            text = re.sub(r'Min\.\s*order.*', '', text).strip()
            if len(text) > 5:
                return text
    return ""


def _extract_price(card) -> Optional[float]:
    """
    从产品卡片中提取价格。
    Alibaba 价格格式：CN¥53.88, US$5.99
    """
    selectors = [
        "div.searchx-price-area",
        "div[class*='price']",
        "span[class*='price']",
    ]
    for sel in selectors:
        elem = card.css(sel).first if card.css(sel) else None
        if elem:
            text = str(elem.text).strip()
            price = _parse_alibaba_price(text)
            if price and price > 0:
                return price
    return None


def _parse_alibaba_price(text: str) -> Optional[float]:
    """解析阿里巴巴价格，支持 CN¥ 和 US$ 格式。"""
    if not text:
        return None

    # 检测货币
    is_cny = "CN¥" in text or "¥" in text
    is_usd = "US$" in text or "$" in text

    # 提取第一个数字
    match = re.search(r'[\d,.]+', text)
    if match:
        try:
            price = float(match.group(0).replace(",", ""))
            # 如果是人民币，转换为美元（近似）
            if is_cny and not is_usd:
                price = price / 7.24  # CNY -> USD
            return round(price, 2)
        except ValueError:
            pass
    return None


def _extract_moq(card) -> str:
    """提取最小起订量。"""
    text = str(card.text).strip()
    match = re.search(r'Min\.\s*order:\s*([\d,]+)', text, re.I)
    if match:
        return match.group(1)
    return ""


def _extract_rating(card) -> Optional[float]:
    """提取评分。格式: 4.2/5.0(58)"""
    text = str(card.text).strip()
    match = re.search(r'(\d+\.?\d*)\s*/\s*5\.?\d*', text)
    if match:
        rating = float(match.group(1))
        if 0 < rating <= 5:
            return rating
    return None


def _extract_reviews(card) -> int:
    """提取评论数。格式: 4.2/5.0(58)"""
    text = str(card.text).strip()
    match = re.search(r'\((\d+)\)', text)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass
    return 0


def _extract_url(card) -> str:
    """提取产品链接。"""
    link = card.css("a[href*='/product-detail/']").first if card.css("a[href*='/product-detail/']") else None
    if link:
        href = link.attrib.get("href", "")
        if href:
            if href.startswith("//"):
                href = "https:" + href
            elif href.startswith("/"):
                href = "https://www.alibaba.com" + href
            return href
    return ""


def _extract_image(card) -> str:
    """提取图片 URL。"""
    img = card.css("img[src*='alicdn']").first if card.css("img[src*='alicdn']") else None
    if not img:
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
        "moq": _extract_moq(card),
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

# 阿里巴巴产品卡片选择器
_CARD_SELECTORS = [
    "div.fy26-product-card-wrapper",
    "div[class*='product-card']",
    "div[class*='organic-list'] > div",
]


def _scrape_alibaba_search(keyword: str, max_results: int = 30) -> list[dict]:
    """
    抓取阿里巴巴国际站搜索结果。

    Args:
        keyword:     搜索关键词
        max_results: 最多返回产品数
    """
    encoded_kw = keyword.replace(" ", "+")
    url = f"https://{_DOMAIN}/trade/search?SearchText={encoded_kw}&tab=all"

    delay = random.uniform(1.5, 2.5)
    time.sleep(delay)

    resp = fetch_page(url)
    print(f"[scraper_alibaba] HTTP {resp.status} | URL: {url}")

    if is_blocked(str(resp.text)):
        raise RuntimeError("被阿里巴巴反爬拦截")

    cards = []
    for sel in _CARD_SELECTORS:
        cards = resp.css(sel)
        if cards:
            break

    print(f"[scraper_alibaba] 找到 {len(cards)} 个产品卡片")

    products = []
    for i, card in enumerate(cards[:max_results], 1):
        product = _parse_product_card(card, i)
        if product:
            products.append(product)

    return products


# ============================================================
# 公开接口
# ============================================================

def fetch_alibaba_best_sellers(region: str = "us") -> tuple[list[dict], dict]:
    """
    获取阿里巴巴国际站热销产品列表（两层降级策略）。

    Args:
        region: 地区代码（仅 us，阿里巴巴国际站无地区差异）

    Returns:
        (products, source_info) 元组
    """
    # ---------- 第一层：实时抓取 ----------
    try:
        products = _scrape_alibaba_search("best seller", max_results=30)
        if len(products) >= 3:
            _save_cache(products, "best_sellers")
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            return products, {"source": "live", "timestamp": timestamp}
        else:
            print(f"[!] 阿里巴巴实时抓取仅获得 {len(products)} 个产品，降级到缓存")
    except Exception as e:
        print(f"[!] 阿里巴巴实时抓取失败: {e}")

    # ---------- 第二层：本地缓存 ----------
    cached = _load_cache("best_sellers")
    if cached and len(cached) >= 3:
        cache_ts = _get_cache_timestamp("best_sellers")
        print(f"[*] 使用阿里巴巴本地缓存 ({len(cached)} 个产品)")
        return cached, {"source": "cache", "timestamp": cache_ts or "unknown"}

    # ---------- 均不可用 ----------
    print("[X] 阿里巴巴实时抓取和本地缓存均不可用")
    return [], {
        "source": "unavailable",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "error": "阿里巴巴国际站实时抓取和本地缓存均不可用",
    }


def search_alibaba(keyword: str, region: str = "us", max_results: int = 30) -> dict:
    """
    在阿里巴巴国际站搜索指定关键词，返回产品列表。
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
        products = _scrape_alibaba_search(keyword, max_results=max_results)
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
            "error": f"阿里巴巴反爬拦截: {e}",
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
