# 变更日志

## [v0.4.0] - 2026-06-01 — Scrapling 抓取引擎集成
- **重大升级**：抓取层从 requests+BeautifulSoup 迁移到 Scrapling 自适应引擎
- 新增：`src/scrapling_adapter.py` 统一抓取适配层（Fetcher→StealthyFetcher 自动降级）
- 新增：Scrapling 配置（`get_scrapling_config()`、`.env.example` SCRAPLING_* 配置项）
- 改写：所有 scraper 模块使用 Scrapling API（`.css()` / `.text` / `.attrib`）
- 改写：`scraper_1688.py` 新增 StealthyFetcher 真实浏览器抓取（AI 估算兜底）
- 移除：`src/selenium_helper.py`（被 StealthyFetcher 替代）
- 移除：`requirements.txt` 中的 requests、beautifulsoup4、selenium、webdriver-manager
- 新增：`requirements.txt` 添加 scrapling[all]、curl_cffi、patchright、playwright、browserforge
- 更新：`src/platforms.py` 新增 `scrape_mode` 字段

## [v0.3.0] - 2026-06-01 — 多平台扩展 + 平台替换
- 新功能：**多平台架构** — 平台注册表模式（`src/platforms.py` PLATFORMS 字典）
- 新功能：**利润计算器工厂模式** — `@register_calculator` 装饰器注册，`get_calculator()` 获取
- 新功能：`src/platforms.py` 平台注册表模块
- 新功能：`src/scraper_ebay.py` eBay 抓取器（Trending + 搜索）
- 新功能：`src/scraper_alibaba.py` 阿里巴巴国际站抓取器（B2B 批发）
- 新功能：eBay 利润计算器（成交费 13.25% + 刊登费 + Payoneer）
- 新功能：Alibaba 利润计算器（佣金 5% + 信保 2%）
- 新功能：历史记录页多平台筛选 + 跨平台对比 Tab
- 新功能：数据库 Schema 新增 platform/region/currency 列
- 新功能：`query_products()` 多条件查询、`get_platform_summary()` 平台统计
- 新功能：`tests/test_integration.py` 全平台集成测试（28 项）
- 移除：AliExpress（需登录，无法抓取）、Shopee（API 403 + CAPTCHA）、Walmart、Etsy
- 修复：ChromeDriver 版本不匹配问题（改用 webdriver-manager，后被 Scrapling 替代）
- 修复：`app.py` BOM 字符导致 Streamlit 导入错误
- 修复：`from __future__ import annotations` 修复 Python 版本兼容性
- 版本：`v0.2.0` → `v0.3.0`

## [v0.2.0] - 2026-05-29 — 指定选品 + 基础功能完善
- 新功能：**指定选品**（关键词搜索分析）— 用户输入关键词搜索 Amazon，生成品类综合报告 + Top 3 推荐 + 1688 比价 + 利润试算
- 新功能：`src/scraper_search.py` Amazon 关键词搜索抓取模块
- 新功能：`src/analyzer.py` 新增 `analyze_category_report()` 品类综合分析
- 新功能：项目初始化，搭建外贸选品工具原型
- 新功能：实现 Amazon Best Sellers 真实抓取，三层降级策略
- 新功能：五维度量化分析体系
- 新功能：SQLite 数据持久化，支持历史记录查询、多条件筛选、CSV 导出
- 新功能：页面导航（实时选品 / 历史记录）
- 新功能：`daily_scrape.py` 独立定时抓取脚本 + GitHub Actions 每日自动运行
- 新功能：`streamlit.secrets` 双源配置加载
- 新功能：JSON 数据源支持 + Streamlit Cloud 数据更新工作流
- 优化：批量 AI 分析（分组 6 个/批，速度从 ~55 分钟降至 ~2 分钟）
- 修复：价格货币换算、全局排名、非实体商品过滤、价格选择器
- 版本：`v0.1.0` → `v0.2.0`

## [v0.1.0] - 2026-05-27 — 初始版本
- 项目初始化，基础框架搭建
