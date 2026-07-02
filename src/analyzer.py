"""
分析模块 — 调用 AI API 进行五维度选品评估。

角色定位：资深跨境电商选品顾问。
分析维度：市场容量、竞争程度、利润潜力、新手友好度、季节性风险。
每个维度 1-10 分 + 解释，最终给出推荐/谨慎/不推荐 verdict。

支持多模型供应商（DeepSeek、MiMo 等），
通过 OpenAI 兼容 API 调用（使用 httpx 直接请求）。
API Key 未配置时返回错误提示。JSON 解析失败时回退为纯文本展示。
"""

from __future__ import annotations

import json
import time
import httpx

from .config import get_llm_config


# ============================================================
# LLM API 调用（httpx 直连，OpenAI 兼容接口）
# ============================================================

def _call_llm(
    llm_cfg: dict,
    messages: list[dict],
    temperature: float = 0.7,
    max_tokens: int = 8000,
    timeout: int = 120,
) -> str:
    """
    调用 OpenAI 兼容的 chat completions API，返回文本内容。

    自动处理思考模型（MiMo 等）的 reasoning_content：当 content 为空时，
    从 reasoning_content 中提取 JSON 或直接使用推理文本。

    Args:
        llm_cfg:     get_llm_config() 返回的配置（含 api_key/base_url/model）
        messages:    消息列表 [{"role": ..., "content": ...}, ...]
        temperature: 采样温度
        max_tokens:  最大输出 token
        timeout:     超时秒数

    Returns:
        AI 返回的文本内容

    Raises:
        Exception: API 调用失败（含 429 限流）
    """
    base_url = llm_cfg["base_url"].rstrip("/")
    url = f"{base_url}/chat/completions"

    payload = {
        "model": llm_cfg["model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    resp = httpx.post(
        url,
        headers={
            "Authorization": f"Bearer {llm_cfg['api_key']}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout,
    )

    # 非 2xx → 抛异常（上层做指数退避重试）
    if resp.status_code != 200:
        raise RuntimeError(f"API 返回 {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    message = data["choices"][0]["message"]
    content = message.get("content") or ""

    # 思考模型（MiMo 等）：content 可能为空，推理结果在 reasoning_content 中
    if not content.strip() and message.get("reasoning_content"):
        reasoning = message["reasoning_content"] or ""
        extracted = _extract_json_from_reasoning(reasoning)
        if extracted:
            content = extracted
        else:
            content = reasoning

    return content

# ============================================================
# 系统 Prompt — 资深跨境电商选品顾问
# ============================================================

SYSTEM_PROMPT = """你是一位拥有 10 年经验的资深跨境电商选品顾问，专精于 Amazon 平台。

请从以下六个维度对给定产品进行量化评估，每个维度给出 1-10 分（10 分为最优）并附 1-2 句解释：

1. 市场容量（market_capacity）：该产品的市场需求规模。注意：你无法获取真实搜索量，请基于评论数和排名用范围表述，不要给出精确数字。在reason中使用"估计"、"推测"等词汇
2. 竞争程度（competition）：注意：分数越高表示竞争越激烈（对卖家越不利）
3. 利润潜力（profit_potential）：扣除采购、物流、平台佣金后的净利润空间
4. 新手友好度（beginner_friendly）：启动资金要求、认证门槛、运营复杂度
5. 季节性风险（seasonality_risk）：注意：分数越高表示季节性波动越大（对卖家越不利）
6. 长期持久力（longevity）：值不值得长期（以年为单位）做，分数越高越长效。同时给 label：evergreen(长青)/trending_up(趋势上升)/fad(阶段性爆品)/declining(夕阳)，以及 key_signal（≤8字主导信号）。判据：复购消耗/痛点vs玩具/品类生命周期/设备绑定细分（绑某代不兼容=trending_up，跨代兼容=evergreen；declining 仅限被新技术替代的品类）

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
  "longevity": {"score": 9, "label": "evergreen", "key_signal": "高频消耗补货", "reason": "日用刚需，常年稳定需求"},
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
        "longevity": {"score": 0, "label": "unknown", "key_signal": "", "reason": ""},
    }


def _validate_result(data: dict) -> bool:
    """验证解析结果包含必要的六维度字段。"""
    required_keys = [
        "market_capacity", "competition", "profit_potential",
        "beginner_friendly", "seasonality_risk", "longevity",
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
BATCH_SYSTEM_PROMPT = """你是一位拥有 10 年经验的资深跨境电商选品顾问，专精于帮助中国卖家从 1688 采购并在 Amazon/eBay/TikTok Shop 等平台销售。

我会给你一批产品，请逐个进行量化评估。评估视角是中国跨境卖家（非品牌方），重点关注能否从中国供应链采购并在海外平台转售。

每个产品从以下六个维度给出 1-10 分并附 1-2 句解释：

1. 市场容量（market_capacity）：该产品的市场需求规模。注意：你无法获取真实搜索量，请基于评论数和排名用范围表述（如"推测月搜索量在10万-50万级别"），不要给出精确数字。在reason中使用"估计"、"推测"等词汇
2. 竞争程度（competition）：分数越高表示竞争越激烈（对卖家越不利）。注意：大品牌垄断的类目竞争分数应很高
3. 利润潜力（profit_potential）：从 1688 采购成本出发，扣除物流、平台佣金后的净利润空间。大品牌产品因授权成本高、利润薄，应给低分
4. 新手友好度（beginner_friendly）：启动资金要求、认证门槛（如 FDA/FCC/CE）、品牌授权风险、运营复杂度。已知大品牌（Apple/Samsung/Nike 等）因授权门槛极高，应给 1-3 分
5. 季节性风险（seasonality_risk）：分数越高表示季节性波动越大（对卖家越不利）
6. 长期持久力（longevity）：值不值得**长期（以年为单位）做**——分数越高越长效、越值得长期投入（10=最长效，与 competition/seasonality 方向相反）。同时给出四档 label：
   - evergreen（长青）：常年稳定需求，消耗品/补货型/解决持续性功能痛点的刚需品（如厨房剪、剃须刀片、咖啡滤纸、宠毛刷）
   - trending_up（趋势上升）：需求上升但波动大，有机会但要快；含"绑定当红机型且不跨代兼容"的配件（随机型换代周期衰退，如某代专用手机壳）
   - fad（阶段性爆品）：短期热度驱动的新奇/玩具/社交爆款，大概率数月后衰退（如指尖陀螺、史莱姆）
   - declining（夕阳）：已被新技术整体替代、长期下行（如 DVD、有线耳机被无线替代）。当前在售数码配件不算夕阳
   长青度判据（按权重）：① 复购/消耗属性（消耗品偏长青）② 痛点 vs 玩具（持续功能痛点=长青，新奇好玩=易过时）③ 品类生命周期 ④ 设备绑定细分（绑某代不兼容=trending_up；跨代标准兼容如表带/USB-C 线=偏 evergreen）。key_signal 用 ≤8 字中文短语点出主导信号。

裁决规则（final_verdict）：
- "recommended"（推荐）：综合条件适合跨境新手入手，通常需满足 — competition ≤ 7 且 beginner_friendly ≥ 5 且 profit_potential ≥ 5
- "cautious"（谨慎）：有一定机会但存在明显风险或门槛，如 competition ≥ 8 或 beginner_friendly ≤ 4
- "not_recommended"（不推荐）：不适合跨境卖家，如 — 知名大品牌（需授权）、竞争极端激烈（competition ≥ 9）、新手友好度极低（beginner_friendly ≤ 3）、利润空间极小（profit_potential ≤ 3）
- 长青性纳入考量（verdict 仍为上述三选一）：longevity=evergreen 可让 borderline 案例倾向 recommended；longevity=fad/declining 应让案例倾向 cautious 或 not_recommended（阶段性爆品不宜长期投入）

特别注意：
- 知名大品牌产品（Apple、Samsung、Nike、STANLEY、Ninja 等）通常需要品牌授权才能合法销售，未授权转售面临 IP 侵权风险，应倾向于 "not_recommended"
- 无品牌/白牌/小众品牌产品如果能从 1688 找到供应链，是跨境卖家的理想选品对象
- 轻小件、无需特殊认证、单价适中（$15-$50）的产品更适合新手

最后给出：
- final_verdict：取值为 "recommended"（推荐）、"cautious"（谨慎）或 "not_recommended"（不推荐）
- verdict_reason：一句话总结判断依据（50 字以内）
- trend_direction：取值为 "rising" "stable" "declining" 或 "unknown"，基于你对品类的了解判断该产品近6个月的搜索热度趋势
- trend_reason：一句话解释趋势判断依据
- estimated_cost_cny：你推测的1688/阿里采购成本（人民币），给出一个近似整数

以严格 JSON **数组** 格式返回，数组中每个元素对应一个产品。示例格式：
[
  {
    "title": "产品标题（必须与输入完全一致）",
    "market_capacity": {"score": 8, "reason": "评论数过万，推测月搜索量在10万-50万级别，类目增长趋势良好"},
    "competition": {"score": 7, "reason": "头部5个品牌占据60%份额，新卖家破局需差异化"},
    "profit_potential": {"score": 6, "reason": "1688采购成本$8，FBA费用$5，净利率约25%"},
    "beginner_friendly": {"score": 9, "reason": "轻小件物流简单，无需特殊认证，启动资金<$2000"},
    "seasonality_risk": {"score": 2, "reason": "全年稳定需求，无明显淡旺季波动"},
    "longevity": {"score": 9, "label": "evergreen", "key_signal": "高频消耗补货", "reason": "日用刚需，常年稳定需求"},
    "final_verdict": "recommended",
    "verdict_reason": "高需求低门槛低风险，适合新手入门选品",
    "trend_direction": "rising",
    "trend_reason": "近6个月搜索热度持续上升，季节性品类扩容",
    "estimated_cost_cny": 25
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
                "longevity": {"score": 0, "label": "unknown", "key_signal": "", "reason": ""},
            })

    return results


def _analyze_batch(batch: list[dict], llm_cfg: dict) -> list[dict]:
    """调用 LLM API 分析一批产品。"""
    prompt = _build_batch_prompt(batch)
    for attempt in range(3):
        try:
            content = _call_llm(
                llm_cfg,
                messages=[
                    {"role": "system", "content": BATCH_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                max_tokens=8000,
            )
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
    return [{"title": p["title"], "raw_text": "AI 分析失败，请检查 API 配置或稍后重试", "parse_error": True, "final_verdict": "cautious", "verdict_reason": "AI 批量分析调用失败", "longevity": {"score": 0, "label": "unknown", "key_signal": "", "reason": ""}} for p in batch]


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
                "longevity": {"score": 0, "label": "unknown", "key_signal": "", "reason": ""},
            })
            if progress_callback:
                progress_callback(i + 1, total)
        return results

    # 批次大小：从配置读取，默认6
    try:
        from .config import get_config
        BATCH_SIZE = int(get_config().get("analysis_batch_size", 6))
    except Exception:
        BATCH_SIZE = 6
    results = []

    for batch_start in range(0, total, BATCH_SIZE):
        batch = products[batch_start:batch_start + BATCH_SIZE]
        batch_results = _analyze_batch(batch, llm_cfg)
        results.extend(batch_results)

        # 进度回调
        if progress_callback:
            progress_callback(len(results), total)

        # 流式回调：每批完成后通知UI（Spec 21）
        if on_complete_callback:
            on_complete_callback(len(results), total, batch_results)

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

    last_error = None
    for attempt in range(3):
        try:
            content = _call_llm(
                llm_cfg,
                messages=[
                    {"role": "system", "content": "你是资深跨境电商选品顾问。只返回 JSON。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                max_tokens=8000,
                timeout=60,
            )
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


# ============================================================
# 跨市场对比分析
# ============================================================

CROSS_MARKET_PROMPT = """你是资深跨境电商选品顾问。

以下是关键词「{keyword}」在 {n} 个市场的扫描数据：
{market_data}

请分析并返回严格 JSON 格式：
{{
  "best_market": {{
    "platform": "amazon",
    "region": "de",
    "reason": "推荐理由（50字以内）"
  }},
  "top3_opportunities": [
    {{"rank": 1, "platform": "amazon", "region": "de", "blue_ocean_score": 8.5, "reason": "理由（30字以内）"}},
    {{"rank": 2, "platform": "ebay", "region": "us", "blue_ocean_score": 7.2, "reason": "理由（30字以内）"}},
    {{"rank": 3, "platform": "amazon", "region": "uk", "blue_ocean_score": 6.8, "reason": "理由（30字以内）"}}
  ],
  "market_comparison": [
    {{"platform": "amazon", "region": "us", "competition": "high", "demand": "high", "profit_margin": "medium"}},
    {{"platform": "amazon", "region": "de", "competition": "low", "demand": "high", "profit_margin": "high"}}
  ],
  "entry_strategy": "建议先进入XX市场，因为...（100字以内）",
  "risk_factors": ["风险1", "风险2"]
}}
只返回 JSON。"""


def analyze_market_comparison(keyword: str, markets: list[dict]) -> dict:
    """
    跨市场对比分析 — AI 生成入场策略。

    Args:
        keyword: 搜索关键词
        markets: 各市场的扫描结果列表

    Returns:
        跨市场对比报告（含 best_market, top3_opportunities, entry_strategy 等）
    """
    llm_cfg = get_llm_config()
    api_key = llm_cfg["api_key"]

    # 构建市场摘要数据
    market_summaries = []
    for m in markets:
        if m.get("error"):
            continue
        summary = {
            "platform": m["platform"],
            "region": m["region"],
            "region_name": m.get("region_name", m["region"]),
            "product_count": m.get("product_count", 0),
            "avg_price": m.get("avg_price", 0),
            "avg_rating": m.get("avg_rating", 0),
        }
        market_summaries.append(summary)

    if not market_summaries:
        return {"success": False, "error": "无有效市场数据"}

    market_data_str = json.dumps(market_summaries, ensure_ascii=False, indent=1)

    # 无 API Key → 返回基础数据
    if not api_key:
        return {
            "success": True,
            "best_market": market_summaries[0] if market_summaries else {},
            "top3_opportunities": [],
            "market_comparison": market_summaries,
            "entry_strategy": "未配置 AI API Key，无法生成智能入场策略。",
            "risk_factors": [],
            "parse_error": False,
        }

    prompt = CROSS_MARKET_PROMPT.format(
        keyword=keyword,
        n=len(market_summaries),
        market_data=market_data_str,
    )

    import random
    last_error = None
    for attempt in range(3):
        try:
            content = _call_llm(
                llm_cfg,
                messages=[
                    {"role": "system", "content": "你是资深跨境电商选品顾问。只返回 JSON。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                max_tokens=4000,
            )
            return _parse_cross_market_response(content)
        except Exception as e:
            last_error = e
            if attempt < 2:
                delay = (2 ** (attempt + 1)) + random.uniform(0, 1)
                if "429" in str(e):
                    delay = 10 * (2 ** attempt)
                time.sleep(delay)

    return {"success": False, "error": f"AI API 调用失败：{last_error}"}


def _parse_cross_market_response(content: str) -> dict:
    """解析跨市场对比的 AI 返回 JSON。"""
    cleaned = _strip_markdown_json(content)
    data = _extract_json_object(cleaned)

    if not data:
        return {"success": False, "error": "AI 返回格式异常", "raw_text": content}

    data.setdefault("success", True)
    data.setdefault("parse_error", False)
    data.setdefault("top3_opportunities", [])
    data.setdefault("market_comparison", [])
    data.setdefault("risk_factors", [])
    return data
