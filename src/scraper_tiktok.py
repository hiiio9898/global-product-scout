"""
TikTok Shop 数据抓取模块 — 东南亚 5 站点关键词搜索。

⚠️ 可靠性说明：
    TikTok Shop 是反爬最重的平台（HTTP 基本必败，CSS 选择器每 2-4 周变）。
    本模块用 StealthyFetcher（浏览器）抓取，解析内嵌 JSON / data-e2e 属性（避开易变的 class）。
    预期成功率低，失败时优雅返回空结果，不崩溃。

设计：
    - stealth_only：HTTP Fetcher 对 TikTok 无效，直接用浏览器
    - 只支持关键词搜索（TikTok 无公开热销榜）
    - 5 东南亚站点：sg 新加坡 / ph 菲律宾 / th 泰国 / vn 越南 / id 印尼
    - 地区通过 URL + locale 参数区分（无住宅代理时可能不准，接受）

输出字段：
    title, price, rating, num_reviews, url, image, currency
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
    is_blocked, parse_price, parse_rating, parse_review_count,
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

# 东南亚 5 站点：货币 + locale
_REGION_CONFIG = {
    "sg": {"name": "新加坡",   "currency": "SGD", "locale": "en-SG"},
    "ph": {"name": "菲律宾",   "currency": "PHP", "locale": "en-PH"},
    "th": {"name": "泰国",     "currency": "THB", "locale": "th-TH"},
    "vn": {"name": "越南",     "currency": "VND", "locale": "vi-VN"},
    "id": {"name": "印尼",     "currency": "IDR", "locale": "id-ID"},
}


def _get_cache_file(region: str, keyword: str) -> str:
    """获取缓存文件路径（按 region+keyword 区分）。"""
    os.makedirs(_CACHE_DIR, exist_ok=True)
    safe_kw = re.sub(r"[^\w-]", "", keyword.replace(" ", "-"))[:30] or "kw"
    return os.path.join(_CACHE_DIR, f"tiktok_search_{region}_{safe_kw}.json")


# ============================================================
# 解析：优先内嵌 JSON，回退 data-e2e / 通用选择器
# ============================================================

def _extract_embedded_json(html: str) -> list:
    """
    从页面内嵌 <script> 中提取产品数据。

    TikTok SPA 常把数据塞进 `__UNIVERSAL_DATA_FOR_REHYDRATION__` 或 `__DEFAULT_SCOPE__`。
    这些 JSON 结构会变，这里用宽松递归搜索：找所有含 title+price 字段的 dict。
    """
    products = []
    # 候选 script id
    for pattern in (
        r'__UNIVERSAL_DATA_FOR_REHYDRATION__[^>]*>(.*?)</script>',
        r'__DEFAULT_SCOPE__[^>]*>(.*?)</script>',
        r'id="__SIGI_STATE__"[^>]*>(.*?)</script>',
    ):
        for m in re.finditer(pattern, html, re.DOTALL):
            try:
                data = json.loads(m.group(1).strip())
            except Exception as e:
                continue
            _harvest_products(data, products)
    return products


def _harvest_products(node, out: list, depth: int = 0):
    """递归遍历 JSON，收集看起来像产品的 dict（含 title 且有价格或 url）。"""
    if depth > 12:
        return
    if isinstance(node, dict):
        title = node.get("title") or node.get("product_name") or node.get("name")
        if isinstance(title, str) and len(title) > 3:
            price = node.get("price") or node.get("price_info") or node.get("sale_price")
            url = node.get("product_link") or node.get("url") or node.get("link")
            if price is not None or url:
                out.append({
                    "title": title,
                    "price": _coerce_price(price),
                    "url": url if isinstance(url, str) else "",
                    "image": node.get("thumb_url") or node.get("image") or node.get("main_image") or "",
                    "rating": _coerce_float(node.get("rating")),
                    "num_reviews": _coerce_int(node.get("reviews") or node.get("sold") or node.get("sales")),
                })
        for v in node.values():
            _harvest_products(v, out, depth + 1)
    elif isinstance(node, list):
        for v in node:
            _harvest_products(v, out, depth + 1)


def _coerce_price(v) -> float:
    """从价格字段（可能是 dict/str/number）提取数值。"""
    if v is None:
        return 0.0
    if isinstance(v, dict):
        v = v.get("price") or v.get("value") or v.get("amount")
    if isinstance(v, (int, float)):
        return float(v)
    p = parse_price(str(v))
    return p or 0.0


def _coerce_float(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (ValueError, TypeError):
        return 0.0


def _coerce_int(v) -> int:
    try:
        return int(v) if v is not None else 0
    except (ValueError, TypeError):
        return 0


def _parse_card_dom(card, rank: int) -> Optional[dict]:
    """DOM 回退解析：用 data-e2e 属性 + img alt（避开易变的 class）。"""
    title = ""
    # data-e2e 是 TikTok 相对稳定的钩子属性
    for sel in ['[data-e2e*="title"]', '[data-e2e*="product-name"]', 'a[aria-label]']:
        elem = card.css(sel).first if card.css(sel) else None
        if elem:
            t = (elem.attrib.get('aria-label') or str(elem.text) or "").strip()
            if t and len(t) > 3:
                title = t
                break
    if not title:
        img = card.css('img').first if card.css('img') else None
        if img:
            title = (img.attrib.get('alt') or '').strip()
    if not title:
        return None

    price = 0.0
    for sel in ['[data-e2e*="price"]', 'span[class*="price"]']:
        elem = card.css(sel).first if card.css(sel) else None
        if elem:
            price = parse_price(str(elem.text)) or 0.0
            if price > 0:
                break

    url = ""
    link = card.css('a[href*="/product"]').first if card.css('a[href*="/product"]') else None
    if link:
        href = link.attrib.get('href', '')
        url = href if href.startswith('http') else f"https://shop.tiktok.com{href}"

    image = ""
    img = card.css('img').first if card.css('img') else None
    if img:
        image = img.attrib.get('src', '') or img.attrib.get('data-src', '')

    return {
        "title": title,
        "price": price,
        "rating": 0.0,
        "num_reviews": 0,
        "rank": rank,
        "category": "",
        "url": url,
        "image": image,
    }


# ============================================================
# 真实抓取
# ============================================================

def _scrape_tiktok_search(keyword: str, region: str = "id", max_results: int = 20) -> list[dict]:
    """
    用 StealthyFetcher 抓 TikTok Shop 搜索结果。

    TikTok 反爬重，HTTP 必败；这里强制浏览器渲染。
    """
    rc = _REGION_CONFIG.get(region, _REGION_CONFIG["id"])
    encoded_kw = keyword.replace(" ", "%20")
    # TikTok Shop 搜索端点（www.tiktok.com/shop/search，shop.tiktok.com 子域已弃用返 404）
    # 地区通过 locale 参数 + 浏览器 geo 区分
    url = (f"https://www.tiktok.com/shop/search?q={encoded_kw}"
           f"&region={region}&locale={rc['locale']}")

    time.sleep(random.uniform(2.0, 4.0))

    # stealth=True 直接走浏览器
    resp = fetch_page(url, stealth=True, wait_seconds=8.0,
                      wait_selector='[data-e2e], a[href*="/product"]')
    _logger.info(f"[scraper_tiktok] HTTP {resp.status} | region={region} | URL: {url}")

    if resp.status != 200 or is_blocked(str(resp.text)):
        raise RuntimeError(f"TikTok 反爬拦截或请求失败 (status={resp.status})")

    html = str(resp.text)
    products = []

    # 策略1：内嵌 JSON（最可靠，避开易变 class）
    embedded = _extract_embedded_json(html)
    for p in embedded[:max_results]:
        if p.get("title"):
            p["rank"] = len(products) + 1
            p.setdefault("category", "")
            products.append(p)
    _logger.info(f"[scraper_tiktok] 内嵌 JSON 提取到 {len(products)} 个产品")

    # 策略2：DOM 回退（data-e2e）
    if len(products) < 3:
        cards = (resp.css('[data-e2e*="product"]')
                 or resp.css('[data-e2e*="card"]')
                 or resp.css('a[href*="/product"]'))
        rank = len(products) + 1
        for card in cards[:max_results]:
            parsed = _parse_card_dom(card, rank)
            if parsed and parsed.get("title"):
                products.append(parsed)
                rank += 1
        _logger.info(f"[scraper_tiktok] DOM 回退后共 {len(products)} 个产品")

    # 清洗：去重 + 标注货币
    seen = set()
    cleaned = []
    for p in products:
        t = (p.get("title") or "").strip()
        if not t or t in seen:
            continue
        seen.add(t)
        p["currency"] = rc["currency"]
        cleaned.append(p)
        if len(cleaned) >= max_results:
            break

    return cleaned


# ============================================================
# 公开接口
# ============================================================

def search_tiktok(keyword: str, region: str = "id", max_results: int = 20) -> dict:
    """
    在 TikTok Shop 搜索关键词（东南亚站点）。

    Args:
        keyword:     搜索关键词（英文）
        region:      sg/ph/th/vn/id，默认 id（印尼，TikTok Shop 最大市场）
        max_results: 最多返回产品数

    Returns:
        与 Amazon 同形态 dict：
        {success, keyword, results, total_found, source, scrape_time, error}
    """
    keyword = (keyword or "").strip()
    rc = _REGION_CONFIG.get(region, _REGION_CONFIG["id"])
    scrape_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    if not keyword:
        return {"success": False, "keyword": keyword, "results": [], "total_found": 0,
                "source": "none", "scrape_time": scrape_time, "error": "关键词不能为空"}

    # 第一层：实时抓取
    try:
        products = _scrape_tiktok_search(keyword, region=region, max_results=max_results)
        if products:
            save_json_cache(products, _get_cache_file(region, keyword))
            return {"success": True, "keyword": keyword, "results": products,
                    "total_found": len(products), "source": "live",
                    "scrape_time": scrape_time, "error": None}
        # 实时 0 结果 → 试缓存
        cached = load_json_cache(_get_cache_file(region, keyword))
        if cached:
            return {"success": True, "keyword": keyword, "results": cached,
                    "total_found": len(cached), "source": "cache",
                    "scrape_time": get_cache_timestamp(_get_cache_file(region, keyword)) or scrape_time,
                    "error": None}
        return {"success": False, "keyword": keyword, "results": [], "total_found": 0,
                "source": "none", "scrape_time": scrape_time,
                "error": f"TikTok {rc['name']} 未返回产品（反爬常态，建议重试或换站点）"}
    except RuntimeError as e:
        return {"success": False, "keyword": keyword, "results": [], "total_found": 0,
                "source": "none", "scrape_time": scrape_time,
                "error": f"TikTok 反爬拦截：{e}"}
    except Exception as e:
        return {"success": False, "keyword": keyword, "results": [], "total_found": 0,
                "source": "none", "scrape_time": scrape_time,
                "error": f"TikTok 搜索失败：{str(e)[:120]}"}


def fetch_tiktok_best_sellers(region: str = "id") -> tuple[list[dict], dict]:
    """
    TikTok Shop 无公开热销榜 → 返回优雅空结果 + 提示用关键词搜索。

    Returns:
        ([], {"source": "unavailable", "error": "TikTok 无公开热销榜..."})
    """
    rc = _REGION_CONFIG.get(region, _REGION_CONFIG["id"])
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return [], {
        "source": "unavailable",
        "timestamp": ts,
        "error": f"TikTok {rc['name']} 无公开热销榜，请改用「指定选品」关键词搜索",
    }
