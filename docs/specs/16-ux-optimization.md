# Spec 16：UX 体验优化

**版本**：v1.0
**状态**：📋 待实施
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
| `ARCHITECTURE_REPORT.md` | **修改** | 更新行动项 |

### 2.2 不改动的文件
- `src/scraper_*.py`（抓取逻辑不变）
- `src/analyzer.py`（分析逻辑不变）
- `src/calculator.py`（计算逻辑不变）
- `src/platforms.py`（平台注册不变）

---

## 3. Phase 1 — P0 关键体验

### 3.1 分析结果速览表

**位置**：实时选品页、指定选品页 — AI 分析卡片上方

**功能**：分析完成后，在展开式卡片上方展示一个紧凑的汇总表，包含：
- 产品标题（截断 40 字 + tooltip）
- 综合判定（🟢/🟡/🔴）
- 五维度分数（每个 `N/10`）
- 价格

**交互**：
- 点击表格行 → 自动滚动到对应的 expander
- 表格默认按判定排序（推荐 > 谨慎 > 不推荐）

```python
def _render_analysis_summary_table(products, results):
    """渲染分析结果速览表。"""
    summary_data = []
    for i, (p, r) in enumerate(zip(products, results)):
        row = {
            "#": i + 1,
            "产品": (p.get("title", "") or "")[:40],
            "判定": VERDICT_LABEL_MAP.get(r.get("final_verdict", ""), "⚪"),
            "价格": f"${float(p.get('price', 0) or 0):.2f}",
        }
        for label, key in ANALYSIS_DIMS:
            dim = r.get(key, {})
            row[label] = f"{dim.get('score', '-')}/10" if isinstance(dim, dict) else "-"
        summary_data.append(row)

    df = pd.DataFrame(summary_data)
    st.dataframe(
        df, width="stretch", hide_index=True,
        column_config={
            "#": st.column_config.NumberColumn(width="small"),
            "产品": st.column_config.TextColumn(width="large"),
            "判定": st.column_config.TextColumn(width="small"),
        },
    )
```

### 3.2 指定选品结果持久化

**问题**：`targeted_step` 在 `st.rerun()` 后能保持，但用户切换到其他页面再切回来时，`targeted_step` 仍为 `"done"`，结果应该还在。

**实际情况**：当前代码已经用 `st.session_state` 持久化了结果，问题在于 `_render_targeted_page` 被重新调用时会检查 `targeted_step`，结果应该能保持。

**经检查**：当前实现已使用 session_state 持久化，切换页面后结果不丢失。此需求**无需改动**。

### 3.3 数据过期提醒

**位置**：Dashboard 页面 — 指标卡片下方

**规则**：
- 数据 ≤ 3 天：无警告
- 数据 3-7 天：黄色提示「⚠️ 数据已 X 天未更新」
- 数据 > 7 天：红色警告「🔴 数据已过期，请运行 daily_scrape.py 更新」

```python
from datetime import datetime, timezone

def _get_data_freshness(latest_time_str: str) -> tuple[str, str]:
    """返回 (状态, 提示文本)。"""
    if not latest_time_str:
        return "error", "无数据"
    try:
        latest = datetime.fromisoformat(latest_time_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        days = (now - latest).days
        if days <= 3:
            return "ok", f"数据更新于 {days} 天前"
        elif days <= 7:
            return "warn", f"⚠️ 数据已 {days} 天未更新，建议运行 daily_scrape.py"
        else:
            return "error", f"🔴 数据已 {days} 天未更新，产品排名可能已变化"
    except (ValueError, TypeError):
        return "unknown", "时间格式异常"
```

### 3.4 产品收藏功能

**数据库变更**：`src/database.py` 新增 `favorites` 表和相关方法

```sql
CREATE TABLE IF NOT EXISTS favorites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    platform TEXT DEFAULT 'amazon',
    price TEXT,
    rating TEXT,
    analysis_json TEXT,
    notes TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(title, platform)
);
```

**新增方法**：
- `add_favorite(title, platform, price, rating, analysis_json, notes)` → bool
- `remove_favorite(title, platform)` → bool
- `get_favorites(platform=None)` → list[dict]
- `is_favorite(title, platform)` → bool

**UI 变更**：
- 实时选品页：每个分析卡片标题旁加 ⭐ 按钮
- 指定选品页：同上
- 历史记录页：新增「⭐ 已收藏」Tab

---

## 4. Phase 2 — P1 重要功能

### 4.1 1688 比价结果持久化

**实现**：将 1688 比价结果存入 `st.session_state`，以产品标题为 key。

```python
# 存储
key = f"price_1688_{product_title}"
st.session_state[key] = result_1688

# 恢复
cached = st.session_state.get(f"price_1688_{product_title}")
if cached:
    _display_1688_result(cached)
```

### 4.2 批量设置采购成本

**位置**：实时选品页 — AI 分析卡片区域顶部

**功能**：在分析结果上方加一个 expander「💰 批量设置采购成本」：
- 输入框：统一采购成本 (¥/件)
- 按钮：「应用到所有产品」
- 点击后更新所有产品的 `procurement` number_input 值

### 4.3 五维度雷达图

**位置**：每个分析卡片内 — 五维度 metric 下方

**实现**：使用 `st.altair_chart` 或 `st.plotly_chart` 绘制五维度雷达图。

```python
import altair as alt

def _render_radar_chart(dim_data: dict):
    """渲染五维度雷达图。"""
    chart_data = []
    for label, key in ANALYSIS_DIMS:
        dim = dim_data.get(key, {})
        score = dim.get("score", 0) if isinstance(dim, dict) else 0
        chart_data.append({"维度": label, "分数": score})

    df = pd.DataFrame(chart_data)
    # 使用极坐标雷达图
    chart = alt.Chart(df).mark_arc(innerRadius=50).encode(
        theta=alt.Theta("维度:N", sort=None),
        radius=alt.Radius("分数:Q", scale=alt.Scale(domain=[0, 10])),
        color=alt.value("#4CAF50"),
    )
    st.altair_chart(chart, width="stretch")
```

> ⚠️ Altair 的雷达图支持有限，可能需要使用 `plotly` 替代。实现时评估可行性。

### 4.4 产品对比功能

**位置**：历史记录页 — 历史记录 Tab

**交互**：
1. 历史产品列表的每一行加复选框
2. 选中 2-3 个产品后，底部出现「⚖️ 对比选中产品」按钮
3. 点击后弹出对比视图（st.dialog 或新 expander）

**对比表格**：
| 维度 | 产品 A | 产品 B | 产品 C |
|------|--------|--------|--------|
| 价格 | $17.90 | $26.50 | $12.97 |
| 市场容量 | 10/10 | 7/10 | 7/10 |
| 竞争程度 | 8/10 | 5/10 | 6/10 |
| ... | ... | ... | ... |
| 净利 | ¥25.30 | ¥38.50 | ¥15.20 |
| 判定 | 🟢 推荐 | 🟢 推荐 | 🟡 谨慎 |

### 4.5 搜索结果排序

**位置**：指定选品页 — 搜索结果表格上方

**实现**：在 dataframe 上方加排序选择器：

```python
sort_by = st.selectbox(
    "排序方式",
    options=["默认（搜索排名）", "价格从低到高", "价格从高到低", "评分从高到低", "评论数从多到少"],
)
```

---

## 5. Phase 3 — P2 锦上添花

### 5.1 Dashboard 平台筛选

在 Dashboard 指标卡片下方加平台筛选 multiselect，允许用户只看特定平台的数据。

### 5.2 跨平台对比空状态优化

当只有一个平台有数据时，跨平台对比 Tab 显示引导提示而非空表格。

### 5.3 历史记录分页

当产品数 > 100 时，历史记录表格加分页（每页 50 条）。

---

## 6. 实现顺序

| 步骤 | 功能 | 优先级 | 预估改动量 |
|------|------|--------|-----------|
| 1 | 分析结果速览表 | P0 | ~60 行 |
| 2 | 数据过期提醒 | P0 | ~30 行 |
| 3 | 1688 比价结果持久化 | P1 | ~40 行 |
| 4 | 批量设置采购成本 | P1 | ~40 行 |
| 5 | 产品收藏功能 | P1 | ~120 行（DB + UI） |
| 6 | 搜索结果排序 | P1 | ~30 行 |
| 7 | 五维度雷达图 | P2 | ~50 行 |
| 8 | 产品对比功能 | P2 | ~100 行 |
| 9 | Dashboard 平台筛选 | P2 | ~30 行 |
| 10 | 跨平台对比空状态 | P2 | ~15 行 |

**总计**：~515 行新增代码

---

## 7. 测试策略

- 速览表：验证数据正确渲染、排序逻辑
- 数据过期：验证 3 天/7 天阈值判断
- 收藏功能：验证 CRUD 操作、唯一约束
- 雷达图：验证数据绑定正确
- 排序：验证各排序方式的顺序正确性
- 全部通过现有 56 项测试无回归
