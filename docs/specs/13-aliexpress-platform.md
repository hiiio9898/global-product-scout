# Spec 13：AliExpress（速卖通）平台集成

**版本**：v1.0  
**状态**：🔄 实施中

**创建日期**：2026-05-29  
**前置依赖**：Spec 8（多平台基础设施框架）

---

## 1. 需求描述

### 1.1 背景
AliExpress（速卖通）是阿里巴巴集团旗下的跨境电商平台，面向全球消费者，是中国卖家出海的核心渠道之一。其优势包括：
- **供应链优势**：直接对接中国工厂，采购成本低
- **全球覆盖**：支持 200+ 国家和地区
- **品类丰富**：从电子产品到家居百货，SKU 超过 1 亿
- **物流体系**：菜鸟物流提供全球配送

对于外贸选品工具，AliExpress 是不可或缺的平台数据源。

### 1.2 目标
在 Spec 8 多平台基础设施上，接入 AliExpress 平台：
1. 实现热销产品榜单抓取
2. 实现关键词搜索抓取
3. 实现 AliExpress 专属利润计算模型
4. 支持多地区站点（美国、欧洲、俄罗斯）
5. 采用 Selenium + undetected-chromedriver 应对反爬

### 1.3 核心需求
1. **榜单抓取**：抓取 AliExpress Best Sellers / 热销页面
2. **关键词搜索**：根据用户输入关键词搜索 AliExpress 产品
3. **利润计算**：AliExpress 卖家费用模型（佣金 + 提现手续费 + 物流）
4. **地区站点**：美国站、欧洲站、俄罗斯站
5. **平台注册**：在 `PLATFORMS` 注册表中注册 AliExpress

---

## 2. 技术挑战与方案

### 2.1 反爬分析
AliExpress 采用多层反爬保护：
- **SPA 架构**：页面内容通过 JavaScript 动态渲染，requests 获取的 HTML 为空壳
- **Cloudflare 防护**：IP 频率限制 + JavaScript Challenge
- **动态加载**：产品列表通过 AJAX 请求加载，需要执行 JS 才能获取

### 2.2 技术方案
采用 **Selenium + undetected-chromedriver** 作为主要抓取方案：

```
抓取策略（三层降级）：
├── 第一层：Selenium + undetected-chromedriver（主要）
│   ├── 自动检测 Chrome 版本
│   ├── 模拟真实浏览器行为（滚动、等待）
│   └── 提取渲染后的产品数据
├── 第二层：requests + BeautifulSoup（快速尝试）
│   └── 部分页面可能直接返回数据
└── 第三层：本地缓存（兜底）
    └── 24 小时 TTL 的 JSON 缓存
```

### 2.3 依赖项
| 依赖 | 版本 | 用途 |
|------|------|------|
| selenium | >=4.0 | 浏览器自动化 |
| undetected-chromedriver | >=3.5 | 绕过反爬检测 |
| Chrome/Chromium | 浏览器 | Selenium 驱动目标 |

---

## 3. 系统设计

### 3.1 新建文件

| 文件 | 说明 |
|------|------|
| `src/scraper_aliexpress.py` | AliExpress 数据抓取模块 |

### 3.2 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `src/platforms.py` | **修改** | 注册 `aliexpress` 平台 |
| `src/calculator.py` | **修改** | 新增 `calculate_aliexpress_profit()` |
| `app.py` | **修改** | AliExpress 错误提示 |
| `.env.example` | **修改** | 新增 AliExpress 配置模板 |
| `tests/test_integration.py` | **修改** | 新增 AliExpress 测试用例 |

### 3.3 不改动的文件
- `src/selenium_helper.py` — 已有 Selenium 基础设施，直接复用
- `src/config.py` — 利润参数从 `PLATFORMS` 读取，无需改动
- `src/database.py` — 多平台支持已内置

---

## 4. 平台注册 — `src/platforms.py`

### 4.1 PLATFORMS 字典新增条目

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
        "us": {"name": "美国站", "domain": "aliexpress.com", "currency": "USD", "exchange_rate": 7.24},
        "eu": {"name": "欧洲站", "domain": "aliexpress.com", "currency": "EUR", "exchange_rate": 7.88},
        "ru": {"name": "俄罗斯站", "domain": "aliexpress.ru", "currency": "RUB", "exchange_rate": 0.079},
    },
    "default_region": "us",
    "profit_defaults": {
        "commission_pct": 0.08,      # 平台佣金 5-8%，取均值
        "withdrawal_fee_pct": 0.01,  # 提现手续费 1%
        "shipping_cny": 8.0,         # 国内物流（AliExpress 通常包邮）
        "packaging_cny": 2.0,        # 包装费用
    },
}
```

### 4.2 设计说明
- **佣金比例**：AliExpress 佣金按类目不同（5%-8%），取 8% 作为默认值
- **提现手续费**：从 AliExpress 提现到国内银行约 1%
- **物流费用**：AliExpress 卖家通常包邮，物流成本已含在售价中
- **地区差异**：欧洲站使用欧元，俄罗斯站使用卢布

---

## 5. 数据抓取 — `src/scraper_aliexpress.py`

### 5.1 模块结构

```
scraper_aliexpress.py
├── 缓存管理
│   ├── _load_cache(region) → Optional[list]
│   ├── _save_cache(products, region) → None
│   └── _get_cache_timestamp(region) → Optional[str]
├── Selenium 抓取
│   └── _scrape_via_selenium(url, wait_seconds) → BeautifulSoup
├── 产品解析
│   ├── _extract_title(card) → str
│   ├── _extract_price(card) → Optional[float]
│   ├── _extract_rating(card) → Optional[float]
│   ├── _extract_reviews(card) → int
│   ├── _extract_url(card) → str
│   ├── _extract_image(card) → str
│   └── _parse_product_card(card, rank) → Optional[dict]
├── 页面抓取
│   ├── _scrape_aliexpress_best_sellers(region) → list[dict]
│   └── _scrape_aliexpress_search(keyword, region, max_results) → list[dict]
└── 公开接口
    ├── fetch_aliexpress_best_sellers(region) → tuple[list[dict], dict]
    └── search_aliexpress(keyword, region, max_results) → dict
```

### 5.2 抓取策略

#### 5.2.1 热销榜单抓取

```python
def _scrape_aliexpress_best_sellers(region: str = "us") -> list[dict]:
    """
    抓取 AliExpress 热销产品。

    策略：
    1. 使用 Selenium 访问热销页面
    2. 等待页面加载（8-12 秒）
    3. 滚动页面触发懒加载
    4. 提取产品卡片数据
    5. 解析并返回标准产品字典

    URL 模式：
    - 美国站：https://www.aliexpress.com/popular/best-sellers.html
    - 欧洲站：https://www.aliexpress.com/popular/best-sellers.html
    - 俄罗斯站：https://www.aliexpress.ru/popular/best-sellers.html
    """
```

#### 5.2.2 关键词搜索

```python
def _scrape_aliexpress_search(keyword: str, region: str = "us", max_results: int = 20) -> list[dict]:
    """
    搜索 AliExpress 产品。

    URL 模式：
    - https://www.aliexpress.com/w/wholesale-{keyword}.html
    - 支持排序参数：SortType=total_orders（按销量）
    """
```

### 5.3 Selenium 配置

```python
def _create_aliexpress_driver():
    """
    创建针对 AliExpress 优化的 Chrome 实例。

    配置：
    - headless 模式（服务器环境）
    - 禁用自动化检测标志
    - 设置真实 User-Agent
    - 禁用图片加载（加速）
    - 页面加载超时 60 秒
    """
```

### 5.4 产品卡片选择器

AliExpress 页面结构可能变化，采用多层选择器兜底：

```python
_CARD_SELECTORS = [
    "div[class*='SearchProductFeed'] div[class*='item']",
    "div[class*='product-card']",
    "div[class*='item-card']",
    "a[href*='/item/']",
    "div[data-widget-cid]",
]

_TITLE_SELECTORS = [
    "h1[class*='title']",
    "div[class*='title']",
    "a[href*='/item/'] h1",
    "span[class*='title']",
]

_PRICE_SELECTORS = [
    "div[class*='price'] span",
    "span[class*='price-current']",
    "div[class*='Price'] span",
]
```

### 5.5 缓存策略

```python
_CACHE_DIR = "data/cache"
_CACHE_TTL = 24 * 60 * 60  # 24 小时

# 缓存文件命名
# aliexpress_best_sellers_{region}.json
# aliexpress_search_{keyword}_{region}.json
```

---

## 6. 利润计算 — `src/calculator.py`

### 6.1 AliExpress 利润模型

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

    费用结构：
    - 平台佣金：售价 × 5-8%（按类目）
    - 提现手续费：售价 × 1%
    - 物流成本：通常包含在售价中（包邮模式）
    - 包装成本：约 2 元/件

    公式：
        售价(USD) × 汇率 = 售价(CNY)
        佣金 = 售价(CNY) × commission_pct
        提现费 = 售价(CNY) × withdrawal_fee_pct
        总成本 = 采购成本 + 物流 + 包装 + 佣金 + 提现费
        净利 = 售价(CNY) - 总成本
        毛利率 = 净利 / 售价(CNY)
    """
```

### 6.2 费用参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `commission_pct` | 0.08 | 平台佣金（5-8%，取均值） |
| `withdrawal_fee_pct` | 0.01 | 提现手续费（约 1%） |
| `shipping_cny` | 8.0 | 国内物流（AliExpress 通常包邮） |
| `packaging_cny` | 2.0 | 包装费用 |

---

## 7. 配置更新 — `.env.example`

```env
# ============================================================
# AliExpress 平台配置
# ============================================================

# --- AliExpress 利润参数 ---
# ALIEXPRESS_COMMISSION_PCT=0.08
# ALIEXPRESS_WITHDRAWAL_FEE_PCT=0.01
# ALIEXPRESS_SHIPPING_CNY=8.0
# ALIEXPRESS_PACKAGING_CNY=2.0
```

---

## 8. 测试策略 — `tests/test_integration.py`

### 8.1 新增测试用例

```python
class TestProfitCalculators:
    # ... 现有测试 ...

    def test_aliexpress_profit_positive(self):
        """AliExpress: $15 售价应盈利。"""
        calc = get_calculator("aliexpress")
        defaults = PLATFORMS["aliexpress"]["profit_defaults"].copy()
        defaults["exchange_rate"] = 7.24
        result = calc(price=15.0, defaults=defaults, procurement_cny=5.0)
        assert result["margin_pct"] > 0
        assert result["is_profitable"] is True

class TestScraperImports:
    @pytest.mark.parametrize("platform_key,expected_func", [
        # ... 现有平台 ...
        ("aliexpress", "fetch_aliexpress_best_sellers"),
    ])
    def test_scraper_module_importable(self, platform_key, expected_func):
        # ...
```

### 8.2 参数化测试更新

更新 `EXPECTED_PLATFORMS` 列表：
```python
EXPECTED_PLATFORMS = ["amazon", "ebay", "aliexpress"]
```

---

## 9. 错误处理

### 9.1 抓取失败场景

| 场景 | 处理方式 |
|------|----------|
| Chrome 未安装 | 提示用户安装 Chrome |
| ChromeDriver 版本不匹配 | 自动检测版本并下载 |
| 页面加载超时 | 重试 3 次，间隔 5 秒 |
| 反爬拦截（CAPTCHA） | 降级到缓存，提示用户 |
| 产品数据为空 | 尝试备用 URL，最终降级 |

### 9.2 用户提示

```python
# app.py 中的错误提示
if platform == "aliexpress":
    st.info(
        "💡 AliExpress 抓取需要 Chrome 浏览器。\n\n"
        "**如果抓取失败：**\n"
        "1. 确保已安装 Chrome 浏览器\n"
        "2. 使用「📄 分析 JSON 数据」分析已有数据\n"
        "3. 使用「🎯 指定选品」通过 AI 搜索产品信息"
    )
```

---

## 10. 实施计划

### 阶段 1：基础框架
1. 删除 Walmart/Etsy 相关代码
2. 在 `platforms.py` 注册 AliExpress
3. 在 `calculator.py` 添加利润计算器

### 阶段 2：抓取器实现
1. 创建 `src/scraper_aliexpress.py`
2. 实现 Selenium 抓取逻辑
3. 实现产品解析器
4. 实现缓存机制

### 阶段 3：集成测试
1. 更新测试用例
2. 运行全平台测试
3. 验证抓取功能

### 阶段 4：文档更新
1. 更新 `.env.example`
2. 更新 Spec 文档状态

---

## 11. 验收标准

- [ ] `platforms.py` 中注册了 `aliexpress` 平台
- [ ] `calculator.py` 中有 `calculate_aliexpress_profit()` 函数
- [ ] `scraper_aliexpress.py` 实现了两层降级抓取
- [ ] 测试用例全部通过（32+ 项）
- [ ] 本地运行 `streamlit run app.py` 可选择 AliExpress 平台
- [ ] 利润计算结果正确（$15 售价，5 元采购成本应盈利）

---

## 12. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| AliExpress 反爬升级 | 抓取失败 | 三层降级 + 用户提示 |
| Chrome 版本不兼容 | Selenium 无法启动 | 自动检测版本 |
| 页面结构变化 | 解析失败 | 多层选择器兜底 |
| IP 被封禁 | 无法访问 | 缓存机制 + 合理延迟 |

---

## 13. 附录

### 13.1 AliExpress URL 模式

| 功能 | URL 模式 |
|------|----------|
| 热销榜单 | `https://www.aliexpress.com/popular/best-sellers.html` |
| 关键词搜索 | `https://www.aliexpress.com/w/wholesale-{keyword}.html` |
| 按销量排序 | `?SortType=total_orders` |

### 13.2 利润计算示例

```
产品售价：$15.00 USD
汇率：7.24
采购成本：¥5.00

计算：
售价(CNY) = $15.00 × 7.24 = ¥108.60
佣金 = ¥108.60 × 8% = ¥8.69
提现费 = ¥108.60 × 1% = ¥1.09
物流 = ¥8.00
包装 = ¥2.00
总成本 = ¥5.00 + ¥8.00 + ¥2.00 + ¥8.69 + ¥1.09 = ¥24.78
净利 = ¥108.60 - ¥24.78 = ¥83.82
毛利率 = 83.82 / 108.60 = 77.2%

结果：盈利 ¥83.82，毛利率 77.2% ✅
```
