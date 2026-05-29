"""
1688 比价模块 — AI 估算参考采购价。

策略：使用 AI（OpenAI SDK 兼容）估算产品在 1688 上的合理批发价，
失败时降级为本地规则估算。1688 为 JS 动态渲染，无法通过 requests 直接抓取。

用法：
    from src.scraper_1688 import estimate_1688_price, search_1688_hybrid
    result = search_1688_hybrid("water bottle", 15.99)
"""

import json
import re
from typing import Optional

from openai import OpenAI

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
        client = OpenAI(
            api_key=llm_config["api_key"],
            base_url=llm_config.get("base_url") or None,
            timeout=60,
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
            max_tokens=2000,
        )

        content = response.choices[0].message.content or ""
        if not content.strip() and hasattr(response.choices[0].message, "reasoning_content"):
            reasoning = response.choices[0].message.reasoning_content or ""
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
    获取 1688 参考采购价（AI 估算）。

    1688 为 JS 动态渲染网站，无法通过 requests 直接抓取，
    因此使用 AI 估算 + 本地规则降级策略。

    Args:
        title:     产品标题
        price_usd: 亚马逊美元售价

    Returns:
        标准格式的结果字典
    """
    # AI 估算（快速返回）
    ai_result = estimate_1688_price(title, price_usd)
    return ai_result
