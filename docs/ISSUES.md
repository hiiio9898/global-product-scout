# 已知问题清单

本文档记录 Global Product Scout 已知问题、修复计划和完成状态。

---

## 🔴 P0 — 紧急

### [P0-1] 分析阻塞时间过长

**描述**：`analyze_products()` 逐产品串行调用 DeepSeek API，36 个产品 × 45s 超时 × 2 次重试，最坏情况 ~55 分钟。浏览器可能超时，Streamlit Cloud 也可能超时 kill 进程。

**文件**：`src/analyzer.py` (`analyze_products`)

**方案**：将 36 个产品分组（6 个/批）后批量调用 DeepSeek API，每批一次调用。新增 `BATCH_SYSTEM_PROMPT`、`_build_batch_prompt()`、`_parse_batch_response()`。`app.py` 同步添加进度条和状态容器。

**状态**：✅ 已修复

---

### [P0-2] 抓取价格货币单位错误（HKD→USD）

**描述**：Amazon 因用户地区返回 HKD（港币）而非 USD 价格。`_parse_price()` 直接提取数字，导致水瓶显示 $235.00（实际 HKD 235 ≈ USD 30）。

**文件**：`src/scraper.py` (`_parse_price`)

**方案**：检测货币前缀（HKD/HK$/SGD/S$/CNY/¥ 等），自动按汇率换算为 USD。

**状态**：✅ 已修复

---

### [P0-3] 所有产品 rank 统一为 "1"

**描述**：Amazon Best Sellers 首页跨类目轮播，每个产品都是其子品类 #1。`_parse_product_card` 读取的 rank badge 是类目内排名，导致全部为 1。

**文件**：`src/scraper.py` (`_parse_product_card`)

**方案**：使用全局序号（enumerate 传递的 rank 参数）代替类目内徽章排名。

**状态**：✅ 已修复

---

## 🟡 P1 — 中等

### [P1-1] 侧边栏数据源状态缺失

**描述**：JSON 加载成功后，侧边栏未显示 `📄 JSON 数据（本地采集）`。因为 `render_sidebar()` 的 source_info 在 `st.rerun()` 后才更新，而 rerun 在分析完成后才触发。若分析中途失败，用户看不到数据来源。

**文件**：`app.py`

**方案**：加载数据后立即 `st.rerun()` 分段更新侧边栏状态，侧边栏即时显示数据来源。

**状态**：✅ 已修复

---

### [P1-2] 无逐产品分析进度

**描述**：36 个产品串行分析，只显示一行 "🤖 AI 正在深度分析..."，用户不知道进度。已随 P0-1 批量分析改造一并修复。

**文件**：`app.py` / `src/analyzer.py`

**方案**：`analyze_products()` 新增 `progress_callback` 参数；`app.py` 中使用 `st.status` + `st.progress` 实时更新进度。

**状态**：✅ 已修复

---

### [P1-3] Cloud 端历史记录永远为空

**描述**：SQLite 在 Streamlit Cloud 上 ephemeral 文件系统重启即丢失，历史记录功能形同虚设。

**文件**：`src/database.py` / `app.py`

**方案**：分析结果同时存入 `st.session_state.history_data` 作为 DB 后备。历史记录页面优先读 DB，DB 为空则读 session state。Cloud 端显示提示信息。

**状态**：✅ 已修复

---

### [P1-4] 抓取了非实体商品

**描述**：榜单包含 "blink plus plan" 等数字订阅服务，非实体选品目标。

**文件**：`src/scraper.py`

**方案**：新增 `_is_physical_product()` 过滤函数 + `_SKIP_KEYWORDS` 黑名单（subscription/plan/digital code 等），解析时跳过非实体商品。

**状态**：✅ 已修复

---

## 🟢 P2 — 低优先级

### [P2-1] 所有类目为空

**描述**：`category: ""` 统一空字符串，分类筛选无意义。Amazon Best Sellers 首页不直接显示类目。

**文件**：`src/scraper.py`

**方案**：后续考虑从产品详情页或面包屑导航获取类目。

**状态**：⏳ 待后续优化

---

### [P2-2] 版本号更新到 v0.2.0

**描述**：页脚版本号已更新。

**文件**：`app.py`

**方案**：`v0.1.0` → `v0.2.0`。

**状态**：✅ 已修复

---

### [P2-3] "开始分析"按钮在分析期间不可点击

**描述**：按钮在分析期间显示为 disabled 状态，避免用户重复点击。

**文件**：`app.py`

**方案**：使用 `st.session_state.analyzing` 标志位 + `disabled` 参数。

**状态**：✅ 已修复
