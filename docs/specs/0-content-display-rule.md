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
