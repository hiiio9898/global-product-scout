# Spec 7：指定选品（关键词搜索分析）

**版本**：v1.0
**状态**：✅ 已实现
**最后更新**：2026-05-28

---

## 1. 需求描述

### 1.1 背景

当前产品的核心流程是**被动扫描**：抓取 Amazon Best Sellers 榜单 → 批量 AI 分析 → 用户浏览结果。但实际选品场景中，用户更常见的需求是：

> "我已经有一个品类/关键词的想法，想看看这个方向值不值得做。"

例如：
- 用户在社交媒体看到一款 "portable blender" 很火，想评估市场
- 用户想做某个垂直品类（如 "cat toys"），需要整体评估
- 用户已有供应商，想反向验证该产品在 Amazon 上的潜力

现有流程无法满足这类**主动搜索 → 深度分析**的场景。

### 1.2 核心需求

1. 新增「🎯 指定选品」页面，用户输入关键词即可触发搜索
2. 抓取 Amazon 搜索结果页的产品列表（Top 20）
3. 对搜索结果进行 AI 五维度评估（复用现有分析引擎）
4. 生成品类综合报告（市场概况 + Top 3 推荐 + 入场建议）
5. 推荐产品可一键查看 1688 比价 + 利润试算（复用现有模块）

### 1.3 用户故事

| # | 作为… | 我想… | 以便… |
|---|-------|-------|-------|
| U1 | 跨境电商卖家 | 输入关键词，看到该品类在 Amazon 上的产品列表 | 了解竞争格局和产品分布 |
| U2 | 跨境电商卖家 | 获得品类综合分析报告 | 判断是否值得进入该品类 |
| U3 | 跨境电商卖家 | 直接看到 Top 3 推荐产品及理由 | 快速锁定值得跟进的产品 |
| U4 | 跨境电商卖家 | 对推荐产品查看 1688 采购价 | 评估真实利润空间 |
| U5 | 跨境电商卖家 | 保存搜索结果到历史记录 | 后续回顾和对比 |

### 1.4 边界约束

| 约束 | 说明 |
|------|------|
| 数据源 | Amazon US 站搜索结果页 |
| 单次搜索上限 | 最多抓取 20 个产品（搜索结果第 1 页） |
| AI 调用 | 复用现有 OpenAI SDK 兼容模式，无需新增供应商 |
| 1688 比价 | 复用现有混合策略（AI 估算 + 真实抓取尝试） |
| 反爬风险 | Amazon 搜索页反爬等级高于 Best Sellers 榜单，需降级方案 |

---

## 2. 系统设计

### 2.1 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `src/scraper_search.py` | **新建** | Amazon 关键词搜索抓取模块 |
| `src/analyzer.py` | **修改** | 新增 `analyze_category_report()` 品类综合分析函数 |
| `app.py` | **修改** | 侧边栏导航新增选项 + `_render_targeted_page()` 函数 |

### 2.2 架构图

```
┌─────────────────────────────────────────────────────────────┐
│                     app.py — 🎯 指定选品页面                  │
│                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │ 用户输入关键词  │───▶│ scraper_     │───▶│ 显示搜索结果   │  │
│  │ + 可选筛选条件  │    │ search.py    │    │ 列表 (20个)   │  │
│  └──────────────┘    └──────────────┘    └──────┬───────┘  │
│                                                  │          │
│                                                  ▼          │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │ 显示品类报告   │◀──│ analyzer.py  │◀──│ 批量 AI 分析   │  │
│  │ + Top3 推荐   │    │ 品类报告函数  │    │ (五维度评估)   │  │
│  └──────┬───────┘    └──────────────┘    └──────────────┘  │
│         │                                                   │
│         ▼                                                   │
│  ┌──────────────┐    ┌──────────────┐                      │
│  │ 1688 比价    │    │ 利润试算     │    （复用现有模块）     │
│  │ + 趋势查询   │    │ + 历史保存   │                      │
│  └──────────────┘    └──────────────┘                      │
└─────────────────────────────────────────────────────────────┘
```

### 2.3 数据流

```
用户输入关键词 "portable blender"
        │
        ▼
scraper_search.py: search_amazon(keyword, max_results=20)
        │
        ▼ 返回 list[dict]，每个 dict 包含:
        │   title, price, rating, num_reviews, rank, url, asin
        │
        ▼
analyzer.py: analyze_products(products)  ← 复用现有五维度分析
        │
        ▼ 同时调用
analyzer.py: analyze_category_report(keyword, products)
        │
        ▼ 返回品类综合报告 dict:
        │   category_overview, top3_recommendations,
        │   entry_suggestion, risk_factors
        │
        ▼
app.py: 渲染结果
        ├─ 品类综合报告（marketplace 卡片）
        ├─ 20 个产品列表 + 每个的五维度评分
        └─ Top 3 推荐卡片（带 1688 比价 + 利润试算按钮）
```

---

## 3. 模块设计

### 3.1 `src/scraper_search.py` — Amazon 关键词搜索

#### 函数签名

```python
def search_amazon(keyword: str, max_results: int = 20) -> dict:
    """
    在 Amazon US 站搜索指定关键词，返回产品列表。

    Args:
        keyword:     搜索关键词（英文，如 "portable blender"）
        max_results: 最多返回产品数，默认 20

    Returns:
        {
            "success": bool,
            "keyword": str,
            "results": list[dict],      # 每个 dict: title, price, rating,
                                        #           num_reviews, rank, url, asin
            "total_found": int,         # Amazon 搜索结果总数（如 "Over 1,000 results"）
            "source": str,              # "live" | "mock"
            "error": str | None,
        }
    """
```

#### 产品字段规范

| 字段 | 类型 | 说明 |
|------|------|------|
| `title` | str | 产品标题 |
| `price` | float | 价格（USD），解析失败时为 0 |
| `rating` | float | 评分（1-5），解析失败时为 0 |
| `num_reviews` | int | 评论数，解析失败时为 0 |
| `rank` | int | 搜索结果排名（1-based） |
| `url` | str | 产品详情页 URL |
| `asin` | str | Amazon 产品编号（从 URL 提取） |
| `category` | str | 搜索关键词作为 category |

#### 搜索 URL 构造

```
https://www.amazon.com/s?k={keyword_encoded}
```

- keyword 需 URL 编码
- 仅抓取第一页（不翻页）

#### 反爬策略（复用 scraper.py 基础设施）

| 策略 | 实现 |
|------|------|
| UA 池 | 复用 `scraper.py` 的 `_USER_AGENTS` 列表 |
| 请求延迟 | 随机 2-4 秒 |
| 多选择器兜底 | 搜索结果页的 CSS 选择器与 Best Sellers 页面不同，需新增 |
| HTTP 503 / CAPTCHA | 捕获异常，降级为 mock 数据 |
| Status Code 检查 | 非 200 直接降级 |

#### CSS 选择器策略

Amazon 搜索结果页结构（2026 年）：

```
div[data-component-type="s-search-result"]   ← 单个产品卡片
  ├── h2 a span                               ← 标题
  ├── span.a-price span.a-offscreen           ← 价格
  ├── i.a-icon-star-small span                ← 评分
  ├── span.a-size-base.s-underline-text       ← 评论数
  └── h2 a[href]                              ← 详情链接 + ASIN
```

需准备 2-3 套备选选择器应对页面变动。

#### Mock 降级数据

当真实抓取失败时，基于关键词生成模拟数据：

```python
def _get_mock_search_results(keyword: str, max_results: int) -> list[dict]:
    """
    根据关键词生成模拟搜索结果。
    使用 keyword 作为 category，生成 max_results 个虚构产品。
    确保价格/评分/评论数分布合理。
    """
```

---

### 3.2 `src/analyzer.py` — 品类综合分析（新增函数）

#### 函数签名

```python
def analyze_category_report(keyword: str, products: list[dict]) -> dict:
    """
    基于搜索结果生成品类综合分析报告。

    Args:
        keyword:  搜索关键词
        products: 搜索到的产品列表（最多 20 个）

    Returns:
        {
            "category_overview": str,         # 品类概况（100字以内）
            "market_size": str,               # 市场规模描述
            "competition_level": str,         # "low" | "medium" | "high"
            "competition_detail": str,        # 竞争详情
            "price_distribution": str,        # 价格分布描述
            "top3": [                         # Top 3 推荐
                {
                    "rank": int,
                    "title": str,
                    "reason": str,            # 推荐理由（50字以内）
                    "score": int,             # 综合评分 1-10
                },
            ],
            "entry_suggestion": str,          # 入场建议（100字以内）
            "differentiation": str,           # 差异化方向建议
            "risk_factors": list[str],        # 风险因素列表
            "parse_error": bool,              # JSON 解析是否失败
            "raw_text": str | None,           # 解析失败时的原始文本
        }
    """
```

#### 品类报告 System Prompt

```
你是一位拥有 10 年经验的资深跨境电商选品顾问。

根据以下关键词在 Amazon 搜索到的产品数据，生成品类综合分析报告。

关键词：{keyword}
产品数据（共 {n} 个）：
{products_json}

请分析并以严格 JSON 格式返回以下内容：
{
  "category_overview": "该品类的整体描述（100字以内）",
  "market_size": "市场规模描述，如'月搜索量约XX万，年增长率XX%'",
  "competition_level": "low/medium/high",
  "competition_detail": "竞争格局描述",
  "price_distribution": "价格区间分布描述，如'$10-$30 为主流价格带'",
  "top3": [
    {"rank": 1, "title": "产品标题", "reason": "推荐理由", "score": 8},
    ...
  ],
  "entry_suggestion": "入场建议，包括启动资金、时机判断等",
  "differentiation": "差异化方向建议",
  "risk_factors": ["风险1", "风险2", ...]
}

只返回 JSON。
```

#### Mock 降级

当 AI API 不可用时，基于产品数据本地生成报告：

```python
def _mock_category_report(keyword: str, products: list[dict]) -> dict:
    """本地模拟品类报告 — 基于产品统计数据生成。"""
    # 计算价格分布、平均评分、评论数分布
    # 按评论数 * rating 综合排序选出 Top 3
    # 生成固定的入场建议模板
```

---

### 3.3 `app.py` — 指定选品页面

#### 侧边栏导航变更

```python
page = st.sidebar.radio(
    "📌 页面导航",
    options=["📊 Dashboard", "🔍 实时选品", "🎯 指定选品", "📚 历史记录"],
    #                                                        ↑ 新增
)
```

#### 新增函数

```python
def _render_targeted_page(api_ok: bool):
    """
    渲染指定选品页面 — 关键词搜索 → AI 分析 → 品类报告。

    流程：
        1. 用户输入关键词 + 可选筛选
        2. 点击「🔍 搜索分析」按钮
        3. 展示搜索结果列表
        4. 展示品类综合报告
        5. 展示每个产品的五维度分析
        6. Top 3 产品提供 1688 比价 + 利润试算
    """
```

#### 页面布局

```
┌─────────────────────────────────────────────────────────┐
│  🎯 指定选品 — 关键词深度分析                              │
│                                                         │
│  输入你想调研的产品关键词，AI 将搜索 Amazon 并生成          │
│  品类综合报告 + Top 3 推荐。                              │
│                                                         │
│  ┌─────────────────────────────────────────┐            │
│  │ 🔍 关键词：[ portable blender      ]    │            │
│  │                                         │            │
│  │ 📊 价格区间（可选）                       │            │
│  │    最低 [$ 0  ] ~ 最高 [$ 100  ]        │            │
│  │                                         │            │
│  │ 📦 最少评论数（可选）：[ 100    ]        │            │
│  │                                         │            │
│  │        [ 🚀 搜索分析 ]                   │            │
│  └─────────────────────────────────────────┘            │
│                                                         │
│  ═══════════════════════════════════════════════════     │
│                                                         │
│  📊 品类综合报告                                         │
│  ┌─────────────────────────────────────────┐            │
│  │ 市场概况：该品类月搜索量约 50 万...       │            │
│  │ 竞争程度：🟡 中等                         │            │
│  │ 价格分布：$15-$35 为主流价格带            │            │
│  └─────────────────────────────────────────┘            │
│                                                         │
│  🏆 Top 3 推荐产品                                      │
│  ┌────────┐ ┌────────┐ ┌────────┐                      │
│  │ #1     │ │ #2     │ │ #3     │                      │
│  │ 产品名  │ │ 产品名  │ │ 产品名  │                      │
│  │ 评分 8  │ │ 评分 7  │ │ 评分 7  │                      │
│  │ 理由    │ │ 理由    │ │ 理由    │                      │
│  │[1688比价]│ │[1688比价]│ │[1688比价]│                     │
│  │[利润试算]│ │[利润试算]│ │[利润试算]│                     │
│  └────────┘ └────────┘ └────────┘                      │
│                                                         │
│  ⚠️ 入场建议：建议启动资金 $3000...                       │
│  ⚠️ 风险因素：• 头部品牌占比高  • 季节性波动...            │
│                                                         │
│  ═══════════════════════════════════════════════════     │
│                                                         │
│  📋 搜索结果列表（20 个产品）                             │
│  ┌─────────────────────────────────────────┐            │
│  │ 排名 │ 产品名称 │ 价格 │ 评分 │ 评论数    │            │
│  │  1   │ xxx      │$29.99│ 4.6 │ 15,420   │            │
│  │  2   │ xxx      │$24.99│ 4.5 │ 19,200   │            │
│  │ ...  │          │      │     │          │            │
│  └─────────────────────────────────────────┘            │
│                                                         │
│  🤖 AI 五维度详细分析                                    │
│  （每个产品的展开卡片，复用现有 expander 样式）             │
└─────────────────────────────────────────────────────────┘
```

#### 筛选逻辑

搜索结果在展示前可按以下条件过滤（客户端过滤，不改变抓取逻辑）：

| 筛选项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| 价格区间 | min/max USD | 0 ~ 无限 | 过滤超出范围的产品 |
| 最少评论数 | int | 0 | 过滤评论数过少的产品（可能是新品，数据不可靠） |

#### Session State 设计

```python
# 指定选品页面使用的 session state keys
st.session_state["targeted_keyword"]      # str, 用户输入的关键词
st.session_state["targeted_results"]      # list[dict], 搜索结果
st.session_state["targeted_category"]     # dict, 品类报告
st.session_state["targeted_analysis"]     # list[dict], 五维度分析结果
st.session_state["targeted_step"]         # str, "idle" | "searched" | "analyzed"
```

---

## 4. 错误处理

| 场景 | 处理方式 |
|------|----------|
| 关键词为空 | 按钮 disabled，提示用户输入 |
| Amazon 搜索被反爬（503） | 自动降级为 mock 数据，显示 ⚠️ 提示 |
| Amazon 搜索返回 0 结果 | 提示用户换关键词，给出热门品类建议 |
| AI API Key 未配置 | 使用本地 mock 分析 + 本地品类报告 |
| AI API 超时/错误 | 单个产品降级为 mock 分析，不阻断其他产品 |
| 1688 比价失败 | 显示提示，不影响主流程 |
| JSON 解析失败 | 显示原始文本（复用现有 parse_error 机制） |

---

## 5. 验收标准

### 5.1 功能验收

| # | 验收项 | 验收方式 |
|---|--------|---------|
| AC1 | 侧边栏出现「🎯 指定选品」导航选项 | 启动应用，检查侧边栏 |
| AC2 | 输入关键词后点击搜索，显示搜索结果列表 | 输入 "portable blender"，验证列表 |
| AC3 | 搜索结果展示品类综合报告 | 检查报告内容包含市场概况、竞争、Top3 |
| AC4 | 每个产品有五维度分析评分 | 展开任意产品 expander，检查 5 个维度 |
| AC5 | Top 3 推荐产品可一键查看 1688 比价 | 点击按钮，验证价格显示 |
| AC6 | 搜索失败时自动降级为模拟数据 | 断网测试，验证 mock 数据展示 |
| AC7 | 筛选条件正确过滤结果 | 设置价格区间，验证列表变化 |

### 5.2 性能验收

| # | 验收项 | 目标 |
|---|--------|------|
| P1 | 搜索抓取耗时 | ≤ 15 秒（含延迟） |
| P2 | AI 分析耗时（20 个产品） | ≤ 60 秒（批量分析） |
| P3 | 品类报告生成耗时 | ≤ 15 秒 |
| P4 | 页面交互响应 | ≤ 2 秒（筛选/排序） |

### 5.3 兼容性验收

| # | 验收项 |
|---|--------|
| C1 | Streamlit Cloud 部署正常（mock 降级场景） |
| C2 | 本地 `.env` 配置 DeepSeek/MiMo API 后 AI 分析正常 |
| C3 | 现有「🔍 实时选品」和「📚 历史记录」功能不受影响 |
| C4 | 所有 Python 文件通过 `python -m py_compile` 检查 |

---

## 6. 实现计划

| 阶段 | 任务 | 预计行数 | 依赖 |
|------|------|---------|------|
| Phase 1 | 新建 `src/scraper_search.py` | ~180 行 | 无 |
| Phase 2 | 扩展 `src/analyzer.py`（品类报告函数 + Prompt） | ~120 行 | 无 |
| Phase 3 | 修改 `app.py`（导航 + `_render_targeted_page`） | ~250 行 | Phase 1, 2 |
| Phase 4 | 本地测试 + 修复 | — | Phase 1-3 |
| Phase 5 | 提交推送 | — | Phase 4 |

---

## 7. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| Amazon 搜索页反爬比 Best Sellers 更严格 | 🔴 高 | 无法获取真实数据 | mock 降级 + 提示用户运行 daily_scrape |
| 搜索结果页 CSS 选择器频繁变动 | 🟡 中 | 解析失败 | 3 套选择器兜底 + 定期检查 |
| 20 个产品 AI 分析 Token 消耗大 | 🟡 中 | API 费用增加 | 批量分析（6个/批，复用现有策略） |
| 品类报告 Prompt 生成的 JSON 不稳定 | 🟡 中 | 解析失败 | 现有 parse_error 兜底机制 |
| Streamlit Cloud 冷启动延迟 | 🟢 低 | 首次加载慢 | 现有 spinner + progress 机制 |

---

## 8. 未来扩展（不在本期范围）

| 扩展项 | 说明 |
|--------|------|
| 多站点搜索 | 支持 Amazon UK/DE/JP 等站点 |
| 翻页支持 | 抓取多页搜索结果（40/60/100 个产品） |
| 历史搜索记录 | 保存用户的搜索历史，方便回顾 |
| 竞品对比 | 选择 2-3 个产品进行横向对比 |
| 搜索建议 | 输入时自动补全热门关键词 |
| 导出报告 | 将品类报告导出为 PDF/Markdown |
