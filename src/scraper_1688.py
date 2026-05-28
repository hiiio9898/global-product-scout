"""
1688 比价模块 — 混合策略获取参考采购价。

策略优先级：
    1. AI 估算参考价（秒返回，永不失败）
    2. 尝试抓取 1688 真实价格（可能被反爬拦截）
    3. 失败时返回 AI 估算结果 + 手动搜索链接

用法：
    from src.scraper_1688 import search_1688
    result = search_1688("water bottle")
"""

import json
import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup
from openai import OpenAI

# 请求间隔（秒），避免触发 1688 反爬
_REQUEST_DELAY = 3

# 真实浏览器 User-Agent
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


def search_1688(keyword: str, max_results: int = 3) -> dict:
    """
    在 1688 上搜索产品，返回价格区间。

    Args:
        keyword:     搜索关键词（通常为产品标题的前 30 字）
        max_results: 最多返回几个结果

    Returns:
        {
            "success": bool,
            "keyword": str,
            "results": [{"title": str, "price": float, "moq": str}],
            "price_range": {"min": float, "max": float} | None,
            "error": str | None,
        }
    """
    if not keyword or not keyword.strip():
        return {
            "success": False,
            "keyword": keyword,
            "results": [],
            "price_range": None,
            "error": "搜索关键词为空",
        }

    keyword = keyword.strip()[:50]  # 限制长度

    # 请求间隔
    time.sleep(_REQUEST_DELAY)

    try:
        url = f"https://s.1688.com/selloffer/offer_search.htm?keywords={keyword}"
        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

        resp = requests.get(url, headers=headers, timeout=15)

        # 检查响应
        if resp.status_code != 200:
            return {
                "success": False,
                "keyword": keyword,
                "results": [],
                "price_range": None,
                "error": f"1688 返回状态码 {resp.status_code}，可能被反爬拦截",
            }

        # 检查是否被重定向到登录页
        if "login" in resp.url.lower() or "passport" in resp.url.lower():
            return {
                "success": False,
                "keyword": keyword,
                "results": [],
                "price_range": None,
                "error": "1688 要求登录，暂时无法自动获取",
            }

        # 尝试解析 HTML
        soup = BeautifulSoup(resp.text, "html.parser")

        # 1688 搜索结果的多种选择器
        results = []

        # 尝试方案 1：直接解析搜索结果卡片
        cards = soup.select(
            ".sm-offer-item, .offer-list-row, "
            "[class*='offer-item'], [class*='card-container']"
        )

        for card in cards[:max_results]:
            title_el = card.select_one(
                "[class*='title'], [class*='subject'], "
                "a[href*='detail.1688.com']"
            )
            price_el = card.select_one(
                "[class*='price'], [class*='price-element']"
            )
            moq_el = card.select_one(
                "[class*='quantity'], [class*='moq']"
            )

            if title_el and price_el:
                title_text = title_el.get_text(strip=True)[:80]
                price_text = price_el.get_text(strip=True)
                price = _extract_price(price_text)
                moq = moq_el.get_text(strip=True) if moq_el else ""

                if price and price > 0:
                    results.append({
                        "title": title_text,
                        "price": price,
                        "moq": moq,
                    })

        # 尝试方案 2：从页面 JSON 数据中提取
        if not results:
            scripts = soup.find_all("script")
            for script in scripts:
                text = script.string or ""
                # 查找包含价格信息的 JSON 片段
                price_matches = re.findall(r'"price"[:\s]*"?([\d.]+)"?', text)
                title_matches = re.findall(r'"subject"[:\s]*"([^"]+)"', text)
                if price_matches and title_matches:
                    for i in range(min(len(price_matches), len(title_matches), max_results)):
                        try:
                            results.append({
                                "title": title_matches[i][:80],
                                "price": float(price_matches[i]),
                                "moq": "",
                            })
                        except (ValueError, IndexError):
                            continue

        if results:
            prices = [r["price"] for r in results]
            return {
                "success": True,
                "keyword": keyword,
                "results": results,
                "price_range": {
                    "min": round(min(prices), 2),
                    "max": round(max(prices), 2),
                },
                "error": None,
            }
        else:
            # 解析成功但无结果
            return {
                "success": False,
                "keyword": keyword,
                "results": [],
                "price_range": None,
                "error": (
                    "未在 1688 搜索结果中找到价格信息。"
                    "1688 页面为 JS 动态渲染，部分数据可能无法通过请求获取。"
                    f"建议手动搜索：https://s.1688.com/selloffer/offer_search.htm?keywords={keyword}"
                ),
            }

    except requests.Timeout:
        return {
            "success": False,
            "keyword": keyword,
            "results": [],
            "price_range": None,
            "error": "请求超时，1688 服务器响应过慢",
        }
    except requests.RequestException as e:
        return {
            "success": False,
            "keyword": keyword,
            "results": [],
            "price_range": None,
            "error": f"网络请求失败：{str(e)[:50]}",
        }
    except Exception as e:
        return {
            "success": False,
            "keyword": keyword,
            "results": [],
            "price_range": None,
            "error": f"解析失败：{str(e)[:50]}",
        }


def _extract_price(text: str) -> Optional[float]:
    """从价格文本中提取数字。"""
    if not text:
        return None
    # 匹配 ¥12.50 或 12.50 或 12-15 等格式
    match = re.search(r'(\d+\.?\d*)', text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return None


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
        与 search_1688 相同格式的结果字典
    """
    # 导入放在函数内，避免循环依赖
    from .config import get_llm_config

    # 获取当前 LLM 配置
    llm_config = get_llm_config()

    if not llm_config.get("configured") or not llm_config.get("api_key"):
        # API 未配置，使用本地估算规则
        return _local_estimate(title, price_usd)

    try:
        client = OpenAI(
            api_key=llm_config["api_key"],
            base_url=llm_config.get("base_url") or None,
            timeout=15,
        )

        prompt = _PRICE_ESTIMATE_PROMPT.format(
            title=title[:80],
            price_usd=price_usd,
        )

        response = client.chat.completions.create(
            model=llm_config["model"],
            messages=[
                {"role": "system", "content": "你是跨境采购价格估算专家。只返回JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=200,
        )

        content = response.choices[0].message.content.strip()
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
    混合策略获取 1688 参考价：
    1. 立即返回 AI 估算结果
    2. 尝试抓取 1688 真实价格（成功则替换估算）

    Args:
        title:     产品标题
        price_usd: 亚马逊美元售价

    Returns:
        与 search_1688 相同格式的结果字典
    """
    # 第一步：AI 估算（快速返回）
    keyword = title[:30].strip()
    ai_result = estimate_1688_price(title, price_usd)

    # 第二步：尝试真实抓取
    real_result = search_1688(keyword)

    if real_result["success"]:
        # 真实抓取成功，合并结果
        real_result["source"] = "1688_real"
        real_result["ai_estimate"] = ai_result.get("price_range")
        return real_result
    else:
        # 真实抓取失败，使用 AI 估算
        ai_result["fallback_reason"] = "1688 页面为 JS 动态渲染，已使用 AI 估算参考价"
        return ai_result
