# add-analysis-type — 新增分析维度

## 触发条件
- 用户要求"新增利润计算"、"添加竞争度打分"、"增加市场趋势分析"等
- 需要为产品分析添加新的评估维度

## 工作流

### 1. 需求确认
- 确认新分析维度的名称和目的
- 确认输出格式（评分、文字描述、等级标签等）
- 确认是否需要额外的输入数据（如采购成本、物流费用等）

### 2. 设计数据结构
在 `src/analyzer.py` 中扩展分析结果字典：
```python
# 在 BATCH_SYSTEM_PROMPT 中新增字段要求
# 在 _validate_result() 中新增字段验证
# 注意：无 API 密钥时 analyzer 返回 error dict（parse_error: True, final_verdict: "cautious"）
```
- 确保新增字段有默认值，不影响现有逻辑

### 3. 更新分析 Prompt
在 `src/analyzer.py` 中：
- 更新 `BATCH_SYSTEM_PROMPT`（批量分析，每批 6 个产品），在输出 JSON 格式要求中新增字段
- 确保 Prompt 明确描述新维度的计算/评估逻辑
- 更新 `_validate_result()` 以验证新字段存在且格式正确

### 4. 更新前端展示
在 `app.py` 中：
- 在产品分析卡片中展示新维度
- 选择合适的展示组件（`st.metric`/`st.progress`/文本标签）

### 5. 更新测试
在 `tests/test_basic.py` 中：
- 验证新字段在 mock 分析结果中存在
- 验证返回字典包含新字段

### 6. 验证
- `python -m py_compile src/analyzer.py` 通过
- `pytest tests/` 通过
- Streamlit 界面正常展示新维度

### 7. 交付说明
告知用户：
- 新增了哪些分析字段
- Prompt 变更要点
- 是否需要更新 `.env` 配置
- 如涉及额外 API 调用，说明费用影响

## 注意事项
- 新增字段必须有默认值，确保向后兼容
- 无 API 密钥时 analyzer 返回 error dict（`parse_error: True`），新增字段需有默认值以兼容此场景
- 不修改与当前任务无关的分析逻辑
- 当前 AI 分析支持多模型切换（DeepSeek / MiMo / OpenAI），新增维度对所有模型生效
- 分析结果支持三种模式：单品分析（`analyze_products`）、品类报告（`analyze_category_report`）、跨市场对比（`analyze_market_comparison`）
