"""
利润计算模块 — 可配置的跨境电商利润计算器。

默认公式：净利 = 售价(USD) × 汇率 - 采购成本 - 头程运费 - 佣金 - 广告费

各参数默认值存储在 src/config.py 的 get_profit_defaults() 中，
用户可在 Streamlit 侧边栏修改。
"""


def calculate_profit(
    price_usd: float,
    defaults: dict,
    procurement_cny: float = 0.0,
    shipping_cny: float = None,
    commission_pct: float = None,
    ad_pct: float = None,
    exchange_rate: float = None,
) -> dict:
    """
    计算单个产品的利润。

    Args:
        price_usd:          产品售价（美元）
        defaults:           get_profit_defaults() 返回的默认参数字典
        procurement_cny:    采购成本（人民币），0 表示未填写
        shipping_cny:       头程运费（人民币），None 表示使用默认值
        commission_pct:     佣金比例，None 表示使用默认值
        ad_pct:             广告预算占比，None 表示使用默认值
        exchange_rate:      汇率，None 表示使用默认值

    Returns:
        {
            "price_usd": float,          # 原始售价
            "price_cny": float,          # 售价（人民币）
            "commission_cny": float,     # 佣金（人民币）
            "ad_cost_cny": float,        # 广告费（人民币）
            "shipping_cny": float,       # 头程运费（人民币）
            "procurement_cny": float,    # 采购成本（人民币）
            "total_cost_cny": float,     # 总成本（人民币）
            "net_profit_cny": float,     # 净利（人民币）
            "net_profit_usd": float,     # 净利（美元）
            "margin_pct": float,         # 毛利率百分比
            "is_profitable": bool,       # 是否盈利
            "has_procurement": bool,     # 是否已填写采购成本
        }
    """
    # 使用默认值填充 None 参数
    if exchange_rate is None:
        exchange_rate = defaults.get("exchange_rate", 7.24)
    if commission_pct is None:
        commission_pct = defaults.get("commission_pct", 0.15)
    if ad_pct is None:
        ad_pct = defaults.get("ad_pct", 0.10)
    if shipping_cny is None:
        shipping_cny = defaults.get("shipping_cny", 15.0)

    # 计算售价（人民币）
    price_cny = price_usd * exchange_rate

    # 计算各项费用（人民币）
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
        "price_usd": round(price_usd, 2),
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
