# add-platform-calculator — 新增平台利润计算器

## 触发条件
- 用户要求"新增 Temu 利润计算"、"添加 Shopee 费用"等
- 需要为新平台实现利润计算逻辑
- 需要修改现有平台的费用结构

## 核心架构

利润计算采用**装饰器注册表模式**（`src/calculator.py`）：
- `_CALCULATOR_REGISTRY` — 全局计算器注册字典
- `@register_calculator("平台key")` — 装饰器注册
- `get_calculator(platform_key)` — 获取计算器（不存在时降级到 Amazon）
- `calculate_profit()` — 统一入口（向后兼容旧代码）

## 工作流

### 1. 确认费用结构
明确平台的收费项目，例如：
- 平台佣金比例
- 支付手续费
- 运费结构（头程/尾程）
- 包装费
- 平台特有费用（如 eBay 的刊登费、Alibaba 的信保费）

### 2. 在 platforms.py 中配置默认参数
在 `src/platforms.py` 的对应平台条目中设置 `profit_defaults`：
```python
"profit_defaults": {
    "commission_pct": 0.15,       # 佣金比例
    "ad_pct": 0.10,               # 广告费比例（可选）
    "shipping_cny": 20.0,         # 头程运费（人民币）
    "packaging_cny": 5.0,         # 包装费（人民币）
    "payoneer_fee_pct": 0.01,     # 提现手续费（可选）
    # ... 平台特有参数
},
```

这些参数会作为 `defaults` 字典传入计算器函数。用户可在 Streamlit 侧边栏覆盖。

### 3. 实现计算器函数
在 `src/calculator.py` 中新增：
```python
@register_calculator("<platform>")
def calculate_<platform>_profit(
    price: float,            # 产品售价（本地货币）
    defaults: dict,          # 利润默认参数（来自 platforms.py）
    procurement_cny: float = 0.0,  # 采购成本（人民币），0 = 未填写
    **kwargs,                # 预留扩展
) -> dict:
    """
    <平台名> 利润计算。

    公式：
        售价(本地货币) × 汇率 = 售价(CNY)
        佣金 = 售价(CNY) × commission_pct
        总成本 = 采购成本 + 运费 + 佣金 + ...
        净利 = 售价(CNY) - 总成本
        毛利率 = 净利 / 售价(CNY)
    """
    exchange_rate = defaults.get("exchange_rate", 7.24)
    commission_pct = defaults.get("commission_pct", 0.15)
    shipping_cny = defaults.get("shipping_cny", 15.0)
    # ... 读取平台特有参数

    price_cny = price * exchange_rate
    commission_cny = price_cny * commission_pct
    total_cost = procurement_cny + shipping_cny + commission_cny
    net_profit_cny = price_cny - total_cost
    net_profit_usd = net_profit_cny / exchange_rate if exchange_rate > 0 else 0.0
    margin_pct = (net_profit_cny / price_cny * 100) if price_cny > 0 else 0.0

    return {
        # ===== 必填字段（标准返回 dict 契约）=====
        "price_local": round(price, 2),
        "price_cny": round(price_cny, 2),
        "commission_cny": round(commission_cny, 2),
        "shipping_cny": round(shipping_cny, 2),
        "procurement_cny": round(procurement_cny, 2),
        "total_cost_cny": round(total_cost, 2),
        "net_profit_cny": round(net_profit_cny, 2),
        "net_profit_usd": round(net_profit_usd, 2),
        "margin_pct": round(margin_pct, 1),
        "is_profitable": net_profit_cny > 0,
        "has_procurement": procurement_cny > 0,
        # ===== 平台特有字段（可选）=====
        # "fvf_cny": round(fvf_cny, 2),       # eBay 成交费
        # "listing_cny": round(listing_cny, 2), # eBay 刊登费
        # "trade_assurance_cny": ...,           # Alibaba 信保费
    }
```

### 4. 标准返回 dict 契约
**必填字段**（所有平台计算器必须返回）：
| 字段 | 类型 | 说明 |
|------|------|------|
| `price_local` | float | 售价（本地货币） |
| `price_cny` | float | 售价（人民币） |
| `commission_cny` | float | 平台佣金（人民币） |
| `shipping_cny` | float | 运费（人民币） |
| `procurement_cny` | float | 采购成本（人民币） |
| `total_cost_cny` | float | 总成本（人民币） |
| `net_profit_cny` | float | 净利润（人民币） |
| `net_profit_usd` | float | 净利润（美元） |
| `margin_pct` | float | 毛利率（百分比） |
| `is_profitable` | bool | 是否盈利 |
| `has_procurement` | bool | 是否填写了采购成本 |

**平台特有字段**（按需添加）：如 `fvf_cny`、`listing_cny`、`payoneer_cny`、`trade_assurance_cny` 等。

### 5. 测试验证
```bash
python -m py_compile src/calculator.py
pytest tests/
```

验证项：
- `calculate_profit(price, defaults, platform="<platform>")` 返回正确结果
- 返回 dict 包含所有必填字段
- `is_profitable` 在净利 > 0 时为 True
- 未填写采购成本时 `has_procurement` 为 False

### 6. 交付说明
告知用户：
- 新增了哪些费用参数
- 利润计算公式
- `defaults` 参数映射关系
- 是否需要用户在侧边栏调整参数

## 注意事项
- `get_calculator()` 找不到平台时会降级到 `calculate_amazon_profit`，不会报错
- `calculate_profit()` 会自动补充 `price_usd` 字段（向后兼容）
- `defaults` 中的 `exchange_rate` 由 `src/platforms.py` 的 `get_region_info()` 提供，支持实时汇率覆盖硬编码值
- 不修改其他平台的计算器逻辑
