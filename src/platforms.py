"""
平台注册表模块 — 多平台可扩展架构的核心。

集中管理所有跨境电商平台的元信息，包括：
    - 平台名称、图标
    - 抓取模块和函数
    - 利润计算函数
    - 支持的地区站点及汇率
    - 默认利润参数

设计模式：
    类似 LLM_PROVIDERS 的字典注册表，后续新增平台只需在 PLATFORMS 中添加条目。

使用方式：
    from src.platforms import PLATFORMS, get_platform_info, get_active_platform
"""

from __future__ import annotations


# ============================================================
# 平台注册表
# ============================================================

PLATFORMS = {
    "amazon": {
        "name": "Amazon",
        "icon": "🟠",
        "scraper_module": "src.scraper",
        "scraper_func": "fetch_amazon_best_sellers",
        "search_module": "src.scraper_search",
        "search_func": "search_amazon",
        "calculator": "calculate_amazon_profit",
        "scrape_mode": "fetcher_first",
        "currency": "USD",
        "regions": {
            "us": {"name": "美国站", "domain": "amazon.com", "currency": "USD", "exchange_rate": 7.24},
            "uk": {"name": "英国站", "domain": "amazon.co.uk", "currency": "GBP", "exchange_rate": 9.32},
            "jp": {"name": "日本站", "domain": "amazon.co.jp", "currency": "JPY", "exchange_rate": 0.048},
            "de": {"name": "德国站", "domain": "amazon.de", "currency": "EUR", "exchange_rate": 7.88},
            "fr": {"name": "法国站", "domain": "amazon.fr", "currency": "EUR", "exchange_rate": 7.88},
            "it": {"name": "意大利站", "domain": "amazon.it", "currency": "EUR", "exchange_rate": 7.88},
            "es": {"name": "西班牙站", "domain": "amazon.es", "currency": "EUR", "exchange_rate": 7.88},
            "ca": {"name": "加拿大站", "domain": "amazon.ca", "currency": "CAD", "exchange_rate": 5.30},
            "au": {"name": "澳洲站", "domain": "amazon.com.au", "currency": "AUD", "exchange_rate": 4.80},
        },
        "default_region": "us",
        "profit_defaults": {
            "commission_pct": 0.15,
            "ad_pct": 0.10,
            "shipping_cny": 15.0,
        },
    },
    "ebay": {
        "name": "eBay",
        "icon": "🔵",
        "scraper_module": "src.scraper_ebay",
        "scraper_func": "fetch_ebay_best_sellers",
        "search_module": "src.scraper_ebay",
        "search_func": "search_ebay",
        "calculator": "calculate_ebay_profit",
        "scrape_mode": "fetcher_first",
        "currency": "USD",
        "regions": {
            "us": {"name": "美国站", "domain": "ebay.com", "currency": "USD", "exchange_rate": 7.24},
            "uk": {"name": "英国站", "domain": "ebay.co.uk", "currency": "GBP", "exchange_rate": 9.18},
            "de": {"name": "德国站", "domain": "ebay.de", "currency": "EUR", "exchange_rate": 7.88},
            "au": {"name": "澳洲站", "domain": "ebay.com.au", "currency": "AUD", "exchange_rate": 4.80},
            "ca": {"name": "加拿大站", "domain": "ebay.ca", "currency": "CAD", "exchange_rate": 5.30},
        },
        "default_region": "us",
        "profit_defaults": {
            "final_value_fee_pct": 0.1325,
            "listing_fee_usd": 0.30,
            "shipping_cny": 20.0,
            "packaging_cny": 5.0,
            "payoneer_fee_pct": 0.01,
        },
    },
    "alibaba": {
        "name": "Alibaba",
        "icon": "🟠",
        "scraper_module": "src.scraper_alibaba",
        "scraper_func": "fetch_alibaba_best_sellers",
        "search_module": "src.scraper_alibaba",
        "search_func": "search_alibaba",
        "calculator": "calculate_alibaba_profit",
        "scrape_mode": "stealth_only",
        "currency": "USD",
        "regions": {
            "us": {"name": "国际站", "domain": "alibaba.com", "currency": "USD", "exchange_rate": 7.24},
        },
        "default_region": "us",
        "profit_defaults": {
            "commission_pct": 0.05,
            "trade_assurance_pct": 0.02,
            "shipping_cny": 25.0,
            "packaging_cny": 3.0,
        },
    },
    "aliexpress": {
        "name": "AliExpress",
        "icon": "🔶",
        "scraper_module": "src.scraper_aliexpress",
        "scraper_func": "fetch_aliexpress_best_sellers",
        "search_module": "src.scraper_aliexpress",
        "search_func": "search_aliexpress",
        "calculator": "calculate_aliexpress_profit",
        "scrape_mode": "stealth_only",
        "currency": "USD",
        "regions": {
            "us": {"name": "美国站", "domain": "aliexpress.us", "currency": "USD", "exchange_rate": 7.24},
            "eu": {"name": "欧洲站", "domain": "aliexpress.com", "currency": "EUR", "exchange_rate": 7.88},
            "ru": {"name": "俄罗斯站", "domain": "aliexpress.ru", "currency": "RUB", "exchange_rate": 0.08},
        },
        "default_region": "us",
        "profit_defaults": {
            "commission_pct": 0.065,
            "withdrawal_fee_pct": 0.02,
            "shipping_cny": 15.0,
            "packaging_cny": 3.0,
        },
    },
}


# ============================================================
# 工具函数
# ============================================================

def get_platform_info(platform_key: str) -> dict:
    """
    获取平台完整信息。

    Args:
        platform_key: 平台标识，如 "amazon"

    Returns:
        平台配置字典

    Raises:
        KeyError: 平台不存在时
    """
    if platform_key not in PLATFORMS:
        raise KeyError(f"未知平台：{platform_key}，可用平台：{list(PLATFORMS.keys())}")
    return PLATFORMS[platform_key]


def get_region_info(platform_key: str, region_key: str) -> dict:
    """
    获取平台某地区站点的信息。

    Args:
        platform_key: 平台标识，如 "amazon"
        region_key:   地区代码，如 "us"

    Returns:
        地区配置字典（name, domain, currency, exchange_rate）

    Raises:
        KeyError: 平台或地区不存在时
    """
    platform = get_platform_info(platform_key)
    if region_key not in platform["regions"]:
        raise KeyError(
            f"平台 {platform_key} 不支持地区 {region_key}，"
            f"可用地区：{list(platform['regions'].keys())}"
        )
    info = dict(platform["regions"][region_key])

    # 尝试用实时汇率覆盖硬编码值
    try:
        from src.exchange_rate import get_rate
        currency = info.get("currency", "USD")
        if currency != "USD":
            usd_to_cny = get_rate("USD", "CNY")
            foreign_to_usd = get_rate("USD", currency)
            if foreign_to_usd and foreign_to_usd > 0:
                info["exchange_rate"] = round(usd_to_cny / foreign_to_usd, 4)
    except Exception:
        pass  # 降级使用硬编码值

    return info


def get_platform_choices() -> list[str]:
    """
    返回所有平台 key 列表，供 selectbox 使用。

    Returns:
        ["amazon", "aliexpress", ...]
    """
    return list(PLATFORMS.keys())


def get_region_choices(platform_key: str) -> list[tuple[str, str]]:
    """
    返回某平台的地区选项列表。

    Args:
        platform_key: 平台标识

    Returns:
        [(region_key, display_name), ...]
        如 [("us", "美国站"), ("uk", "英国站"), ...]
    """
    platform = get_platform_info(platform_key)
    return [(k, v["name"]) for k, v in platform["regions"].items()]


def get_active_platform() -> str:
    """
    从 st.session_state 读取用户当前选择的平台。

    Returns:
        平台 key，默认 "amazon"
    """
    try:
        import streamlit as st
        return st.session_state.get("active_platform", "amazon")
    except (ImportError, RuntimeError):
        return "amazon"


def get_active_region(platform_key: str = None) -> str:
    """
    从 st.session_state 读取用户当前选择的地区。

    Args:
        platform_key: 平台标识，默认从 session_state 读取

    Returns:
        地区 key，默认该平台的 default_region
    """
    if platform_key is None:
        platform_key = get_active_platform()
    platform = get_platform_info(platform_key)
    default_region = platform.get("default_region", "us")

    try:
        import streamlit as st
        return st.session_state.get("active_region", default_region)
    except (ImportError, RuntimeError):
        return default_region


def get_exchange_rate(platform_key: str, region_key: str) -> float:
    """
    获取平台某地区的汇率。

    Args:
        platform_key: 平台标识
        region_key:   地区代码

    Returns:
        汇率（CNY / 本地货币）
    """
    region = get_region_info(platform_key, region_key)
    return region.get("exchange_rate", 7.24)
