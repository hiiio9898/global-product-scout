# 内容展示规范（Anti-Truncation Rule）

**版本**：v1.0  
**生效日期**：2026-05-28

---

## 核心原则

**所有面向用户展示的内容，必须完整可见，禁止无理由截断。**

---

## 规则清单

### 1. 禁止截断的场景

| 场景 | 错误做法 | 正确做法 |
|------|----------|----------|
| DataFrame 列 | `title[:60]` | 直接传完整文本，用 `column_config` 控制宽度 |
| 卡片/容器内文本 | `title[:55]` | 直接展示完整文本，容器自动换行 |
| 详情区域文本 | `reason[:40]` | 完整展示，用 `st.markdown` 或 `st.caption` |
| 列表项文本 | `item[:50]` | 完整展示 |
| verdict_reason | `reason[:60]` | 完整展示 |

### 2. 允许截断的场景（有限例外）

| 场景 | 截断方式 | 原因 |
|------|----------|------|
| `st.expander()` 标题 | `title[:40]` + `…` | expander 标题栏宽度有限，但必须搭配 `help=` 显示完整文本 |
| `st.selectbox()` 选项 | `title[:50]` + `…` | 下拉框宽度有限，但必须搭配 `help=` 显示完整文本 |
| 趋势查询关键词 | `[:30]` | 这是传给 API 的参数，不是展示，允许截断 |
| 1688 搜索关键词 | `[:30]` | 同上，API 参数限制 |

### 3. 实现要求

#### 3.1 DataFrame
```python
# ✗ 错误
df["标题"] = df["标题"].str[:60]

# ✓ 正确 — 使用 column_config 控制宽度，文本自动换行
st.dataframe(
    df,
    column_config={
        "标题": st.column_config.TextColumn(width="large"),
    },
)
```

#### 3.2 st.metric delta
```python
# ✗ 错误 — delta 截断到 40 字
st.metric(label, value, delta=reason[:40])

# ✓ 正则 — 完整 delta + help tooltip
st.metric(label, value, delta=reason, help=reason)
```

#### 3.3 expander 标题
```python
# ✗ 错误 — 截断且无完整信息
with st.expander(f"{title[:55]}…"):

# ✓ 正确 — 短标题 + help tooltip
with st.expander(f"{verdict_label} #{i} {title[:40]}{'…' if len(title) > 40 else ''}", help=title):
```

#### 3.4 卡片内容
```python
# ✗ 错误
st.markdown(f"**{title[:60]}**")

# ✓ 正确 — 完整文本，容器自动处理换行
st.markdown(f"**{title}**")
```

---

## 检查清单

新增或修改 UI 代码时，自查以下项：

- [ ] 所有 `[:N]` 截断是否有合理理由？（参见「允许截断的场景」）
- [ ] 截断处是否提供了完整信息的查看方式（tooltip / expander / 悬浮提示）？
- [ ] DataFrame 列是否使用 `column_config` 而非字符串截断？
- [ ] st.metric 的 delta 是否完整展示？
- [ ] `st.expander()` 标题截断时是否包含 `help=完整文本`？
- [ ] `st.selectbox()` 选项截断时是否包含 `help=完整文本`？

---

## 4. 多平台 UI 规范

### 4.1 禁止硬编码平台名称

所有面向用户的文本必须动态读取当前平台信息，禁止硬编码 "Amazon" 等平台名。

```python
# ✗ 错误 — 硬编码平台名
st.caption("数据来源：Amazon Best Sellers（实时抓取）")
st.markdown("AI 将搜索 Amazon 并生成报告")

# ✓ 正确 — 动态平台名
pf_info = get_platform_info(st.session_state.get("active_platform", "amazon"))
pf_name = f"{pf_info['icon']} {pf_info['name']}"
st.caption(f"数据来源：{pf_name}（实时抓取）")
st.markdown(f"AI 将搜索 {pf_name} 并生成报告")
```

### 4.2 平台自适应参数面板

侧边栏利润参数应根据当前平台动态调整：

```python
# ✓ 正确 — Amazon 特有参数仅在 Amazon 平台显示
if active_pf == "amazon":
    ad_pct = st.slider("广告预算占比", ...)
else:
    ad_pct = 0.0  # 非 Amazon 平台无广告费

# ✓ 正确 — 各平台使用对应术语
commission_label = {
    "amazon": "亚马逊佣金比例",
    "ebay": "eBay 成交费比例",
    "alibaba": "阿里巴巴佣金比例",
}.get(active_pf, "平台佣金比例")
```

### 4.3 动态加载平台抓取/搜索函数

禁止直接调用特定平台的抓取函数，必须通过平台注册表动态加载：

```python
# ✗ 错误 — 硬编码调用
from src.scraper_search import search_amazon
result = search_amazon(keyword)

# ✓ 正确 — 动态加载
import importlib
pf_info = get_platform_info(platform_key)
mod = importlib.import_module(pf_info["search_module"])
func = getattr(mod, pf_info["search_func"])
result = func(keyword, region=region)
```

---

## 5. 版本号管理

版本号必须定义为模块级常量 `APP_VERSION`，所有页脚统一引用：

```python
# ✓ 正确
APP_VERSION = "v0.5.0"
st.caption(f"Global Product Scout {APP_VERSION}")

# ✗ 错误 — 硬编码版本号
st.caption("Global Product Scout v0.2.0")
```

---

## 6. 模块级常量提取

以下常用映射/列表必须定义为模块级常量，禁止在函数内重复定义：

```python
# 推荐判定标签映射
VERDICT_LABEL_MAP = {
    "recommended": "🟢 推荐入手",
    "cautious": "🟡 谨慎评估",
    "not_recommended": "🔴 不推荐",
}

# AI 分析五维度
ANALYSIS_DIMS = [
    ("📊 市场容量", "market_capacity"),
    ("⚔️ 竞争程度", "competition"),
    ("💰 利润潜力", "profit_potential"),
    ("🎓 新手友好", "beginner_friendly"),
    ("🌡️ 季节风险", "seasonality_risk"),
]
```
