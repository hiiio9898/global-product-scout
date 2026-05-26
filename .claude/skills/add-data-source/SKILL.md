# add-data-source — 新增数据源

## 触发条件
- 用户要求"新增抓取源"、"添加速卖通"、"支持 Shopee"等
- 需要接入新的电商平台数据

## 工作流

### 1. 需求确认
- 确认目标平台名称（如 AliExpress、Shopee、eBay、Temu 等）
- 确认目标页面类型（Best Sellers、新品榜、搜索结果等）
- 确认目标站点区域（如 `aliexpress.com` vs `aliexpress.us`）

### 2. 调研目标网站
- 访问目标网站，分析页面结构（产品列表容器、标题/价格/评分选择器）
- 检查 `robots.txt` 确认抓取合规性
- 记录请求头要求、反爬策略（如是否需要 Cookie、是否动态加载）
- 如页面为 JavaScript 动态渲染，评估是否需要 Selenium/Playwright

### 3. 实现抓取模块
在 `src/scraper.py` 中新增：
```python
def scrape_<platform>_best_sellers(url: str, max_products: int = 20, use_mock: bool = False) -> list[Product]:
    """抓取 <平台名> Best Sellers 产品列表"""
    ...
```
- 复用现有 `Product` 数据类
- 新增对应的 `MOCK_<PLATFORM>_PRODUCTS` mock 数据（至少 5 条）
- 设置合理的请求延迟（1-2 秒）和 User-Agent

### 4. 更新配置
- 在 `.env.example` 中新增平台相关配置项：
  - `<PLATFORM>_SITE`：站点域名
  - `<PLATFORM>_BEST_SELLERS_URL`：榜单 URL
- 在 `src/config.py` 中新增对应属性

### 5. 更新前端
- 在 `app.py` 的 `st.sidebar` 站点选择器中新增平台选项
- 根据选择调用对应的抓取函数

### 6. 测试与验证
- 使用 mock 数据运行测试
- 确认 `python -m py_compile src/scraper.py` 通过
- 确认 Streamlit 界面可正常切换数据源并展示数据

### 7. 交付说明
告知用户：
- 新增了哪些文件/修改了哪些函数
- 新增的 `.env` 配置项
- 目标网站的反爬风险（如频率限制、验证码）
- 如需真实抓取，建议的代理方案

## 注意事项
- 抓取逻辑必须包含 mock 降级方案
- 遵守目标网站 `robots.txt`
- 不修改与当前任务无关的现有代码
