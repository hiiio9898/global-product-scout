"""
分析模块 — 调用 DeepSeek API 进行五维度选品评估。

角色定位：资深跨境电商选品顾问。
分析维度：市场容量、竞争程度、利润潜力、新手友好度、季节性风险。
每个维度 1-10 分 + 解释，最终给出推荐/谨慎/不推荐 verdict。

使用 OpenAI SDK 兼容模式调用 DeepSeek（base_url="https://api.deepseek.com"）。
API Key 未配置时自动降级为本地模拟分析，结构完全一致。
JSON 解析失败时回退为纯文本展示。
"""

import json
import time
from openai import OpenAI

from .config import get_config

# ============================================================
# 系统 Prompt — 资深跨境电商选品顾问
# ============================================================

SYSTEM_PROMPT = """你是一位拥有 10 年经验的资深跨境电商选品顾问，专精于 Amazon 平台。

请从以下五个维度对给定产品进行量化评估，每个维度给出 1-10 分（10 分为最优）并附 1-2 句解释：

1. 市场容量（market_capacity）：该产品的市场需求规模（搜索量、类目总销量）
2. 竞争程度（competition）：注意：分数越高表示竞争越激烈（对卖家越不利）
3. 利润潜力（profit_potential）：扣除采购、物流、平台佣金后的净利润空间
4. 新手友好度（beginner_friendly）：启动资金要求、认证门槛、运营复杂度
5. 季节性风险（seasonality_risk）：注意：分数越高表示季节性波动越大（对卖家越不利）

最后给出：
- final_verdict：取值为 "recommended"（推荐）、"cautious"（谨慎）或 "not_recommended"（不推荐）
- verdict_reason：一句话总结判断依据（50 字以内）

以严格 JSON 格式返回，不要包含任何其他文字。格式示例：
{
  "market_capacity": {"score": 8, "reason": "月搜索量约50万，类目年增长率15%"},
  "competition": {"score": 7, "reason": "头部5个品牌占据60%份额，新卖家破局需差异化"},
  "profit_potential": {"score": 6, "reason": "采购成本$8，FBA费用$5，净利率约25%"},
  "beginner_friendly": {"score": 9, "reason": "轻小件物流简单，无需特殊认证，启动资金<$2000"},
  "seasonality_risk": {"score": 2, "reason": "全年稳定需求，无明显淡旺季波动"},
  "final_verdict": "recommended",
  "verdict_reason": "高需求低门槛低风险，适合新手入门选品，建议差异化包装提升竞争力"
}
只返回 JSON。"""


# ============================================================
# 模拟分析引擎 — 与 DeepSeek 输出结构完全一致
# ============================================================

def _mock_analyze(product: dict) -> dict:
    """
    本地模拟分析 — 基于产品多维数据生成五维度量化评分。

    评分逻辑：
        - 市场容量：评论数越高 → 市场越大（但上限为 9，留余地给真实数据）
        - 竞争程度：评论数越高 → 竞争越激烈（反向关系）
        - 利润潜力：价格区间 + 类目推断毛利率
        - 新手友好度：类目特性（电子低、家居高）+ 价格门槛
        - 季节性风险：类目特性（服装高、日用品低）
        - final_verdict：综合加权计算

    返回结构与 DeepSeek API 输出完全一致，确保前端无缝渲染。
    """
    title = product["title"]
    price = product.get("price", 0) or 0
    rating = product.get("rating", 0) or 0
    reviews = product.get("num_reviews", 0) or 0
    category = product.get("category", "")
    title_lower = title.lower()

    # ---- 市场容量（基于评论数推算） ----
    if reviews > 50000:
        mc_score, mc_reason = 9, "头部类目，月搜索量百万级，市场容量极大"
    elif reviews > 20000:
        mc_score, mc_reason = 7, "中大型类目，月搜索量数十万级，需求旺盛"
    elif reviews > 10000:
        mc_score, mc_reason = 6, "中等类目，市场有一定规模，增长稳定"
    elif reviews > 5000:
        mc_score, mc_reason = 4, "中小类目，需求较集中，天花板有限"
    else:
        mc_score, mc_reason = 3, "小众类目，市场规模较小但可能有蓝海机会"

    # ---- 竞争程度（评论数越高竞争越激烈） ----
    if reviews > 50000:
        comp_score, comp_reason = 9, "头部品牌垄断严重，广告竞价高，新卖家进入难度大"
    elif reviews > 20000:
        comp_score, comp_reason = 7, "竞争激烈但存在细分缝隙市场，需差异化切入"
    elif reviews > 10000:
        comp_score, comp_reason = 5, "竞争适中，腰部卖家有机会通过优化 Listing 突围"
    elif reviews > 5000:
        comp_score, comp_reason = 3, "竞争较低，早期进入者可建立先发优势"
    else:
        comp_score, comp_reason = 2, "蓝海类目，竞争对手少，易于占领市场份额"

    # ---- 利润潜力（基于价格 + 类目） ----
    if price < 15:
        profit_score, profit_reason = 4, "客单价低，毛利空间有限需走量。FBA费用占比高，净利约15-25%"
    elif price < 25:
        profit_score, profit_reason = 6, "轻小件物流成本可控，毛利率约35-50%，净利空间良好"
    elif price < 40:
        profit_score, profit_reason = 7, "中等价位利润可观，毛利率约30-45%，单品利润绝对值高"
    else:
        profit_score, profit_reason = 8, "高客单价毛利率25-35%，单笔利润高但资金周转需注意"

    # 按类目微调利润
    if "electronics" in category.lower():
        profit_score = max(1, profit_score - 1)
        profit_reason += "。电子类退货率较高需预留售后成本"

    # ---- 新手友好度（基于类目 + 价格） ----
    if "speaker" in title_lower or "charger" in title_lower or "power bank" in title_lower or "lamp" in title_lower:
        bf_score, bf_reason = 4, "电子产品需FCC/UL认证，存在退货和售后压力，启动资金$3000+"
    elif "t-shirt" in title_lower or "cotton" in title_lower:
        bf_score, bf_reason = 5, "服装类需管理尺码和颜色SKU，退货率偏高，但采购门槛不高"
    elif "pillow" in title_lower:
        bf_score, bf_reason = 8, "轻小件无认证门槛，物流简单，启动资金$1000即够"
    elif "bottle" in title_lower:
        bf_score, bf_reason = 8, "耐用品复购好，无特殊认证，适合新手试水"
    elif "cutting board" in title_lower:
        bf_score, bf_reason = 9, "厨房用品无认证门槛，退货率极低，启动资金$500-$1000"
    else:
        bf_score, bf_reason = 6, "类目门槛适中，建议先小批量试销验证市场反应"

    if price > 30:
        bf_score = max(1, bf_score - 1)
        bf_reason += "。客单价较高，需要更多启动资金"

    # ---- 季节性风险 ----
    if "t-shirt" in title_lower or "cotton" in title_lower:
        sr_score, sr_reason = 7, "服装有换季需求波动，需精准备货避免库存积压"
    elif "speaker" in title_lower or "charger" in title_lower or "power bank" in title_lower:
        sr_score, sr_reason = 3, "电子产品全年需求稳定，Q4 旺季（黑五/圣诞）销量冲高"
    elif "pillow" in title_lower:
        sr_score, sr_reason = 4, "旅行用品暑假和节假日为旺季，平时需求略降但整体稳定"
    elif "bottle" in title_lower:
        sr_score, sr_reason = 2, "日用品全年需求均衡，夏天略高但不影响整体稳定性"
    elif "lamp" in title_lower:
        sr_score, sr_reason = 3, "办公/学习场景需求稳定，开学季小幅冲高"
    elif "cutting board" in title_lower:
        sr_score, sr_reason = 2, "厨房刚需品，全年无显著季节性波动"
    else:
        sr_score, sr_reason = 3, "需求波动较小，属于稳定性类目"

    # ---- 综合 verdict ----
    # 加权计算：市场容量(正向) + 利润(正向) + 新手友好(正向) - 竞争(反向) - 季节风险(反向)
    weighted = (
        mc_score * 1.0
        + profit_score * 1.2
        + bf_score * 0.8
        - comp_score * 1.0
        - sr_score * 0.5
    )
    if weighted >= 12:
        final_verdict = "recommended"
        verdict_reason = "市场容量大、利润可观、新手友好，综合选品价值高，建议入手"
    elif weighted >= 8:
        final_verdict = "cautious"
        verdict_reason = "有一定机会但需注意竞争或季节性风险，建议精细化运营后进入"
    else:
        final_verdict = "not_recommended"
        verdict_reason = "竞争激烈或利润偏低，新手进入风险较高，建议观望或寻找细分切口"

    return {
        "title": title,
        "market_capacity": {"score": mc_score, "reason": mc_reason},
        "competition": {"score": comp_score, "reason": comp_reason},
        "profit_potential": {"score": profit_score, "reason": profit_reason},
        "beginner_friendly": {"score": bf_score, "reason": bf_reason},
        "seasonality_risk": {"score": sr_score, "reason": sr_reason},
        "final_verdict": final_verdict,
        "verdict_reason": verdict_reason,
    }


# ============================================================
# JSON 解析与容错
# ============================================================

def _parse_ai_response(content: str, product_title: str) -> dict:
    """
    解析 DeepSeek 返回的 JSON 字符串。

    容错策略：
        1. 清理 markdown 代码块标记（```json ... ```）
        2. 尝试 json.loads 直接解析
        3. 尝试提取第一个 { 到最后一个 } 之间的内容再解析
        4. 全部失败则回退为纯文本展示

    Returns:
        成功时返回标准分析字典，失败时返回纯文本回退字典。
    """
    # 清理 markdown 包裹
    cleaned = content.strip()
    if cleaned.startswith("```"):
        parts = cleaned.split("```")
        if len(parts) >= 2:
            cleaned = parts[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip()

    # 尝试直接解析
    try:
        data = json.loads(cleaned)
        if _validate_result(data):
            data["title"] = product_title
            return data
    except json.JSONDecodeError:
        pass

    # 尝试提取 JSON 块
    try:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            data = json.loads(cleaned[start:end + 1])
            if _validate_result(data):
                data["title"] = product_title
                return data
    except json.JSONDecodeError:
        pass

    # 回退：纯文本展示
    return {
        "title": product_title,
        "raw_text": content,
        "parse_error": True,
        "final_verdict": "cautious",
        "verdict_reason": "AI 返回格式异常，请查看原始文本",
    }


def _validate_result(data: dict) -> bool:
    """验证解析结果包含必要的五维度字段。"""
    required_keys = [
        "market_capacity", "competition", "profit_potential",
        "beginner_friendly", "seasonality_risk",
    ]
    for key in required_keys:
        if key not in data:
            return False
        dim = data[key]
        if not isinstance(dim, dict):
            return False
        if "score" not in dim or "reason" not in dim:
            return False
    if "final_verdict" not in data:
        return False
    return True


# ============================================================
# 批量分析入口
# ============================================================

def analyze_products(products: list[dict]) -> list[dict]:
    """
    批量分析产品 — 五维度量化评估。

    每个产品返回字典结构：
        {
            "title": "...",
            "market_capacity":    {"score": 1-10, "reason": "..."},
            "competition":        {"score": 1-10, "reason": "..."},
            "profit_potential":   {"score": 1-10, "reason": "..."},
            "beginner_friendly":  {"score": 1-10, "reason": "..."},
            "seasonality_risk":   {"score": 1-10, "reason": "..."},
            "final_verdict":      "recommended" | "cautious" | "not_recommended",
            "verdict_reason":     "一句话总结"
        }

    优先使用 DeepSeek API（需配置 DEEPSEEK_API_KEY），
    否则降级为本地模拟分析。
    单产品 API 调用失败重试 1 次，仍失败则使用模拟结果。
    JSON 解析失败时回退为纯文本展示（raw_text 字段）。
    """
    cfg = get_config()
    api_key = cfg["deepseek_api_key"]

    # 无 API Key → 全部模拟
    if not api_key:
        return [_mock_analyze(p) for p in products]

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com", timeout=45)
    results = []

    for product in products:
        # 构建用户 prompt
        prompt = (
            f"产品名称：{product['title']}\n"
            f"售价：${product.get('price', 'N/A')}\n"
            f"评分：{product.get('rating', 'N/A')}\n"
            f"评论数：{product.get('num_reviews', 'N/A')}\n"
            f"类目：{product.get('category', '未知')}\n"
            f"BSR排名：#{product.get('rank', 'N/A')}\n"
        )

        result = None
        for attempt in range(2):
            try:
                resp = client.chat.completions.create(
                    model=cfg["deepseek_model"],
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.7,
                    max_tokens=800,
                )
                content = resp.choices[0].message.content.strip()
                result = _parse_ai_response(content, product["title"])
                break
            except Exception:
                if attempt < 1:
                    time.sleep(2)
                else:
                    result = _mock_analyze(product)

        if result is None:
            result = _mock_analyze(product)

        results.append(result)

    return results
