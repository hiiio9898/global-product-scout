# Spec 6：Google Trends 趋势监控

**版本**：v1.0
**状态**：✅ 已实现并验收通过
**最后更新**：2026-05-28

---

## 1. 需求描述

### 1.1 背景
Best Sellers 榜单只代表"现在热销"，选品需要预判"未来什么会火"。接入 Google Trends 趋势数据，让工具具备前瞻性。

### 1.2 核心需求
1. 新建 `src/trends.py`，实现 `get_trends(keyword)` 函数
2. 查询过去 3 个月的搜索热度趋势
3. 在分析结果中新增 `trend_direction` 维度（上升/平稳/下降）
4. 分析卡片中展示趋势图标 📈/➡️/📉

### 1.3 风险评估

| 风险 | 级别 | 应对 |
|------|------|------|
| pytrends 已归档（2025-04-17） | 🟡 中 | 仍可使用，但未来可能失效 |
| 频率限制（约 1400 次请求后被限制） | 🟡 中 | 每次只查 1 个关键词，间隔 5 秒 |
| 需要 60 秒冷却期 | 🟡 中 | 降级友好，失败不影响主流程 |
| 网络环境可能无法访问 Google | 🔴 高 | 失败时返回 None，不展示趋势 |

**关键决策**：pytrends 仅作为**可选增强**功能。失败时降级为不展示趋势维度，不影响其他分析维度。**不在 Streamlit Cloud 分析流程中调用**（频率限制风险），仅在手动分析时可选启用。

---

## 2. 系统设计

### 2.1 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `src/trends.py` | **新建** | Google Trends 查询模块 |
| `src/analyzer.py` | **修改** | `_mock_analyze()` 新增 trend_direction 维度 |
| `app.py` | **修改** | 分析卡片中展示趋势图标 |
| `requirements.txt` | **修改** | 新增 pytrends 依赖 |

### 2.2 模块设计

```python
# src/trends.py

def get_trend_direction(keyword: str) -> dict:
    """
    查询关键词的 Google Trends 趋势方向。

    Args:
        keyword: 搜索关键词（如 "water bottle"）

    Returns:
        {
            "direction": str,     # "rising" | "stable" | "declining"
            "interest": int,      # 最近一周兴趣值 (0-100)
            "avg_interest": float, # 3 个月平均兴趣值
            "available": bool,    # 是否成功获取数据
            "error": str | None,  # 失败时的错误信息
        }
    """
```

### 2.3 趋势判断逻辑

```python
# 从 interest_over_time 数据中提取趋势
recent = interest_data[-4:]   # 最近 4 周
overall_avg = interest_data.mean()

if recent.mean() > overall_avg * 1.2:
    direction = "rising"      # 上升
elif recent.mean() < overall_avg * 0.8:
    direction = "declining"   # 下降
else:
    direction = "stable"      # 平稳
```

### 2.4 UI 展示

在分析卡片的五维度评分中新增趋势指标：

```
📊 市场容量 8/10  |  ⚔️ 竞争程度 7/10  |  💰 利润潜力 6/10
🎓 新手友好 9/10  |  🌡️ 季节风险 2/10  |  📈 趋势：上升
```

趋势图标映射：
- `rising` → `📈 上升`
- `stable` → `➡️ 平稳`
- `declining` → `📉 下降`
- 无数据 → 不显示

---

## 3. 接口定义

### 3.1 `src/trends.py`

```python
def get_trend_direction(keyword: str) -> dict:
    """
    查询关键词的 Google Trends 趋势方向。

    使用 pytrends 库查询过去 3 个月的搜索热度。
    失败时返回 available=False，不影响主流程。

    注意：
        - 频率限制：每次查询间隔 5 秒
        - 网络要求：需能访问 Google
        - pytrends 已归档，未来可能失效
    """
```

### 3.2 `requirements.txt` 变更

```
pytrends>=4.9.2
```

### 3.3 分析 Prompt 变更

**不在 SYSTEM_PROMPT 中要求 AI 返回 trend_direction**。趋势数据由 pytrends 独立获取，不依赖 AI 推断。

---

## 4. 验收标准

| # | 验收条件 | 验证方法 |
|---|---------|---------|
| 1 | `get_trend_direction()` 返回正确结构 | 单元测试 |
| 2 | 成功时返回 direction + interest | 实际调用（需网络） |
| 3 | 失败时返回 available=False + error | 模拟网络错误 |
| 4 | `requirements.txt` 包含 pytrends | 检查文件 |
| 5 | `python -m py_compile src/trends.py` 通过 | 终端执行 |
| 6 | 主分析流程不受趋势查询影响 | 趋势失败时仍能完成分析 |

---

## 5. 不在本次范围内

- 分析 Prompt 中让 AI 推断趋势（独立获取，不依赖 AI）
- Streamlit Cloud 自动趋势分析（频率限制风险）
- 多关键词批量趋势对比
- 趋势数据持久化到数据库
