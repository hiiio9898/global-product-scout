# Spec 9：AliExpress 平台集成

**版本**：v1.0
**状态**：📋 待实施
**创建日期**：2026-05-29
**前置依赖**：Spec 8（多平台基础设施框架）

---

## 1. 需求描述

### 1.1 背景
AliExpress（速卖通）是中国跨境电商最大平台之一，面向全球消费者以 B2C 模式销售。其利润模型与 Amazon FBA 有本质区别：卖家多从国内发货（或海外仓），没有 FBA 仓储费，但有平台成交费和提现手续费。对于外贸选品工具来说，AliExpress 是仅次于 Amazon 的重要数据源。

### 1.2 目标
在 Spec 8 多平台基础设施上，接入 AliExpress 平台：实现 Best Sellers 榜单抓取、关键词搜索抓取、AliExpress 专属利润计算、3 个地区站点支持。

### 1.3 核心需求
1. **榜单抓取**：抓取 AliExpress Best Sellers 页面热销产品数据
2. **关键词搜索**：根据用户输入关键词搜索 AliExpress 产品
3. **利润计算**：AliExpress 卖家利润模型（无 FBA，有平台成交费 + 提现手续费）
4. **地区站点**：美国站、欧洲站、俄罗斯站
5. **平台注册**：在 `PLATFORMS` 注册表中注册 AliExpress

---

## 2. 系统设计

### 2.1 新建文件

| 文件 | 说明 |
|------|------|
| `src/scraper_aliexpress.py` | AliExpress 数据抓取模块（榜单 + 搜索） |

### 2.2 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `src/platforms.py` | **修改** | 注册 `aliexpress` 平台 |
| `src/calculator.py` | **修改** | 新增 `calculate_aliexpress_profit()` |
| `src/config.py` | **修改** | 支持 AliExpress 配置项 |
| `app.py` | **修改** | AliExpress 平台的路由和展示（已由 Spec 8 框架自动支持） |
| `.env.example` | **修改** | 新增 AliExpress 相关配置模板 |

---

## 3. 平台注册 — `src/platforms.py` 新增

### 3.1 PLATFORMS 字典新增条目

```python
"aliexpress": {
    "name": "AliExpress",
    "icon": "🔴",
    "scraper_module": "src.scraper_aliexpress",
    "scraper_func": "fetch_aliexpress_best_sellers",
    "search_module": "src.scraper_aliexpress",
    "search_func": "search_aliexpress",
    "calculator": "calculate_aliexpress_profit",
    "currency": "USD",
    "regions": {
        "us": {"name": "美国站", "domain": "aliexpress.com",       "currency": "USD", "exchange_rate": 7.24},
        "eu": {"name": "欧洲站", "domain": "aliexpress.com",       "currency": "EUR", "exchange_rate": 7.88},
        "ru": {"name": "俄罗斯站", "domain": "aliexpress.ru",      "currency": "RUB", "exchange_rate": 0.079},
    },
    "default_region": "us",
    "profit_defaults": {
        "commission_pct": 0.08,     # 平台成交费（约 5%-8%）
        "withdrawal_fee_pct": 0.01, # 提现手续费（约 1%）
        "shipping_cny": 8.0,        # 国内直发运费（比 FBA 便宜）
        "packaging_cny": 2.0,       # 包装费用
    },
},
```

---

## 4. 数据抓取 — `src/scraper_aliexpress.py`

### 4.1 榜单抓取

```python
def fetch_aliexpress_best_sellers(region: str = "us") -> tuple[list[dict], dict]:
    """
    抓取 AliExpress Best Sellers 热销产品。

    Args:
        region: 地区代码（us/eu/ru）

    抓取策略：
        URL: https://www.aliexpress.com/glo/best-sellers-{category}.html
        或使用搜索排序方式：https://www.aliexpress.com/w/wholesale-best-selling.html?SortType=total_orders

    返回:
        (products_list, source_info_dict)
        - products_list: 产品列表，每项包含标准产品字段
        - source_info: {"source": "aliexpress_best_sellers", "region": region, ...}
    """
```

**抓取细节**：
- 使用 `requests` + `BeautifulSoup` 抓取 HTML
- 设置 `User-Agent` 模拟浏览器
- 请求间延迟 1.5-2 秒
- 缓存文件：`data/cache/aliexpress_best_sellers_{region}.json`
- 缓存有效期 24 小时
- 遵守 `robots.txt`

**CSS 选择器（预估值，需实际调试）**：
```python
_TITLE_SELECTORS = [
    "h3.manhattan--title--2i-6M",
    "div.product-title",
    "h1.product-title-text",
    "[class*='title'] a",
]
_PRICE_SELECTORS = [
    "span.manhattan--price--2i-6M",
    "div.product-price",
    "span[class*='price-current']",
]
_RATING_SELECTORS = [
    "span.manhattan--rating--2i-6M",
    "span.rating-value",
    "[class*='rating']",
]
```

### 4.2 关键词搜索

```python
def search_aliexpress(keyword: str, region: str = "us", max_pages: int = 2) -> tuple[list[dict], dict]:
    """
    根据关键词搜索 AliExpress 产品。

    Args:
        keyword: 搜索关键词
        region:  地区代码（us/eu/ru）
        max_pages: 最大抓取页数

    搜索 URL:
        https://www.aliexpress.com/w/wholesale-{keyword}.html?SortType=total_orders

    返回:
        (products_list, source_info_dict)
    """
```

### 4.3 辅助函数

```python
def _extract_title(card) -> str:
    """从产品卡片中提取标题，尝试多个选择器。"""

def _extract_price(card) -> float:
    """从产品卡片中提取价格，清洗货币符号后转浮点数。"""

def _extract_rating(card) -> float:
    """从产品卡片中提取评分。"""

def _extract_reviews(card) -> int:
    """从产品卡片中提取评论/销量数。"""

def _extract_url(card) -> str:
    """从产品卡片中提取产品链接。"""

def _extract_image(card) -> str:
    """从产品卡片中提取产品图片 URL。"""

# 过滤关键词（排除不相关产品）
_SKIP_KEYWORDS = ["virtual", "gift card", "coupon", "top up", "recharge"]
```

---

## 5. 利润计算器 — `src/calculator.py` 新增

### 5.1 AliExpress 利润模型

AliExpress 卖家成本结构与 Amazon FBA 不同：

| 费用项 | Amazon FBA | AliExpress |
|--------|-----------|------------|
| 平台佣金 | 15%（类目浮动） | 5-8% 成交费 |
| FBA 仓储配送 | ~$3-5/件 | 无（卖家自发货或海外仓） |
| 国内运费 | FBA 头程 ¥15 | 国内直发 ¥8 |
| 广告费 | 10% PPC | 可选，暂不计 |
| 提现手续费 | 无 | 1% |
| 包装费 | 含在 FBA | ¥2/件 |

### 5.2 计算函数

```python
@register_calculator("aliexpress")
def calculate_aliexpress_profit(
    price: float,
    defaults: dict,
    procurement_cny: float = 0.0,
    **kwargs,
) -> dict:
    """
    AliExpress 卖家利润计算。

    公式：
        售价(USD) × 汇率 = 售价(CNY)
        成交费 = 售价(CNY) × commission_pct (5-8%)
        提现手续费 = 售价(CNY) × withdrawal_fee_pct (1%)
        总成本 = 采购成本 + 国内运费 + 包装费 + 成交费 + 提现手续费
        净利 = 售价(CNY) - 总成本
        毛利率 = 净利 / 售价(CNY)

    Args:
        price: 售价（USD 或本地货币）
        defaults: 利润参数字典，含 exchange_rate, commission_pct, withdrawal_fee_pct,
                  shipping_cny, packaging_cny
        procurement_cny: 采购成本（人民币）
        **kwargs: 预留扩展参数

    Returns:
        标准利润结果字典：
        {
            "price_local": float,         # 售价（本地货币）
            "price_cny": float,           # 售价（人民币）
            "commission_cny": float,      # 平台成交费
            "withdrawal_fee_cny": float,  # 提现手续费
            "shipping_cny": float,        # 国内运费
            "packaging_cny": float,       # 包装费
            "procurement_cny": float,     # 采购成本
            "total_cost_cny": float,      # 总成本
            "net_profit_cny": float,      # 净利润
            "net_profit_usd": float,      # 净利润（美元）
            "margin_pct": float,          # 毛利率 %
            "is_profitable": bool,        # 是否盈利
            "has_procurement": bool,      # 是否有采购成本
        }
    """
    exchange_rate = defaults.get("exchange_rate", 7.24)
    commission_pct = defaults.get("commission_pct", 0.08)
    withdrawal_fee_pct = defaults.get("withdrawal_fee_pct", 0.01)
    shipping_cny = defaults.get("shipping_cny", 8.0)
    packaging_cny = defaults.get("packaging_cny", 2.0)

    price_cny = price * exchange_rate
    commission_cny = price_cny * commission_pct
    withdrawal_fee_cny = price_cny * withdrawal_fee_pct
    total_cost = procurement_cny + shipping_cny + packaging_cny + commission_cny + withdrawal_fee_cny
    net_profit_cny = price_cny - total_cost
    margin_pct = (net_profit_cny / price_cny * 100) if price_cny > 0 else 0

    return {
        "price_local": price,
        "price_cny": round(price_cny, 2),
        "commission_cny": round(commission_cny, 2),
        "withdrawal_fee_cny": round(withdrawal_fee_cny, 2),
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
# AliExpress 平台配置
# ============================================================

# --- AliExpress 地区站点 ---
ALIEXPRESS_US_URL=https://www.aliexpress.com
ALIEXPRESS_EU_URL=https://www.aliexpress.com
ALIEXPRESS_RU_URL=https://www.aliexpress.ru

# --- AliExpress 利润参数 ---
ALIEXPRESS_COMMISSION_PCT=0.08
ALIEXPRESS_WITHDRAWAL_FEE_PCT=0.01
ALIEXPRESS_SHIPPING_CNY=8.0
ALIEXPRESS_PACKAGING_CNY=2.0
```

---

## 7. `src/config.py` 变更

`get_profit_defaults()` 中 `platform_key="aliexpress"` 分支从环境变量读取 AliExpress 参数：

```python
if platform_key == "aliexpress":
    defaults["commission_pct"] = float(os.environ.get("ALIEXPRESS_COMMISSION_PCT", 0.08))
    defaults["withdrawal_fee_pct"] = float(os.environ.get("ALIEXPRESS_WITHDRAWAL_FEE_PCT", 0.01))
    defaults["shipping_cny"] = float(os.environ.get("ALIEXPRESS_SHIPPING_CNY", 8.0))
    defaults["packaging_cny"] = float(os.environ.get("ALIEXPRESS_PACKAGING_CNY", 2.0))
```

---

## 8. 数据流

```
用户在侧边栏选择「AliExpress」+「美国站」
    ↓
app.py 从 PLATFORMS 获取 aliexpress 配置
    ↓
点击「实时选品」
    ↓
调用 fetch_aliexpress_best_sellers(region="us")
    ↓
抓取 aliexpress.com Best Sellers 页面
    ↓
解析 HTML → 标准产品列表
    ↓
写入数据库（platform="aliexpress", region="us", currency="USD"）
    ↓
用户查看产品列表 → 输入采购成本
    ↓
调用 calculate_aliexpress_profit() 计算利润
    ↓
显示利润结果（AliExpress 专用字段：成交费、提现手续费、包装费）
```

---

## 9. 抓取反爬策略

| 策略 | 说明 |
|------|------|
| User-Agent 轮换 | 准备 3-5 个常见浏览器 UA，随机选择 |
| 请求延迟 | 每次请求间隔 1.5-2.5 秒（随机） |
| Cookies 处理 | 使用 `requests.Session()` 维持会话 |
| 重试机制 | 最多重试 3 次，指数退避 |
| 降级策略 | 如果榜单页被封，切换到搜索排序页 |
| 缓存 | 24 小时缓存，避免重复请求 |
| 超时 | 单次请求 30 秒超时 |

---

## 10. 验收标准

1. 侧边栏选择 AliExpress 后，可进一步选择地区（美国/欧洲/俄罗斯）
2. 点击「实时选品」能抓取 AliExpress Best Sellers 产品数据
3. 抓取数据包含：标题、价格、评分、销量、产品链接、图片
4. 利润计算器使用 AliExpress 公式（无 FBA，有成交费+提现费）
5. 利润结果展示 AliExpress 特有字段（成交费、提现手续费、包装费）
6. 数据库记录 `platform="aliexpress"` + 对应 region/currency
7. 关键词搜索功能正常（指定选品页面）
8. 抓取失败时显示友好错误提示，不崩溃
9. `pytest tests/` 全部通过
10. 所有 Python 文件通过 `python -m py_compile` 编译检查

---

## 11. 风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| AliExpress 页面结构频繁变化 | 多层 CSS 选择器兜底 + 定期维护 |
| AliExpress 反爬较严格 | User-Agent 轮换 + 延迟 + 缓存策略 |
| 俄罗斯站 `aliexpress.ru` 结构可能不同 | 独立 CSS 选择器配置，按 region 分支 |
| 价格格式多样（含折扣价、区间价） | 优先取实际售价，折扣价作为参考 |
| 部分产品缺销量数据 | 显示为 "N/A"，不影响核心功能 |
