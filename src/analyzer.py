"""
分析模块 — 调用 AI API 进行五维度选品评估。

角色定位：资深跨境电商选品顾问。
分析维度：市场容量、竞争程度、利润潜力、新手友好度、季节性风险。
每个维度 1-10 分 + 解释，最终给出推荐/谨慎/不推荐 verdict。

支持多模型供应商（DeepSeek、MiMo、OpenAI 等），
通过 OpenAI SDK 兼容模式调用。API Key 未配置时返回错误提示。
JSON 解析失败时回退为纯文本展示。
"""

from __future__ import annotations

import json
import time
from openai import OpenAI

from .config import get_llm_config

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


def _extract_json_from_reasoning(reasoning: str) -> str:
    """
    从思考模型的推理内容中提取 JSON 响应。

    MiMo 等思考模型的 reasoning_content 中可能包含完整的 JSON，
    尤其是当 max_tokens 不足导致 content 为空时。
    """
    if not reasoning:
        return ""

    # 尝试找到 JSON 块（最后一个完整的 JSON 对象）
    # 思考模型通常在最后会写出最终的 JSON
    last_brace = reasoning.rfind("}")
    if last_brace == -1:
        return ""

    # 向前找到匹配的 {
    depth = 0
    start = last_brace
    for i in range(last_brace, -1, -1):
        if reasoning[i] == "}":
            depth += 1
        elif reasoning[i] == "{":
            depth -= 1
        if depth == 0:
            start = i
            break

    if depth != 0:
        return ""

    candidate = reasoning[start:last_brace + 1]
    # 验证是否是合法 JSON
    try:
        json.loads(candidate)
        return candidate
    except json.JSONDecodeError:
        return ""


# ============================================================
# JSON 解析与容错
# ============================================================

def _strip_markdown_json(content: str) -> str:
    """清理 markdown 代码块标记（```json ... ```），返回干净的文本。"""
    cleaned = content.strip()
    if cleaned.startswith("```"):
        parts = cleaned.split("```")
        if len(parts) >= 2:
            cleaned = parts[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip()
    return cleaned


def _extract_json_object(text: str) -> dict | None:
    """尝试从文本中提取并解析第一个 JSON 对象，失败返回 None。"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    return None


def _extract_json_array(text: str) -> list | None:
    """尝试从文本中提取并解析 JSON 数组，失败返回 None。"""
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
        # 单个对象包装为列表
        if isinstance(data, dict):
            return [data]
    except json.JSONDecodeError:
        pass
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(text[start:end + 1])
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
    return None


def _parse_ai_response(content: str, product_title: str) -> dict:
    """
    解析 AI 返回的 JSON 字符串。

    容错策略：
        1. 清理 markdown 代码块标记（```json ... ```）
        2. 尝试 json.loads 直接解析
        3. 尝试提取第一个 { 到最后一个 } 之间的内容再解析
        4. 全部失败则回退为纯文本展示

    Returns:
        成功时返回标准分析字典，失败时返回纯文本回退字典。
    """
    cleaned = _strip_markdown_json(content)
    data = _extract_json_object(cleaned)
    if data and _validate_result(data):
        data["title"] = product_title
        return data

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

# 批量分析的系统 Prompt — 一次分析多个产品，返回 JSON 数组
BATCH_SYSTEM_PROMPT = """你是一位拥有 10 年经验的资深跨境电商选品顾问，专精于 Amazon 平台。

我会给你一批产品，请逐个进行量化评估。每个产品从以下五个维度给出 1-10 分并附 1-2 句解释：

1. 市场容量（market_capacity）：该产品的市场需求规模（搜索量、类目总销量）
2. 竞争程度（competition）：注意：分数越高表示竞争越激烈（对卖家越不利）
3. 利润潜力（profit_potential）：扣除采购、物流、平台佣金后的净利润空间
4. 新手友好度（beginner_friendly）：启动资金要求、认证门槛、运营复杂度
5. 季节性风险（seasonality_risk）：注意：分数越高表示季节性波动越大（对卖家越不利）

最后给出：
- final_verdict：取值为 "recommended"（推荐）、"cautious"（谨慎）或 "not_recommended"（不推荐）
- verdict_reason：一句话总结判断依据（50 字以内）

以严格 JSON **数组** 格式返回，数组中每个元素对应一个产品。示例格式：
[
  {
    "title": "产品标题（必须与输入完全一致）",
    "market_capacity": {"score": 8, "reason": "月搜索量约50万，类目年增长率15%"},
    "competition": {"score": 7, "reason": "头部5个品牌占据60%份额，新卖家破局需差异化"},
    "profit_potential": {"score": 6, "reason": "采购成本$8，FBA费用$5，净利率约25%"},
    "beginner_friendly": {"score": 9, "reason": "轻小件物流简单，无需特殊认证，启动资金<$2000"},
    "seasonality_risk": {"score": 2, "reason": "全年稳定需求，无明显淡旺季波动"},
    "final_verdict": "recommended",
    "verdict_reason": "高需求低门槛低风险，适合新手入门选品"
  }
]
只返回 JSON 数组。"""


def _build_batch_prompt(products: list[dict]) -> str:
    """构建批量分析的用户消息。"""
    lines = []
    for i, p in enumerate(products, 1):
        lines.append(
            f"产品 {i}：\n"
            f"  名称：{p['title']}\n"
            f"  售价：${p.get('price', 'N/A')}\n"
            f"  评分：{p.get('rating', 'N/A')}\n"
            f"  评论数：{p.get('num_reviews', 'N/A')}\n"
            f"  类目：{p.get('category', '未知')}\n"
            f"  排名：#{p.get('rank', 'N/A')}\n"
        )
    return "\n".join(lines)


def _parse_batch_response(content: str, batch_products: list[dict]) -> list[dict]:
    """
    解析 AI 返回的批量 JSON 数组。

    容错策略：与 _parse_ai_response 类似，但处理 JSON 数组。
    如果某个产品的解析结果无效，会回退为错误提示字典。
    """
    cleaned = _strip_markdown_json(content)
    parsed_items = _extract_json_array(cleaned) or []

    # 按 title 匹配回产品
    title_map = {}
    for item in parsed_items:
        if isinstance(item, dict) and "title" in item:
            title_map[item["title"]] = item

    results = []
    for product in batch_products:
        title = product["title"]
        matched = title_map.get(title)
        if matched and _validate_result(matched):
            matched["title"] = title
            results.append(matched)
        else:
            # 回退：保留原始响应文本供调试
            fallback_text = content if content else "(AI 返回内容为空)"
            # 如果有部分匹配（title 不同但结构有效），也记录下来
            if matched and not _validate_result(matched):
                fallback_text = json.dumps(matched, ensure_ascii=False, indent=2)
            results.append({
                "title": title,
                "raw_text": fallback_text,
                "parse_error": True,
                "final_verdict": "cautious",
                "verdict_reason": "AI 返回结果中未匹配到该产品",
            })

    return results


def _analyze_batch(batch: list[dict], client, llm_cfg: dict) -> list[dict]:
    """调用 LLM API 分析一批产品。"""
    prompt = _build_batch_prompt(batch)
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=llm_cfg["model"],
                messages=[
                    {"role": "system", "content": BATCH_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                max_tokens=8000,
            )
            content = resp.choices[0].message.content or ""
            # 思考模型（MiMo 等）可能将内容放在 reasoning_content 中
            if not content.strip() and hasattr(resp.choices[0].message, "reasoning_content"):
                reasoning = resp.choices[0].message.reasoning_content or ""
                extracted = _extract_json_from_reasoning(reasoning)
                if extracted:
                    content = extracted
                else:
                    # reasoning 中也提取不出 JSON，直接用 reasoning 原文
                    content = reasoning
            content = content.strip()
            batch_results = _parse_batch_response(content, batch)
            if batch_results:
                return batch_results
        except Exception as e:
            if attempt < 2:
                # 指数退避：2s → 4s → 8s，限流时更长
                import random
                delay = (2 ** (attempt + 1)) + random.uniform(0, 1)
                if "429" in str(e):
                    delay = 10 * (2 ** attempt)
                time.sleep(delay)

    # 全部失败 → 返回错误信息
    return [{"title": p["title"], "raw_text": "AI 分析失败，请检查 API 配置或稍后重试", "parse_error": True, "final_verdict": "cautious", "verdict_reason": "AI 批量分析调用失败"} for p in batch]


def analyze_products(
    products: list[dict],
    progress_callback: callable = None,
    on_complete_callback: callable = None,
) -> list[dict]:
    """
    批量分析产品 — 五维度量化评估。

    将产品分组（每批 6 个），每组一次 LLM API 调用，
    大幅减少串行等待时间。支持进度回调以驱动前端进度条。

    支持多模型供应商（DeepSeek / MiMo / OpenAI 等），
    通过 get_llm_config() 读取当前激活的供应商配置。

    Args:
        products: 产品字典列表
        progress_callback: 可选进度回调函数，接收 (已完成数, 总数)
        on_complete_callback: 可选完成回调函数，每批完成后调用，
                              接收 (当前已分析数, 总数, 本批结果列表)

    Returns:
        list[dict]: 每个产品的分析结果
    """
    llm_cfg = get_llm_config()
    api_key = llm_cfg["api_key"]
    total = len(products)

    # 无 API Key → 返回错误提示
    if not api_key:
        results = []
        for i, p in enumerate(products):
            results.append({
                "title": p["title"],
                "raw_text": "未配置 AI API Key，无法进行智能分析。请在侧边栏选择模型并输入 API Key。",
                "parse_error": True,
                "final_verdict": "cautious",
                "verdict_reason": "API Key 未配置",
            })
            if progress_callback:
                progress_callback(i + 1, total)
        return results

    client = OpenAI(
        api_key=api_key,
        base_url=llm_cfg["base_url"],
        timeout=120,
    )
    BATCH_SIZE = 6
    results = []

    for batch_start in range(0, total, BATCH_SIZE):
        batch = products[batch_start:batch_start + BATCH_SIZE]
        batch_results = _analyze_batch(batch, client, llm_cfg)
        results.extend(batch_results)

        if progress_callback:
            progress_callback(min(len(results), total), total)
        if on_complete_callback:
            on_complete_callback(min(len(results), total), total, batch_results)

    return results


# ============================================================
# 品类综合报告分析（指定选品功能）
# ============================================================

CATEGORY_REPORT_PROMPT = """你是一位拥有 10 年经验的资深跨境电商选品顾问，专精于 Amazon 平台。

根据以下关键词在 Amazon 搜索到的产品数据，生成品类综合分析报告。

关键词：{keyword}
产品数据（共 {n} 个）：
{products_json}

请分析并以严格 JSON 格式返回以下内容：
{{
  "category_overview": "该品类的整体描述（100字以内）",
  "market_size": "市场规模描述，如'月搜索量约XX万，年增长率XX%'",
  "competition_level": "low/medium/high",
  "competition_detail": "竞争格局描述（50字以内）",
  "price_distribution": "价格区间分布描述，如'$10-$30 为主流价格带，$30-$50 为中高端'",
  "top3": [
    {{"rank": 1, "title": "产品标题（必须与输入完全一致）", "reason": "推荐理由（50字以内）", "score": 8}},
    {{"rank": 2, "title": "产品标题", "reason": "推荐理由", "score": 7}},
    {{"rank": 3, "title": "产品标题", "reason": "推荐理由", "score": 7}}
  ],
  "entry_suggestion": "入场建议，包括启动资金估算、时机判断、注意事项（100字以内）",
  "differentiation": "差异化方向建议，如何避开头部竞争（50字以内）",
  "risk_factors": ["风险因素1", "风险因素2", "风险因素3"]
}}
只返回 JSON。"""


def analyze_category_report(keyword: str, products: list[dict]) -> dict:
    """
    基于搜索结果生成品类综合分析报告。

    Args:
        keyword:  搜索关键词
        products: 搜索到的产品列表（最多 20 个）

    Returns:
        dict: 品类报告，包含 category_overview, top3, entry_suggestion 等
    """
    llm_cfg = get_llm_config()
    api_key = llm_cfg["api_key"]

    # 无 API Key → 返回错误
    if not api_key:
        return {
            "success": False,
            "category_overview": "",
            "market_size": "",
            "competition_level": "unknown",
            "competition_detail": "",
            "price_distribution": "",
            "top3": [],
            "entry_suggestion": "",
            "differentiation": "",
            "risk_factors": [],
            "parse_error": False,
            "raw_text": None,
            "error": "AI API 未配置，无法生成品类报告。请在侧边栏配置 API Key。",
        }

    # 构建产品摘要（只传关键字段，减少 Token 消耗）
    summary = []
    for p in products[:20]:
        summary.append({
            "title": p.get("title", ""),
            "price": p.get("price", 0),
            "rating": p.get("rating", 0),
            "num_reviews": p.get("num_reviews", 0),
        })

    prompt = CATEGORY_REPORT_PROMPT.format(
        keyword=keyword,
        n=len(summary),
        products_json=json.dumps(summary, ensure_ascii=False, indent=1),
    )

    client = OpenAI(
        api_key=api_key,
        base_url=llm_cfg["base_url"],
        timeout=60,
    )

    last_error = None
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=llm_cfg["model"],
                messages=[
                    {"role": "system", "content": "你是资深跨境电商选品顾问。只返回 JSON。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                max_tokens=8000,
            )
            # MiMo 等思考模型：content 可能为空，推理结果在 reasoning_content 中
            content = resp.choices[0].message.content or ""
            if not content.strip() and hasattr(resp.choices[0].message, "reasoning_content"):
                reasoning = resp.choices[0].message.reasoning_content or ""
                # 尝试从推理内容中提取 JSON
                content = _extract_json_from_reasoning(reasoning)
            return _parse_category_report_response(content, keyword, products)
        except Exception as e:
            last_error = e
            if attempt < 2:
                import random
                delay = (2 ** (attempt + 1)) + random.uniform(0, 1)
                if "429" in str(e):
                    delay = 10 * (2 ** attempt)
                time.sleep(delay)

    # API 调用失败 → 返回错误（包含具体原因）
    return {
        "success": False,
        "category_overview": "",
        "market_size": "",
        "competition_level": "unknown",
        "competition_detail": "",
        "price_distribution": "",
        "top3": [],
        "entry_suggestion": "",
        "differentiation": "",
        "risk_factors": [],
        "parse_error": False,
        "raw_text": None,
        "error": f"AI API 调用失败：{last_error}",
    }


def _parse_category_report_response(
    content: str, keyword: str, products: list[dict]
) -> dict:
    """
    解析品类报告的 AI 返回 JSON。

    容错策略与 _parse_ai_response 类似。
    """
    cleaned = _strip_markdown_json(content)
    data = _extract_json_object(cleaned)

    # 解析失败的回退模板
    _fallback = {
        "success": False,
        "category_overview": "",
        "market_size": "",
        "competition_level": "unknown",
        "competition_detail": "",
        "price_distribution": "",
        "top3": [],
        "entry_suggestion": "",
        "differentiation": "",
        "risk_factors": [],
        "parse_error": True,
        "raw_text": content,
    }

    if not data:
        return {**_fallback, "error": "AI 返回格式异常，无法解析品类报告"}

    # 验证必要字段
    required = [
        "category_overview", "competition_level", "top3",
        "entry_suggestion", "risk_factors",
    ]
    for key in required:
        if key not in data:
            return {**_fallback, "error": f"AI 返回缺少必要字段「{key}」，报告不完整"}

    if not isinstance(data.get("top3"), list):
        data["top3"] = []

    data["parse_error"] = False
    data["raw_text"] = None
    data["success"] = True
    return data
