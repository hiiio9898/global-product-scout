# Spec 8：多平台基础设施框架

**版本**：v1.0
**状态**：📋 待实施
**创建日期**：2026-05-29
**前置依赖**：Spec 0-A（多模型支持）、Spec 0-B（利润公式可配置）

---

## 1. 需求描述

### 1.1 背景
当前系统硬编码为 Amazon 单一平台：抓取器只认 Amazon Best Sellers、利润公式只算亚马逊 FBA、数据库无平台字段、侧边栏数据源选择器只有一个选项。用户需求是支持多个主流跨境电商平台（Amazon、AliExpress、Shopee、eBay），每个平台支持多个地区站点，且各平台利润计算模型不同。

### 1.2 目标
将系统从「Amazon 单平台」重构为「多平台可扩展架构」，为后续添加 AliExpress / Shopee / eBay 打好基础框架。本 Spec 只做基础设施，不添加新平台。

### 1.3 核心需求
1. **平台注册表**：类似 `LLM_PROVIDERS` 的 `PLATFORMS` 字典，集中管理平台元信息
2. **利润计算器工厂**：策略模式，每个平台独立的利润计算函数
3. **地区/站点切换**：每个平台支持多个地区站点（Amazon US/UK/JP/DE 等）
4. **数据库改造**：products 表新增 `platform`、`region`、`currency` 列
5. **侧边栏 UI 改造**：数据源选择器从单选变为「平台 + 地区」联动
6. **抓取器参数化**：现有 Amazon 抓取器接受 `region` 参数

---

## 2. 系统设计

### 2.1 新建文件

| 文件 | 说明 |
|------|------|
| `src/platforms.py` | 平台注册表 + 工具函数 |

### 2.2 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `src/calculator.py` | **重构** | 改为工厂模式，保留 `calculate_profit()` 向后兼容，新增 `get_calculator()` |
| `src/config.py` | **修改** | `get_profit_defaults()` 改为接受 `platform_key` 参数 |
| `src/scraper.py` | **修改** | `fetch_amazon_best_sellers()` 新增 `region` 参数 |
| `src/scraper_search.py` | **修改** | `search_amazon()` 新增 `region` 参数 |
| `src/database.py` | **修改** | products 表新增 `platform`/`region`/`currency` 列 |
| `app.py` | **修改** | 侧边栏数据源改为平台+地区联动选择器；利润参数面板动态适配平台 |
| `.env.example` | **修改** | 新增多平台相关配置模板 |

---

## 3. 平台注册表设计 — `src/platforms.py`

### 3.1 数据结构

```python
PLATFORMS = {
    "amazon": {
        "name": "Amazon",
        "icon": "🟠",
        "scraper_module": "src.scraper",           # 榜单抓取
        "scraper_func": "fetch_amazon_best_sellers",
        "search_module": "src.scraper_search",      # 关键词搜索
        "search_func": "search_amazon",
        "calculator": "calculate_amazon_profit",    # 利润计算函数名
        "currency": "USD",
        "regions": {
            "us": {"name": "美国站", "domain": "amazon.com",    "currency": "USD", "exchange_rate": 7.24},
            "uk": {"name": "英国站", "domain": "amazon.co.uk",  "currency": "GBP", "exchange_rate": 9.32},
            "jp": {"name": "日本站", "domain": "amazon.co.jp",  "currency": "JPY", "exchange_rate": 0.048},
            "de": {"name": "德国站", "domain": "amazon.de",     "currency": "EUR", "exchange_rate": 7.88},
        },
        "default_region": "us",
        "profit_defaults": {
            "commission_pct": 0.15,    # 亚马逊佣金
            "ad_pct": 0.10,            # PPC 广告
            "shipping_cny": 15.0,      # FBA 头程
        },
    },
    # --- 以下平台在后续 Spec 中注册 ---
    # "aliexpress": { ... },   # Spec 9
    # "shopee":     { ... },   # Spec 10
    # "ebay":       { ... },   # Spec 11
}
```

### 3.2 工具函数

```python
def get_platform_info(platform_key: str) -> dict:
    """获取平台完整信息，不存在时抛出 KeyError。"""

def get_region_info(platform_key: str, region_key: str) -> dict:
    """获取平台某地区的信息。"""

def get_platform_choices() -> list[str]:
    """返回所有平台 key 列表，供 selectbox 使用。"""

def get_region_choices(platform_key: str) -> list[tuple[str, str]]:
    """返回某平台的地区选项 [(key, display_name), ...]。"""

def get_active_platform() -> str:
    """从 st.session_state 读取用户当前选择的平台，默认 'amazon'。"""

def get_active_region(platform_key: str) -> str:
    """从 st.session_state 读取用户当前选择的地区，默认平台的 default_region。"""
```

---

## 4. 利润计算器工厂 — `src/calculator.py` 重构

### 4.1 工厂函数

```python
# 利润计算函数注册表
_CALCULATOR_REGISTRY: dict[str, Callable] = {}

def register_calculator(platform_key: str):
    """装饰器：注册平台利润计算函数。"""
    def decorator(func):
        _CALCULATOR_REGISTRY[platform_key] = func
        return func
    return decorator

def get_calculator(platform_key: str) -> Callable:
    """获取平台对应的利润计算函数，不存在则返回默认（Amazon FBA）。"""
    return _CALCULATOR_REGISTRY.get(platform_key, calculate_amazon_profit)
```

### 4.2 Amazon FBA 计算器（现有逻辑封装）

```python
@register_calculator("amazon")
def calculate_amazon_profit(
    price: float,
    defaults: dict,
    procurement_cny: float = 0.0,
    **kwargs,
) -> dict:
    """
    Amazon FBA 利润计算。

    公式：
        售价(本地货币) × 汇率 = 售价(CNY)
        佣金 = 售价(CNY) × commission_pct
        广告 = 售价(CNY) × ad_pct
        总成本 = 采购成本 + 头程 + 佣金 + 广告
        净利 = 售价(CNY) - 总成本
        毛利率 = 净利 / 售价(CNY)

    Returns: 标准利润结果字典（见 Spec 0-B）
    """
```

### 4.3 通用计算接口

```python
def calculate_profit(
    price: float,
    defaults: dict,
    procurement_cny: float = 0.0,
    platform: str = "amazon",
    **kwargs,
) -> dict:
    """
    统一利润计算入口（向后兼容）。

    根据平台选择对应的计算函数，返回标准结果字典。
    """
    calculator = get_calculator(platform)
    return calculator(price, defaults, procurement_cny, **kwargs)
```

---

## 5. 现有 Amazon 抓取器改造

### 5.1 `src/scraper.py` — `fetch_amazon_best_sellers()`

**改动**：新增 `region` 参数，默认 `"us"`。

```python
def fetch_amazon_best_sellers(region: str = "us") -> tuple[list[dict], dict]:
    """
    抓取 Amazon Best Sellers 首页。

    Args:
        region: 地区代码（us/uk/jp/de），决定目标域名

    根据 region 拼接 URL：
        us → https://www.amazon.com/Best-Sellers/zgbs/
        uk → https://www.amazon.co.uk/Best-Sellers/zgbs/
        jp → https://www.amazon.co.jp/Best-Sellers/zgbs/
        de → https://www.amazon.de/Best-Sellers/zgbs/
    """
```

**缓存文件**：按地区分别缓存
```
data/cache/amazon_best_sellers_us.json
data/cache/amazon_best_sellers_uk.json
data/cache/amazon_best_sellers_jp.json
data/cache/amazon_best_sellers_de.json
```

### 5.2 `src/scraper_search.py` — `search_amazon()`

**改动**：新增 `region` 参数，默认 `"us"`。

```python
def search_amazon(keyword: str, region: str = "us", max_pages: int = 2) -> tuple[list[dict], dict]:
    """
    根据关键词搜索 Amazon 产品。

    Args:
        keyword: 搜索关键词
        region:  地区代码（us/uk/jp/de）
        max_pages: 最大抓取页数

    根据 region 拼接搜索 URL：
        us → https://www.amazon.com/s?k={keyword}
        uk → https://www.amazon.co.uk/s?k={keyword}
        jp → https://www.amazon.co.jp/s?k={keyword}
        de → https://www.amazon.de/s?k={keyword}
    """
```

---

## 6. 数据库改造 — `src/database.py`

### 6.1 新增字段

```sql
-- 新增列（ALTER TABLE，幂等，已在 init_db() 中执行）
ALTER TABLE products ADD COLUMN platform TEXT DEFAULT 'amazon';
ALTER TABLE products ADD COLUMN region   TEXT DEFAULT 'us';
ALTER TABLE products ADD COLUMN currency TEXT DEFAULT 'USD';
```

### 6.2 `init_db()` 变更

在现有的字段兼容性 ALTER TABLE 循环中追加：

```python
for col, default in [
    ("procurement_cost", "REAL DEFAULT 0.0"),
    ("asin", "TEXT DEFAULT ''"),
    ("platform", "TEXT DEFAULT 'amazon'"),    # 新增
    ("region",   "TEXT DEFAULT 'us'"),        # 新增
    ("currency", "TEXT DEFAULT 'USD'"),       # 新增
]:
```

### 6.3 `save_products()` 变更

新增 `platform`、`region`、`currency` 参数：

```python
def save_products(
    products: list[dict],
    analysis_results: list[dict],
    source: str = "amazon_best_sellers",
    platform: str = "amazon",     # 新增
    region: str = "us",           # 新增
    currency: str = "USD",        # 新增
    db_path: Optional[str] = None,
) -> int:
```

INSERT 语句增加这三列。

### 6.4 `get_all_products()` 变更

`filters` 新增 `platform`、`region` 筛选键：

```python
filters = {
    ...,
    "platform": "amazon",    # 按平台筛选
    "region": "us",          # 按地区筛选
}
```

---

## 7. 侧边栏 UI 改造 — `app.py`

### 7.1 平台+地区联动选择器

替换现有的硬编码 `st.sidebar.selectbox("选择数据源", options=["Amazon Best Sellers"])`：

```python
from src.platforms import (
    get_platform_choices, get_region_choices,
    get_platform_info, get_active_platform, get_active_region,
)

# ---- 平台选择 ----
platform_keys = get_platform_choices()
platform_names = {k: f"{get_platform_info(k)['icon']} {get_platform_info(k)['name']}" for k in platform_keys}

selected_platform = st.sidebar.selectbox(
    "🛒 选择平台",
    options=platform_keys,
    format_func=lambda k: platform_names[k],
    key="selected_platform",
)
st.session_state["active_platform"] = selected_platform

# ---- 地区选择（联动） ----
region_choices = get_region_choices(selected_platform)
region_keys = [r[0] for r in region_choices]
region_names = {r[0]: r[1] for r in region_choices}

selected_region = st.sidebar.selectbox(
    "🌍 选择地区",
    options=region_keys,
    format_func=lambda k: region_names.get(k, k),
    key="selected_region",
)
st.session_state["active_region"] = selected_region
```

### 7.2 利润参数动态适配

利润参数面板根据平台动态显示不同字段：

```python
platform_info = get_platform_info(selected_platform)
profit_params = platform_info.get("profit_defaults", {})

# 根据平台显示不同的参数标签和范围
if selected_platform == "amazon":
    commission_pct = st.slider("亚马逊佣金比例", ...)
    ad_pct = st.slider("广告预算占比", ...)
    shipping_cny = st.number_input("FBA 头程运费 (¥/件)", ...)
# 其他平台的参数在后续 Spec 中扩展
```

### 7.3 实时选品页面适配

`_render_live_page()` 中的抓取调用改为：

```python
from src.platforms import get_platform_info

platform = st.session_state.get("active_platform", "amazon")
region = st.session_state.get("active_region", "us")
platform_info = get_platform_info(platform)

# 动态调用对应平台的抓取函数
scraper_func = _import_scraper_func(platform_info["scraper_module"], platform_info["scraper_func"])
products, source_info = scraper_func(region=region)
```

### 7.4 指定选品页面适配

`_render_targeted_page()` 中的搜索调用改为：

```python
search_func = _import_scraper_func(platform_info["search_module"], platform_info["search_func"])
products, source_info = search_func(keyword=keyword, region=region)
```

---

## 8. 配置更新 — `.env.example`

新增以下模板（保留现有内容）：

```env
# ============================================================
# 多平台配置
# ============================================================

# --- Amazon 地区站点 URL（按需切换） ---
AMAZON_US_URL=https://www.amazon.com/Best-Sellers/zgbs/
AMAZON_UK_URL=https://www.amazon.co.uk/Best-Sellers/zgbs/
AMAZON_JP_URL=https://www.amazon.co.jp/Best-Sellers/zgbs/
AMAZON_DE_URL=https://www.amazon.de/Best-Sellers/zgbs/

# --- Amazon 利润参数 ---
PROFIT_EXCHANGE_RATE=7.24
PROFIT_COMMISSION_PCT=0.15
PROFIT_AD_PCT=0.10
PROFIT_SHIPPING_CNY=15.0
```

---

## 9. `src/config.py` 变更

### 9.1 `get_profit_defaults()` 改造

```python
def get_profit_defaults(platform_key: str = "amazon") -> dict:
    """
    返回指定平台的利润计算默认参数。

    Args:
        platform_key: 平台标识，默认 "amazon"

    Returns:
        利润参数字典（含 exchange_rate, commission_pct, ad_pct, shipping_cny 等）
    """
    from .platforms import get_platform_info

    try:
        platform = get_platform_info(platform_key)
    except KeyError:
        platform = get_platform_info("amazon")

    region_key = "us"  # 默认区域，后续从 session_state 读取
    try:
        import streamlit as st
        region_key = st.session_state.get("active_region", platform.get("default_region", "us"))
    except (ImportError, RuntimeError):
        pass

    regions = platform.get("regions", {})
    region_info = regions.get(region_key, {})

    defaults = platform.get("profit_defaults", {}).copy()
    defaults["exchange_rate"] = region_info.get("exchange_rate", 7.24)
    defaults["procurement_cny"] = 0.0

    return defaults
```

---

## 10. 统一产品数据格式

所有平台的抓取器返回统一格式：

```python
{
    "title": str,              # 产品标题
    "price": float | str,      # 售价（原始值）
    "price_float": float,      # 售价（标准化为浮点数）
    "rating": float | str,     # 评分
    "num_reviews": int | str,  # 评论数
    "rank": int,               # 排名
    "category": str,           # 分类
    "url": str,                # 产品链接
    "image_url": str,          # 产品图片（可选）
    "asin": str,               # 唯一标识（Amazon）/ 平台对应 ID
    "platform": str,           # 平台标识："amazon" / "aliexpress" / "shopee" / "ebay"
    "region": str,             # 地区代码："us" / "uk" / "jp" / ...
    "currency": str,           # 货币代码："USD" / "GBP" / "JPY" / ...
    "scrape_time": str,        # 抓取时间 ISO 格式
}
```

---

## 11. 向后兼容保证

| 改动点 | 兼容策略 |
|--------|----------|
| `calculate_profit()` | 保留原签名，新增 `platform` 参数默认 `"amazon"` |
| `fetch_amazon_best_sellers()` | 新增 `region` 参数默认 `"us"`，不传参行为不变 |
| `search_amazon()` | 新增 `region` 参数默认 `"us"`，不传参行为不变 |
| `save_products()` | 新增 `platform`/`region`/`currency` 参数，均有默认值 |
| `get_profit_defaults()` | 新增 `platform_key` 参数默认 `"amazon"` |
| `get_config()` | 保留原 `amazon_url` 字段，内部改为动态拼接 |
| 数据库 | `platform`/`region`/`currency` 默认值确保旧数据兼容 |

---

## 12. 验收标准

1. `streamlit run app.py` 正常启动，无 import 错误
2. 侧边栏显示「平台 + 地区」联动选择器，Amazon 默认选中 US
3. 选择 Amazon UK 后，抓取目标变为 `amazon.co.uk`，利润汇率变为 9.32
4. 选择 Amazon JP 后，抓取目标变为 `amazon.co.jp`，利润汇率变为 0.048
5. 数据库新记录自动写入 `platform`/`region`/`currency` 字段
6. 旧数据（无平台字段）默认为 `amazon/us/USD`
7. 现有 4 个页面全部功能不受影响
8. `pytest tests/` 全部通过
9. 所有 Python 文件通过 `python -m py_compile` 编译检查

---

## 13. 风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| Amazon 各站点页面结构可能不同 | 复用现有 CSS 选择器兜底策略；抓取失败时返回友好提示 |
| 旧数据库兼容性问题 | ALTER TABLE 幂等操作 + 默认值 |
| 侧边栏状态管理复杂化 | 使用 `st.session_state` 统一管理平台/地区选择 |
| 利润计算器重构可能引入 bug | 保留原 `calculate_profit()` 入口，内部路由到平台计算器 |
