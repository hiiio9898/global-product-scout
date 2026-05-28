# Spec 3：产品趋势追踪

**版本**：v1.0
**状态**：✅ 已实现并验收通过
**最后更新**：2026-05-28

---

## 1. 需求描述

### 1.1 背景
当前数据库已存储多次抓取记录，但历史记录页面仅做列表展示。真正有价值的是**时间维度上的变化**：同一产品在不同日期的排名、价格、评论数的变化趋势。例如"上周排名第 3 的产品这周跌到第 20"说明热度在降，"之前没见过的产品突然冲进前 5"值得研究。

### 1.2 核心需求
1. 解析 Amazon 产品页面中的 ASIN（`data-asin` 属性），存入数据库
2. 历史记录页面新增"📈 产品趋势"子页面
3. 按产品（ASIN）分组，展示同一产品在不同抓取时间的排名/价格/评论数变化
4. 用 `st.line_chart` 绘制变化曲线
5. AI 趋势判断（可选，降级友好）

---

## 2. 系统设计

### 2.1 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `src/scraper.py` | **修改** | `_parse_product_card()` 新增解析 `data-asin` 属性 |
| `src/database.py` | **修改** | products 表新增 `asin` 字段；新增 `get_trend_data()` 函数 |
| `app.py` | **修改** | 历史记录页面新增"📈 产品趋势"tab |
| `docs/specs/3-product-trend-tracking.md` | **新建** | 本 Spec |

### 2.2 数据库变更

```sql
-- 新增字段
ALTER TABLE products ADD COLUMN asin TEXT DEFAULT '';
```

### 2.3 数据流

```
scraper 解析 ASIN（从 data-asin 属性）
        ↓
存入 products 表 asin 字段
        ↓
app.py 历史记录页面 → "📈 产品趋势" tab
        ↓
调用 get_trend_data(asin) → 按时间排序的历史数据
        ↓
st.line_chart 展示排名/价格/评论数变化曲线
```

---

## 3. 接口定义

### 3.1 `src/scraper.py` — 修改 `_parse_product_card()`

在 `_parse_product_card(card, rank)` 中新增 ASIN 解析：

```python
def _parse_product_card(card, rank: int) -> Optional[dict]:
    title = _extract_title(card)
    if not title:
        return None

    # 解析 ASIN
    asin = card.get("data-asin", "").strip()

    price = _extract_price(card)
    # ... 其余不变

    return {
        "title": title,
        "asin": asin,  # 新增
        "price": price,
        # ...
    }
```

### 3.2 `src/database.py` — 新增函数

```python
def get_trend_data(
    asin: str = None,
    title: str = None,
    db_path: Optional[str] = None,
) -> list[dict]:
    """
    获取单个产品的趋势数据（按时间排序）。

    Args:
        asin:   产品 ASIN（优先）
        title:  产品标题（ASIN 为空时回退到标题匹配）
        db_path: 数据库路径

    Returns:
        按 scrape_time 升序排列的数据列表：
        [
            {
                "scrape_time": "2026-05-20 14:00:00",
                "price": 38.32,
                "rank": 1,
                "num_reviews": 121944,
                "rating": 4.7,
            },
            ...
        ]
    """
```

### 3.3 `app.py` — 新增趋势页面

在 `_render_history_page()` 中新增 tab：

```python
def _render_history_page():
    # ... 现有内容 ...

    tab_list, tab_trend = st.tabs(["📚 历史记录", "📈 产品趋势"])

    with tab_list:
        # ... 现有历史记录内容 ...

    with tab_trend:
        _render_trend_page()
```

```python
def _render_trend_page():
    """渲染产品趋势页面。"""
    st.subheader("📈 产品趋势分析")
    st.caption("对比同一产品在不同抓取时间的排名、价格、评论数变化")

    # 选择产品
    products = get_all_products()
    if not products:
        st.info("暂无数据，请先运行分析。")
        return

    # 去重：按 title 获取唯一产品列表
    unique_titles = list({p.get("title", "") for p in products if p.get("title")})
    selected_title = st.selectbox(
        "选择产品",
        options=unique_titles,
        format_func=lambda t: t[:60] + "…" if len(t) > 60 else t,
    )

    if not selected_title:
        return

    # 获取趋势数据
    trend_data = get_trend_data(title=selected_title)

    if len(trend_data) < 2:
        st.warning("该产品仅有一次抓取记录，至少需要两次抓取才能显示趋势。")
        # 显示单次数据
        if trend_data:
            d = trend_data[0]
            st.json(d)
        return

    # 转为 DataFrame
    df = pd.DataFrame(trend_data)
    df["scrape_time"] = pd.to_datetime(df["scrape_time"])

    # 排名变化曲线
    st.markdown("### 📊 排名变化")
    st.line_chart(df.set_index("scrape_time")["rank"])

    # 价格变化曲线
    st.markdown("### 💰 价格变化")
    st.line_chart(df.set_index("scrape_time")["price"])

    # 评论数变化曲线
    st.markdown("### 💬 评论数变化")
    st.line_chart(df.set_index("scrape_time")["num_reviews"])

    # 趋势总结
    if len(trend_data) >= 2:
        first = trend_data[0]
        last = trend_data[-1]
        rank_change = first["rank"] - last["rank"]  # 正数 = 排名上升
        price_change = last["price"] - first["price"]
        review_change = last["num_reviews"] - first["num_reviews"]

        st.markdown("### 📋 趋势总结")
        cols = st.columns(3)
        cols[0].metric(
            "排名变化",
            f"#{last['rank']}",
            delta=f"{'↑' if rank_change > 0 else '↓'} {abs(rank_change)} 位" if rank_change != 0 else "无变化",
            delta_color="normal" if rank_change > 0 else "inverse",
        )
        cols[1].metric(
            "价格变化",
            f"${last['price']:.2f}",
            delta=f"{'↑' if price_change > 0 else '↓'} ${abs(price_change):.2f}",
        )
        cols[2].metric(
            "评论数变化",
            f"{last['num_reviews']:,}",
            delta=f"{'↑' if review_change > 0 else '↓'} {abs(review_change):,}",
        )
```

---

## 4. 验收标准

| # | 验收条件 | 验证方法 |
|---|---------|---------|
| 1 | `_parse_product_card()` 返回包含 `asin` 字段 | 调试脚本验证 |
| 2 | 数据库表包含 `asin` 字段 | 检查表结构 |
| 3 | `get_trend_data()` 返回按时间排序的数据 | 单元测试 |
| 4 | 历史记录页面新增"📈 产品趋势"tab | UI 验证 |
| 5 | 选择产品后展示排名/价格/评论数曲线 | UI 验证（需 ≥2 次抓取数据） |
| 6 | 趋势总结展示排名/价格/评论数变化 | UI 验证 |
| 7 | 仅一次抓取时显示提示 | UI 验证 |
| 8 | `python -m py_compile src/scraper.py` 通过 | 终端执行 |
| 9 | `python -m py_compile src/database.py` 通过 | 终端执行 |
| 10 | `python -m py_compile app.py` 通过 | 终端执行 |
| 11 | `daily_scrape.py` 不受影响 | 向后兼容 |

---

## 5. 不在本次范围内

- AI 趋势分析（DeepSeek 结合变化数据给出"上升潜力"/"风险预警"）
- 产品图片展示
- ASIN 去重（同一产品多次抓取产生的重复行）
- 多产品对比趋势（同期对比）
