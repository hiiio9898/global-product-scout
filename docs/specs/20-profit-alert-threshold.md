# Spec 20：利润预警阈值

**版本**：v1.0
**状态**：📋 待实现
**创建日期**：2026-06-03

---

## 1. 需求描述

### 1.1 背景
利润为负或毛利极低时无任何提示，用户可能误判产品盈利性。

### 1.2 核心需求
1. 毛利 <0% 时显示红色警告
2. 毛利 0-15% 时显示黄色提示
3. 毛利 >15% 时正常显示（绿色）
4. 无采购成本时显示 "N/A"（已有）

---

## 2. 系统设计

### 2.1 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `app.py` | **修改** | `_render_live_page()` 和 `_render_targeted_page()` 中利润展示区添加预警 |

### 2.2 预警逻辑

```python
margin = profit_result["margin_pct"]

if not profit_result["has_procurement"]:
    st.caption("请输入采购成本以计算利润")
elif margin < 0:
    st.error(f"利润为负（毛利率 {margin}%）— 建议放弃该产品")
elif margin < 15:
    st.warning(f"利润微薄（毛利率 {margin}%）— 需要优化成本结构")
elif margin < 30:
    st.info(f"利润尚可（毛利率 {margin}%）")
else:
    st.success(f"利润可观（毛利率 {margin}%）")
```

---

## 3. 验收标准

- [ ] 负利润显示红色错误提示
- [ ] 0-15% 显示黄色警告
- [ ] >15% 正常显示
- [ ] 无采购成本时显示 N/A
- [ ] 所有现有测试通过
