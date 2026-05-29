# Spec 12：历史记录增强 + 全平台集成测试

**版本**：v1.0
**状态**：📋 待实施
**创建日期**：2026-05-29
**前置依赖**：Spec 8（多平台基础设施）、Spec 9（AliExpress）、Spec 10（Shopee）、Spec 11（eBay）

---

## 1. 需求描述

### 1.1 背景
经过 Spec 8-11 的实施，系统将支持 4 个平台（Amazon、AliExpress、Shopee、eBay），每个平台 2-5 个地区站点。现有的历史记录页面（"历史选品" tab）仅基于 Amazon 单平台设计，缺少平台/地区筛选、跨平台对比、数据统计等功能。此外，多平台功能需要集成测试来验证端到端可用性。

### 1.2 目标
1. 增强历史记录页面，支持多平台/多地区筛选
2. 新增跨平台产品对比功能
3. 新增数据统计仪表盘（各平台产品数量、利润分布等）
4. 编写全平台集成测试，验证 Spec 8-11 的功能完整性

### 1.3 核心需求
1. **历史记录筛选**：按平台、地区、时间范围筛选历史产品
2. **跨平台对比**：同一产品在多个平台的利润对比
3. **数据统计仪表盘**：展示各平台数据量、利润率分布、热门类目等
4. **集成测试**：覆盖所有平台的抓取→存储→计算→展示全链路

---

## 2. 系统设计

### 2.1 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `app.py` | **修改** | 历史记录页面重构（筛选器 + 统计 + 对比） |
| `src/database.py` | **修改** | 新增多条件查询方法 |
| `tests/test_integration.py` | **新建** | 全平台集成测试 |

### 2.2 不改动的文件

以下文件在 Spec 8-11 中已完成改动，本阶段不涉及：
- `src/platforms.py`（已完成全部平台注册）
- `src/calculator.py`（已完成全部利润计算器）
- `src/scraper_*.py`（已完成全部抓取模块）
- `src/config.py`（已完成全部配置项）

---

## 3. 历史记录页面重构 — `app.py`

### 3.1 新增筛选器

在"历史选品"tab 页面顶部添加筛选条件：

```python
def _render_history_page():
    """历史选品页面（多平台增强版）。"""
    st.header("📊 历史选品")

    # ── 筛选器区域 ──
    with st.expander("🔍 筛选条件", expanded=True):
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            # 平台筛选（多选）
            selected_platforms = st.multiselect(
                "平台",
                options=list(PLATFORMS.keys()),
                default=list(PLATFORMS.keys()),
                format_func=lambda k: f"{PLATFORMS[k]['icon']} {PLATFORMS[k]['name']}",
            )

        with col2:
            # 地区筛选（根据选中平台动态更新）
            available_regions = _get_available_regions(selected_platforms)
            selected_regions = st.multiselect(
                "地区",
                options=available_regions,
                default=available_regions,
            )

        with col3:
            # 时间范围筛选
            date_range = st.date_input(
                "时间范围",
                value=(datetime.now() - timedelta(days=30), datetime.now()),
            )

        with col4:
            # 最低利润率筛选
            min_margin = st.slider(
                "最低毛利率 %",
                min_value=-50,
                max_value=80,
                value=-50,
                step=5,
            )

    # ── 数据查询 ──
    products = db.query_products(
        platforms=selected_platforms,
        regions=selected_regions,
        date_range=date_range,
        min_margin=min_margin,
    )

    # ── 统计仪表盘 ──
    _render_stats_dashboard(products, selected_platforms)

    # ── 跨平台对比 ──
    if len(selected_platforms) >= 2:
        _render_cross_platform_comparison(products)

    # ── 产品列表 ──
    _render_product_table(products)
```

### 3.2 统计仪表盘

```python
def _render_stats_dashboard(products: list[dict], platforms: list[str]):
    """渲染数据统计仪表盘。"""
    st.subheader("📈 数据统计")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("总产品数", len(products))

    with col2:
        # 各平台产品数量
        platform_counts = {}
        for p in products:
            pf = p.get("platform", "unknown")
            platform_counts[pf] = platform_counts.get(pf, 0) + 1
        st.metric("平台覆盖", f"{len(platform_counts)} 个平台")

    with col3:
        # 平均毛利率
        margins = [p.get("margin_pct", 0) for p in products if p.get("margin_pct") is not None]
        avg_margin = sum(margins) / len(margins) if margins else 0
        st.metric("平均毛利率", f"{avg_margin:.1f}%")

    with col4:
        # 盈利产品占比
        profitable = sum(1 for p in products if p.get("is_profitable"))
        pct = (profitable / len(products) * 100) if products else 0
        st.metric("盈利产品占比", f"{pct:.0f}%")

    # 各平台产品数量柱状图
    st.bar_chart(
        data=_build_platform_chart_data(platform_counts),
        x_label="平台",
        y_label="产品数量",
    )
```

### 3.3 跨平台对比

```python
def _render_cross_platform_comparison(products: list[dict]):
    """
    渲染跨平台产品对比。

    展示内容：
    - 各平台平均售价对比
    - 各平台平均毛利率对比
    - 各平台费用结构对比（柱状图/表格）
    """
    st.subheader("⚖️ 跨平台对比")

    # 按平台分组统计
    platform_stats = _compute_platform_stats(products)

    # 对比表格
    comparison_df = pd.DataFrame(platform_stats).T
    comparison_df = comparison_df[["avg_price", "avg_margin", "avg_commission", "avg_shipping", "count"]]
    comparison_df.columns = ["平均售价", "平均毛利率%", "平均佣金", "平均运费", "产品数"]

    st.dataframe(
        comparison_df,
        use_container_width=True,
        column_config={
            "平均售价": st.column_config.NumberColumn(format="%.2f"),
            "平均毛利率%": st.column_config.NumberColumn(format="%.1f%%"),
            "平均佣金": st.column_config.NumberColumn(format="%.2f"),
            "平均运费": st.column_config.NumberColumn(format="%.2f"),
        },
    )

    # 毛利率对比柱状图
    st.bar_chart(
        data=_build_margin_comparison_data(platform_stats),
        x_label="平台",
        y_label="平均毛利率 %",
    )
```

---

## 4. 数据库增强 — `src/database.py`

### 4.1 新增多条件查询方法

```python
def query_products(
    platforms: list[str] | None = None,
    regions: list[str] | None = None,
    date_range: tuple | None = None,
    min_margin: float | None = None,
    keyword: str | None = None,
    limit: int = 500,
) -> list[dict]:
    """
    多条件查询历史产品。

    Args:
        platforms: 平台列表（如 ["amazon", "aliexpress"]）
        regions: 地区列表（如 ["us", "sg"]）
        date_range: 时间范围 (start_date, end_date)
        min_margin: 最低毛利率
        keyword: 标题关键词搜索
        limit: 返回数量上限

    Returns:
        产品列表（包含利润计算结果）
    """
    conditions = []
    params = []

    if platforms:
        placeholders = ",".join(["?"] * len(platforms))
        conditions.append(f"platform IN ({placeholders})")
        params.extend(platforms)

    if regions:
        placeholders = ",".join(["?"] * len(regions))
        conditions.append(f"region IN ({placeholders})")
        params.extend(regions)

    if date_range and len(date_range) == 2:
        conditions.append("scrape_time BETWEEN ? AND ?")
        params.extend([date_range[0].isoformat(), date_range[1].isoformat()])

    if keyword:
        conditions.append("title LIKE ?")
        params.append(f"%{keyword}%")

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    sql = f"SELECT * FROM products WHERE {where_clause} ORDER BY scrape_time DESC LIMIT ?"
    params.append(limit)

    rows = _execute_query(sql, params)

    # 如果有 min_margin 筛选，需要计算利润后过滤
    products = [_row_to_dict(row) for row in rows]
    if min_margin is not None and min_margin > -50:
        products = [p for p in products if _compute_margin(p) >= min_margin]

    return products
```

### 4.2 辅助方法

```python
def _compute_margin(product: dict) -> float:
    """从产品的 analysis_json 中提取毛利率。"""
    import json
    try:
        analysis = json.loads(product.get("analysis_json", "{}"))
        return analysis.get("margin_pct", -999)
    except (json.JSONDecodeError, TypeError):
        return -999

def get_platform_summary() -> dict:
    """
    获取各平台的数据摘要统计。

    Returns:
        {
            "amazon": {"count": 36, "regions": ["us", "uk"], "latest": "2025-01-15"},
            "aliexpress": {"count": 24, "regions": ["us"], "latest": "2025-01-14"},
            ...
        }
    """
    sql = """
        SELECT platform, region, COUNT(*) as cnt, MAX(scrape_time) as latest
        FROM products
        GROUP BY platform, region
        ORDER BY platform, region
    """
    rows = _execute_query(sql, [])
    summary = {}
    for row in rows:
        pf = row["platform"]
        if pf not in summary:
            summary[pf] = {"count": 0, "regions": [], "latest": ""}
        summary[pf]["count"] += row["cnt"]
        summary[pf]["regions"].append(row["region"])
        if row["latest"] > summary[pf]["latest"]:
            summary[pf]["latest"] = row["latest"]
    return summary
```

---

## 5. 集成测试 — `tests/test_integration.py`

### 5.1 测试范围

| 测试类别 | 说明 | 测试方法 |
|---------|------|---------|
| 平台注册完整性 | 4 个平台全部注册 | 检查 PLATFORMS 字典包含所有 key |
| 利润计算器工厂 | 每个平台计算器可正常调用 | `get_calculator(platform_key)` 返回有效函数 |
| 利润计算结果 | 每个平台的利润公式正确 | 用固定输入验证输出 |
| 数据库 Schema | platform/region/currency 列存在 | `PRAGMA table_info` |
| 数据库多条件查询 | 按平台、地区、时间筛选 | 插入测试数据后查询 |
| 前端路由 | 每个平台的抓取函数可调用 | Mock 方式验证调用链 |
| 降级策略 | 抓取失败时友好降级 | 模拟异常验证降级 |

### 5.2 测试代码框架

```python
"""全平台集成测试 — 验证 Spec 8-11 实施完整性。"""
import pytest
import json
from unittest.mock import patch, MagicMock

# ── 测试平台注册完整性 ──
class TestPlatformRegistry:
    """Spec 8: 平台注册表。"""

    EXPECTED_PLATFORMS = ["amazon", "aliexpress", "shopee", "ebay"]

    def test_all_platforms_registered(self):
        """验证 4 个平台全部注册到 PLATFORMS。"""
        from src.platforms import PLATFORMS
        for pf in self.EXPECTED_PLATFORMS:
            assert pf in PLATFORMS, f"平台 {pf} 未注册"
            assert "name" in PLATFORMS[pf]
            assert "icon" in PLATFORMS[pf]
            assert "calculator" in PLATFORMS[pf]
            assert "regions" in PLATFORMS[pf]

    def test_each_platform_has_scraper(self):
        """验证每个平台都配置了抓取模块。"""
        from src.platforms import PLATFORMS
        for pf, cfg in PLATFORMS.items():
            assert "scraper_module" in cfg
            assert "scraper_func" in cfg

    def test_region_config_complete(self):
        """验证每个地区的配置完整。"""
        from src.platforms import PLATFORMS
        for pf, cfg in PLATFORMS.items():
            for region_key, region_cfg in cfg["regions"].items():
                assert "name" in region_cfg, f"{pf}.{region_key} 缺少 name"
                assert "domain" in region_cfg, f"{pf}.{region_key} 缺少 domain"
                assert "currency" in region_cfg, f"{pf}.{region_key} 缺少 currency"
                assert "exchange_rate" in region_cfg, f"{pf}.{region_key} 缺少 exchange_rate"


# ── 测试利润计算器 ──
class TestProfitCalculators:
    """Spec 8-11: 各平台利润计算器。"""

    @pytest.mark.parametrize("platform_key", ["amazon", "aliexpress", "shopee", "ebay"])
    def test_calculator_exists(self, platform_key):
        """验证每个平台的利润计算器已注册。"""
        from src.calculator import get_calculator
        calc = get_calculator(platform_key)
        assert callable(calc)

    @pytest.mark.parametrize("platform_key,expected_positive", [
        ("amazon", True),       # $20 售价 Amazon 应盈利
        ("aliexpress", True),   # $15 售价 AliExpress 应盈利
        ("shopee", True),       # $10 售价 Shopee 可能盈利
        ("ebay", False),        # $5 售价 eBay 可能亏损（13.25% 成交费）
    ])
    def test_profit_calculation_basic(self, platform_key, expected_positive):
        """用固定输入验证各平台利润计算。"""
        from src.calculator import get_calculator
        from src.platforms import PLATFORMS

        calc = get_calculator(platform_key)
        defaults = PLATFORMS[platform_key]["profit_defaults"]
        defaults["exchange_rate"] = PLATFORMS[platform_key]["regions"][
            PLATFORMS[platform_key]["default_region"]
        ]["exchange_rate"]

        test_prices = {"amazon": 20.0, "aliexpress": 15.0, "shopee": 10.0, "ebay": 5.0}
        result = calc(
            price=test_prices[platform_key],
            defaults=defaults,
            procurement_cny=10.0,
        )

        assert "margin_pct" in result
        assert "is_profitable" in result
        assert "total_cost_cny" in result
        assert "net_profit_cny" in result
        assert result["is_profitable"] == expected_positive

    def test_zero_procurement_cost(self):
        """未输入采购成本时，结果仍然有效。"""
        from src.calculator import get_calculator
        from src.platforms import PLATFORMS

        for pf in ["amazon", "aliexpress", "shopee", "ebay"]:
            calc = get_calculator(pf)
            defaults = PLATFORMS[pf]["profit_defaults"]
            defaults["exchange_rate"] = 7.24
            result = calc(price=10.0, defaults=defaults, procurement_cny=0.0)
            assert result["has_procurement"] is False
            assert "margin_pct" in result


# ── 测试数据库 ──
class TestDatabaseMultiPlatform:
    """Spec 8: 数据库多平台支持。"""

    def test_platform_column_exists(self, tmp_path):
        """验证 products 表包含 platform 列。"""
        from src.database import init_db
        # 使用临时数据库
        with patch("src.database.DB_PATH", str(tmp_path / "test.db")):
            init_db()
            # PRAGMA table_info 检查
            ...

    def test_query_by_platform(self, tmp_path):
        """验证按平台筛选查询。"""
        ...

    def test_query_by_region(self, tmp_path):
        """验证按地区筛选查询。"""
        ...

    def test_query_by_date_range(self, tmp_path):
        """验证按时间范围筛选。"""
        ...


# ── 测试抓取降级 ──
class TestScraperFallback:
    """Spec 9-11: 各平台抓取降级策略。"""

    @pytest.mark.parametrize("platform_key", ["aliexpress", "shopee", "ebay"])
    def test_scraper_returns_tuple(self, platform_key):
        """验证抓取函数返回 (list, dict) 格式。"""
        from src.platforms import PLATFORMS
        module_name = PLATFORMS[platform_key]["scraper_module"]
        func_name = PLATFORMS[platform_key]["scraper_func"]

        module = __import__(module_name, fromlist=[func_name])
        func = getattr(module, func_name)

        # Mock requests 避免真实网络请求
        with patch("requests.get", side_effect=Exception("Network error")):
            with patch("requests.Session"):
                try:
                    products, info = func(region=PLATFORMS[platform_key]["default_region"])
                    assert isinstance(products, list)
                    assert isinstance(info, dict)
                except Exception:
                    # 如果完全失败也应抛出可控异常
                    pass
```

### 5.3 测试运行要求

```bash
# 运行全部集成测试
pytest tests/test_integration.py -v

# 运行特定测试类
pytest tests/test_integration.py::TestPlatformRegistry -v
pytest tests/test_integration.py::TestProfitCalculators -v
pytest tests/test_integration.py::TestDatabaseMultiPlatform -v

# 运行全部测试（含已有单元测试）
pytest tests/ -v
```

---

## 6. 前端交互细节

### 6.1 历史页面 Tab 结构

```
📊 历史选品
├── 🔍 筛选条件（expander，默认展开）
│   ├── 平台多选框
│   ├── 地区多选框（联动平台选择）
│   ├── 时间范围选择器
│   └── 最低毛利率滑块
├── 📈 数据统计
│   ├── 指标卡片（总数、平台数、平均毛利率、盈利占比）
│   └── 各平台产品数量柱状图
├── ⚖️ 跨平台对比（仅选中 2+ 平台时显示）
│   ├── 对比表格
│   └── 毛利率对比图
└── 📋 产品列表
    └── DataFrame 表格（含利润结果列）
```

### 6.2 地区联动逻辑

```python
def _get_available_regions(selected_platforms: list[str]) -> list[str]:
    """根据选中的平台，返回所有可用地区代码。"""
    from src.platforms import PLATFORMS
    regions = []
    for pf in selected_platforms:
        for region_key, region_cfg in PLATFORMS[pf]["regions"].items():
            label = f"{PLATFORMS[pf]['icon']} {region_cfg['name']}"
            if label not in regions:
                regions.append(label)
    return regions
```

---

## 7. 数据流

### 7.1 历史记录查询流

```
用户打开「历史选品」Tab
    ↓
加载全部历史产品（默认最近 30 天，所有平台）
    ↓
用户调整筛选条件（平台/地区/时间/毛利率）
    ↓
调用 db.query_products(platforms, regions, date_range, min_margin)
    ↓
返回筛选结果 → 更新统计仪表盘 + 对比图 + 产品表格
    ↓
用户点击产品行 → 展开详情（含利润分析完整结果）
```

### 7.2 跨平台对比流

```
用户选中 2+ 平台
    ↓
加载各平台产品数据
    ↓
按平台分组计算：
    - 平均售价
    - 平均毛利率
    - 平均佣金
    - 平均运费
    - 产品数量
    ↓
展示对比表格 + 毛利率柱状图
```

---

## 8. 验收标准

### 8.1 历史记录增强

1. 历史页面支持按平台多选筛选（至少 4 个平台可选）
2. 历史页面支持按地区筛选（地区选项随平台联动）
3. 历史页面支持按时间范围筛选
4. 历史页面支持按最低毛利率筛选
5. 统计仪表盘正确显示指标卡片和柱状图
6. 跨平台对比表格在选中 2+ 平台时自动显示
7. 产品列表完整展示所有字段，不截断

### 8.2 数据库增强

8. `query_products()` 支持多条件组合查询
9. `get_platform_summary()` 返回各平台统计摘要
10. 查询性能：500 条记录查询 < 1 秒

### 8.3 集成测试

11. 4 个平台注册完整性测试通过
12. 4 个平台利润计算器测试通过
13. 利润计算结果正确性验证通过
14. 数据库多条件查询测试通过
15. 抓取降级策略测试通过
16. `pytest tests/ -v` 全部通过
17. 所有 Python 文件通过 `python -m py_compile` 编译检查

---

## 9. 风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| 历史数据缺少 platform/region 字段 | 为旧数据设置默认值 `platform="amazon", region="us"` |
| 大量数据时查询变慢 | SQLite 索引优化 + LIMIT 限制 |
| 跨平台对比时各平台费用结构不同 | 统一输出格式，展示各自特有字段 |
| 统计图表在数据量少时不美观 | 最少数据量提示 |
| 集成测试需要 Mock 多个外部依赖 | 使用 `unittest.mock` 统一管理 |
