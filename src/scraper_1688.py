"""
1688 比价模块 — 真实抓取 + AI 估算参考采购价。

策略：
    1. StealthyFetcher 真实浏览器抓取 1688 搜索结果（优先）
    2. AI（OpenAI SDK 兼容）估算参考价（降级）
    3. 本地规则估算（最终兜底）

1688 为 JS 动态渲染网站，需使用 StealthyFetcher（Patchright 反检测浏览器）。

用法：
    from src.scraper_1688 import estimate_1688_price, search_1688_hybrid
    result = search_1688_hybrid("water bottle", 15.99)
"""

from __future__ import annotations

import json
import re
import time
import random
from typing import Optional

import httpx


# ============================================================
# 真实抓取 — 使用 Scrapling StealthyFetcher
# ============================================================

def _scrape_1688_search(keyword: str, max_results: int = 10) -> list[dict]:
    """
    使用 StealthyFetcher 真实抓取 1688 搜索结果。

    1688 是 JS 动态渲染网站，必须用 StealthyFetcher（Patchright 浏览器）。

    Args:
        keyword:     搜索关键词
        max_results: 最多返回产品数

    Returns:
        产品列表，每项包含 title, price, moq, url
    """
    from .scrapling_adapter import fetch_page

    encoded_kw = keyword.replace(" ", "+")
    url = f"https://s.1688.com/selloffer/offer_search.htm?keywords={encoded_kw}"

    delay = random.uniform(2.0, 4.0)
    time.sleep(delay)

    try:
        # 1688 需要 StealthyFetcher（JS 渲染）
        resp = fetch_page(url, stealth=True, wait_seconds=8)

        # 产品卡片选择器（1688 页面结构）
        card_selectors = [
            "div.sm-offer-item",
            "div[data-offer-id]",
            "div.offer-item",
            "div[class*='offer-card']",
            "div[class*='item-card']",
        ]

        cards = []
        for sel in card_selectors:
            cards = resp.css(sel)
            if cards:
                break

        if not cards:
            print(f"[scraper_1688] 未找到产品卡片")
            return []

        print(f"[scraper_1688] 找到 {len(cards)} 个产品卡片")

        products = []
        for i, card in enumerate(cards[:max_results], 1):
            product = _parse_1688_card(card, i)
            if product:
                products.append(product)

        return products

    except Exception as e:
        print(f"[scraper_1688] 真实抓取失败: {e}")
        return []


def _parse_1688_card(card, rank: int) -> Optional[dict]:
    """解析 1688 产品卡片。"""
    # 标题
    title_selectors = [
        "a[class*='title']",
        "div[class*='title']",
        "h4",
        "a[href*='detail']",
    ]
    title = ""
    for sel in title_selectors:
        elem = card.css(sel).first if card.css(sel) else None
        if elem:
            text = str(elem.text).strip()
            if text and len(text) > 5:
                title = text
                break

    if not title:
        return None

    # 价格
    price_selectors = [
        "span[class*='price']",
        "div[class*='price']",
        "em[class*='price']",
    ]
    price = 0.0
    for sel in price_selectors:
        elem = card.css(sel).first if card.css(sel) else None
        if elem:
            text = str(elem.text).strip()
            match = re.search(r'[\d,.]+', text)
            if match:
                try:
                    price = float(match.group(0).replace(",", ""))
                    break
                except ValueError:
                    pass

    # MOQ
    moq = ""
    card_text = str(card.text)
    moq_match = re.search(r'(\d+)\s*(?:件|个|只|起批|起订)', card_text)
    if moq_match:
        moq = moq_match.group(0)

    # URL
    url = ""
    link = card.css("a[href*='detail']").first if card.css("a[href*='detail']") else None
    if not link:
        link = card.css("a[href]").first if card.css("a[href]") else None
    if link:
        href = link.attrib.get("href", "")
        if href:
            if href.startswith("//"):
                href = "https:" + href
            url = href

    return {
        "title": title,
        "price": price,
        "moq": moq,
        "rank": rank,
        "url": url,
    }

# ============================================================
# AI 估算参考价 — 使用 LLM 给出合理采购价区间
# ============================================================

_PRICE_ESTIMATE_PROMPT = """你是一位资深跨境采购专家，熟悉 1688.com 上的批发价格。

请根据以下产品信息，估算该产品在 1688 上的合理批发采购价区间（人民币）。

产品标题：{title}
售价：${price_usd}

请考虑：
1. 产品类型和材质（塑料/不锈钢/电子等）
2. 亚马逊售价与 1688 采购价的典型倍率（通常 3-8 倍）
3. 起订量（MOQ）通常为 2-50 件，量大价格更低

只返回 JSON，不要其他文字：
{{
  "price_min": 最低批发价（人民币），
  "price_max": 最高批发价（人民币），
  "confidence": "high/medium/low"，
  "reason": "一句话说明估算依据（30字内）"
}}"""


def estimate_1688_price(title: str, price_usd: float = 0.0) -> dict:
    """
    使用 AI 估算产品在 1688 上的参考采购价。

    Args:
        title:     产品标题
        price_usd: 产品在亚马逊上的美元售价

    Returns:
        标准格式的结果字典
    """
    # 导入放在函数内，避免循环依赖
    from .config import get_llm_config

    # 获取当前 LLM 配置
    llm_config = get_llm_config()

    if not llm_config.get("configured") or not llm_config.get("api_key"):
        # API 未配置，使用本地估算规则
        return _local_estimate(title, price_usd)

    try:
        prompt = _PRICE_ESTIMATE_PROMPT.format(
            title=title[:80],
            price_usd=price_usd,
        )

        base_url = (llm_config.get("base_url") or "").rstrip("/")
        resp = httpx.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {llm_config['api_key']}",
                "Content-Type": "application/json",
            },
            json={
                "model": llm_config["model"],
                "messages": [
                    {"role": "system", "content": "你是跨境采购价格估算专家。只返回JSON。"},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 2000,
            },
            timeout=60,
        )

        if resp.status_code != 200:
            raise RuntimeError(f"API {resp.status_code}")

        message = resp.json()["choices"][0]["message"]
        content = message.get("content") or ""
        if not content.strip() and message.get("reasoning_content"):
            reasoning = message["reasoning_content"] or ""
            # 从推理内容中提取 JSON
            last_brace = reasoning.rfind("}")
            if last_brace != -1:
                depth = 0
                start = last_brace
                for idx in range(last_brace, -1, -1):
                    if reasoning[idx] == "}":
                        depth += 1
                    elif reasoning[idx] == "{":
                        depth -= 1
                    if depth == 0:
                        start = idx
                        break
                if depth == 0:
                    try:
                        json.loads(reasoning[start:last_brace + 1])
                        content = reasoning[start:last_brace + 1]
                    except json.JSONDecodeError:
                        pass
        content = content.strip()
        # 清理 markdown 代码块包裹
        if content.startswith("```"):
            content = re.sub(r'^```\w*\n?', '', content)
            content = re.sub(r'\n?```$', '', content)
            content = content.strip()

        data = json.loads(content)

        price_min = float(data.get("price_min", 0))
        price_max = float(data.get("price_max", 0))
        confidence = data.get("confidence", "medium")
        reason = data.get("reason", "")

        if price_min > price_max:
            price_min, price_max = price_max, price_min

        return {
            "success": True,
            "keyword": title[:30],
            "source": "ai_estimate",
            "confidence": confidence,
            "results": [
                {
                    "title": f"AI 估算参考价（{confidence}）",
                    "price": price_min,
                    "price_max": price_max,
                    "moq": reason,
                }
            ],
            "price_range": {
                "min": round(price_min, 2),
                "max": round(price_max, 2),
            },
            "error": None,
        }

    except Exception:
        # AI 估算失败，使用本地规则
        return _local_estimate(title, price_usd)


def _local_estimate(title: str, price_usd: float) -> dict:
    """
    本地规则估算 1688 参考价（无需 API 调用）。

    基于产品类型和亚马逊售价，使用典型倍率估算。
    常见倍率：售价 / 采购价 = 3~8 倍。
    """
    # 默认倍率 5 倍
    multiplier = 5.0
    title_lower = title.lower()

    # 根据产品类型调整倍率
    # 电子产品倍率高（8-10倍），日用品倍率低（3-5倍）
    if any(kw in title_lower for kw in ["cable", "charger", "earbuds", "speaker", "electronic", "led", "usb"]):
        multiplier = 8.0
    elif any(kw in title_lower for kw in ["phone", "tablet", "monitor", "camera"]):
        multiplier = 7.0
    elif any(kw in title_lower for kw in ["bottle", "cup", "container", " organizer", "holder", "hanger"]):
        multiplier = 4.0
    elif any(kw in title_lower for kw in ["bag", "case", "cover", "pouch"]):
        multiplier = 4.5
    elif any(kw in title_lower for kw in ["toy", "game", "puzzle"]):
        multiplier = 5.5
    elif any(kw in title_lower for kw in ["shoe", "boot", "sock"]):
        multiplier = 5.0
    elif any(kw in title_lower for kw in ["dress", "shirt", "jacket", "coat"]):
        multiplier = 5.0
    elif any(kw in title_lower for kw in ["tool", "drill", "wrench"]):
        multiplier = 6.0

    # USD 转 CNY（按 7.2 汇率）
    usd_to_cny = 7.2

    if price_usd and price_usd > 0:
        # 亚马逊售价转为人民币后除以倍率
        retail_cny = price_usd * usd_to_cny
        est_min = retail_cny / (multiplier * 1.3)  # 量大价更低
        est_max = retail_cny / (multiplier * 0.8)   # 量少价更高
    else:
        # 无售价信息，给一个宽泛区间
        est_min = 5.0
        est_max = 50.0

    return {
        "success": True,
        "keyword": title[:30],
        "source": "local_estimate",
        "confidence": "low",
        "results": [
            {
                "title": "本地规则估算（仅供参考）",
                "price": round(est_min, 2),
                "price_max": round(est_max, 2),
                "moq": f"基于 {multiplier:.0f} 倍率估算，汇率 {usd_to_cny}",
            }
        ],
        "price_range": {
            "min": round(est_min, 2),
            "max": round(est_max, 2),
        },
        "error": None,
    }


# ============================================================
# 混合策略入口 — AI 估算 + 1688 真实价格
# ============================================================

def search_1688_hybrid(title: str, price_usd: float = 0.0) -> dict:
    """
    获取 1688 参考采购价（真实抓取优先 + AI 估算兜底）。

    策略：
    1. StealthyFetcher 真实浏览器抓取 1688 搜索结果
    2. AI 估算参考价
    3. 本地规则估算（最终兜底）

    Args:
        title:     产品标题
        price_usd: 亚马逊美元售价

    Returns:
        标准格式的结果字典
    """
    # 第一层：真实抓取 1688
    try:
        keyword = title.split(" - ")[0].split(",")[0][:30].strip()
        products = _scrape_1688_search(keyword, max_results=5)
        if products:
            return {
                "success": True,
                "keyword": keyword,
                "source": "1688_real",
                "confidence": "high",
                "results": [
                    {
                        "title": p["title"][:60],
                        "price": p["price"],
                        "price_max": p["price"] * 1.2,
                        "moq": p.get("moq", ""),
                    }
                    for p in products
                ],
                "price_range": {
                    "min": min(p["price"] for p in products if p["price"] > 0) if products else 0,
                    "max": max(p["price"] for p in products if p["price"] > 0) if products else 0,
                },
                "ai_estimate": None,
                "error": None,
            }
    except Exception as e:
        print(f"[scraper_1688] 真实抓取降级: {e}")

    # 第二层：AI 估算
    ai_result = estimate_1688_price(title, price_usd)
    return ai_result
