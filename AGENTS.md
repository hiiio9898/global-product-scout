# AGENTS.md

本文件是「外贸 AI 选品工具」的 AI 协作规则唯一真源。

## 1. 项目定位
- 项目名称：Global Product Scout（全球产品侦察兵）
- 目标用户：跨境电商卖家、外贸创业者
- 核心功能：自动抓取多平台（亚马逊、速卖通等）热销/飙升产品数据，通过 DeepSeek 大模型分析产品潜力，提供选品建议。
- 技术栈：Python 3.10+、Streamlit（前端）、DeepSeek API（AI 分析）、Requests/BeautifulSoup（数据抓取）

## 2. 硬规则
- 不执行 `git commit`、`git push` 或任何远端操作，除非用户明确要求。
- 所有秘钥、API Key 必须通过 `.env` 文件加载，且 `.env` 不提交到 Git。
- 代码注释和文档使用中文，变量名、函数名使用英文。
- 新增功能必须同步更新 `.env.example` 文件。
- 抓取数据需遵守目标网站 robots.txt，并设置合理延迟，避免被封。
- DeepSeek 调用必须包含超时、重试和错误提示逻辑。
- 不做与当前任务无关的重构或"顺手优化"。

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
│   ├── scraper.py          # 数据抓取模块
│   ├── analyzer.py         # DeepSeek 分析模块
│   ├── database.py         # SQLite 数据库模块
│   └── utils.py            # 工具函数
├── tests/
│   └── test_basic.py
├── docs/
│   ├── CHANGELOG.md
│   └── DEPLOY.md           # 部署备忘录
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
- 示例数据源：Amazon Best Sellers（https://www.amazon.com/Best-Sellers/zgbs/）
- 抓取策略：只抓取首页榜单，每天最多一次。用户可在界面选择站点（需后续扩展）。
- 必须设置 User-Agent 和 Request 间延迟（1-2 秒）。
- 如果网站结构变动导致抓取失败，应向用户提示，并降级为展示旧数据或示例数据。

## 8. DeepSeek 集成
- 使用 OpenAI SDK 兼容模式调用 DeepSeek（base_url="https://api.deepseek.com"）
- 默认模型：deepseek-v4-flash/deepseek-v4-pro（后续要具备兼容更多模型能力）
- 分析 Prompt 模板存放在 `src/prompts.py` 中（后续添加），现在可内嵌在 analyzer.py 内。
- 分析任务需异步或长时间执行时，Streamlit 中应显示进度条。

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

### 🔐 密钥管理原则
1. 所有密钥 **只存在于**：本地 `.env`、Streamlit Cloud Secrets、GitHub Actions Secrets
2. `.env.example` 是模板文件，**可以推送**（值写 `your_api_key_here`）
3. 新增密钥时：更新 `.env.example`（模板）→ 更新 `src/config.py`（代码）→ 更新本文档
4. 部署到 Streamlit Cloud / GitHub Actions 前，参考 `docs/DEPLOY.md`
