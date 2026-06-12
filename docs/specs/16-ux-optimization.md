# Spec 16：UX 体验优化

**版本**：v3.0
**状态**：🔄 实施中（P0-P2 已完成，P3 待实现，P4 新增）
**创建日期**：2026-06-02
**前置依赖**：Spec 12（历史记录增强）、Spec 15（Alibaba 平台）

---

## 1. 需求描述

### 1.1 背景
项目已完成多平台抓取 + AI 分析 + 利润计算的完整链路。经过深度使用测试，发现以下用户体验问题：
- 分析 20 个产品后，结果平铺展示，无法快速定位好产品
- 指定选品页切换页面后结果丢失
- 1688 比价和利润试算结果不持久
- 没有产品收藏功能
- 五维度分数缺乏可视化
- 数据过期无提醒

### 1.2 目标
提升日常选品效率，解决高频操作中的体验痛点。

### 1.3 核心需求
1. **分析结果速览表** — 一眼看出哪些产品值得深入
2. **指定选品结果持久化** — 切换页面不丢失
3. **数据过期提醒** — 知道数据是否还新鲜
4. **产品收藏/标记** — 标记感兴趣的产品
5. **1688 比价结果持久化** — 参考价不丢失
6. **批量设置采购成本** — 不用逐个输入
7. **五维度雷达图** — 直观对比产品优劣
8. **产品对比功能** — 并排比较 2-3 个产品
9. **搜索结果排序** — 按价格/评分/评论数排序
10. **Dashboard 平台筛选** — 只看关心的平台

---

## 2. 系统设计

### 2.1 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `app.py` | **修改** | 所有 UX 改进均在 app.py 中实现 |
| `src/database.py` | **修改** | 新增收藏相关方法 |
| `requirements.txt` | **修改** | 新增 plotly（雷达图） |
| `ARCHITECTURE_REPORT.md` | **修改** | 更新行动项 |

### 2.2 不改动的文件
- `src/scraper_*.py`（抓取逻辑不变）
- `src/analyzer.py`（分析逻辑不变）
- `src/calculator.py`（计算逻辑不变）
- `src/platforms.py`（平台注册不变）

---

## 3. Phase 1 — P0 关键体验 ✅ 已完成

### 3.1 分析结果速览表 ✅
- 位置：实时选品页 + 指定选品页，AI 分析卡片上方
- 功能：紧凑汇总表（产品/判定/价格/五维度），按判定排序

### 3.2 指定选品结果持久化 ✅
- 当前实现已使用 session_state 持久化，切换页面后结果不丢失

### 3.3 数据过期提醒 ✅
- Dashboard 根据抓取时间显示 ok/warn/error 状态（3天/7天阈值）

---

## 4. Phase 2 — P1 重要功能 ✅ 已完成

### 4.1 1688 比价结果持久化 ✅
- 存入 session_state，切换页面后自动恢复

### 4.2 批量设置采购成本 ✅
- 实时选品页新增「批量设置采购成本」expander

### 4.3 搜索结果排序 ✅
- 指定选品页新增排序选择器（价格/评分/评论数）

### 4.4 Dashboard 平台筛选 ✅
- 多平台数据时显示筛选 multiselect

### 4.5 跨平台对比空状态 ✅
- 仅一个平台数据时显示引导提示

---

## 5. Phase 3 — P3 剩余功能 📋 待实现

### 5.1 产品收藏功能

**数据库变更**：`src/database.py` 新增 `favorites` 表

```sql
CREATE TABLE IF NOT EXISTS favorites (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT NOT NULL,
    platform      TEXT DEFAULT 'amazon',
    price         TEXT,
    rating        TEXT,
    num_reviews   TEXT DEFAULT '0',
    analysis_json TEXT,
    notes         TEXT DEFAULT '',
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(title, platform)
);
```

**新增数据库方法**（`src/database.py`）：

| 方法 | 签名 | 说明 |
|------|------|------|
| `add_favorite` | `(title, platform, price, rating, num_reviews, analysis_json, notes="") → bool` | 添加收藏（UPSERT） |
| `remove_favorite` | `(title, platform) → bool` | 取消收藏 |
| `is_favorite` | `(title, platform) → bool` | 检查是否已收藏 |
| `get_favorites` | `(platform=None) → list[dict]` | 获取收藏列表 |

**UI 变更**（`app.py`）：

1. **实时选品页 / 指定选品页**：每个分析 expander 标题旁加 ⭐ 按钮
   - 未收藏：`st.button("⭐ 收藏", key=f"fav_{i}")`
   - 已收藏：`st.button("⭐ 已收藏", key=f"unfav_{i}")`
   - 点击后调用 `add_favorite` / `remove_favorite`

2. **历史记录页**：Tabs 新增「⭐ 已收藏」Tab
   - 展示收藏产品列表
   - 每行有「取消收藏」按钮
   - 支持查看收藏产品的完整分析

### 5.2 五维度雷达图

**技术方案**：使用 Plotly 绘制雷达图（需安装 `plotly`）

> 备选方案：Streamlit 原生 `st.bar_chart` 绘制水平条形图（无需额外依赖）

**实现**（`app.py` 辅助函数）：

```python
import plotly.graph_objects as go

def _render_radar_chart(dim_data: dict, title: str = ""):
    """渲染五维度雷达图。"""
    labels = [label for label, _ in ANALYSIS_DIMS]
    values = []
    for _, key in ANALYSIS_DIMS:
        dim = dim_data.get(key, {})
        values.append(dim.get("score", 0) if isinstance(dim, dict) else 0)

    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=values + [values[0]],  # 闭合
        theta=labels + [labels[0]],
        fill='toself',
        name=title,
    ))
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 10])),
        showlegend=False,
        height=300,
        margin=dict(l=60, r=60, t=30, b=30),
    )
    st.plotly_chart(fig, width="stretch")
```

**位置**：每个分析 expander 内，五维度 metric 下方

**依赖变更**：`requirements.txt` 新增 `plotly>=5.0.0`

### 5.3 产品对比功能

**位置**：历史记录页 — 历史记录 Tab

**交互流程**：
1. 历史产品表格改为可选择的 DataFrame（使用 `st.dataframe` 的 `selection_mode="multi-row"`）
2. 用户选中 2-3 个产品
3. 底部显示「⚖️ 对比选中产品」按钮
4. 点击后弹出对比视图

**对比视图内容**：
- 并排展示每个产品的：标题、价格、评分、五维度分数、判定、利润率
- 用颜色高亮最优项（绿色 = 最佳，红色 = 最差）

**实现方案**：
- 使用 `st.dataframe` 的 `on_select="rerun"` 获取选中行
- 构建对比 DataFrame，每列一个产品

```python
# 对比视图
selected_rows = st.dataframe(
    df_display, width="stretch", hide_index=True,
    selection_mode="multi-row",
    on_select="rerun",
)
if selected_rows and len(selected_rows.selection.rows) >= 2:
    selected_indices = selected_rows.selection.rows
    if st.button("⚖️ 对比选中产品"):
        _render_comparison_view(products, selected_indices)
```

### 5.4 历史记录分页

**位置**：历史记录页 — 历史记录 Tab

**规则**：当产品数 > 50 时启用分页

**实现**：
```python
PAGE_SIZE = 50
if len(products) > PAGE_SIZE:
    total_pages = (len(products) + PAGE_SIZE - 1) // PAGE_SIZE
    col_page, col_info = st.columns([1, 3])
    with col_page:
        page_num = st.number_input(
            "页码", min_value=1, max_value=total_pages, value=1, step=1,
        )
    with col_info:
        st.caption(f"共 {len(products)} 条记录，{total_pages} 页")

    start = (page_num - 1) * PAGE_SIZE
    end = start + PAGE_SIZE
    page_products = products[start:end]
else:
    page_products = products
```

---

## 6. 实现顺序

| 步骤 | 功能 | 文件 | 预估改动量 |
|------|------|------|-----------|
| 1 | 安装 plotly | requirements.txt | 1 行 |
| 2 | 数据库收藏表 + 方法 | src/database.py | ~80 行 |
| 3 | 五维度雷达图 | app.py | ~40 行 |
| 4 | 产品收藏 UI（实时/指定选品页） | app.py | ~50 行 |
| 5 | 产品对比功能 | app.py | ~80 行 |
| 6 | 历史记录分页 | app.py | ~20 行 |
| 7 | 已收藏 Tab | app.py | ~40 行 |
| 8 | 测试验证 | tests/ | — |

**总计**：~310 行新增代码

---

## 7. 测试策略

- 收藏 CRUD：验证添加、删除、查询、唯一约束
- 雷达图：验证数据绑定正确（无 import 错误）
- 对比：验证选中 2-3 个产品后对比视图正确渲染
- 分页：验证 >50 条时分页逻辑正确
- 全部通过现有 56 项测试无回归

---

## 8. P4：侧边栏优化 + 收藏采购流程（新增）

### 8.1 侧边栏瘦身

**问题**：侧边栏10+控件，利润参数藏在折叠面板里，AI模型选择器总是显示。

**方案**：
- AI模型/供应商选择器移入"⚙️ 高级设置"折叠面板（大多数人只设一次）
- 利润参数（运费档位、佣金比例）保持展开，因为用户经常调整
- 侧边栏只保留：页面导航、平台/地区、数据状态、利润参数

### 8.2 收藏采购流程

**问题**：收藏后没有下一步，是死胡同。

**方案**：收藏Tab增加采购工作流状态机

```
收藏 → 🔍 1688找供应商 → 📦 申请样品 → 💰 计算落地成本 → 🚀 准备上架
```

每个状态可标记，用不同颜色标签展示进度。

**数据库**：favorites表增加 `status TEXT DEFAULT 'saved'` 字段
- `saved` — 仅收藏
- `sourcing` — 正在找供应商
- `sampling` — 已申请样品
- `ready` — 准备上架
- `launched` — 已上架
