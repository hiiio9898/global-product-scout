"""
汇率获取模块 — 实时汇率 + 本地缓存 + 降级策略。

使用免费 API（exchangerate-api.com）获取最新汇率，
本地缓存到 data/exchange_rates.json（24 小时有效期），
离线或 API 失败时降级使用 platforms.py 中硬编码的默认值。

使用方式：
    from src.exchange_rate import get_rate, get_rate_status
    rate = get_rate("USD", "CNY")  # → 7.24
"""

import json
import os
import time
from datetime import datetime, timezone

# 缓存文件路径
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CACHE_DIR = os.path.join(_PROJECT_ROOT, "data")
_CACHE_FILE = os.path.join(_CACHE_DIR, "exchange_rates.json")

# 缓存有效期（秒）：24 小时
_CACHE_TTL = 24 * 60 * 60

# 免费 API（无需 API Key，每月 1500 次请求）
_FREE_API_URL = "https://open.er-api.com/v6/latest/USD"


def _read_cache() -> dict | None:
    """读取本地汇率缓存。"""
    if not os.path.exists(_CACHE_FILE):
        return None
    try:
        with open(_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 检查缓存是否过期
        updated_at = data.get("updated_at", "")
        if updated_at:
            cache_time = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            if cache_time.tzinfo is None:
                cache_time = cache_time.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - cache_time).total_seconds()
            if age < _CACHE_TTL:
                return data
        return None
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


def _write_cache(rates: dict, source: str = "exchangerate-api.com") -> None:
    """写入汇率缓存。"""
    os.makedirs(_CACHE_DIR, exist_ok=True)
    data = {
        "base": "USD",
        "rates": rates,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
    }
    with open(_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _fetch_from_api() -> dict | None:
    """从免费 API 获取最新汇率。"""
    try:
        import urllib.request
        req = urllib.request.Request(
            _FREE_API_URL,
            headers={"User-Agent": "GlobalProductScout/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("result") == "success":
            return data.get("rates", {})
    except Exception:
        pass
    return None


def get_rate(from_currency: str = "USD", to_currency: str = "CNY") -> float:
    """
    获取汇率（from_currency → to_currency）。

    优先级：
        1. 本地缓存（<24h）
        2. 免费 API
        3. 硬编码默认值（7.24）

    Returns:
        汇率值（如 1 USD = 7.24 CNY 时返回 7.24）
    """
    if from_currency == to_currency:
        return 1.0

    # 1. 尝试缓存
    cache = _read_cache()
    if cache and cache.get("rates", {}).get(to_currency):
        return cache["rates"][to_currency]

    # 2. 尝试 API
    rates = _fetch_from_api()
    if rates and to_currency in rates:
        _write_cache(rates)
        return rates[to_currency]

    # 3. 降级：硬编码默认值
    _defaults = {
        ("USD", "CNY"): 7.24,
        ("USD", "EUR"): 0.92,
        ("USD", "GBP"): 0.79,
        ("USD", "JPY"): 157.0,
        ("USD", "CAD"): 1.37,
        ("USD", "AUD"): 1.53,
    }
    return _defaults.get((from_currency, to_currency), 1.0)


def get_rate_status() -> dict:
    """
    获取汇率状态信息（用于侧边栏显示）。

    Returns:
        {
            "rate": float,         # 当前汇率
            "source": str,         # 数据来源
            "updated_at": str,     # 更新时间
            "age_hours": float,    # 数据年龄（小时）
            "is_stale": bool,      # 是否过期
        }
    """
    cache = _read_cache()
    if cache:
        rate = cache.get("rates", {}).get("CNY", 7.24)
        updated_at = cache.get("updated_at", "")
        source = cache.get("source", "cache")
        try:
            cache_time = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            if cache_time.tzinfo is None:
                cache_time = cache_time.replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - cache_time).total_seconds() / 3600
        except (ValueError, TypeError):
            age_hours = 999
        return {
            "rate": rate,
            "source": source,
            "updated_at": updated_at[:16].replace("T", " "),
            "age_hours": round(age_hours, 1),
            "is_stale": age_hours > 24,
        }

    # 无缓存，尝试实时获取
    rate = get_rate("USD", "CNY")
    return {
        "rate": rate,
        "source": "default" if rate == 7.24 else "api",
        "updated_at": "N/A",
        "age_hours": 999,
        "is_stale": True,
    }
