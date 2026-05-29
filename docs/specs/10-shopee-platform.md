# Spec 10：Shopee 平台集成

**版本**：v1.0
**状态**：📋 待实施
**创建日期**：2026-05-29
**前置依赖**：Spec 8（多平台基础设施框架）

---

## 1. 需求描述

### 1.1 背景
Shopee（虾皮）是东南亚最大电商平台，覆盖新加坡、马来西亚、泰国、越南、菲律宾、印尼等市场。东南亚电商增速全球领先，对于跨境卖家来说是重要蓝海。Shopee 平台具有公开的 API 接口，数据获取相对稳定可靠。

### 1.2 目标
在 Spec 8 多平台基础设施上，接入 Shopee 平台：利用 Shopee 公开 API 或页面抓取获取热销产品数据，实现 Shopee 专属利润计算，支持 5 个东南亚地区站点。

### 1.3 核心需求
1. **榜单抓取**：通过 Shopee 公开接口获取各站点热销产品
2. **关键词搜索**：根据用户输入关键词搜索 Shopee 产品
3. **利润计算**：Shopee 卖家利润模型（佣金 + 运费 + 服务费）
4. **地区站点**：新加坡、马来西亚、泰国、越南、菲律宾（5 站）
5. **平台注册**：在 `PLATFORMS` 注册表中注册 Shopee

---

## 2. 系统设计

### 2.1 新建文件

| 文件 | 说明 |
|------|------|
| `src/scraper_shopee.py` | Shopee 数据抓取模块（API 优先 + HTML 降级） |

### 2.2 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `src/platforms.py` | **修改** | 注册 `shopee` 平台 |
| `src/calculator.py` | **修改** | 新增 `calculate_shopee_profit()` |
| `src/config.py` | **修改** | 支持 Shopee 配置项 |
| `app.py` | **修改** | Shopee 平台的路由和展示（已由 Spec 8 框架自动支持） |
| `.env.example` | **修改** | 新增 Shopee 相关配置模板 |

---

## 3. 平台注册 — `src/platforms.py` 新增

### 3.1 PLATFORMS 字典新增条目

```python
"shopee": {
    "name": "Shopee",
    "icon": "🟠",
    "scraper_module": "src.scraper_shopee",
    "scraper_func": "fetch_shopee_best_sellers",
    "search_module": "src.scraper_shopee",
    "search_func": "search_shopee",
    "calculator": "calculate_shopee_profit",
    "currency": "SGD",
    "regions": {
        "sg": {"name": "新加坡站", "domain": "shopee.sg",    "currency": "SGD", "exchange_rate": 5.42},
        "my": {"name": "马来西亚站", "domain": "shopee.com.my", "currency": "MYR", "exchange_rate": 1.58},
        "th": {"name": "泰国站",   "domain": "shopee.co.th", "currency": "THB", "exchange_rate": 0.20},
        "vn": {"name": "越南站",   "domain": "shopee.vn",    "currency": "VND", "exchange_rate": 0.00029},
        "ph": {"name": "菲律宾站", "domain": "shopee.ph",    "currency": "PHP", "exchange_rate": 0.13},
    },
    "default_region": "sg",
    "profit_defaults": {
        "commission_pct": 0.06,        # Shopee 佣金（约 2-6%，取较高值）
        "service_fee_pct": 0.02,       # 平台服务费（约 1-2%）
        "shipping_cny": 12.0,          # 国际段运费（发往东南亚）
        "packaging_cny": 3.0,          # 包装费
        "exchange_loss_pct": 0.01,     # 汇率损耗（约 1%）
    },
},
```

---

## 4. 数据抓取 — `src/scraper_shopee.py`

### 4.1 抓取策略：API 优先 + HTML 降级

Shopee 提供部分公开 API，可获取产品列表和详情。优先使用 API，失败时降级为 HTML 抓取。

#### API 方式（优先）

```python
# Shopee 公开 API 端点（无需 API Key）
_SHOPEE_API_BASE = "https://shopee.{domain}/api/v4"

# 热销产品 API
_SHOPEE_TOP_PRODUCTS_API = (
    "/recommend/recommend?limit=50&offset=0"
    "&section=top_sold"
)

# 搜索 API
_SHOPEE_SEARCH_API = (
    "/search/search_items?keyword={keyword}&limit=50&offset=0"
    "&sort_by=sales"
)
```

#### HTML 方式（降级）

```python
# 榜单页 URL
_SHOPEE_TOP_PRODUCTS_URL = "https://shopee.{domain}/top_sold"

# 搜索页 URL
_SHOPEE_SEARCH_URL = "https://shopee.{domain}/search?keyword={keyword}&sortBy=sales"
```

### 4.2 榜单抓取

```python
def fetch_shopee_best_sellers(region: str = "sg") -> tuple[list[dict], dict]:
    """
    抓取 Shopee 热销产品。

    Args:
        region: 地区代码（sg/my/th/vn/ph）

    抓取策略：
        1. 优先调用 Shopee 公开 API 获取 top_sold 产品
        2. API 失败时降级为 HTML 页面抓取
        3. 两种方式都失败时返回友好错误

    返回:
        (products_list, source_info_dict)
    """
    domain = _get_domain(region)
    products = []

    # 尝试 API 方式
    try:
        products = _fetch_via_api(domain, _SHOPEE_TOP_PRODUCTS_API)
    except Exception:
        # 降级为 HTML 方式
        try:
            products = _fetch_via_html(domain, _SHOPEE_TOP_PRODUCTS_URL)
        except Exception:
            pass

    source_info = {
        "source": "shopee_best_sellers",
        "region": region,
        "domain": domain,
        "count": len(products),
        "fetch_method": "api" if products else "failed",
    }
    return products, source_info
```

### 4.3 关键词搜索

```python
def search_shopee(keyword: str, region: str = "sg", max_pages: int = 2) -> tuple[list[dict], dict]:
    """
    根据关键词搜索 Shopee 产品。

    Args:
        keyword: 搜索关键词
        region:  地区代码（sg/my/th/vn/ph）
        max_pages: 最大抓取页数

    返回:
        (products_list, source_info_dict)
    """
```

### 4.4 API 响应解析

```python
def _parse_api_product(item: dict) -> dict:
    """
    解析 Shopee API 返回的产品数据。

    API 返回格式（预估值）：
    {
        "itemid": 123456,
        "shopid": 789012,
        "name": "产品标题",
        "price": 99000,              # 注意：Shopee 价格通常乘以 100000
        "price_min": 89000,
        "item_rating": {
            "rating_star": 4.8,
            "rating_count": [0, 0, 0, 50, 450]
        },
        "historical_sold": 5000,
        "image": "xxx",
        "catid": 123,
    }

    Returns: 标准产品字典
    """
    return {
        "title": item.get("name", ""),
        "price": item.get("price", 0) / 100000,  # Shopee 价格单位转换
        "price_float": item.get("price", 0) / 100000,
        "rating": item.get("item_rating", {}).get("rating_star", 0),
        "num_reviews": sum(item.get("item_rating", {}).get("rating_count", [0,0,0,0,0])),
        "rank": 0,  # 榜单排名在搜索结果中无意义
        "category": str(item.get("catid", "")),
        "url": f"https://shopee.{domain}/product/{item.get('shopid')}-{item.get('itemid')}",
        "image_url": f"https://down-{region}.img.susercontent.com/{item.get('image', '')}",
        "asin": f"{item.get('shopid')}-{item.get('itemid')}",  # Shopee 的唯一标识
        "platform": "shopee",
        "region": region,
        "currency": _get_currency(region),
        "scrape_time": datetime.now().isoformat(),
    }
```

### 4.5 辅助函数

```python
def _get_domain(region: str) -> str:
    """根据地区代码返回域名。"""
    _DOMAIN_MAP = {
        "sg": "shopee.sg",
        "my": "shopee.com.my",
        "th": "shopee.co.th",
        "vn": "shopee.vn",
        "ph": "shopee.ph",
    }
    return _DOMAIN_MAP.get(region, "shopee.sg")

def _get_currency(region: str) -> str:
    """根据地区代码返回货币代码。"""
    _CURRENCY_MAP = {
        "sg": "SGD", "my": "MYR", "th": "THB",
        "vn": "VND", "ph": "PHP",
    }
    return _CURRENCY_MAP.get(region, "SGD")

def _fetch_via_api(domain: str, endpoint: str) -> list[dict]:
    """通过 Shopee 公开 API 获取数据。"""
    url = f"https://{domain}/api/v4{endpoint}"
    headers = {
        "User-Agent": _random_ua(),
        "Accept": "application/json",
        "X-Shopee-Language": "en",
        "X-API-SOURCE": "pc",
        "af-ac-enc-dat": "null",   # Shopee API 反爬参数
    }
    # ...

def _fetch_via_html(domain: str, url_template: str) -> list[dict]:
    """降级：通过 HTML 页面抓取数据。"""
    # 使用 requests + BeautifulSoup
    # Shopee 页面为 SPA，HTML 中可能不含产品数据
    # 尝试从 <script> 标签中的 JSON 数据提取
    # ...
```

### 4.6 缓存

```python
_CACHE_DIR = "data/cache"
_CACHE_TTL = 24 * 60 * 60  # 24 小时

def _get_cache_path(prefix: str, region: str) -> str:
    """返回缓存文件路径。"""
    return os.path.join(_CACHE_DIR, f"shopee_{prefix}_{region}.json")
```

---

## 5. 利润计算器 — `src/calculator.py` 新增

### 5.1 Shopee 利润模型

| 费用项 | Shopee | 说明 |
|--------|--------|------|
| 平台佣金 | 2-6% | 按类目不同，取较高值 6% |
| 服务费 | 1-2% | 交易手续费 |
| 国际运费 | ¥12/件 | 国内发往东南亚 |
| 包装费 | ¥3/件 | 比国内直发略高 |
| 汇率损耗 | 1% | 东南亚小币种汇兑损失 |

### 5.2 计算函数

```python
@register_calculator("shopee")
def calculate_shopee_profit(
    price: float,
    defaults: dict,
    procurement_cny: float = 0.0,
    **kwargs,
) -> dict:
    """
    Shopee 卖家利润计算。

    公式：
        售价(本地货币) × 汇率 = 售价(CNY)
        佣金 = 售价(CNY) × commission_pct
        服务费 = 售价(CNY) × service_fee_pct
        汇率损耗 = 售价(CNY) × exchange_loss_pct
        总成本 = 采购成本 + 国际运费 + 包装费 + 佣金 + 服务费 + 汇率损耗
        净利 = 售价(CNY) - 总成本
        毛利率 = 净利 / 售价(CNY)

    Returns:
        标准利润结果字典
    """
    exchange_rate = defaults.get("exchange_rate", 5.42)
    commission_pct = defaults.get("commission_pct", 0.06)
    service_fee_pct = defaults.get("service_fee_pct", 0.02)
    shipping_cny = defaults.get("shipping_cny", 12.0)
    packaging_cny = defaults.get("packaging_cny", 3.0)
    exchange_loss_pct = defaults.get("exchange_loss_pct", 0.01)

    price_cny = price * exchange_rate
    commission_cny = price_cny * commission_pct
    service_fee_cny = price_cny * service_fee_pct
    exchange_loss_cny = price_cny * exchange_loss_pct
    total_cost = (procurement_cny + shipping_cny + packaging_cny
                  + commission_cny + service_fee_cny + exchange_loss_cny)
    net_profit_cny = price_cny - total_cost
    margin_pct = (net_profit_cny / price_cny * 100) if price_cny > 0 else 0

    return {
        "price_local": price,
        "price_cny": round(price_cny, 2),
        "commission_cny": round(commission_cny, 2),
        "service_fee_cny": round(service_fee_cny, 2),
        "exchange_loss_cny": round(exchange_loss_cny, 2),
        "shipping_cny": round(shipping_cny, 2),
        "packaging_cny": round(packaging_cny, 2),
        "procurement_cny": round(procurement_cny, 2),
        "total_cost_cny": round(total_cost, 2),
        "net_profit_cny": round(net_profit_cny, 2),
        "net_profit_usd": round(net_profit_cny / 7.24, 2),
        "margin_pct": round(margin_pct, 1),
        "is_profitable": net_profit_cny > 0,
        "has_procurement": procurement_cny > 0,
    }
```

---

## 6. 配置更新 — `.env.example`

新增以下模板：

```env
# ============================================================
# Shopee 平台配置
# ============================================================

# --- Shopee 利润参数 ---
SHOPEE_COMMISSION_PCT=0.06
SHOPEE_SERVICE_FEE_PCT=0.02
SHOPEE_SHIPPING_CNY=12.0
SHOPEE_PACKAGING_CNY=3.0
SHOPEE_EXCHANGE_LOSS_PCT=0.01
```

---

## 7. 数据流

```
用户在侧边栏选择「Shopee」+「新加坡站」
    ↓
app.py 从 PLATFORMS 获取 shopee 配置
    ↓
点击「实时选品」
    ↓
调用 fetch_shopee_best_sellers(region="sg")
    ↓
1. 尝试 Shopee 公开 API（优先）
   2. API 失败 → 降级 HTML 抓取
    ↓
解析数据 → 标准产品列表（价格 /100000 转换）
    ↓
写入数据库（platform="shopee", region="sg", currency="SGD"）
    ↓
用户查看产品列表 → 输入采购成本
    ↓
调用 calculate_shopee_profit() 计算利润
    ↓
显示利润结果（Shopee 专用字段：佣金、服务费、汇率损耗）
```

---

## 8. 特殊处理：越南盾（VND）

越南盾面值极大，一个普通产品价格可能在 50,000 - 500,000 VND 范围。需要特殊处理：

```python
# 价格显示格式化
def format_price(price: float, currency: str) -> str:
    if currency == "VND":
        return f"₫{price:,.0f}"       # 无小数位
    elif currency == "THB":
        return f"฿{price:,.2f}"
    elif currency == "PHP":
        return f"₱{price:,.2f}"
    elif currency == "MYR":
        return f"RM{price:,.2f}"
    elif currency == "SGD":
        return f"S${price:,.2f}"
    else:
        return f"${price:,.2f}"
```

---

## 9. 抓取反爬策略

| 策略 | 说明 |
|------|------|
| API 优先 | Shopee 公开 API 比 HTML 更稳定 |
| af-ac-enc-dat Header | Shopee API 需要 `af-ac-enc-dat: null` 绕过加密验证 |
| User-Agent 轮换 | 准备 3-5 个常见浏览器 UA |
| 请求延迟 | 每次请求间隔 2-3 秒 |
| Cookie 管理 | 使用 `requests.Session()` |
| 重试机制 | 最多重试 3 次，指数退避 |
| 降级策略 | API → HTML → 友好错误 |
| 缓存 | 24 小时缓存 |
| 超时 | 单次请求 30 秒 |

---

## 10. 验收标准

1. 侧边栏选择 Shopee 后，可进一步选择 5 个东南亚地区站点
2. 点击「实时选品」能通过 API 抓取 Shopee 热销产品数据
3. API 不可用时自动降级为 HTML 抓取
4. 抓取数据包含：标题、价格（正确转换）、评分、销量、产品链接
5. 利润计算器使用 Shopee 公式（佣金+服务费+汇率损耗）
6. 越南站价格显示正确（无小数，₫ 符号）
7. 数据库记录 `platform="shopee"` + 对应 region/currency
8. 关键词搜索功能正常（指定选品页面）
9. 抓取失败时显示友好错误提示，不崩溃
10. `pytest tests/` 全部通过

---

## 11. 风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| Shopee API 可能需要特定 Header | 研究实际请求，模拟完整 Header |
| Shopee SPA 页面无法直接抓取 | 优先 API 方式，HTML 作为降级 |
| 越南盾面值大，价格转换容易出错 | 统一 `/100000` 转换 + 单元测试覆盖 |
| 东南亚各站点语言不同（泰文、越南文） | 产品标题保持原文，不做翻译 |
| API 接口变更 | 版本锁定 `v4` + 多版本兼容尝试 |
