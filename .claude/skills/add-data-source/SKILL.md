# add-data-source — 新增数据源平台

## 触发条件
- 用户要求"新增抓取源"、"添加速卖通"、"支持 Shopee"、"接入 Temu"等
- 需要接入新的电商平台数据

## 工作流

### 1. 需求确认
- 确认目标平台名称（如 AliExpress、Shopee、Temu 等）
- 确认目标页面类型（Best Sellers、新品榜、搜索结果等）
- 确认目标站点区域（如 `aliexpress.com` vs `aliexpress.us`）
- 确认平台货币和默认汇率

### 2. 调研目标网站
- 访问目标网站，分析页面结构（产品列表容器、标题/价格/评分选择器）
- 检查 `robots.txt` 确认抓取合规性
- 记录请求头要求、反爬策略（如是否需要 Cookie、是否动态加载）
- 确定抓取策略：`fetcher_first`（一般站点）或 `stealth_only`（强反爬站点）

### 3. 实现爬虫模块
创建独立文件 `src/scraper_<platform>.py`（**不是**塞进 `src/scraper.py`）：
```python
"""
<平台名> 数据抓取模块。

两层数据获取策略：
    1. 实时抓取 — 通过 scrapling_adapter 抓取
    2. 本地缓存 — 抓取失败时复用上次结果
"""
from .scrapling_adapter import fetch_page
from .utils import is_blocked, parse_price, parse_rating, load_json_cache, save_json_cache

def fetch_<platform>_best_sellers(region: str = "us", max_products: int = 30) -> tuple[list[dict], dict]:
    """抓取 <平台名> 热销产品。返回 (产品列表, 元信息)。"""
    # 1. 尝试实时抓取
    # 2. 失败时降级到本地缓存
    ...

def search_<platform>(keyword: str, region: str = "us", max_products: int = 20) -> tuple[list[dict], dict]:
    """关键词搜索产品。"""
    ...
```

**关键规则：**
- 使用 `from .scrapling_adapter import fetch_page` 统一抓取接口
- 产品数据返回 `list[dict]`，**无** `Product` dataclass
- 必须包含缓存降级（`load_json_cache` / `save_json_cache`）
- 每个字段单独 `try/except`，避免一个字段失败导致整条记录丢失
- 如需反爬较强的站点，在 `fetch_page()` 调用时传 `stealth=True`

### 4. 注册平台到 platforms.py
在 `src/platforms.py` 的 `PLATFORMS` 字典中新增条目：
```python
"<platform>": {
    "name": "<平台显示名>",
    "icon": "🟢",                              # emoji 图标
    "scraper_module": "src.scraper_<platform>", # 爬虫模块路径
    "scraper_func": "fetch_<platform>_best_sellers",  # 爬取函数名
    "search_module": "src.scraper_<platform>",  # 搜索模块（可同上）
    "search_func": "search_<platform>",         # 搜索函数名
    "calculator": "calculate_<platform>_profit", # 利润计算器函数名
    "scrape_mode": "fetcher_first",             # 或 "stealth_only"
    "currency": "USD",                          # 平台主货币
    "regions": {
        "us": {"name": "美国站", "domain": "<domain>", "currency": "USD", "exchange_rate": 7.24},
        # ... 更多区域
    },
    "default_region": "us",
    "profit_defaults": {
        "commission_pct": 0.15,    # 平台佣金比例
        "shipping_cny": 20.0,     # 默认头程运费(元)
        # ... 平台特有费用参数
    },
},
```

### 5. 实现利润计算器
在 `src/calculator.py` 中新增（参考 `add-platform-calculator` skill）：
```python
@register_calculator("<platform>")
def calculate_<platform>_profit(price, defaults, procurement_cny=0.0, **kwargs) -> dict:
    ...
```

### 6. 更新 daily_scrape.py
无需手动修改 — `daily_scrape.py` 通过 `PLATFORMS` 字典动态加载爬虫模块（`importlib.import_module`），新增平台自动生效。

### 7. 更新前端
无需手动修改 — `app.py` 通过 `get_platform_choices()` 从 `PLATFORMS` 动态生成平台选择器，新增平台自动出现在侧边栏。

### 8. 测试与验证
```bash
# 语法检查
python -m py_compile src/scraper_<platform>.py
python -m py_compile src/platforms.py
python -m py_compile src/calculator.py

# 运行测试
pytest tests/

# 手动验证爬取
python daily_scrape.py --platforms <platform>

# 验证 Streamlit 界面
streamlit run app.py
```

### 9. 交付说明
告知用户：
- 新增了哪些文件、修改了哪些函数
- 新增的 `PLATFORMS` 配置条目内容
- 目标网站的反爬风险（如频率限制、验证码）
- 利润计算的费用结构

## 注意事项
- 爬虫必须包含缓存降级方案（`load_json_cache` / `save_json_cache`）
- 遵守目标网站 `robots.txt`
- 不修改与当前任务无关的现有代码
- 产品字段使用 `dict`，不要创建 dataclass
- 抓取函数签名统一为 `fetch_<platform>_best_sellers(region, max_products) -> tuple[list[dict], dict]`
