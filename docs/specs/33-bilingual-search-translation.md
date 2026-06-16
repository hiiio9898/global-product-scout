# Spec 33：中文搜索自动翻译（中英互译选品）

**版本**：v1.0
**状态**：✅ 已实现
**创建日期**：2026-06-16
**前置依赖**：Spec 7（指定选品搜索）、Spec 0A（多模型支持）、Spec 19（指数退避重试）

---

## 1. 需求描述

### 1.1 背景
当前「指定选品」页面（`_render_targeted_page`）要求用户输入**英文关键词**搜索（placeholder 提示"输入英文关键词效果最佳"），且搜索回来的产品标题/描述均为英文。对中国卖家而言，用英文构思搜索词、阅读英文产品信息存在门槛。

### 1.2 目标
- 用户可直接输入**中文关键词**，系统自动翻译为英文去各平台搜索
- 搜索结果的**产品标题自动翻译为中文**展示，同时保留英文原文对照
- 翻译复用现有 AI 供应商（mimo/deepseek/openai），**不引入额外翻译服务**

### 1.3 用户故事
- 作为中国卖家，我想输入"便携式榨汁机"就能搜到对应产品，而不是先想好"portable blender"
- 搜索结果我想看到中文名快速判断品类，必要时再看英文原文

### 1.4 边界约束
- 翻译**可选**：用户已有英文关键词时直接用，不强翻
- 翻译失败时降级为原文展示，**不阻塞搜索流程**
- 翻译调用须有超时、重试、错误提示（遵循 AGENTS.md「AI 分析容错」规则）
- 仅翻译**搜索关键词**和**产品标题**，不翻译价格/评分等数值字段

---

## 2. 系统设计

### 2.1 改动文件清单
| 文件 | 类型 | 说明 |
|------|------|------|
| `src/translator.py` | **新建** | 翻译模块：关键词翻译 + 产品标题批量翻译 |
| `app.py` | 修改 | 「指定选品」页接入翻译；侧边栏加翻译开关 |
| `.env.example` | 修改 | 新增 `TRANSLATION_ENABLED` / `TRANSLATION_BATCH_SIZE` |

### 2.2 数据流
```
用户输入(中文/英文)
   ↓ contains_chinese() ?  → translate_keyword()  → 英文搜索词
英文搜索词 → 现有 search_func(region) → 英文产品列表
   ↓ translate_product_titles() → 每个产品加 title_zh
展示: 中文标题(title_zh) + 英文原文(title) + AI 分析
```

### 2.3 复用现有基础设施
- AI 调用：复用 `src.config.get_llm_config()` + OpenAI SDK（同 analyzer.py）
- 重试机制：复用 analyzer 的指数退避 + 429 特殊处理 + 思考模型 `reasoning_content` 回退
- JSON 解析：复用 analyzer 的 `_strip_markdown_json` / `_extract_json_array` 容错

---

## 3. 接口设计

### 3.1 `src/translator.py`
```python
def contains_chinese(text: str) -> bool
    """检测文本是否含中文字符（CJK 统一汉字区间）。"""

def is_translation_enabled() -> bool
    """读取 TRANSLATION_ENABLED 配置（默认 True）。"""

def translate_keyword(text: str) -> dict
    """
    中文关键词 → 英文搜索词。
    Returns: {"success": bool, "original": str, "translated": str, "error": str|None}
    纯英文/不含中文 → 原样返回（translated = original, success=True）。
    API 未配置/失败 → 降级返回原文 + error。
    """

def translate_product_titles(titles: list[str], batch_size: int = 10) -> list[str]
    """
    批量翻译产品标题为中文，返回与输入等长的中文标题列表。
    失败项回退为原标题。用一次 JSON 数组调用翻译一批，减少 API 次数。
    """
```

### 3.2 数据结构
产品字典新增**运行时**字段（不写库）：
- `title_zh: str` — 中文标题；翻译失败时缺省，展示回退到 `title`

### 3.3 配置（`.env.example` 新增）
```bash
# 中文搜索翻译（Spec 33）
TRANSLATION_ENABLED=true         # 是否启用中文搜索/结果翻译
TRANSLATION_BATCH_SIZE=10        # 标题批量翻译每批数量
```

---

## 4. 错误处理
- API 未配置 → `translate_keyword` 返回原文，`translate_product_titles` 回退原标题，UI 提示"翻译未启用"
- API 调用失败（重试 3 次后）→ 同上降级，**不中断搜索**
- 翻译结果数量与输入不匹配 → 按顺序对齐，多余/不足项回退原文

---

## 5. 验收标准
- [ ] 输入"便携式榨汁机" → 翻译为 "portable blender" 类英文词 → 搜索返回结果
- [ ] 结果列表标题显示中文，下方显示英文原文
- [ ] 输入纯英文 "yoga mat" → 不调用翻译，直接搜索（向后兼容）
- [ ] 翻译开关关闭时，行为与改造前完全一致
- [ ] API 未配置/失败时，搜索仍能完成，标题显示英文原文 + 提示
- [ ] `python -m py_compile src/translator.py` 通过

---

## 6. 实施计划
1. 新建 `src/translator.py`（复用 analyzer 的调用/重试/解析模式）
2. 修改 `app.py` `_render_targeted_page`：搜索前翻译关键词、搜索后翻译标题、展示中英对照
3. 侧边栏加「🌐 中文搜索翻译」开关（session_state + 默认读 `TRANSLATION_ENABLED`）
4. 更新 `.env.example`
5. 本地 streamlit 验证：中文搜索 + 结果翻译 + 开关关闭回归

---

## 7. 未来扩展
- 描述/类目字段翻译
- 翻译结果缓存（避免重复翻译相同标题，省 API 费用）
- 可选独立翻译 API（如 DeepL/Google）作为 AI 之外的备选
