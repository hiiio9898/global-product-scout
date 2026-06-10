# init-project — 初始化项目结构

## 触发条件
- 用户要求"初始化项目"、"搭建项目骨架"、"从零开始创建项目"
- 新仓库首次开发

## 工作流

### 1. 确认项目配置
- 读取 `AGENTS.md` 获取项目定位、技术栈和目录结构约定
- 确认用户需求：是否需要全部模块，或仅核心骨架

### 2. 创建目录结构
按 `AGENTS.md` 中定义的结构创建：
```
/
├── AGENTS.md
├── SKILL.md
├── .env.example
├── .gitignore
├── requirements.txt
├── packages.txt
├── runtime.txt
├── app.py
├── daily_scrape.py
├── src/
│   ├── __init__.py
│   ├── config.py
│   ├── platforms.py          # 平台注册表（PLATFORMS 字典）
│   ├── scrapling_adapter.py  # Scrapling 适配层
│   ├── scraper.py            # Amazon 爬虫
│   ├── scraper_ebay.py       # eBay 爬虫（每平台独立文件）
│   ├── scraper_alibaba.py    # Alibaba 爬虫
│   ├── scraper_search.py     # 关键词搜索
│   ├── scraper_1688.py       # 1688 比价
│   ├── analyzer.py           # AI 分析引擎
│   ├── calculator.py         # 利润计算器（工厂模式）
│   ├── database.py           # SQLite 数据库
│   ├── exchange_rate.py      # 实时汇率
│   ├── market_scanner.py     # 市场扫描引擎
│   ├── trends.py             # Google Trends
│   └── utils.py              # 工具函数
├── tests/
│   ├── __init__.py
│   ├── test_basic.py
│   └── test_integration.py
├── docs/
│   ├── CHANGELOG.md
│   ├── DEPLOY.md
│   └── specs/
├── data/
│   ├── products.json
│   └── cache/
├── .github/workflows/
├── .streamlit/
├── .claude/skills/
└── .devcontainer/
```

### 3. 生成核心文件
按以下顺序生成：
1. `.env.example` — 所有配置项及说明
2. `.gitignore` — Python 标准忽略 + `.env` + `.streamlit/secrets.toml`
3. `requirements.txt` — 依赖清单
4. `src/config.py` — 配置读取（st.secrets > .env 双源）
5. `src/platforms.py` — 平台注册表（PLATFORMS 字典）
6. `src/scrapling_adapter.py` — Scrapling 适配层（Fetcher→StealthyFetcher 降级）
7. `src/utils.py` — 工具函数（UA 池、反爬检测、价格解析、JSON 缓存）
8. `src/scraper.py` — Amazon 抓取模块（通过 scrapling_adapter）
9. `src/calculator.py` — 利润计算器（@register_calculator 装饰器工厂）
10. `src/analyzer.py` — AI 分析模块（OpenAI SDK 兼容，批量 6 个/批）
11. `src/database.py` — SQLite 数据库（幂等初始化 + ALTER TABLE 迁移）
12. `app.py` — Streamlit 主程序入口（5 个页面 + session_state 路由）
13. `daily_scrape.py` — 独立定时抓取脚本
14. `tests/test_basic.py` — 基础测试

### 4. 验证
- 每个文件创建后执行 `python -m py_compile <file>` 确认无语法错误
- 运行 `pytest tests/` 确认测试通过
- 提示用户复制 `.env.example` 为 `.env` 并填入 API Key

### 5. 交付说明
告知用户：
- 创建了哪些文件
- 下一步需要做什么（配置 `.env`、运行 `streamlit run app.py`）
- 可能的风险点

## 注意事项
- 所有代码注释使用中文，变量名/函数名使用英文
- 优先使用 mock 数据，确保离线可运行
- 不执行 `git commit` 等远端操作
