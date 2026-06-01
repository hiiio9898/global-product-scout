# ARCHITECTURE_REPORT.md

> Global Product Scout — 项目架构全面梳理报告
> 生成时间：2026-06-01 | 基于 commit `8af8d40`

---

## 1. 项目定位

| 项 | 值 |
|---|---|
| 项目名称 | Global Product Scout（全球产品侦察兵） |
| 目标用户 | 跨境电商卖家、外贸创业者 |
| 核心功能 | 多平台热销产品抓取 → AI 五维度分析 → 利润计算 → 选品建议 |
| 技术栈 | Python 3.12、Streamlit、Scrapling（抓取）、OpenAI SDK 兼容 API（AI 分析）、SQLite |
| 部署方式 | 本地运行 + Streamlit Cloud + GitHub Actions 定时抓取 |

---

## 2. 目录结构

```
handpicked/
├── app.py                      # Streamlit 主程序入口（~1700 行）
├── daily_scrape.py             # 独立定时抓取脚本（CLI）
├── requirements.txt            # Python 依赖
├── packages.txt                # 系统级依赖（Streamlit Cloud Chrome）
├── runtime.txt                 # Python 版本（3.12）
├── .env.example                # 环境变量模板
├── .gitignore                  # Git 忽略规则
├── AGENTS.md                   # AI 协作规则
├── SKILL.md                    # 技能系统说明
├── todo.md                     # 原始需求文档（已过时）
│
├── src/
│   ├── __init__.py             # 包初始化
│   ├── config.py               # 配置加载（st.secrets + .env 双源）
│   ├── platforms.py            # 平台注册表（PLATFORMS 字典）
│   ├── scrapling_adapter.py    # Scrapling 适配层（统一抓取接口）
│   ├── scraper.py              # Amazon Best Sellers 抓取
│   ├── scraper_search.py       # Amazon 关键词搜索
│   ├── scraper_ebay.py         # eBay 抓取
│   ├── scraper_alibaba.py      # 阿里巴巴国际站抓取
│   ├── scraper_1688.py         # 1688 比价（AI 估算 + 真实抓取）
│   ├── analyzer.py             # AI 分析引擎（五维度评估）
│   ├── calculator.py           # 利润计算器（工厂模式）
│   ├── database.py             # SQLite 数据库
│   ├── trends.py               # Google Trends 趋势查询
│   └── utils.py                # 工具函数（UA 池、反爬检测、价格解析）
│
├── tests/
│   ├── __init__.py
│   ├── test_basic.py           # 基础单元测试
│   └── test_integration.py     # 全平台集成测试（28 项）
│
├── docs/
│   ├── CHANGELOG.md            # 变更日志
│   ├── DEPLOY.md               # 部署备忘录
│   └── specs/                  # 功能规格文档（15 份）
│
├── data/
│   ├── products.json           # 最新产品数据（提交到 Git）
│   ├── products.db             # SQLite 数据库（不提交）
│   ├── cache/                  # 抓取缓存（不提交）
│   ├── debug_amazon.html       # 调试文件（不提交，应清理）
│   └── debug_live.html         # 调试文件（不提交，应清理）
│
├── .github/workflows/          # GitHub Actions 定时抓取
├── .streamlit/                 # Streamlit Cloud 配置
└── Scrapling-main/             # Scrapling 源码（本地 editable 安装，不提交）
```

---

## 3. 核心业务逻辑链条

```
用户操作
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  app.py（Streamlit 前端）                                │
│  ├── render_sidebar()      → 平台/地区/AI模型/利润参数    │
│  ├── _render_dashboard_page() → 数据概览 + TOP5          │
│  ├── _render_live_page()   → 实时选品（抓取→分析→展示）   │
│  ├── _render_targeted_page() → 关键词搜索选品             │
│  └── _render_history_page() → 历史记录+趋势+跨平台对比    │
└────────────────────┬────────────────────────────────────┘
                     │
     ┌───────────────┼───────────────┐
     ▼               ▼               ▼
┌──────────┐  ┌──────────┐  ┌──────────────┐
│ 抓取层    │  │ 分析层    │  │ 存储层        │
│          │  │          │  │              │
│ scraper  │→ │ analyzer │→ │ database     │
│ _*.py    │  │ .py      │  │ .py          │
└────┬─────┘  └──────────┘  └──────────────┘
     │
     ▼
┌──────────────────┐
│ scrapling_adapter │ ← 统一抓取适配层
│ .py              │
├──────────────────┤
│ Fetcher          │ ← curl_cffi TLS 指纹（快速）
│   ↓ 被拦截       │
│ StealthyFetcher  │ ← Patchright 反检测浏览器（兜底）
└──────────────────┘
```

### 3.1 数据流

```
实时选品：
  用户点击「📡 实时抓取」
    → platforms.py 获取抓取函数
    → scrapling_adapter.fetch_page() 抓取页面
    → scraper_*.py 解析产品卡片
    → analyzer.py AI 五维度分析（批量 6 个/批）
    → calculator.py 利润计算
    → database.py 保存到 SQLite
    → app.py 展示结果

历史记录：
  用户打开「📚 历史记录」
    → database.py.query_products() 多条件查询
    → app.py 渲染统计仪表盘 + 跨平台对比 + 产品列表

1688 比价：
  用户点击「🔍 查看1688参考价」
    → scraper_1688.py._scrape_1688_search() 真实抓取
    → 失败时降级 → estimate_1688_price() AI 估算
    → 失败时降级 → _local_estimate() 本地规则估算
```

### 3.2 模块依赖关系

```
app.py
├── src/config.py          (配置)
├── src/platforms.py       (平台注册表)
├── src/scraper.py         (Amazon 抓取)
├── src/scraper_search.py  (Amazon 搜索)
├── src/analyzer.py        (AI 分析)
├── src/calculator.py      (利润计算)
├── src/scraper_1688.py    (1688 比价)
├── src/trends.py          (Google Trends)
└── src/database.py        (数据库)

src/scraper.py
├── src/config.py
├── src/scrapling_adapter.py
└── src/utils.py

src/scraper_search.py
├── src/scrapling_adapter.py
└── src/utils.py

src/scraper_ebay.py
├── src/scrapling_adapter.py
└── src/utils.py

src/scraper_alibaba.py
├── src/scrapling_adapter.py
└── src/utils.py

src/scraper_1688.py
├── src/scrapling_adapter.py
└── src/config.py

src/scrapling_adapter.py
├── src/config.py
└── src/utils.py

src/analyzer.py
└── src/config.py

src/calculator.py
└── (无内部依赖，纯函数)

src/database.py
└── src/config.py

src/platforms.py
└── (无内部依赖，纯数据)

src/config.py
└── (无内部依赖，根模块)
```

---

## 4. 平台注册表

当前注册 3 个平台（`src/platforms.py`）：

| 平台 | 图标 | 抓取器 | 搜索器 | 利润计算器 | 地区 | 抓取模式 |
|------|------|--------|--------|-----------|------|---------|
| Amazon | 🟠 | scraper.py | scraper_search.py | calculate_amazon_profit | US/UK/JP/DE | fetcher_first |
| eBay | 🔵 | scraper_ebay.py | scraper_ebay.py | calculate_ebay_profit | US/UK/DE | fetcher_first |
| Alibaba | 🟠 | scraper_alibaba.py | scraper_alibaba.py | calculate_alibaba_profit | US(国际站) | stealth_only |

### 利润计算器对比

| 平台 | 费用项 | 公式核心 |
|------|--------|---------|
| Amazon | 佣金 15% + 广告 10% + 头程 ¥15 | FBA 模式 |
| eBay | 成交费 13.25% + 刊登费 $0.30 + Payoneer 1% | Managed Payments |
| Alibaba | 佣金 5% + 信保 2% + 国际运费 ¥25 | B2B 批发 |

---

## 5. 问题清单

### 5.1 过时/冗余文件

| 文件 | 问题 | 建议 |
|------|------|------|
| `todo.md` | 原始需求文档，内容大量过时（提及"速卖通、Shopee"等已移除平台，阶段〇标记"⏳ 待实现"但已完成） | 删除或归档到 `docs/archive/` |
| `data/debug_amazon.html` | 调试产生的 634KB HTML 文件 | 删除，加入 .gitignore |
| `data/debug_live.html` | 调试产生的 630KB HTML 文件 | 删除，加入 .gitignore |
| `docs/CHANGELOG.md` | 最后更新停留在 v0.2.0，未记录多平台扩展和 Scrapling 集成 | 更新至当前版本 |
| `docs/DEPLOY.md` | 仅描述 Amazon 单平台部署，未更新多平台和 Scrapling 相关配置 | 更新 |

### 5.2 AGENTS.md 过时内容

| 位置 | 过时内容 | 应更新为 |
|------|---------|---------|
| §1 项目定位 | "技术栈：Requests/BeautifulSoup（数据抓取）" | "Scrapling（自适应抓取引擎）" |
| §3 目录结构 | 缺少 `platforms.py`、`scrapling_adapter.py`、`scraper_ebay.py`、`scraper_alibaba.py` | 补全 |
| §3 目录结构 | 列出 `scraper_1688.py` 描述为"混合策略" | 已升级为"AI 估算 + 真实浏览器抓取" |
| §7 数据源 | "只抓取首页榜单，每天最多一次" | 已支持多平台多地区 |
| §9 Git 推送规范 | "严禁推送"表格重复了 5 行（密钥/虚拟环境/缓存/IDE/系统各出现两次） | 去重 |

### 5.3 SKILL.md 过时内容

| 位置 | 过时内容 | 应更新为 |
|------|---------|---------|
| 项目架构概览 | "src/scraper.py → requests + BeautifulSoup + 货币换算" | "Scrapling 自适应抓取" |
| 项目架构概览 | 缺少 `platforms.py`、`scrapling_adapter.py`、多平台抓取器 | 补全 |
| 数据抓取要点 | "使用 requests.Session()" | "使用 Scrapling Fetcher/StealthyFetcher" |
| 领域知识库 | 未提及多平台架构、利润计算器工厂模式 | 补充 |

### 5.4 .gitignore 问题

| 问题 | 说明 |
|------|------|
| 编码损坏 | 中文注释显示为乱码（`鐜境鍙橀噺` 等），文件可能被错误编码保存 |
| `data/debug_*.html` | 已在 .gitignore 中但文件仍存在于本地（应手动删除） |
| `tode.md` | .gitignore 中有 `tode.md`（拼写错误），实际文件名是 `todo.md`（已忽略） |

### 5.5 代码层面问题

| 文件 | 问题 | 严重度 |
|------|------|--------|
| `src/scraper.py` | Scrapling 已内置 UA 管理，已清理冗余导入 | ✅ 已修复 |
| `src/scraper_search.py` | 同上 | ✅ 已修复 |
| `src/scraper_ebay.py` | 同上 | ✅ 已修复 |
| `src/scraper_alibaba.py` | 同上 | ✅ 已修复 |
| `src/utils.py` | `USER_AGENTS` 常量仍被多文件导入但 Scrapling 已替代其用途 | 低 |
| `app.py:73` | Dashboard 图标显示为 `� Dashboard`（编码问题） | 中 |
| `src/config.py` | `get_config()` 中 `amazon_url` 仍硬编码为 Amazon 专用 | 低 |
| `daily_scrape.py` | 未适配多平台 | ✅ 已修复（支持 --platforms 参数，遍历 PLATFORMS 注册表） |
| `requirements.txt` | `requests` 和 `beautifulsoup4` 已被移除但 Scrapling 内部仍依赖它们（通过 curl_cffi） | 无 |

### 5.6 Specs 文档缺失

| 编号 | 文档 | 状态 |
|------|------|------|
| 9 | `docs/specs/9-aliexpress-platform.md` | ❌ 已删除（AliExpress 已移除） |
| 10 | `docs/specs/10-shopee-platform.md` | ❌ 已删除（Shopee 已移除） |
| `docs/specs/15-alibaba-platform.md` | ✅ 已完成（补写） |
| — | `docs/specs/16-daily-scrape-multi-platform.md` | ❌ 缺失（已直接实现，功能简单无需单独 Spec） |

---

## 6. 技术债务总结

### 🔴 高优先级

1. **`app.py:73` 编码问题** — `📊 Dashboard` 显示为 `� Dashboard`，影响用户体验
2. **`daily_scrape.py` 未适配多平台** — 定时抓取仍只抓 Amazon，多平台数据无法自动更新
3. **`todo.md` 严重过时** — 内容与当前架构完全脱节，容易误导

### 🟡 中优先级

4. **AGENTS.md 目录结构过时** — 缺少 5 个新增文件，技术栈描述错误
5. **SKILL.md 架构描述过时** — 仍描述 requests+BS4 架构
6. **CHANGELOG.md 未更新** — 缺少 v0.3.0+ 的所有变更记录
7. **DEPLOY.md 未更新** — 缺少 Scrapling 和多平台部署说明
8. **.gitignore 编码损坏** — 中文注释乱码

### 🟢 低优先级

9. **scraper_*.py 冗余导入 `USER_AGENTS`** — Scrapling 已内置 UA 管理
10. **`data/debug_*.html` 残留** — 调试文件未清理
11. **Spec 15/16 缺失** — Alibaba 平台和 daily_scrape 多平台无正式 Spec

---

## 7. 文件清单（完整）

### 核心源码（13 个）

| 文件 | 行数 | 职责 |
|------|------|------|
| `src/config.py` | ~240 | 配置加载、LLM 供应商注册表、Scrapling 配置 |
| `src/platforms.py` | ~130 | 平台注册表（PLATFORMS 字典 + 工具函数） |
| `src/scrapling_adapter.py` | ~120 | Scrapling 适配层（Fetcher→StealthyFetcher 降级） |
| `src/scraper.py` | ~400 | Amazon Best Sellers 抓取 |
| `src/scraper_search.py` | ~350 | Amazon 关键词搜索 |
| `src/scraper_ebay.py` | ~500 | eBay 抓取 |
| `src/scraper_alibaba.py` | ~400 | 阿里巴巴国际站抓取 |
| `src/scraper_1688.py` | ~350 | 1688 比价（AI 估算 + StealthyFetcher 真实抓取） |
| `src/analyzer.py` | ~300 | AI 五维度分析引擎 |
| `src/calculator.py` | ~350 | 利润计算器（工厂模式，3 个平台） |
| `src/database.py` | ~350 | SQLite 数据库（多平台 Schema） |
| `src/trends.py` | ~100 | Google Trends 趋势查询 |
| `src/utils.py` | ~120 | 工具函数（UA 池、反爬检测、价格解析） |

### 入口文件（2 个）

| 文件 | 行数 | 职责 |
|------|------|------|
| `app.py` | ~1700 | Streamlit 主程序（侧边栏 + 4 个页面路由） |
| `daily_scrape.py` | ~160 | 独立定时抓取脚本（多平台，支持 --platforms 参数） |

### 测试文件（2 个）

| 文件 | 测试数 | 职责 |
|------|--------|------|
| `tests/test_basic.py` | ~15 | 基础单元测试（配置、抓取、分析、工具函数） |
| `tests/test_integration.py` | 28 | 全平台集成测试（平台注册、利润计算、数据库、导入） |

### 文档文件（17 个）

| 文件 | 状态 |
|------|------|
| `AGENTS.md` | ⚠️ 部分过时 |
| `SKILL.md` | ⚠️ 部分过时 |
| `todo.md` | ❌ 严重过时 |
| `docs/CHANGELOG.md` | ⚠️ 未更新至最新 |
| `docs/DEPLOY.md` | ⚠️ 未更新至最新 |
| `docs/specs/0-content-display-rule.md` | ✅ 有效 |
| `docs/specs/0A-multi-model-support.md` | ✅ 有效 |
| `docs/specs/0B-configurable-profit-formula.md` | ✅ 有效 |
| `docs/specs/1-profit-persistence.md` | ✅ 有效 |
| `docs/specs/2-automation-cicd.md` | ✅ 有效 |
| `docs/specs/3-product-trend-tracking.md` | ✅ 有效 |
| `docs/specs/4-1688-comparison.md` | ✅ 有效 |
| `docs/specs/5-dashboard-homepage.md` | ✅ 有效 |
| `docs/specs/6-google-trends.md` | ✅ 有效 |
| `docs/specs/7-targeted-product-search.md` | ✅ 有效 |
| `docs/specs/8-multi-platform-infrastructure.md` | ✅ 有效 |
| `docs/specs/11-ebay-platform.md` | ✅ 有效 |
| `docs/specs/12-history-enhancement.md` | ✅ 有效 |
| `docs/specs/13-aliexpress-platform.md` | ⚠️ 内容有效但平台已替换为 Alibaba |
| `docs/specs/14-scrapling-integration.md` | ✅ 已完成 |

---

## 8. 架构优势

1. **平台注册表模式** — 新增平台只需在 `PLATFORMS` 添加条目 + 写抓取器 + 注册计算器，零改动 app.py
2. **Scrapling 自适应抓取** — Fetcher→StealthyFetcher 自动降级，比手动维护 requests+BS4 更健壮
3. **利润计算器工厂模式** — `@register_calculator` 装饰器注册，`get_calculator()` 获取，解耦干净
4. **三层 1688 降级** — 真实抓取 → AI 估算 → 本地规则，确保比价功能始终可用
5. **双源配置** — `.env` 本地 + `st.secrets` 云端，代码无感知切换
6. **28 项集成测试** — 覆盖平台注册、利润计算、数据库、模块导入

---

## 9. 建议行动项

### 立即修复
- [x] 修复 `app.py:73` 的 `📊 Dashboard` 编码问题
- [x] 删除 `data/debug_amazon.html` 和 `data/debug_live.html`
- [x] 修复 `.gitignore` 中文注释编码

### 短期更新
- [x] 更新 `AGENTS.md` 目录结构和技术栈描述
- [x] 更新 `SKILL.md` 架构概览
- [x] 更新 `docs/CHANGELOG.md` 至当前版本
- [x] 更新 `docs/DEPLOY.md` 添加 Scrapling 和多平台说明
- [x] 删除或归档 `todo.md`

### 中期规划
- [x] `daily_scrape.py` 适配多平台抓取
- [x] 补写 Spec 15（Alibaba 平台正式 Spec）
- [x] 清理 scraper_*.py 中冗余的 `USER_AGENTS` 导入
