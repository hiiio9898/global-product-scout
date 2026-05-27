# 变更日志

## [Unreleased]
- 新功能：项目初始化，搭建外贸选品工具原型，包含模拟数据抓取与 DeepSeek 分析。
- 新功能：实现 Amazon Best Sellers 真实抓取（requests+BeautifulSoup），三层降级策略。
- 新功能：五维度量化分析体系（市场容量/竞争程度/利润潜力/新手友好度/季节性风险）。
- 新功能：SQLite 数据持久化，分析结果自动保存，支持历史记录查询、多条件筛选、CSV 导出。
- 新功能：页面导航（实时选品 / 历史记录），侧边栏显示数据库记录数。
- 新功能：`daily_scrape.py` 独立定时抓取脚本 + GitHub Actions 每日自动运行。
- 新功能：`streamlit.secrets` 双源配置加载（本地 `.env` + 云端 Secrets）。
- 新功能：**新增 JSON 数据源支持**（database.py 新增 `get_latest_products()`，daily_scrape.py 导出 products.json，app.py 实现四层降级策略：JSON → live → cache → mock）
- 新功能：**Streamlit Cloud 数据更新工作流**（本地抓取 → 提交 JSON → 云端自动部署，无需数据库文件）
- 文档：新增 `docs/DEPLOY.md` 部署备忘录，`AGENTS.md` Git 推送规范和数据更新工作流。
- 修复：`.gitignore` 允许 `data/products.json` 提交，继续忽略 `data/products.db` 和 `data/cache.json`。
