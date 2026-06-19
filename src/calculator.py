"""
利润计算模块 — 可配置的跨境电商利润计算器（多平台工厂模式）。

架构：
    - 利润计算函数注册表（_CALCULATOR_REGISTRY）
    - @register_calculator("平台key") 装饰器注册各平台计算器
    - get_calculator(platform_key) 获取对应计算器
    - calculate_profit() 统一入口（向后兼容旧代码）

各参数默认值存储在 src/platforms.py 的平台配置中，
用户可在 Streamlit 侧边栏修改。
"""

from __future__ import annotations

from typing import Callable


# ============================================================
# 利润计算函数注册表
# ============================================================

_CALCULATOR_REGISTRY: dict[str, Callable] = {}


def register_calculator(platform_key: str):
    """
    装饰器：注册平台利润计算函数。

    使用方式：
        @register_calculator("amazon")
        def calculate_amazon_profit(price, defaults, procurement_cny=0.0, **kwargs):
            ...
    """
    def decorator(func):
        _CALCULATOR_REGISTRY[platform_key] = func
        return func
    return decorator


def get_calculator(platform_key: str) -> Callable:
    """
    获取平台对应的利润计算函数。

    Args:
        platform_key: 平台标识，如 "amazon"

    Returns:
        利润计算函数，不存在时返回 Amazon FBA 计算器
    """
    return _CALCULATOR_REGISTRY.get(platform_key, calculate_amazon_profit)


# ============================================================
# Amazon FBA 利润计算器
# ============================================================

@register_calculator("amazon")
def calculate_amazon_profit(
    price: float,
    defaults: dict,
    procurement_cny: float = 0.0,
    **kwargs,
) -> dict:
    """
    Amazon FBA 利润计算。

    公式：
        售价(本地货币) × 汇率 = 售价(CNY)
        佣金 = 售价(CNY) × commission_pct
        广告 = 售价(CNY) × ad_pct
        总成本 = 采购成本 + 头程运费 + 佣金 + 广告
        净利 = 售价(CNY) - 总成本
        毛利率 = 净利 / 售价(CNY)

    Args:
        price:             产品售价（本地货币，如 USD）
        defaults:          利润默认参数字典
        procurement_cny:   采购成本（人民币），0 表示未填写
        **kwargs:          预留扩展

    Returns:
        标准利润结果字典
    """
    exchange_rate = defaults.get("exchange_rate", 7.24)
    commission_pct = defaults.get("commission_pct", 0.15)
    ad_pct = defaults.get("ad_pct", 0.10)
    shipping_cny = defaults.get("shipping_cny", 15.0)

    # 售价（人民币）
    price_cny = price * exchange_rate

    # 各项费用
    commission_cny = price_cny * commission_pct
    ad_cost_cny = price_cny * ad_pct

    # 总成本
    total_cost_cny = procurement_cny + shipping_cny + commission_cny + ad_cost_cny

    # 净利
    net_profit_cny = price_cny - total_cost_cny
    net_profit_usd = net_profit_cny / exchange_rate if exchange_rate > 0 else 0.0

    # 毛利率
    margin_pct = (net_profit_cny / price_cny * 100) if price_cny > 0 else 0.0

    return {
        "price_local": round(price, 2),
        "price_cny": round(price_cny, 2),
        "commission_cny": round(commission_cny, 2),
        "ad_cost_cny": round(ad_cost_cny, 2),
        "shipping_cny": round(shipping_cny, 2),
        "procurement_cny": round(procurement_cny, 2),
        "total_cost_cny": round(total_cost_cny, 2),
        "net_profit_cny": round(net_profit_cny, 2),
        "net_profit_usd": round(net_profit_usd, 2),
        "margin_pct": round(margin_pct, 1),
        "is_profitable": net_profit_cny > 0,
        "has_procurement": procurement_cny > 0,
    }


# ============================================================
# eBay 利润计算器
# ============================================================

@register_calculator("ebay")
def calculate_ebay_profit(
    price: float,
    defaults: dict,
    procurement_cny: float = 0.0,
    **kwargs,
) -> dict:
    """
    eBay 卖家利润计算（Managed Payments）。

    公式：
        售价(USD) × 汇率 = 售价(CNY)
        成交费 = 售价(CNY) × final_value_fee_pct (13.25%)
        刊登费 = listing_fee_usd × 汇率
        Payoneer 提现费 = 售价(CNY) × payoneer_fee_pct (1%)
        总成本 = 采购成本 + 国际运费 + 包装费 + 成交费 + 刊登费 + 提现费
        净利 = 售价(CNY) - 总成本
        毛利率 = 净利 / 售价(CNY)

    Args:
        price:             产品售价（本地货币）
        defaults:          利润默认参数字典
        procurement_cny:   采购成本（人民币）
        **kwargs:          预留扩展

    Returns:
        标准利润结果字典
    """
    exchange_rate = defaults.get("exchange_rate", 7.24)
    final_value_fee_pct = defaults.get("final_value_fee_pct", 0.1325)
    listing_fee_usd = defaults.get("listing_fee_usd", 0.30)
    shipping_cny = defaults.get("shipping_cny", 20.0)
    packaging_cny = defaults.get("packaging_cny", 5.0)
    payoneer_fee_pct = defaults.get("payoneer_fee_pct", 0.01)

    price_cny = price * exchange_rate
    fvf_cny = price_cny * final_value_fee_pct
    listing_cny = listing_fee_usd * exchange_rate
    payoneer_cny = price_cny * payoneer_fee_pct
    total_cost = (procurement_cny + shipping_cny + packaging_cny
                  + fvf_cny + listing_cny + payoneer_cny)
    net_profit_cny = price_cny - total_cost
    net_profit_usd = net_profit_cny / exchange_rate if exchange_rate > 0 else 0.0
    margin_pct = (net_profit_cny / price_cny * 100) if price_cny > 0 else 0.0

    return {
        "price_local": round(price, 2),
        "price_cny": round(price_cny, 2),
        "fvf_cny": round(fvf_cny, 2),
        "listing_cny": round(listing_cny, 2),
        "payoneer_cny": round(payoneer_cny, 2),
        "shipping_cny": round(shipping_cny, 2),
        "packaging_cny": round(packaging_cny, 2),
        "procurement_cny": round(procurement_cny, 2),
        "total_cost_cny": round(total_cost, 2),
        "net_profit_cny": round(net_profit_cny, 2),
        "net_profit_usd": round(net_profit_usd, 2),
        "margin_pct": round(margin_pct, 1),
        "is_profitable": net_profit_cny > 0,
        "has_procurement": procurement_cny > 0,
    }


# ============================================================
# AliExpress 利润计算器（Spec 13）
# ============================================================

@register_calculator("aliexpress")
def calculate_aliexpress_profit(
    price: float,
    defaults: dict,
    procurement_cny: float = 0.0,
    **kwargs,
) -> dict:
    """
    AliExpress 卖家利润计算。

    公式：
        售价(USD) × 汇率 = 售价(CNY)
        佣金 = 售价(CNY) × commission_pct (5-8%)
        提现手续费 = 售价(CNY) × withdrawal_fee_pct (2%)
        总成本 = 采购成本 + 国际运费 + 包装费 + 佣金 + 提现手续费
        净利 = 售价(CNY) - 总成本
    """
    exchange_rate = defaults.get("exchange_rate", 7.24)
    commission_pct = defaults.get("commission_pct", 0.065)
    withdrawal_fee_pct = defaults.get("withdrawal_fee_pct", 0.02)
    shipping_cny = defaults.get("shipping_cny", 15.0)
    packaging_cny = defaults.get("packaging_cny", 3.0)

    price_cny = price * exchange_rate
    commission_cny = price_cny * commission_pct
    withdrawal_cny = price_cny * withdrawal_fee_pct
    total_cost = procurement_cny + shipping_cny + packaging_cny + commission_cny + withdrawal_cny
    net_profit_cny = price_cny - total_cost
    net_profit_usd = net_profit_cny / exchange_rate if exchange_rate > 0 else 0.0
    margin_pct = (net_profit_cny / price_cny * 100) if price_cny > 0 else 0.0

    return {
        "price_local": round(price, 2),
        "price_cny": round(price_cny, 2),
        "commission_cny": round(commission_cny, 2),
        "withdrawal_cny": round(withdrawal_cny, 2),
        "shipping_cny": round(shipping_cny, 2),
        "packaging_cny": round(packaging_cny, 2),
        "procurement_cny": round(procurement_cny, 2),
        "total_cost_cny": round(total_cost, 2),
        "net_profit_cny": round(net_profit_cny, 2),
        "net_profit_usd": round(net_profit_usd, 2),
        "margin_pct": round(margin_pct, 1),
        "is_profitable": net_profit_cny > 0,
        "has_procurement": procurement_cny > 0,
    }


# ============================================================
# 统一利润计算入口（向后兼容）
# ============================================================

def calculate_profit(
    price_usd: float,
    defaults: dict,
    procurement_cny: float = 0.0,
    platform: str = "amazon",
    **kwargs,
) -> dict:
    """
    统一利润计算入口 — 向后兼容旧代码调用方式。

    根据 platform 选择对应的计算函数，返回标准结果字典。
    旧代码只传 price_usd/defaults/procurement_cny 仍可正常工作。

    Args:
        price_usd:        产品售价（本地货币）
        defaults:         利润默认参数字典
        procurement_cny:  采购成本（人民币）
        platform:         平台标识，默认 "amazon"
        **kwargs:         传递给具体计算器的额外参数

    Returns:
        标准利润结果字典
    """
    calculator = get_calculator(platform)
    result = calculator(price_usd, defaults, procurement_cny, **kwargs)

    # 向后兼容：旧代码期望 price_usd 字段
    if "price_usd" not in result:
        result["price_usd"] = result.get("price_local", round(price_usd, 2))

    return result
