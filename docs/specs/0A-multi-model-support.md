# Spec 0-A：多模型 AI 供应商支持

**版本**：v1.0
**状态**：✅ 已实现并验收通过
**最后更新**：2026-05-28

---

## 1. 需求描述

### 1.1 背景
当前 AI 分析功能硬编码为 DeepSeek 供应商（`base_url="https://api.deepseek.com"`），无法切换到其他模型。项目 `.env.example` 已预配置了 DeepSeek 和 MiMo 两个供应商，但 `config.py` 和 `analyzer.py` 仍只读取 `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL`，代码与配置脱节。

### 1.2 目标用户
全球产品侦察兵的用户——跨境电商卖家，需要根据不同场景选择合适的 AI 模型（速度 vs 质量 vs 成本）。

### 1.3 核心需求
1. 支持多个 AI 供应商（DeepSeek、MiMo、OpenAI 等），通过配置文件选择
2. 用户可在 Streamlit 侧边栏实时切换供应商和模型
3. 切换后立即生效，无需重启应用
4. 未配置任何 API Key 时，自动降级为本地模拟分析

---

## 2. 系统设计

### 2.1 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `src/config.py` | **重写** | 新增 `get_llm_config()` 函数，读取 `ACTIVATE_PROVIDER` + 各供应商独立配置 |
| `src/analyzer.py` | **修改** | `analyze_products()` 和 `_analyze_batch()` 使用通用 LLM 配置替代硬编码 DeepSeek |
| `app.py` | **修改** | 侧边栏新增"🤖 AI 模型"选择器；移除硬编码 "DeepSeek API" 显示 |
| `.env.example` | **微调** | 确保现有配置项与新代码对齐 |

### 2.2 数据流

```
用户点击侧边栏 "🤖 AI 模型" 选择器
        ↓
st.session_state["llm_provider"] + st.session_state["llm_model"] 更新
        ↓
用户点击 "开始分析"
        ↓
app.py 调用 analyze_products(products, progress_callback)
        ↓
analyze_products() 读取 get_config() 获取当前激活的 provider/model/api_key/base_url
        ↓
OpenAI(api_key=..., base_url=...) 创建客户端
        ↓
client.chat.completions.create(model=当前模型, ...)
        ↓
返回分析结果
```

### 2.3 供应商配置注册表

在 `src/config.py` 中定义供应商注册表：

```python
LLM_PROVIDERS = {
    "deepseek": {
        "name": "DeepSeek",
        "base_url_key": "DEEPSEEK_BASE_URL",
        "api_key_key": "DEEPSEEK_API_KEY",
        "models": ["deepseek-v4-flash", "deepseek-v4-pro"],
        "default_model": "deepseek-v4-flash",
    },
    "mimo": {
        "name": "小米 MiMo",
        "base_url_key": "MIMO_BASE_URL",
        "api_key_key": "MIMO_API_KEY",
        "models": ["mimo-v2.5-pro", "mimo-v2-pro"],
        "default_model": "mimo-v2.5-pro",
    },
    "openai": {
        "name": "OpenAI",
        "base_url_key": "OPENAI_BASE_URL",
        "api_key_key": "OPENAI_API_KEY",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"],
        "default_model": "gpt-4o-mini",
    },
}
```

---

## 3. 接口定义

### 3.1 `src/config.py` — 新增函数

```python
def get_llm_config() -> dict:
    """
    获取当前激活的 LLM 供应商配置。

    读取 ACTIVATE_PROVIDER 环境变量确定供应商，
    读取 ACTIVATE_MODEL 环境变量确定模型，
    自动拼接对应的 API_KEY 和 BASE_URL。

    Returns:
        {
            "provider": str,          # 供应商标识，如 "deepseek"
            "provider_name": str,     # 显示名称，如 "DeepSeek"
            "model": str,             # 模型名，如 "deepseek-v4-flash"
            "api_key": str,           # API Key
            "base_url": str,          # API Base URL
            "configured": bool,       # 是否已配置（api_key 非空）
        }

    Raises:
        无。所有异常静默降级。
    """
```

**实现逻辑**：
1. 读取 `ACTIVATE_PROVIDER`（默认 `"deepseek"`）
2. 在 `LLM_PROVIDERS` 注册表中查找供应商配置
3. 读取该供应商的 `API_KEY` 和 `BASE_URL`
4. 读取 `ACTIVATE_MODEL`（默认使用供应商的 `default_model`）
5. 如果 `ACTIVATE_MODEL` 不在该供应商的 `models` 列表中，使用 `default_model`
6. 返回配置字典

**保留向后兼容**：`get_config()` 中原有的 `deepseek_api_key` 和 `deepseek_model` 字段保留，但 `analyzer.py` 不再使用它们。

### 3.2 `src/analyzer.py` — 修改函数

#### `_analyze_batch(batch, client, cfg)` → `_analyze_batch(batch, client, llm_cfg)`

```python
def _analyze_batch(batch: list[dict], client, llm_cfg: dict) -> list[dict]:
    """
    调用 LLM API 分析一批产品。

    Args:
        batch: 产品字典列表（最多 6 个）
        client: OpenAI SDK 客户端实例
        llm_cfg: get_llm_config() 返回的配置字典

    Returns:
        分析结果字典列表
    """
```

**关键变更**：
- `model` 参数从 `cfg["deepseek_model"]` 改为 `llm_cfg["model"]`

#### `analyze_products(products, progress_callback)` 内部变更

```python
def analyze_products(products, progress_callback=None):
    llm_cfg = get_llm_config()  # 替代 get_config()
    api_key = llm_cfg["api_key"]

    if not api_key:
        # 无 API Key → 全部 mock
        ...

    client = OpenAI(
        api_key=api_key,
        base_url=llm_cfg["base_url"],  # 替代硬编码 "https://api.deepseek.com"
        timeout=120,
    )

    for batch_start in range(0, total, BATCH_SIZE):
        batch_results = _analyze_batch(batch, client, llm_cfg)  # 传入 llm_cfg
        ...
```

### 3.3 `app.py` — 侧边栏变更

#### 新增：AI 模型选择器

位置：侧边栏，"选择数据源" 下方，API 配置状态上方。

```python
# ---- AI 模型选择器 ----
from src.config import get_llm_config, LLM_PROVIDERS

llm_cfg = get_llm_config()

st.sidebar.subheader("🤖 AI 模型")

# 供应商选择
provider_names = {k: v["name"] for k, v in LLM_PROVIDERS.items()}
selected_provider = st.sidebar.selectbox(
    "AI 供应商",
    options=list(provider_names.keys()),
    format_func=lambda k: provider_names[k],
    index=list(LLM_PROVIDERS.keys()).index(llm_cfg["provider"]),
    key="llm_provider",
)

# 模型选择
available_models = LLM_PROVIDERS[selected_provider]["models"]
selected_model = st.sidebar.selectbox(
    "模型",
    options=available_models,
    index=available_models.index(llm_cfg["model"]) if llm_cfg["model"] in available_models else 0,
    key="llm_model",
)
```

#### 修改：API 配置状态显示

从硬编码的 "DeepSeek API: ✅ 已配置" 改为动态显示当前供应商：

```python
# 修改前
st.sidebar.caption(f"DeepSeek API: {'✅ 已配置' if api_ok else '⚠️ 未配置'}")

# 修改后
provider_name = LLM_PROVIDERS[llm_cfg["provider"]]["name"]
model_name = llm_cfg["model"]
if llm_cfg["configured"]:
    st.sidebar.caption(f"✅ {provider_name} {model_name}")
else:
    st.sidebar.caption(f"⚠️ {provider_name} 未配置（使用模拟分析）")
    st.sidebar.info(
        f"💡 在 `.env` 文件中配置 `{llm_cfg['provider'].upper()}_API_KEY`\n"
        f"即可启用 {provider_name} AI 分析。"
    )
```

---

## 4. 数据模型

### 4.1 Session State 新增字段

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `llm_provider` | str | 当前选中的供应商 key（如 `"deepseek"`） |
| `llm_model` | str | 当前选中的模型名（如 `"deepseek-v4-flash"`） |

**注意**：这两个字段仅用于 UI 选择器的 `key`，实际的 API 调用仍从环境变量读取。用户在侧边栏切换模型后，需要写回环境变量或 session state 供 `get_llm_config()` 读取。

**实现方案**：`get_llm_config()` 优先读取 `st.session_state` 中的 `llm_provider` / `llm_model`，然后回退到环境变量。

### 4.2 配置文件变更

`.env.example` 已有完整配置，无需修改。确认以下字段存在：

```bash
ACTIVATE_PROVIDER=deepseek
ACTIVATE_MODEL=deepseek-v4-flash

DEEPSEEK_API_KEY=your-deepseek-api-key-here
DEEPSEEK_BASE_URL=https://api.deepseek.com

MIMO_API_KEY=your-mimo-api-key-here
MIMO_BASE_URL=https://api.xiaomimimo.com/v1

OPENAI_API_KEY=your-openai-api-key-here
OPENAI_BASE_URL=https://api.openai.com/v1
```

---

## 5. UI 设计

### 5.1 侧边栏布局（变更后）

```
⚙️ 设置
│
├─ 📌 页面导航
│   ├─ 🔍 实时选品
│   └─ 📚 历史记录
│
├─ [选择数据源]
│   └─ Amazon Best Sellers
│
├─ 📊 数据状态：📄 JSON 数据（本地采集）
│
├─ ─────────────
│
├─ 🤖 AI 模型              ← 新增
│   ├─ AI 供应商: [DeepSeek ▼]
│   └─ 模型:     [deepseek-v4-flash ▼]
│
├─ ─────────────
│
├─ ✅ DeepSeek deepseek-v4-flash   ← 修改（动态显示）
│
├─ ─────────────
│
└─ 📦 历史记录：0 条产品数据
```

### 5.2 切换行为

- 用户在侧边栏切换供应商/模型 → `st.session_state` 更新 → `st.rerun()`
- 下一次点击"开始分析"时，使用新选择的模型
- 切换不会中断当前正在运行的分析

---

## 6. 验收标准

### 6.1 功能验收

| # | 验收条件 | 验证方法 |
|---|---------|---------|
| 1 | `.env` 设置 `ACTIVATE_PROVIDER=mimo` 后，分析使用 MiMo API | 检查 `get_llm_config()["provider"] == "mimo"` |
| 2 | 侧边栏可切换供应商和模型 | UI 操作验证 |
| 3 | 切换后点击"开始分析"，使用新模型 | 检查 API 调用的 `model` 参数 |
| 4 | 未配置 API Key 时，自动降级为模拟分析 | 删除 Key 后运行 |
| 5 | 侧边栏正确显示当前供应商名和模型名 | UI 验证 |
| 6 | `python -m py_compile src/config.py` 通过 | 终端执行 |
| 7 | `python -m py_compile src/analyzer.py` 通过 | 终端执行 |
| 8 | `python -m py_compile app.py` 通过 | 终端执行 |

### 6.2 非功能验收

| # | 验收条件 |
|---|---------|
| 9 | 向后兼容：`get_config()` 原有字段不变，不破坏现有调用方 |
| 10 | 新增供应商时，只需在 `LLM_PROVIDERS` 注册表中添加条目 + `.env` 新增配置 |
| 11 | 不引入新的 Python 依赖（继续使用 `openai` SDK） |
| 12 | `daily_scrape.py` 不受影响（仍使用 `get_config()` 中的原有字段） |

---

## 7. 不在本次范围内

- UI 上动态新增自定义供应商（本次仅支持注册表中的预定义供应商）
- 模型响应质量对比功能
- 多模型并行分析 / 自动选择最佳结果
- 流式输出（Streaming）
