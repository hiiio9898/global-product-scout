# SKILL.md

本项目使用 `.claude/skills/` 存放 AI 协作技能，同时通过 `skills-lock.json` 安装了外部通用技能包。

---

## 技能清单

### 📦 项目专属技能 (`.claude/skills/`)

| 技能 | 触发场景 | 简介 |
|------|----------|------|
| **init-project** | 初始化项目、搭建骨架 | 创建完整目录结构、核心文件、配置模板，含mock数据确保离线可运行 |
| **add-data-source** | 新增抓取源（如速卖通、Shopee） | 调研网站 → 创建独立爬虫文件 → 注册PLATFORMS → 实现利润计算器 → 测试 |
| **add-analysis-type** | 新增分析维度（如利润计算、竞争度打分） | 设计数据结构 → 更新AI Prompt → 前端展示 → 测试，确保向后兼容 |
| **add-platform-calculator** | 新增平台利润计算器 | @register_calculator装饰器 → 标准返回dict → platforms.py参数配置 |
| **add-streamlit-page** | 新增Streamlit页面 | 创建_render函数 → 侧边栏radio选项 → 底部路由elif → session_state |
| **migrate-database** | 数据库Schema迁移 | ALTER TABLE ADD COLUMN + try/except → CREATE TABLE → CREATE INDEX |
| **fix-scraper** | 网站改版导致抓取失效 | 查platforms.py定位文件 → 分析变更 → 更新选择器 → 增强容错 |

### 🌐 外部通用技能 (`skills-lock.json`)

| 技能 | 来源 | 用途 |
|------|------|------|
| **claude-skill** | myysophia/codex-config | Claude Code 技能开发参考 |
| **code-documentation** | skillcreatorai/Ai-Agent-Skills | 代码文档自动生成 |
| **codex-review** | alinaqi/claude-bootstrap | 代码审查规范 |
| **database-design** | skillcreatorai/Ai-Agent-Skills | 数据库设计指导 |
| **doc-coauthoring** | anthropics/skills | 文档协作撰写 |
| **docx** | anthropics/skills | Word文档处理 |
| **find-skills** | vercel-labs/skills | 搜索发现新技能 |
| **frontend-code-review** | langgenius/dify | 前端代码审查 |
| **frontend-design** | anthropics/skills | 前端设计指导 |
| **karpathy-guidelines** | multica-ai/andrej-karpathy-skills | Andrej Karpathy 编程规范 |
| **pdf** | anthropics/skills | PDF文档处理 |
| **python-skills** | llama-farm/llamafarm | Python开发最佳实践 |
| **skill-creator** | anthropics/skills | 创建新技能模板 |
| **ui-ux-pro-max** | likaia/nginxpulse | UI/UX设计指导 |
| **web-design-guidelines** | vercel-labs/agent-skills | Web设计规范 |
| **xlsx** | anthropics/skills | Excel文档处理 |

---

每个技能文件夹内包含 `SKILL.md` 详细工作流。

---

## 领域知识库

以下为本项目积累的通用技术知识，供各技能参考。

### 项目架构概览

```
app.py              Streamlit 主程序入口（侧边栏 + 页面路由 + Session State）
├── render_sidebar()           侧边栏：平台/地区选择、AI 模型、利润参数
├── _render_dashboard_page()   Dashboard：数据概览 + TOP5 推荐
├── _render_live_page()        实时选品页：数据加载 → AI 分析 → 展示结果
├── _render_targeted_page()    指定选品页：关键词搜索 → 品类报告
└── _render_history_page()     历史记录页：多平台筛选、趋势、跨平台对比

src/config.py           配置加载（st.secrets > .env 双源）
src/platforms.py        平台注册表（PLATFORMS 字典 + 工具函数）
src/scrapling_adapter.py Scrapling 适配层（Fetcher→StealthyFetcher 自动降级）
src/scraper.py          Amazon Best Sellers 抓取（Scrapling）
src/scraper_search.py   Amazon 关键词搜索（Scrapling）
src/scraper_ebay.py     eBay 抓取（Scrapling）
src/scraper_alibaba.py  阿里巴巴国际站抓取（Scrapling StealthyFetcher）
src/scraper_1688.py     1688 比价（StealthyFetcher 真实抓取 + AI 估算兜底）
src/analyzer.py         AI 分析引擎（OpenAI SDK 兼容，批量分组 6 个/批）
src/calculator.py       利润计算器（工厂模式，3 个平台）
src/database.py         SQLite 数据库（多平台 Schema + 收藏表 + 市场扫描表）
src/exchange_rate.py    实时汇率模块（open.er-api.com + 24h缓存）
src/market_scanner.py   市场扫描引擎（蓝海指数、趋势预测、跨平台对比）
src/trends.py           Google Trends 趋势查询
src/utils.py            工具函数（UA 池、反爬检测、价格解析）
daily_scrape.py         独立定时抓取脚本（CLI 运行，多平台支持 --platforms 参数）
```

### 多模型 AI 分析架构

当前支持通过 OpenAI SDK 兼容模式调用任意 LLM 供应商（DeepSeek、MiMo、OpenAI 等）。

**配置方式**（`.env.example` + `src/config.py`）：
```bash
# 激活哪个供应商和模型
ACTIVATE_PROVIDER=mimo             # deepseek / mimo / openai
ACTIVATE_MODEL=mimo-v2.5           # 对应供应商下的具体模型名

# 各供应商独立配置
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_BASE_URL=https://api.deepseek.com

MIMO_API_KEY=sk-xxx
MIMO_BASE_URL=https://api.xiaomimimo.com/v1

OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.openai.com/v1
```

**代码调用方式**（`src/analyzer.py`）：
```python
from openai import OpenAI
cfg = get_config()
client = OpenAI(api_key=cfg["llm_api_key"], base_url=cfg["llm_base_url"], timeout=120)
resp = client.chat.completions.create(model=cfg["llm_model"], ...)
```

**切换供应商**：只需修改 `.env` 中的 `ACTIVATE_PROVIDER` 和 `ACTIVATE_MODEL`，代码无需改动。
**UI 切换**：侧边栏提供供应商/模型选择器，用户可在界面上实时切换。

### 利润计算公式（可配置）

默认公式：`净利 = 售价(USD) × 汇率 - 采购成本 - 头程运费 - 佣金 - 广告费`

各参数默认值存储在 `src/config.py` 的 `get_profit_defaults()` 中，用户可在侧边栏修改：
- 佣金比例：15%
- 广告预算占比：10%
- 汇率：7.24（CNY/USD）
- 头程运费：¥15/件

### 数据抓取要点
- 抓取引擎：Scrapling（Fetcher + StealthyFetcher 自动降级）
- 适配层：`src/scrapling_adapter.py` 统一接口，所有平台共用
- 反爬策略：Scrapling 内置 TLS 指纹模拟、UA 轮换、反检测浏览器
- 价格货币自动换算：HKD/SGD/CNY 等 → USD（`_parse_price()` 内置汇率表）
- 非实体商品过滤：`_is_physical_product()` 关键词黑名单（subscription/plan/digital code 等）
- 排名使用全局序号（1-36），而非类目内 badge 排名
- 如遇验证码或 503，Scrapling 自动降级到 StealthyFetcher

### DeepSeek / 多模型 API 调用
- 使用 OpenAI SDK 兼容模式：`base_url` 由配置决定
- 批量分析策略：每批 6 个产品，拼接为一次 API 调用（`BATCH_SYSTEM_PROMPT`）
- 调用时必须设置 `timeout=120` 和重试逻辑（最多 2 次）
- Prompt 中明确要求 JSON 数组格式输出，代码中做容错解析
- `progress_callback` 支持前端进度条实时更新

### Streamlit 开发
- `st.sidebar` 放筛选配置、`st.columns` 卡片网格、`st.expander` 展示详情
- `st.session_state` 管理状态：products / results / source_info / step / analyzing / history_data
- 数据加载后立即 `st.rerun()` 让侧边栏即时更新
- 分析按钮使用 `disabled` 参数防止重复点击
- Cloud 端历史记录用 `session_state.history_data` 作为 SQLite 后备

### 数据更新工作流
```bash
# 本地（每周）
python daily_scrape.py   # 抓取 → SQLite + products.json

# 提交
git add data/products.json && git commit -m "Update products" && git push

# 云端 → Streamlit Cloud 自动重新部署
```
- 使用 `st.session_state` 缓存数据，`@st.cache_data` 缓存耗时操作
