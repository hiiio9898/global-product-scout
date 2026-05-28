# Spec 0-B：利润计算公式可配置

**版本**：v1.0
**状态**：✅ 已实现并验收通过
**最后更新**：2026-05-28

---

## 1. 需求描述

### 1.1 背景
当前 AI 分析给出的"利润潜力"维度只是模糊的 1-10 评分，用户无法知道"这款产品从 1688 拿货到亚马逊卖，到底能赚多少钱"。需要一个可配置的利润计算器，让用户输入实际成本参数，自动算出净利润和毛利率。

### 1.2 目标用户
跨境电商卖家——需要快速判断"这个产品值不值得做"。

### 1.3 核心需求
1. 提供默认利润计算公式和参数（佣金 15%、广告 10%、汇率 7.24、头程 ¥15/件）
2. 用户可在侧边栏修改各参数的默认值
3. 每个产品 expander 内展示"💰 利润试算"卡片，使用全局默认参数
4. 用户可为单个产品覆盖默认参数（输入自定义采购成本等）
5. 公式：`净利 = 售价(USD) × 汇率 - 采购成本(CNY) - 头程运费(CNY) - 佣金(USD) - 广告费(USD)`

---

## 2. 系统设计

### 2.1 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `src/calculator.py` | **新建** | 利润计算引擎，纯函数，无副作用 |
| `src/config.py` | **修改** | 新增 `get_profit_defaults()` 返回默认参数 |
| `app.py` | **修改** | 侧边栏新增"💰 利润参数"折叠区；每个产品 expander 内新增利润试算卡片 |
| `tests/test_basic.py` | **修改** | 新增利润计算单元测试 |

### 2.2 数据流

```
侧边栏 "💰 利润参数" 折叠区
  ├─ 用户修改默认值 → st.session_state["profit_*"]
  ↓
产品 expander 内 "💰 利润试算" 卡片
  ├─ 读取全局默认参数（或用户单产品覆盖）
  ├─ 调用 calculate_profit(product_price, defaults, overrides)
  ↓
返回 { gross_profit_cny, gross_profit_usd, margin_pct, ... }
  ↓
展示：净利 ¥XX.XX / 毛利率 XX% / 颜色标识
```

### 2.3 利润计算公式

```
售价人民币 = 产品价格(USD) × 汇率(CNY/USD)
佣金 = 售价人民币 × 佣金比例
广告费 = 售价人民币 × 广告预算占比
总成本 = 采购成本 + 头程运费 + 佣金 + 广告费
净利 = 售价人民币 - 总成本
毛利率 = 净利 / 售价人民币 × 100%
```

**注意**：佣金和广告费以人民币计价（因为其他成本都是人民币），简化计算。

---

## 3. 接口定义

### 3.1 `src/config.py` — 新增函数

```python
def get_profit_defaults() -> dict:
    """
    返回利润计算的默认参数。

    Returns:
        {
            "exchange_rate": float,      # 汇率 CNY/USD，默认 7.24
            "commission_pct": float,     # 佣金比例，默认 0.15 (15%)
            "ad_pct": float,             # 广告预算占比，默认 0.10 (10%)
            "shipping_cny": float,       # 头程运费（人民币/件），默认 15.0
            "procurement_cny": float,    # 采购成本（人民币/件），默认 0.0（需用户填写）
        }
    """
```

### 3.2 `src/calculator.py` — 新建模块

```python
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
        defaults:           get_profit_defaults() 返回的默认参数
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

    Raises:
        无。所有异常静默处理。
    """
```

### 3.3 `app.py` — 侧边栏变更

#### 新增：利润参数折叠区

位置：侧边栏，"🤖 AI 模型" 区域下方。

```python
# ---- 💰 利润参数 ----
st.sidebar.divider()
with st.sidebar.expander("💰 利润参数（可配置）", expanded=False):
    profit_defaults = get_profit_defaults()

    exchange_rate = st.number_input(
        "汇率 (CNY/USD)", min_value=5.0, max_value=10.0,
        value=float(profit_defaults["exchange_rate"]), step=0.01,
        help="1 美元兑换多少人民币",
    )
    commission_pct = st.slider(
        "亚马逊佣金比例", min_value=0.0, max_value=0.50,
        value=float(profit_defaults["commission_pct"]), step=0.01,
        format="%.0f%%",
    )
    ad_pct = st.slider(
        "广告预算占比", min_value=0.0, max_value=0.50,
        value=float(profit_defaults["ad_pct"]), step=0.01,
        format="%.0f%%",
    )
    shipping_cny = st.number_input(
        "头程运费 (¥/件)", min_value=0.0, max_value=200.0,
        value=float(profit_defaults["shipping_cny"]), step=1.0,
        help="从国内发到亚马逊仓库的单件运费",
    )

# 存入 session_state 供计算器使用
st.session_state["profit_defaults"] = {
    "exchange_rate": exchange_rate,
    "commission_pct": commission_pct,
    "ad_pct": ad_pct,
    "shipping_cny": shipping_cny,
    "procurement_cny": 0.0,
}
```

#### 新增：产品 expander 内利润试算

在每个产品 expander 的五维度评分下方，新增利润试算区域：

```python
# 在 st.expander(expander_label) 内部，五维度展示之后

st.divider()
st.markdown("**💰 利润试算**")

defaults = st.session_state.get("profit_defaults", get_profit_defaults())

# 单产品采购成本输入
procurement = st.number_input(
    "预估采购成本 (¥/件)",
    min_value=0.0, max_value=1000.0, value=0.0, step=1.0,
    key=f"procurement_{i}",
    help="从 1688 等平台采购的单件成本",
)

result = calculate_profit(
    price_usd=product_price,
    defaults=defaults,
    procurement_cny=procurement,
)

# 展示结果
if result["has_procurement"]:
    color = "normal" if result["is_profitable"] else "inverse"
    cols = st.columns(3)
    cols[0].metric("净利", f"¥{result['net_profit_cny']:.2f}", delta=f"${result['net_profit_usd']:.2f}")
    cols[1].metric("毛利率", f"{result['margin_pct']:.1f}%", delta="盈利" if result["is_profitable"] else "亏损", delta_color=color)
    cols[2].metric("总成本", f"¥{result['total_cost_cny']:.2f}")
else:
    st.caption("👆 请输入采购成本以计算利润")
```

---

## 4. 数据模型

### 4.1 Session State 新增字段

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `profit_defaults` | dict | 当前利润参数（从侧边栏输入同步） |

### 4.2 配置文件变更

无。所有默认值硬编码在 `get_profit_defaults()` 中，侧边栏可覆盖。

---

## 5. UI 设计

### 5.1 侧边栏布局（新增部分）

```
...
├─ ─────────────
│
├─ 💰 利润参数（可配置）  ← 新增折叠区
│   ├─ 汇率 (CNY/USD): [7.24]
│   ├─ 亚马逊佣金比例: [15%] (slider)
│   ├─ 广告预算占比: [10%] (slider)
│   └─ 头程运费 (¥/件): [15]
│
├─ ─────────────
└─ 📦 历史记录：0 条产品数据
```

### 5.2 产品 expander 内利润试算（新增部分）

```
🟢 推荐入手 #1 Owala FreeSip Water Bottle...
├─ ✅ 推荐入手 — 高需求低门槛低风险
├─ [五维度评分卡片]  (现有)
├─ [详细分析文本]    (现有)
├─ ─────────────
├─ 💰 利润试算       ← 新增
│   ├─ 预估采购成本 (¥/件): [  25  ]
│   ├─ [净利 ¥102.87] [毛利率 35.2%] [总成本 ¥53.40]
│   └─ (或未填采购成本时) "👆 请输入采购成本以计算利润"
```

### 5.3 利润颜色标识

| 毛利率 | 颜色 | 含义 |
|--------|------|------|
| ≥ 30% | 🟢 绿色 | 利润可观，值得做 |
| 15% - 29% | 🟡 黄色 | 利润一般，需精打细算 |
| < 15% | 🔴 红色 | 利润微薄，风险较高 |
| 亏损 | 🔴 红色 + 负数 | 不推荐 |

---

## 6. 验收标准

### 6.1 功能验收

| # | 验收条件 | 验证方法 |
|---|---------|---------|
| 1 | `get_profit_defaults()` 返回正确结构 | 单元测试断言 |
| 2 | `calculate_profit()` 计算结果正确 | 手动计算验证 + 单元测试 |
| 3 | 侧边栏可修改汇率、佣金、广告、头程运费 | UI 操作 |
| 4 | 修改参数后，产品利润卡片实时更新 | 修改参数 → 查看 expander 内数值变化 |
| 5 | 未填采购成本时，显示提示而非计算结果 | UI 验证 |
| 6 | 填入采购成本后，显示净利、毛利率、总成本 | UI 验证 |
| 7 | 毛利率颜色标识正确（绿/黄/红） | UI 验证 |
| 8 | `python -m py_compile src/calculator.py` 通过 | 终端执行 |
| 9 | `python -m py_compile app.py` 通过 | 终端执行 |
| 10 | `pytest tests/` 通过 | 终端执行 |

### 6.2 非功能验收

| # | 验收条件 |
|---|---------|
| 11 | 不引入新的 Python 依赖 |
| 12 | `daily_scrape.py` 和 `src/analyzer.py` 不受影响 |
| 13 | 利润计算为纯函数，不依赖外部 API 或网络 |
| 14 | 单产品参数覆盖不影响其他产品的全局默认值 |

---

## 7. 不在本次范围内

- 实时汇率 API 调用（本次使用手动输入的固定汇率）
- 从 1688 自动抓取采购价格（阶段四的功能）
- 利润数据持久化到数据库（后续增强）
- 多件装 / 批量采购的阶梯价格计算
- FBA 费用精确计算（简化为固定头程运费）
