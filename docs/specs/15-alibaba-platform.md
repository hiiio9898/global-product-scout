# Spec 15：阿里巴巴国际站平台集成

**版本**：v1.0
**状态**：✅ 已完成
**创建日期**：2026-06-01（补写）
**前置依赖**：Spec 8（多平台基础设施框架）、Spec 14（Scrapling 抓取引擎集成）

---

## 1. 需求描述

### 1.1 背景
阿里巴巴国际站（alibaba.com）是全球最大的 B2B 跨境电商平台，连接中国供应商与海外买家。对于跨境电商卖家而言，阿里巴巴是寻找供应链、比价采购的核心渠道。与 Amazon/eBay 的 B2C 模式不同，阿里巴巴以批发为主，产品页面包含 MOQ（最小起订量）、工厂直供价格等 B2B 特有信息。

阿里巴巴国际站采用强反爬策略（JS 动态渲染 + Cloudflare 防护），必须使用 Scrapling 的 StealthyFetcher（Patchright 反检测浏览器）才能有效抓取。

### 1.2 目标
在 Spec 8 多平台基础设施和 Spec 14 Scrapling 引擎上，接入阿里巴巴国际站：实现热销产品抓取、关键词搜索、B2B 专属利润计算（佣金 + 信保费用模型）、国际站单一地区支持。

### 1.3 核心需求
1. **热销抓取**：抓取阿里巴巴国际站搜索结果页热销产品
2. **关键词搜索**：根据用户输入关键词搜索阿里巴巴产品
3. **利润计算**：阿里巴巴 B2B 费用模型（佣金 5% + 信保 2% + 国际运费）
4. **地区站点**：国际站（US，无地区差异）
5. **平台注册**：在 `PLATFORMS` 注册表中注册 Alibaba

---

## 2. 系统设计

### 2.1 新建文件

| 文件 | 说明 |
|------|------|
| `src/scraper_alibaba.py` | 阿里巴巴国际站数据抓取模块（热销 + 搜索） |

### 2.2 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `src/platforms.py` | **修改** | 注册 `alibaba` 平台 |
| `src/calculator.py` | **修改** | 新增 `calculate_alibaba_profit()` |
| `app.py` | **修改** | Alibaba 平台的路由和展示（已由 Spec 8 框架自动支持） |
| `.env.example` | **修改** | 新增阿里巴巴利润参数配置模板 |

---

## 3. 平台注册 — `src/platforms.py`

### 3.1 PLATFORMS 字典新增条目

```python
"alibaba": {
    "name": "Alibaba",
    "icon": "🟠",
    "scraper_module": "src.scraper_alibaba",
    "scraper_func": "fetch_alibaba_best_sellers",
    "search_module": "src.scraper_alibaba",
    "search_func": "search_alibaba",
    "calculator": "calculate_alibaba_profit",
    "scrape_mode": "stealth_only",       # 强反爬，必须用 StealthyFetcher
    "currency": "USD",
    "regions": {
        "us": {"name": "国际站", "domain": "alibaba.com", "currency": "USD", "exchange_rate": 7.24},
    },
    "default_region": "us",
    "profit_defaults": {
        "commission_pct": 0.05,          # 阿里巴巴佣金 5%
        "trade_assurance_pct": 0.02,     # 信保费用 2%
        "shipping_cny": 25.0,            # 国际运费
        "packaging_cny": 3.0,            # 包装费
    },
},
```

**关键设计决策**：
- `scrape_mode: "stealth_only"` — 阿里巴巴使用 Cloudflare + JS 动态渲染，普通 Fetcher（curl_cffi）无法获取内容，必须直接使用 StealthyFetcher
- 仅支持 `us` 地区（国际站统一入口，无地区差异）
- B2B 费用模型与 B2C（Amazon/eBay）不同，增加信保费用项

---

## 4. 数据抓取 — `src/scraper_alibaba.py`

### 4.1 抓取策略

阿里巴巴国际站为 JS 动态渲染网站，采用 Scrapling StealthyFetcher（Patchright 反检测浏览器）进行抓取。

**抓取流程**：
```
fetch_page(url, stealth_only=True)
    → StealthyFetcher (Patchright 反检测浏览器)
    → 等待 JS 渲染完成
    → 返回渲染后的 HTML
    → CSS 选择器解析产品卡片
```

### 4.2 热销产品抓取

```python
def fetch_alibaba_best_sellers(region: str = "us") -> tuple[list[dict], dict]:
    """
    获取阿里巴巴国际站热销产品（两层降级策略）。

    第一层：实时抓取 alibaba.com 搜索 "best seller" 结果
    第二层：本地 JSON 缓存（24 小时 TTL）

    返回:
        (products_list, source_info_dict)
    """
```

**搜索 URL**：
```
https://www.alibaba.com/trade/search?SearchText=best+seller&tab=all
```

### 4.3 关键词搜索

```python
def search_alibaba(keyword: str, region: str = "us", max_results: int = 30) -> dict:
    """
    在阿里巴巴国际站搜索指定关键词。

    搜索 URL:
        https://www.alibaba.com/trade/search?SearchText={keyword}&tab=all

    返回:
        {
            "success": bool,
            "keyword": str,
            "results": list[dict],
            "total_found": int,
            "source": "live" | "none",
            "scrape_time": str,
            "error": str | None,
        }
    """
```

### 4.4 CSS 选择器

```python
# 产品卡片容器（多选择器兜底）
_CARD_SELECTORS = [
    "div.fy26-product-card-wrapper",      # Alibaba 2026 新版
    "div[class*='product-card']",          # 通用匹配
    "div[class*='organic-list'] > div",    # 有机搜索结果
]

# 子元素选择器
_TITLE_SELECTORS = [
    "h2.searchx-product-e-title",
    "h2[class*='title']",
    "a[href*='/product-detail/'] h2",
]
_PRICE_SELECTORS = [
    "div.searchx-price-area",
    "div[class*='price']",
    "span[class*='price']",
]
```

### 4.5 B2B 特有字段解析

| 字段 | 解析方式 | 示例 |
|------|---------|------|
| `title` | CSS 选择器 `h2.searchx-product-e-title` | "Custom Logo Stainless Steel Water Bottle" |
| `price` | CSS 选择器 `div.searchx-price-area`，支持 CN¥/US$ 双货币 | US$2.50 - US$5.99 |
| `moq` | 正则 `Min.\s*order:\s*([\d,]+)` | "500" |
| `rating` | 正则 `(\d+\.?\d*)\s*/\s*5\.?\d*` | 4.2 |
| `num_reviews` | 正则 `\((\d+)\)` | 58 |
| `url` | `a[href*='/product-detail/']` | https://www.alibaba.com/product-detail/... |
| `image` | `img[src*='alicdn']` | https://sc04.alicdn.com/... |

### 4.6 价格解析特殊处理

阿里巴巴价格有三种格式：
- `US$5.99` — 直接取 USD 值
- `CN¥53.88` — 除以 7.24 换算为 USD
- `US$2.50 - US$5.99` — 取第一个价格（最低价）

```python
def _parse_alibaba_price(text: str) -> Optional[float]:
    """解析阿里巴巴价格，支持 CN¥ 和 US$ 格式。"""
    is_cny = "CN¥" in text or "¥" in text
    match = re.search(r'[\d,.]+', text)
    if match:
        price = float(match.group(0).replace(",", ""))
        if is_cny:
            price = price / 7.24  # CNY → USD
        return round(price, 2)
    return None
```

---

## 5. 利润计算 — `src/calculator.py`

### 5.1 阿里巴巴 B2B 费用模型

```python
@register_calculator("alibaba")
def calculate_alibaba_profit(price, defaults, procurement_cny=0.0, **kwargs):
    """
    阿里巴巴国际站 (B2B) 卖家利润计算。

    公式：
        售价(USD) × 汇率 = 售价(CNY)
        佣金 = 售价(CNY) × commission_pct (5%)
        信保费用 = 售价(CNY) × trade_assurance_pct (2%)
        总成本 = 采购成本 + 国际运费 + 包装费 + 佣金 + 信保费用
        净利 = 售价(CNY) - 总成本
        毛利率 = 净利 / 售价(CNY)
    """
```

### 5.2 与 Amazon/eBay 费用模型对比

| 费用项 | Amazon FBA | eBay Managed Payments | Alibaba B2B |
|--------|-----------|----------------------|-------------|
| 平台佣金 | 15% | 13.25% (成交费) | 5% |
| 广告/推广 | 10% | — | — |
| 信保费用 | — | — | 2% |
| 刊登费 | — | $0.30 | — |
| 提现手续费 | — | 1% (Payoneer) | — |
| 国际运费 | ¥15 (FBA 头程) | ¥20 (自发货) | ¥25 (B2B 物流) |
| 包装费 | — | ¥5 | ¥3 |

### 5.3 输出字段

```python
{
    "price_local": 5.99,           # 售价 (USD)
    "price_cny": 43.37,            # 售价 (CNY)
    "commission_cny": 2.17,        # 阿里巴巴佣金
    "trade_assurance_cny": 0.87,   # 信保费用
    "shipping_cny": 25.0,          # 国际运费
    "packaging_cny": 3.0,          # 包装费
    "procurement_cny": 0.0,        # 采购成本（用户填写）
    "total_cost_cny": 31.04,       # 总成本
    "net_profit_cny": 12.33,       # 净利 (CNY)
    "net_profit_usd": 1.70,        # 净利 (USD)
    "margin_pct": 28.4,            # 毛利率
    "is_profitable": True,         # 是否盈利
    "has_procurement": False,      # 是否填写了采购成本
}
```

---

## 6. Scrapling 集成要点

### 6.1 为什么 Alibaba 必须用 StealthyFetcher

| 特征 | Amazon/eBay | Alibaba |
|------|------------|---------|
| HTML 渲染 | 服务端渲染（SSR） | JS 动态渲染（CSR） |
| 反爬等级 | 中等 | 高（Cloudflare） |
| Fetcher 可用 | ✅ 是 | ❌ 否（返回空壳 HTML） |
| StealthyFetcher | 降级兜底 | **必须使用** |

### 6.2 scrapling_adapter 调用

```python
from .scrapling_adapter import fetch_page

# Alibaba 使用 stealth_only 模式
resp = fetch_page(url)  # scrapling_adapter 根据 PLATFORMS[alibaba]["scrape_mode"] 自动选择
```

`scrapling_adapter.py` 内部逻辑：
1. 读取平台的 `scrape_mode` 配置
2. `stealth_only` 模式 → 直接调用 `StealthyFetcher`（跳过 `Fetcher`）
3. StealthyFetcher 启动 Patchright 浏览器 → 渲染 JS → 返回 DOM

---

## 7. 配置项 — `.env.example`

```bash
# ============================================================
# 阿里巴巴国际站配置
# ============================================================

# --- 阿里巴巴利润参数 ---
# ALIBABA_COMMISSION_PCT=0.05
# ALIBABA_TRADE_ASSURANCE_PCT=0.02
# ALIBABA_SHIPPING_CNY=25.0
# ALIBABA_PACKAGING_CNY=3.0
```

---

## 8. 测试覆盖

`tests/test_integration.py` 中 Alibaba 相关测试项：

| 测试 | 验证内容 |
|------|---------|
| `test_platform_registry_contains_alibaba` | PLATFORMS 包含 alibaba 键 |
| `test_alibaba_platform_config` | 配置完整性（scraper_module, calculator, regions 等） |
| `test_alibaba_calculator_basic` | 基础利润计算正确性 |
| `test_alibaba_calculator_with_procurement` | 含采购成本的利润计算 |
| `test_alibaba_scraper_import` | scraper_alibaba 模块可正常导入 |
| `test_alibaba_profit_defaults` | 默认利润参数合理性 |

---

## 9. 已知限制

1. **仅支持国际站** — 阿里巴巴国际站（alibaba.com）统一入口，不支持 1688.com 等国内站
2. **价格范围解析** — 阿里巴巴产品常显示价格范围（如 $2.50 - $5.99），当前取最低价
3. **MOQ 信息** — 最小起订量仅做展示，未纳入利润计算（B2B 场景需人工评估）
4. **反爬风险** — 阿里巴巴反爬策略持续升级，Scrapling StealthyFetcher 可能需要定期更新
5. **抓取速度** — StealthyFetcher 需启动浏览器实例，单次抓取耗时 5-15 秒（比 Fetcher 慢 3-5 倍）
