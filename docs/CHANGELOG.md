# 变更日志

## [Unreleased]
- 新功能：项目初始化，搭建外贸选品工具原型，包含模拟数据抓取与 DeepSeek 分析。
- 新功能：实现 Amazon Best Sellers 真实抓取（requests+BeautifulSoup），三层降级策略。
- 新功能：五维度量化分析体系（市场容量/竞争程度/利润潜力/新手友好度/季节性风险）。
- 新功能：SQLite 数据持久化，分析结果自动保存，支持历史记录查询、多条件筛选、CSV 导出。
- 新功能：页面导航（实时选品 / 历史记录），侧边栏显示数据库记录数。
- 新功能：`daily_scrape.py` 独立定时抓取脚本 + GitHub Actions 每日自动运行。
- 新功能：`streamlit.secrets` 双源配置加载（本地 `.env` + 云端 Secrets）。
- 新功能：**JSON 数据源支持**（database.py 新增 `get_latest_products()`，daily_scrape.py 导出 products.json）
- 新功能：**Streamlit Cloud 数据更新工作流**（本地抓取 → 提交 JSON → 云端自动部署）
- 优化：**两级数据策略**（JSON → 实时抓取，去掉缓存/模拟降级）
- 优化：**批量 AI 分析**（分组 6 个/批调用 DeepSeek，速度从 ~55 分钟降至 ~2 分钟，附带进度条）
- 优化：**侧边栏数据源即时显示**（加载后立即 rerun，不再等分析完成）
- 优化：**分析按钮 disabled**（分析期间不可重复点击）
- 修复：**价格货币换算**（HKD/SGD/CNY 自动转为 USD，修正 HKD 显示为均价问题）
- 修复：**全局排名**（去掉类目内 badge 排名，使用全局序号 1-36）
- 修复：**非实体商品过滤**（跳过 subscription/plan/digital code 等订阅类产品）
- 修复：**价格选择器**（去掉不可靠的正则兜底，只信任 CSS 选择器）
- 修复：**Cloud 端历史记录**（session state 后备，Cloud 上仍可查看当前会话历史）
- 文档：新增 `docs/DEPLOY.md` 部署备忘录，`AGENTS.md` Git 推送规范和数据更新工作流。
- 文档：新增 `docs/ISSUES.md` 问题跟踪清单。
- 修复：`.gitignore` 允许 `data/products.json` 提交。
- 版本：`v0.1.0` → `v0.2.0`
