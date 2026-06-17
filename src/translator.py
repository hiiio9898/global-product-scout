"""
翻译模块 — 中文搜索关键词 ↔ 英文互译，复用现有 LLM 供应商。

Spec 33：中文搜索自动翻译。
    - translate_keyword:          中文关键词 → 英文搜索词
    - translate_product_titles:   批量英文产品标题 → 中文标题

设计要点：
    复用 src.analyzer 的 AI 调用、指数退避重试、思考模型 reasoning_content 回退、
    JSON 解析容错，不引入任何额外翻译服务或依赖。
"""

from __future__ import annotations

import random
import time

import httpx

from .analyzer import _strip_markdown_json, _extract_json_array
from .config import _get_secret, _safe_int, get_llm_config


# ============================================================
# 基础工具
# ============================================================

def contains_chinese(text: str) -> bool:
    """检测文本是否含中文字符（CJK 统一汉字区间）。"""
    if not text:
        return False
    return any("一" <= ch <= "鿿" for ch in text)


def is_translation_enabled() -> bool:
    """读取 TRANSLATION_ENABLED 配置（默认开启）。"""
    return _get_secret("TRANSLATION_ENABLED", "true").strip().lower() in (
        "true", "1", "yes", "on",
    )


def _get_batch_size() -> int:
    """翻译批次大小（默认 10）。"""
    return _safe_int(_get_secret("TRANSLATION_BATCH_SIZE", "10"), 10)


# ============================================================
# 通用 LLM 调用（复用 analyzer 的重试 + 思考模型回退模式）
# ============================================================

def _call_llm_once(
    llm_cfg: dict, system_prompt: str, user_prompt: str,
    temperature: float = 0.3, max_tokens: int = 4000,
) -> str:
    """
    单次 LLM 调用，返回纯文本内容；重试 3 次后失败返回空串。

    复用 analyzer._analyze_batch 的容错策略：
        - 指数退避：2s → 4s → 8s
        - 限流（429）时退避更长
        - 思考模型（MiMo 等）content 为空时回退 reasoning_content
    """
    base_url = (llm_cfg.get("base_url") or "").rstrip("/")
    for attempt in range(3):
        try:
            resp = httpx.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {llm_cfg['api_key']}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": llm_cfg["model"],
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
                timeout=60,
            )
            if resp.status_code != 200:
                raise RuntimeError(f"API {resp.status_code}")
            message = resp.json()["choices"][0]["message"]
            content = message.get("content") or ""
            # 思考模型：content 可能为空，回退 reasoning_content
            if not content.strip() and message.get("reasoning_content"):
                content = message["reasoning_content"] or ""
            return content.strip()
        except Exception as e:
            if attempt < 2:
                delay = (2 ** (attempt + 1)) + random.uniform(0, 1)
                if "429" in str(e):
                    delay = 10 * (2 ** attempt)
                time.sleep(delay)
    return ""


# ============================================================
# 关键词翻译：中文搜索词 → 英文搜索词
# ============================================================

_KEYWORD_SYSTEM_PROMPT = (
    "你是跨境电商搜索词翻译专家。把用户输入的产品搜索词翻译成最合适的英文电商搜索词。\n"
    "要求：\n"
    "1) 只返回英文搜索词本身，不要任何解释、引号或标点；\n"
    "2) 贴近海外电商平台（Amazon/eBay）的常用表达；\n"
    "3) 若输入已是英文或无需翻译，原样返回。"
)


def translate_keyword(text: str) -> dict:
    """
    中文关键词 → 英文搜索词。

    Args:
        text: 用户输入的搜索词（中文或英文）

    Returns:
        {
            "success": bool,
            "original": str,     # 原始输入
            "translated": str,   # 翻译结果（失败时回退为原文）
            "error": str | None,
        }

    规则：
        - 纯英文 / 不含中文 → 原样返回（不调用 API）
        - 含中文 → 调用 LLM 翻译
        - API 未配置 / 失败 → 降级返回原文 + error
    """
    original = (text or "").strip()
    result = {"success": True, "original": original, "translated": original, "error": None}

    if not original:
        return result
    # 纯英文 / 不含中文 → 不翻译
    if not contains_chinese(original):
        return result

    llm_cfg = get_llm_config()
    if not llm_cfg.get("configured"):
        result["error"] = "AI API 未配置，跳过关键词翻译"
        return result

    content = _call_llm_once(llm_cfg, _KEYWORD_SYSTEM_PROMPT, original)

    if not content:
        result["error"] = "关键词翻译调用失败，使用原文"
        return result

    # 清理：去掉引号/换行，只取第一行
    cleaned = content.strip().strip('"').strip("'").split("\n")[0].strip()
    if cleaned:
        result["translated"] = cleaned
    else:
        result["error"] = "关键词翻译结果为空，使用原文"
    return result


# ============================================================
# 产品标题批量翻译：英文标题 → 中文标题
# ============================================================

_TITLES_SYSTEM_PROMPT = (
    "你是专业的英中翻译专家。把给定的英文产品标题翻译成准确、自然的中文标题。\n"
    "要求：\n"
    "1) 严格以 JSON 数组返回，每个元素形如 {\"index\": 序号, \"title_zh\": \"中文标题\"}；\n"
    "2) index 必须与输入序号一一对应，顺序一致；\n"
    "3) 品牌名、型号、规格保留原文（如 Apple、iPhone 15、USB-C）；\n"
    "4) 不要输出 JSON 以外的任何解释文字。"
)


def translate_product_titles(titles: list[str], batch_size: int = None) -> list[str]:
    """
    批量翻译产品标题为中文。

    Args:
        titles:     英文标题列表
        batch_size: 每批翻译数量（默认读 TRANSLATION_BATCH_SIZE）

    Returns:
        与输入等长的中文标题列表。翻译失败的项回退为原标题。
    """
    if batch_size is None:
        batch_size = _get_batch_size()

    n = len(titles)
    translated = list(titles)  # 默认回退原文

    llm_cfg = get_llm_config()
    if not llm_cfg.get("configured"):
        return translated

    for start in range(0, n, batch_size):
        batch = titles[start:start + batch_size]
        lines = [f"{i}. {t}" for i, t in enumerate(batch, 1)]
        user_prompt = "请翻译以下英文产品标题为中文：\n" + "\n".join(lines)

        content = _call_llm_once(
            llm_cfg, _TITLES_SYSTEM_PROMPT, user_prompt,
            temperature=0.3, max_tokens=4000,
        )
        if not content:
            continue  # 本批失败，保留原文

        # 解析 JSON 数组，建立 index → 中文标题 映射
        cleaned = _strip_markdown_json(content)
        items = _extract_json_array(cleaned) or []
        zh_map = {}
        for item in items:
            if isinstance(item, dict):
                idx = item.get("index")
                zh = item.get("title_zh") or item.get("zh") or item.get("translation")
                if idx is not None and zh:
                    try:
                        zh_map[int(idx)] = zh.strip()
                    except (ValueError, TypeError):
                        pass

        # 按批内序号写回（index 从 1 开始）
        for i in range(1, len(batch) + 1):
            if i in zh_map:
                translated[start + i - 1] = zh_map[i]

    return translated
