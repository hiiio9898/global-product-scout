# SKILL.md

本项目使用 `.claude/skills/` 存放 AI 协作技能。预设技能：

1. **init-project**：初始化整个项目结构。
2. **add-data-source**：新增一个数据源（如速卖通、Shopee）。
3. **add-analysis-type**：新增一种分析维度（如利润计算、竞争度打分）。
4. **fix-scraper**：修复因网站改版导致的抓取失效。

每个技能文件夹内包含 `SKILL.md` 详细工作流。

---

## 领域知识库

以下为本项目积累的通用技术知识，供各技能参考。

### 项目架构概览

```
app.py              Streamlit 主程序入口（侧边栏 + 页面路由 + Session State）
├── render_sidebar()           侧边栏：导航、数据源状态、API 配置状态
├── _render_live_page()        实时选品页：数据加载 → AI 分析 → 展示结果
├── _render_history_page()     历史记录页：筛选、排序、导出 CSV
└── _load_products()           两级数据策略：JSON → 实时抓取

src/config.py       配置加载（st.secrets > .env 双源）
src/scraper.py      Amazon Best Sellers 抓取（requests + BeautifulSoup + 货币换算）
src/analyzer.py     AI 分析引擎（OpenAI SDK 兼容，批量分组 6 个/批）
src/database.py     SQLite 数据库（建表、保存、查询、导出 CSV）
src/utils.py        工具函数
daily_scrape.py     独立定时抓取脚本（CLI 运行，导出 products.json）
```

### 多模型 AI 分析架构

当前支持通过 OpenAI SDK 兼容模式调用任意 LLM 供应商（DeepSeek、MiMo、OpenAI 等）。

**配置方式**（`.env.example` + `src/config.py`）：
```bash
# 激活哪个供应商和模型
ACTIVATE_PROVIDER=deepseek        # deepseek / mimo / openai
ACTIVATE_MODEL=deepseek-v4-flash  # 对应供应商下的具体模型名

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
- 亚马逊 Best Sellers URL：`https://www.amazon.com/Best-Sellers/zgbs/`
- 反爬策略：User-Agent 模拟真实浏览器、请求间隔 1-2 秒、使用 `requests.Session()`
- 价格货币自动换算：HKD/SGD/CNY 等 → USD（`_parse_price()` 内置汇率表）
- 非实体商品过滤：`_is_physical_product()` 关键词黑名单（subscription/plan/digital code 等）
- 排名使用全局序号（1-36），而非类目内 badge 排名
- 如遇验证码或 503，抛出异常由 `app.py` 显示错误提示

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
