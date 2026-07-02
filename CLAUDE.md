# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Global Product Scout（全球产品侦察兵）— 跨境电商 AI 选品工具。Streamlit 应用，抓取 Amazon 等平台热销品，用 LLM 做**六维度**量化分析（市场容量/竞争/利润/新手友好/季节性/长期持久力），算利润，给选品建议。**AI 协作的完整硬规则见 [AGENTS.md](AGENTS.md)（唯一真源）**；本文件聚焦架构与快速上手。

## 常用命令

| 命令 | 用途 |
|---|---|
| `pip install -r requirements.txt` | 安装依赖 |
| `streamlit run app.py` | 启动 Web 应用 |
| `pytest tests/` | 全量测试（`tests/test_basic.py` + `tests/test_integration.py`） |
| `pytest tests/test_basic.py::TestAnalyzer::test_parse_valid_json` | 跑单个测试 |
| `pytest -k longevity` | 按名匹配跑测试 |
| `python -m py_compile <file>` | 语法检查（改完任何 .py 都跑一遍） |
| `python daily_scrape.py` | 全平台抓取（**默认只跑 `available=True` 的平台**） |
| `python daily_scrape.py --platforms amazon --skip-analysis` | 指定平台 / 仅抓取不分析 |
| `python scripts/diagnose_sites.py "keyword" --json` | 诊断各平台可用性（测**全部**平台含不可用的，作证据来源） |
| `flake8 src/` | 代码风格 |

## 架构（big picture）

**注册表驱动**是核心范式——三个字典注册表决定一切：

- **`PLATFORMS`** ([src/platforms.py](src/platforms.py))：每个平台一条字典（爬虫模块/函数名、计算器函数名、区域×汇率、`available` 标志、`profit_defaults`）。UI 选择器、daily_scrape、诊断工具全部经 `get_platform_choices()` / `get_available_platform_choices()` 读它。**加新平台 = 一条字典 + 一个 scraper 模块 + 一个 calculator**（对应 `add-data-source` / `add-platform-calculator` skill）。
- **`LLM_PROVIDERS`** ([src/config.py](src/config.py))：AI 供应商字典，`ACTIVATE_PROVIDER`+`ACTIVATE_MODEL` 切换。
- **`@register_calculator`** ([src/calculator.py](src/calculator.py))：装饰器注册各平台利润计算器。

**数据流**（一次实时选品）：
```
app.py (_render_live_page)
  → platforms.py 查注册表 → importlib 动态加载 scraper
  → scrapling_adapter.fetch_page() (Fetcher → StealthyFetcher 自动降级)
  → scraper_*.py 解析 HTML → 产品 dict 列表
  → analyzer.analyze_products() (每批 6 个、一次 LLM 调用、六维度评分)
  → calculator.calculate_profit() (按平台公式，金额先算 CNY)
  → database 存 SQLite (analysis 序列化为 JSON blob 存 TEXT 列)
  → app.py Streamlit 渲染
```

**抓取层**（[src/scrapling_adapter.py](src/scrapling_adapter.py)）：
- 统一 `fetch_page(url, stealth=False)`。默认 `fetcher_first`：Fetcher 被反爬拦截 → 自动升 StealthyFetcher（patchright 浏览器；Streamlit Cloud 首次 `ensure_browser_installed()` 自动装 chromium）。
- **Amazon Best Sellers 必须 `stealth=True`**——价格由客户端 JS 注入，Fetcher 静态 HTML 里没有价格元素（否则价格全 0）。已落地：首页（固定 ~36 个）+ 翻页品类页凑 `max_results`（默认 60），按 ASIN 去重；价格选择器用子串 `span[class*="p13n-sc-price"]`（不依赖会变的 CSS-modules 哈希）。

**AI 分析**（[src/analyzer.py](src/analyzer.py)）：
- 六维度 prompt 内嵌在 `SYSTEM_PROMPT`（单品）/ `BATCH_SYSTEM_PROMPT`（批量，主力）。`_validate_result` 强制校验六维全在；**所有 parse_error 兜底 dict（无 key、解析失败、批量失败等 4 处）必须带六维默认值**。新增维度用 `add-analysis-type` skill，务必同步所有兜底。
- `final_verdict` 枚举（recommended/cautious/not_recommended）被 app.py 十几处过滤/统计引用——**不要轻易改枚举值**，新维度走"独立字段 + UI 徽章"而非新 verdict。

**前端**（[app.py](app.py)，~2750 行单文件）：`ANALYSIS_DIMS` 列表同时驱动雷达图和维度展示——加维度只要往这里 append；`VERDICT_LABEL_MAP` / `LONGEVITY_LABEL_MAP` 驱动徽章。页面渲染函数 `_render_live_page` / `_render_targeted_page` / `_render_market_scanner_page` / `_render_history_page`。

## 必须知道的硬约束 & 坑

- **免费约束（长期、硬性）**：用户**永久拒绝**付费代理 / 付费 API（Scrapfly/Oxylabs/住宅代理等）。Clash 可切很多节点，但**免费节点基本都是机房 IP**（出口随节点切换而变，住宅节点极少且不稳）；**只有 Amazon 能稳定爬**（不做机房 IP 封锁，7/9 站）。eBay/AliExpress/TikTok 被 Akamai/eBay 在**网络层**按"机房 IP"封死，Lazada 同理——换不同的免费节点也基本救不了（除非碰巧切到住宅节点）。UC/patchright 都只伪装浏览器指纹、伪装不了 IP——换抓取工具无解。→ **不要再尝试"修复"这三个平台的抓取**，除非用户明确说"现在切到了住宅/付费代理"。它们在注册表里 `available=False`，scraper/calculator 代码保留待将来启用。

- **Streamlit widget-key 坑**：widget 绑了 `key="xxx"` 后，在该 widget 渲染后的同一 run 内**不能** `st.session_state["xxx"]=value`（抛 `StreamlitAPIException`）。程序化改 widget 值：写一个 pending key + `st.rerun()`，在 widget **渲染前**注入（见 app.py 中 1688 回填采购成本的处理，或用 `on_click` 回调）。

- **内容展示禁止截断**：面向用户的文本必须完整可见。允许的例外仅：expander 标题 `[:40]`+`help=`、selectbox 选项 `[:50]`+`help=`、API 参数。DataFrame 用 `column_config` 控宽，不截断字符串。详见 [docs/specs/0-content-display-rule.md](docs/specs/0-content-display-rule.md)。

- **Cloud 的 number_input 混合类型**：新版 Streamlit 强校验 `value`/`min_value`/`step` 必须同类型（int/float 不能混）。变量来源的 `value` 统一 `float()` 转换。

- **注释中文、标识符英文**；不做与当前任务无关的重构/"顺手优化"（AGENTS.md §2）。

## 配置 & 部署

- **配置双源**：`st.secrets` > `.env`（python-dotenv）。`.env` 已 gitignore，Cloud 用 secrets。
- **多模型**：`.env` 的 `ACTIVATE_PROVIDER`+`ACTIVATE_MODEL` + 对应 `*_API_KEY`/`*_BASE_URL`。默认小米 MiMo。侧边栏有 UI 实时切换器。
- **Streamlit Cloud**：主部署，push 到 master 自动重新部署。Python 3.14（`runtime.txt` 已对齐）。
- **GitHub Actions**：每日自动跑 daily_scrape，auto-commit+push `data/products.json`（唯一被跟踪的数据文件，`.gitignore` 里 `!data/products.json`）。`data/products.db`、`data/cache/*` 不提交。
- **依赖**：scrapling 是本地 editable 安装（`Scrapling-main/`，不提交）；`patchright==1.59.1` + `playwright==1.59.0` 版本锁。

## Skill 系统

[.claude/skills/](.claude/skills/) 里有领域工作流 skill，**任务匹配时先调 skill 再动手**（项目约定）：
- `fix-scraper` — 抓取失效/解析异常（**先查 platforms.py 定位爬虫文件**，不是所有爬虫都在 scraper.py）
- `add-data-source` / `add-platform-calculator` — 加新平台
- `add-analysis-type` — 加分析维度
- `add-streamlit-page` / `init-project` / `migrate-database` / `minimalist-architect`
