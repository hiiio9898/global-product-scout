"""
LLM 客户端 — 统一的 OpenAI 兼容 API 调用层。

将 analyzer.py / translator.py 中重复的 httpx 调用、reasoning_content 回退、
指数退避重试逻辑收敛为单一入口。

核心函数：
    call_llm(messages, ...)  — 带重试的 LLM 调用，返回文本内容
    call_llm_raw(messages, ...) — 单次调用（不重试），失败抛异常
"""

from __future__ import annotations

import json
import random
import time

import httpx


# ============================================================
# JSON 提取工具（从 reasoning_content 中恢复 JSON）
# ============================================================

def extract_json_from_reasoning(reasoning: str) -> str:
    """
    从思考模型的推理内容中提取 JSON 响应。

    MiMo 等思考模型的 reasoning_content 中可能包含完整的 JSON，
    尤其是当 max_tokens 不足导致 content 为空时。
    """
    if not reasoning:
        return ""

    # 找到最后一个 } 并向前匹配 {
    last_brace = reasoning.rfind("}")
    if last_brace == -1:
        return ""

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
    try:
        json.loads(candidate)
        return candidate
    except json.JSONDecodeError:
        return ""


# ============================================================
# 单次调用（不重试）
# ============================================================

def call_llm_raw(
    llm_cfg: dict,
    messages: list[dict],
    temperature: float = 0.7,
    max_tokens: int = 8000,
    timeout: int = 120,
) -> str:
    """
    单次调用 OpenAI 兼容的 chat completions API，返回文本内容。

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
        RuntimeError: API 返回非 200 状态码（含 429 限流）
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

    if resp.status_code != 200:
        raise RuntimeError(f"API 返回 {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    message = data["choices"][0]["message"]
    content = message.get("content") or ""

    # 思考模型：content 为空时回退 reasoning_content
    if not content.strip() and message.get("reasoning_content"):
        reasoning = message["reasoning_content"] or ""
        extracted = extract_json_from_reasoning(reasoning)
        content = extracted if extracted else reasoning

    return content


# ============================================================
# 带重试的调用（指数退避）
# ============================================================

def call_llm(
    llm_cfg: dict,
    messages: list[dict],
    temperature: float = 0.7,
    max_tokens: int = 8000,
    timeout: int = 120,
    retries: int = 3,
) -> str:
    """
    带指数退避重试的 LLM 调用。

    重试策略：
        - 普通错误：2s → 4s → 8s（+随机抖动）
        - 限流（429）：10s → 20s → 40s

    Args:
        retries: 最大尝试次数（含首次），默认 3

    Returns:
        AI 返回的文本内容

    Raises:
        最后一次失败的异常（当所有重试用尽时）
    """
    last_error = None
    for attempt in range(retries):
        try:
            return call_llm_raw(
                llm_cfg, messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
        except Exception as e:
            last_error = e
            if attempt < retries - 1:
                delay = (2 ** (attempt + 1)) + random.uniform(0, 1)
                if "429" in str(e):
                    delay = 10 * (2 ** attempt)
                time.sleep(delay)

    raise last_error
