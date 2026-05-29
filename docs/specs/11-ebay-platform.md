# Spec 11：eBay 平台集成

**版本**：v1.0
**状态**：📋 待实施
**创建日期**：2026-05-29
**前置依赖**：Spec 8（多平台基础设施框架）

---

## 1. 需求描述

### 1.1 背景
eBay 是全球最大的 C2C/B2C 电商平台之一，在北美、欧洲、澳洲等成熟市场拥有庞大用户群。对于跨境卖家来说，eBay 的优势在于品类灵活、门槛较低、没有自有仓储要求。eBay 页面结构相对稳定，有完善的公开 HTML 结构，数据抓取可靠性较高。

### 1.2 目标
在 Spec 8 多平台基础设施上，接入 eBay 平台：实现 Best Sellers/Trending 榜单抓取、关键词搜索抓取、eBay 专属利润计算（Managed Payments 费用模型）、3 个主要地区站点支持。

### 1.3 核心需求
1. **榜单抓取**：抓取 eBay Trending / Best Sellers 页面热销产品
2. **关键词搜索**：根据用户输入关键词搜索 eBay 产品
3. **利润计算**：eBay Managed Payments 费用模型（成交费 + 支付费 + 刊登费）
4. **地区站点**：美国站、英国站、德国站
5. **平台注册**：在 `PLATFORMS` 注册表中注册 eBay

---

## 2. 系统设计

### 2.1 新建文件

| 文件 | 说明 |
|------|------|
| `src/scraper_ebay.py` | eBay 数据抓取模块（榜单 + 搜索） |

### 2.2 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `src/platforms.py` | **修改** | 注册 `ebay` 平台 |
| `src/calculator.py` | **修改** | 新增 `calculate_ebay_profit()` |
| `src/config.py` | **修改** | 支持 eBay 配置项 |
| `app.py` | **修改** | eBay 平台的路由和展示（已由 Spec 8 框架自动支持） |
| `.env.example` | **修改** | 新增 eBay 相关配置模板 |

---

## 3. 平台注册 — `src/platforms.py` 新增

### 3.1 PLATFORMS 字典新增条目

```python
"ebay": {
    "name": "eBay",
    "icon": "🔵",
    "scraper_module": "src.scraper_ebay",
    "scraper_func": "fetch_ebay_best_sellers",
    "search_module": "src.scraper_ebay",
    "search_func": "search_ebay",
    "calculator": "calculate_ebay_profit",
    "currency": "USD",
    "regions": {
        "us": {"name": "美国站", "domain": "ebay.com",     "currency": "USD", "exchange_rate": 7.24},
        "uk": {"name": "英国站", "domain": "ebay.co.uk",   "currency": "GBP", "exchange_rate": 9.18},
        "de": {"name": "德国站", "domain": "ebay.de",      "currency": "EUR", "exchange_rate": 7.88},
    },
    "default_region": "us",
    "profit_defaults": {
        "final_value_fee_pct": 0.1325,  # 成交费（eBay Managed Payments，约 13.25%）
        "listing_fee_usd": 0.30,        # 刊登费（前 250 条免费，超出 $0.35/条，取均值）
        "shipping_cny": 20.0,           # 国际运费（eBay 卖家多自发货）
        "packaging_cny": 5.0,           # 包装费
        "payoneer_fee_pct": 0.01,       # Payoneer/提现手续费（约 1%）
    },
},
```

---

## 4. 数据抓取 — `src/scraper_ebay.py`

### 4.1 榜单抓取

```python
def fetch_ebay_best_sellers(region: str = "us") -> tuple[list[dict], dict]:
    """
    抓取 eBay Trending / Best Sellers 热销产品。

    Args:
        region: 地区代码（us/uk/de）

    抓取策略：
        优先 URL: https://www.ebay.com/trending/
        备选 URL: https://www.ebay.com/b/Best-Sellers/bn_7001234567
        搜索排序: https://www.ebay.com/sch/i.html?_nkw=best+sellers&_sop=12

    返回:
        (products_list, source_info_dict)
    """
```

**eBay 页面特点**：
- HTML 结构稳定，CSS 类名变化少
- 产品列表使用 `ul.srp-results` 或 `div.b-list__items` 容器
- Trending 页面产品卡片有 `div.ebayui-dne-itemtcard` 类名
- 支持直接 `requests` + `BeautifulSoup` 抓取，无需 API Key

### 4.2 关键词搜索

```python
def search_ebay(keyword: str, region: str = "us", max_pages: int = 2) -> tuple[list[dict], dict]:
    """
    根据关键词搜索 eBay 产品。

    Args:
        keyword: 搜索关键词
        region:  地区代码（us/uk/de）
        max_pages: 最大抓取页数

    搜索 URL:
        https://www.ebay.{domain}/sch/i.html?_nkw={keyword}&_sop=12
        _sop=12 表示按销量排序（Best Match 默认）

    返回:
        (products_list, source_info_dict)
    """
```

### 4.3 CSS 选择器

```python
# eBay 搜索结果页选择器
_SR_RESULTS_CONTAINER = "ul.srp-results li.s-item"
_SR_TITLE = "div.s-item__title"
_SR_PRICE = "span.s-item__price"
_SR_SHIPPING = "span.s-item__shipping"
_SR_RATING = "div.x-star-rating"
_SR_URL = "a.s-item__link"
_SR_IMAGE = "img.s-item__image-img"
_SR_REVIEWS = "span.s-item__reviews-count"

# eBay Trending 页面选择器
_TRENDING_CARD = "div.ebayui-dne-itemtcard"
_TRENDING_TITLE = "h3.texttt"
_TRENDING_PRICE = "div.displayprice"
_TRENDING_URL = "a[href]"
```

### 4.4 辅助函数

```python
def _extract_title(card) -> str:
    """从产品卡片提取标题。"""

def _extract_price(card) -> float:
    """
    从产品卡片提取价格。
    eBay 价格格式：
      - "$12.99"
      - "$12.99 to $29.99"（取最低价）
      - "C $15.00"（加拿大元，需注意）
    """

def _extract_shipping(card) -> float:
    """
    提取运费。
    eBay 运费格式：
      - "Free shipping" → 0
      - "+$5.99 shipping" → 5.99
    """

def _extract_rating(card) -> float:
    """提取评分（可能为空，eBay 不总是显示评分）。"""

def _extract_reviews(card) -> int:
    """提取评论数。"""

def _extract_url(card) -> str:
    """提取产品链接。"""

def _extract_image(card) -> str:
    """提取图片 URL。"""

def _clean_price(price_str: str) -> float:
    """
    清洗价格字符串。
    处理格式："$12.99", "$12.99 to $29.99", "C $15.00"
    """
    # 移除货币符号，取第一个价格
    # ...
```

### 4.5 缓存

```python
_CACHE_DIR = "data/cache"
_CACHE_TTL = 24 * 60 * 60  # 24 小时

def _get_cache_path(prefix: str, region: str) -> str:
    """返回缓存文件路径。"""
    return os.path.join(_CACHE_DIR, f"ebay_{prefix}_{region}.json")
```

---

## 5. 利润计算器 — `src/calculator.py` 新增

### 5.1 eBay 利润模型

| 费用项 | eBay | 说明 |
|--------|------|------|
| 成交费 (Final Value Fee) | 13.25% | eBay Managed Payments 统一费率 |
| 刊登费 (Listing Fee) | $0.30/条 | 前 250 条免费，超出 $0.35 |
| 国际运费 | ¥20/件 | eBay 卖家多为自发货，成本较高 |
| 包装费 | ¥5/件 | |
| Payoneer 提现费 | 1% | 从 eBay 收款到国内银行卡 |

> **注意**：eBay 的成交费 (13.25%) 远高于 AliExpress (8%) 和 Shopee (6%)，但运费由卖家自控，灵活度较高。

### 5.2 计算函数

```python
@register_calculator("ebay")
def calculate_ebay_profit(
    price: float,
    defaults: dict,
    procurement_cny: float = 0.0,
    **kwargs,
) -> dict:
    """
    eBay 卖家利润计算。

    公式：
        售价(USD) × 汇率 = 售价(CNY)
        成交费 = 售价(CNY) × final_value_fee_pct (13.25%)
        刊登费 = listing_fee_usd × 汇率
        提现手续费 = 售价(CNY) × payoneer_fee_pct (1%)
        总成本 = 采购成本 + 国际运费 + 包装费 + 成交费 + 刊登费 + 提现手续费
        净利 = 售价(CNY) - 总成本
        毛利率 = 净利 / 售价(CNY)

    Returns:
        标准利润结果字典
    """
    exchange_rate = defaults.get("exchange_rate", 7.24)
    final_value_fee_pct = defaults.get("final_value_fee_pct", 0.1325)
    listing_fee_usd = defaults.get("listing_fee_usd", 0.30)
    shipping_cny = defaults.get("shipping_cny", 20.0)
    packaging_cny = defaults.get("packaging_cny", 5.0)
    payoneer_fee_pct = defaults.get("payoneer_fee_pct", 0.01)

    price_cny = price * exchange_rate
    fvf_cny = price_cny * final_value_fee_pct
    listing_cny = listing_fee_usd * exchange_rate
    payoneer_cny = price_cny * payoneer_fee_pct
    total_cost = (procurement_cny + shipping_cny + packaging_cny
                  + fvf_cny + listing_cny + payoneer_cny)
    net_profit_cny = price_cny - total_cost
    margin_pct = (net_profit_cny / price_cny * 100) if price_cny > 0 else 0

    return {
        "price_local": price,
        "price_cny": round(price_cny, 2),
        "fvf_cny": round(fvf_cny, 2),              # 成交费
        "listing_cny": round(listing_cny, 2),       # 刊登费
        "payoneer_cny": round(payoneer_cny, 2),     # 提现手续费
        "shipping_cny": round(shipping_cny, 2),
        "packaging_cny": round(packaging_cny, 2),
        "procurement_cny": round(procurement_cny, 2),
        "total_cost_cny": round(total_cost, 2),
        "net_profit_cny": round(net_profit_cny, 2),
        "net_profit_usd": round(net_profit_cny / exchange_rate, 2),
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
# eBay 平台配置
# ============================================================

# --- eBay 利润参数 ---
EBAY_FINAL_VALUE_FEE_PCT=0.1325
EBAY_LISTING_FEE_USD=0.30
EBAY_SHIPPING_CNY=20.0
EBAY_PACKAGING_CNY=5.0
EBAY_PAYONEER_FEE_PCT=0.01
```

---

## 7. 数据流

```
用户在侧边栏选择「eBay」+「美国站」
    ↓
app.py 从 PLATFORMS 获取 ebay 配置
    ↓
点击「实时选品」
    ↓
调用 fetch_ebay_best_sellers(region="us")
    ↓
抓取 ebay.com/trending 页面
    ↓
解析 HTML → 标准产品列表
    ↓
写入数据库（platform="ebay", region="us", currency="USD"）
    ↓
用户查看产品列表 → 输入采购成本
    ↓
调用 calculate_ebay_profit() 计算利润
    ↓
显示利润结果（eBay 专用字段：成交费、刊登费、Payoneer 提现费）
```

---

## 8. 抓取反爬策略

| 策略 | 说明 |
|------|------|
| User-Agent 轮换 | 准备 5 个常见浏览器 UA |
| 请求延迟 | 每次请求间隔 1.5-2.5 秒 |
| Accept-Language | 按地区设置 `en-US`, `en-GB`, `de-DE` |
| Cookies 处理 | 使用 `requests.Session()` |
| 重试机制 | 最多重试 3 次，指数退避 |
| 降级策略 | Trending → 搜索排序 → 友好错误 |
| 缓存 | 24 小时缓存 |
| 超时 | 单次请求 30 秒 |

---

## 9. 验收标准

1. 侧边栏选择 eBay 后，可进一步选择地区（美国/英国/德国）
2. 点击「实时选品」能抓取 eBay Trending 产品数据
3. 抓取数据包含：标题、价格、运费、评分、评论数、产品链接、图片
4. 价格解析正确处理区间价（"$12.99 to $29.99"）
5. 运费解析正确处理 "Free shipping" 和 "+$5.99 shipping"
6. 利润计算器使用 eBay 公式（13.25% 成交费 + 刊登费）
7. 利润结果展示 eBay 特有字段（成交费、刊登费、Payoneer 费）
8. 数据库记录 `platform="ebay"` + 对应 region/currency
9. 关键词搜索功能正常（指定选品页面）
10. 英国站显示英镑（£），德国站显示欧元（€）
11. 抓取失败时显示友好错误提示，不崩溃
12. `pytest tests/` 全部通过

---

## 10. 风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| eBay Trending 页面结构变化 | 多层 CSS 选择器兜底 + 搜索排序降级 |
| 价格格式多样（区间价、拍卖价） | 优先取 Buy It Now 最低价 |
| eBay 反爬较严格（CAPTCHA） | 合理延迟 + 缓存 + UA 轮换 |
| 德国站 (ebay.de) 界面为德语 | CSS 选择器通常相同，标题保持原文 |
| 成交费按类目不同（8%-15%） | 默认取 13.25%（大多数类目），用户可在侧边栏调整 |
