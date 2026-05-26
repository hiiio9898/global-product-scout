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

### 数据抓取要点
- 亚马逊 Best Sellers URL：`https://www.amazon.com/Best-Sellers/zgbs/`
- 反爬策略：User-Agent 模拟真实浏览器、请求间隔 1-2 秒、使用 `requests.Session()`
- 如遇验证码或 503，降级为 mock 数据
- 选择器：`div[data-component-type="s-product-card"] h2`（标题）、`.a-price .a-offscreen`（价格）

### DeepSeek API 调用
- 使用 OpenAI SDK 兼容模式：`base_url="https://api.deepseek.com"`
- 调用时必须设置 `timeout` 和 `max_retries`
- Prompt 中明确要求 JSON 格式输出，代码中做容错解析

### Streamlit 开发
- `st.sidebar` 放筛选配置、`st.columns` 卡片网格、`st.expander` 展示详情
- 使用 `st.session_state` 缓存数据，`@st.cache_data` 缓存耗时操作
