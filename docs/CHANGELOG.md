# 变更日志

## [v0.6.0] - 2026-06-02 — UX 体验优化（Spec 16）
- 新功能：**产品收藏/标记** — favorites 表 + CRUD 方法 + 实时/指定选品页 ⭐ 按钮 + 已收藏 Tab
- 新功能：**五维度雷达图** — Plotly 雷达图，每个分析卡片内直观展示产品优劣
- 新功能：**产品对比功能** — 历史记录页多选行 → 并排对比表格（最多 5 个产品）
- 新功能：**历史记录分页** — >50 条时自动分页（每页 50 条）
- 新功能：**分析结果速览表** — 实时选品 + 指定选品页，分析完成后展示紧凑汇总表
- 新功能：**数据过期提醒** — Dashboard 根据抓取时间显示 ok/warn/error 状态（3天/7天阈值）
- 新功能：**1688 比价结果持久化** — 存入 session_state，切换页面后自动恢复
- 新功能：**批量设置采购成本** — 实时选品页新增「批量设置采购成本」expander
- 新功能：**搜索结果排序** — 指定选品页新增排序选择器（价格/评分/评论数）
- 新功能：**Dashboard 平台筛选** — 多平台数据时显示筛选 multiselect
- 新功能：**跨平台对比空状态** — 仅一个平台数据时显示引导提示
- 新增：`src/database.py` 新增 favorites 表 + `add_favorite`/`remove_favorite`/`is_favorite`/`get_favorites` 方法
- 新增：`requirements.txt` 添加 `plotly>=5.0.0`
- 更新：`docs/specs/16-ux-optimization.md` UX 改进规格文档
- 版本：`v0.5.0` → `v0.6.0`

## [v0.5.0] - 2026-06-02 — UI 审查修复 + AI 解析增强
- 修复：指定选品页标题从英文恢复为中文
- 修复：Streamlit 1.57.0 弃用 `use_container_width` → `width="stretch"`（13 处）
- 修复：6 处 expander/selectbox 截断添加 `help=` 参数（Spec 0 合规）
- 修复：指定选品页改为动态平台加载（不再硬编码 `search_amazon()`）
- 修复：数据来源提示改为动态平台名
- 修复：侧边栏利润参数多平台适配（广告预算仅 Amazon 显示）
- 修复：佣金/运费标签新增 eBay/Alibaba 专属文案
- 修复：版本号统一为 `APP_VERSION` 常量（v0.5.0）
- 修复：提取 `VERDICT_LABEL_MAP` 和 `ANALYSIS_DIMS` 模块级常量
- 修复：历史记录地区筛选器添加实际过滤逻辑
- 增强：AI 解析异常时保留原始响应文本，增加诊断信息
- 更新：`docs/specs/0-content-display-rule.md` 新增多平台 UI 规范
- 版本：`v0.4.0` → `v0.5.0`

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
