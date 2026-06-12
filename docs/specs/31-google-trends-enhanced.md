# Spec 31：Google Trends增强

**版本**：v1.0
**状态**：📋 待实现
**创建日期**：2026-06-10
**前置依赖**：Spec 6（Google Trends基础版，已完成）

---

## 1. 需求描述

### 1.1 背景
当前Google Trends集成太浅：从标题截取关键词不可靠，只返回一个方向箭头，没有时间序列数据。

### 1.2 核心需求
1. 关键词提取改进：用AI从标题中提取核心品类词
2. 展示真实的时间序列趋势图（Plotly折线图）
3. 支持多关键词对比
4. 趋势数据缓存（避免重复查询）

---

## 2. 系统设计

### 2.1 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `src/trends.py` | **修改** | 新增 `get_trend_timeseries()` 返回12个月数据；缓存结果 |
| `src/analyzer.py` | **修改** | AI分析时同时提取核心品类关键词 |
| `app.py` | **修改** | 分析卡片中展示趋势折线图 |

### 2.2 关键词提取改进

```python
# analyzer.py — 在 BATCH_SYSTEM_PROMPT 中增加
# 同时输出 search_keyword 字段（2-3个英文核心品类词，用于Google Trends查询）
```

### 2.3 趋势图展示

```python
# app.py — 分析卡片中
if product.get("trend_data"):
    import plotly.express as px
    fig = px.line(x=product["trend_data"]["dates"],
                  y=product["trend_data"]["values"],
                  title="Google Trends 搜索趋势")
    st.plotly_chart(fig, use_container_width=True)
```

---

## 3. 验收标准

- [ ] AI提取的关键词比标题截取更准确
- [ ] 展示12个月趋势折线图
- [ ] 趋势数据缓存24小时
- [ ] 查询失败时优雅降级（不显示图表）
- [ ] 所有现有测试通过
