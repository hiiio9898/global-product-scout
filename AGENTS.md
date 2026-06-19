# AGENTS.md

本文件是「外贸 AI 选品工具」的 AI 协作规则唯一真源。

## 1. 项目定位
- 项目名称：Global Product Scout（全球产品侦察兵）
- 目标用户：跨境电商卖家、外贸创业者
- 核心功能：自动抓取多平台（Amazon、eBay、AliExpress、TikTok Shop）热销产品数据，通过多模型 AI 分析产品潜力，提供选品建议。
- 技术栈：Python 3.12、Streamlit（前端）、OpenAI SDK 兼容 API（多模型 AI 分析）、Scrapling（自适应抓取引擎）

## 2. 硬规则
- 不执行 `git commit`、`git push` 或任何远端操作，除非用户明确要求。
- 所有秘钥、API Key 必须通过 `.env` 文件加载，且 `.env` 不提交到 Git。
- 代码注释和文档使用中文，变量名、函数名使用英文。
- 新增功能必须同步更新 `.env.example` 文件。
- 抓取数据需遵守目标网站 robots.txt，并设置合理延迟，避免被封。
- AI 分析调用必须包含超时、重试和错误提示逻辑（支持任意 OpenAI SDK 兼容供应商）。
- 不做与当前任务无关的重构或"顺手优化"。
- **内容展示禁止截断**：所有面向用户展示的文本必须完整可见。详见 `docs/specs/0-content-display-rule.md`。允许的例外：expander 标题（`[:40]` + `help=`）、selectbox 选项（`[:50]` + `help=`）、API 参数（`[:30]`）。DataFrame 用 `column_config` 控制宽度，不用字符串截断。

## 3. 目录结构
```
/
├── AGENTS.md               # AI 协作规则（本文件）
├── SKILL.md                # 技能系统说明
├── .env.example            # 环境变量模板（推 GitHub）
├── .gitignore              # Git 忽略规则
├── requirements.txt        # Python 依赖
├── packages.txt            # 系统级依赖（Streamlit Cloud 用）
├── app.py                  # Streamlit 主程序入口
├── daily_scrape.py         # 每日定时抓取脚本（独立于 Streamlit）
├── .claude/skills/         # AI 协作技能
├── .github/workflows/      # GitHub Actions 工作流
├── .streamlit/             # Streamlit Cloud 配置（secrets.toml 不提交）
├── src/
│   ├── __init__.py
│   ├── config.py           # 配置加载（st.secrets + .env 双源）
│   ├── platforms.py        # 平台注册表（PLATFORMS 字典）
│   ├── scrapling_adapter.py # Scrapling 适配层（统一抓取接口）
│   ├── scraper.py          # Amazon Best Sellers 抓取
│   ├── scraper_search.py   # Amazon 关键词搜索
│   ├── scraper_ebay.py     # eBay 抓取
│   ├── scraper_aliexpress.py  # 速卖通抓取
│   ├── scraper_tiktok.py   # TikTok Shop 抓取（东南亚 5 站）
│   ├── scraper_1688.py     # 1688 比价（AI 估算 + 真实抓取）
│   ├── analyzer.py         # AI 分析模块（五维度评估 + 品类报告）
│   ├── calculator.py       # 利润计算器（工厂模式，多平台）
│   ├── trends.py           # Google Trends 趋势查询
│   ├── database.py         # SQLite 数据库模块
│   ├── market_scanner.py   # 市场扫描引擎（蓝海指数、趋势预测）
│   └── utils.py            # 工具函数
├── tests/
│   └── test_basic.py
├── docs/
│   ├── CHANGELOG.md
│   ├── DEPLOY.md           # 部署备忘录
│   └── specs/              # 功能规格文档（17 份）
└── data/                   # 本地数据（不提交）
    ├── cache/
    └── products.db
```

## 4. 常用命令
- 安装依赖：`pip install -r requirements.txt`
- 运行应用：`streamlit run app.py`
- 运行测试：`pytest tests/`
- 运行每日抓取：`python daily_scrape.py`
- 代码风格检查：`flake8 src/`

## 5. 数据更新工作流（本地 + 云端）
### 5.1 本地数据更新
```bash
# 每周运行一次抓取脚本
python daily_scrape.py

# 输出：
# 1. 抓取 Amazon Best Sellers 首页榜单（约 36 个产品）
# 2. 保存到 SQLite 数据库（data/products.db）
# 3. 导出 products.json（data/products.json，可提交到 Git）
# 4. 导出 cache.json（data/cache.json，本地缓存）
```

### 5.2 提交到 GitHub
```bash
git add data/products.json
git commit -m "Update product data"
git push
```

### 5.3 云端自动更新
- Streamlit Cloud 监测到新推送 → 自动重新部署
- 用户打开应用 → 看到最新抓取的真实产品 + AI 分析
- 数据来源显示：`数据来源：JSON 文件 | 抓取时间：YYYY-MM-DD HH:MM:SS`

## 5. 开发工作流
1. 接到需求后，先阅读 AGENTS.md 和 SKILL.md，了解当前项目结构。
2. 识别改动范围（数据抓取 / 分析 / 前端界面 / 配置）。
3. 优先采用模拟数据（mock）进行开发和测试，避免依赖网络和真实 API。
4. 修改 `.env.example` 同步新增的配置项。
5. 交付时说明：改了什么、为什么、验证截图/日志、风险点（如网站反爬）。

## 6. 验证要求
- Streamlit 应用必须能启动且无 import 错误。
- 测试用例可使用模拟数据，无需真实调用 DeepSeek 或网络请求。
- 所有 python 文件可通过 `python -m py_compile` 编译检查。
- 如使用异步或协程，确保与 Streamlit 兼容（Streamlit 默认同步）。

## 7. 数据源与合规
- 示例数据源：Amazon Best Sellers、eBay Trending、AliExpress、TikTok Shop
- 抓取引擎：Scrapling（Fetcher + StealthyFetcher 自动降级）
- 抓取策略：每个平台每天最多一次，设置合理延迟避免被封。
- 必须设置 User-Agent 和 Request 间延迟（1-2 秒）。
- 如果网站结构变动导致抓取失败，应向用户提示，并降级为展示旧数据或示例数据。

## 8. AI 多模型集成
- 使用 OpenAI SDK 兼容模式，支持任意供应商（DeepSeek、MiMo、OpenAI 等）
- 通过 `.env` 中的 `ACTIVATE_PROVIDER` + `ACTIVATE_MODEL` 切换供应商和模型
- 侧边栏提供 UI 切换器，用户可在界面上实时切换模型
- 每个供应商独立配置 `API_KEY` + `BASE_URL`（见 `.env.example`）
- 默认供应商：小米 MiMo（mimo-v2.5 / mimo-v2.5-pro）
- 分析 Prompt 模板内嵌在 `src/analyzer.py` 的 `SYSTEM_PROMPT` 和 `BATCH_SYSTEM_PROMPT`
- 批量分析策略：每批 6 个产品，拼接为一次 API 调用
- 分析任务需长时间执行时，Streamlit 中应显示进度条

## 9. Git 推送规范

### ✅ 必须推送的文件
| 类别 | 文件示例 | 说明 |
|------|----------|------|
| 源码 | `app.py`, `src/*.py`, `daily_scrape.py` | 所有 Python 源代码 |
| 测试 | `tests/*.py` | 单元测试 |
| 配置模板 | `.env.example` | **不含真实 Key**，仅模板 |
| 依赖声明 | `requirements.txt`, `packages.txt` | 不含版本锁死 |
| 规则文件 | `AGENTS.md`, `SKILL.md`, `.gitignore` | 项目协作规范 |
| 技能 | `.claude/skills/*.md` | AI 协作技能定义 |
| CI/CD | `.github/workflows/*.yml` | GitHub Actions 工作流 |
| 文档 | `docs/*.md` | CHANGELOG、部署说明等 |
| 数据 | `data/products.json` | **最新抓取数据，供 Streamlit Cloud 使用** |

### ❌ 严禁推送的文件
| 类别 | 文件示例 | 原因 |
|------|----------|------|
| 密钥 | `.env` | 含 API Key，已 `.gitignore` |
| 密钥 | `.streamlit/secrets.toml` | 含 API Key，已 `.gitignore` |
| 虚拟环境 | `.venv/`, `venv/` | 体积大、平台相关 |
| 缓存 | `__pycache__/`, `*.pyc` | 编译产物 |
| 数据 | `data/cache/*`, `data/products.db` | 本地抓取缓存和历史数据库 |
| IDE | `.vscode/`, `.idea/` | 个人编辑器配置 |
| 系统 | `.DS_Store`, `Thumbs.db` | 操作系统自动生成 |
| 抓取源码 | `Scrapling-main/` | 本地 editable 安装，不提交 |

### 🔐 密钥管理原则
1. 所有密钥 **只存在于**：本地 `.env`、Streamlit Cloud Secrets、GitHub Actions Secrets
2. `.env.example` 是模板文件，**可以推送**（值写 `your_api_key_here`）
3. 新增密钥时：更新 `.env.example`（模板）→ 更新 `src/config.py`（代码）→ 更新本文档
4. 部署到 Streamlit Cloud / GitHub Actions 前，参考 `docs/DEPLOY.md`
