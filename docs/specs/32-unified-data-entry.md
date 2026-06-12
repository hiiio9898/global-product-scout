# Spec 32：JSON/实时抓取合并

**版本**：v1.0
**状态**：📋 待实现
**创建日期**：2026-06-10

---

## 1. 需求描述

### 1.1 背景
实时选品页有两个按钮："分析JSON数据"和"实时抓取"。新用户不知道"JSON数据"是什么（需要先跑CLI命令），两个入口让人困惑。

### 1.2 核心需求
1. 合并为单一入口："获取数据"
2. 自动选择最佳数据源：优先JSON → 降级实时抓取
3. 明确告知用户数据来源和时间
4. 保留手动刷新按钮

---

## 2. 系统设计

### 2.1 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `app.py` | **修改** | `_render_live_page()` 合并两个按钮为统一入口 |

### 2.2 统一入口逻辑

```python
# 单一按钮
if st.button("🔍 获取数据", type="primary"):
    # 1. 尝试读取 products.json（每日自动更新）
    json_data = _load_json_data(platform, region)
    if json_data:
        st.session_state.products = json_data
        st.session_state.source_info = {"source": "daily_update", "age": "..."}
    else:
        # 2. 降级到实时抓取
        with st.spinner("正在实时抓取..."):
            products, info = scrape_live(platform, region)
            st.session_state.products = products
            st.session_state.source_info = info

# 数据来源提示
if st.session_state.source_info:
    source = st.session_state.source_info["source"]
    if source == "daily_update":
        st.info("📊 数据来自每日自动更新（GitHub Actions）")
    elif source == "live":
        st.success("🔴 实时抓取数据")
```

---

## 3. 验收标准

- [ ] 只有一个"获取数据"按钮
- [ ] 自动选择最佳数据源
- [ ] 明确显示数据来源和时间
- [ ] 新用户不会困惑
- [ ] 所有现有测试通过
