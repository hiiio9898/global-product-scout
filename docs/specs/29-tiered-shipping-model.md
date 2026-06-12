# Spec 29：运费分档模型

**版本**：v1.0
**状态**：📋 待实现
**创建日期**：2026-06-10

---

## 1. 需求描述

### 1.1 背景
当前运费是固定值（Amazon默认15元/件），50g手机壳和5kg家电算同样运费，利润计算对重货完全不准。

### 1.2 核心需求
1. 运费按重量/体积分3档：轻件、中件、重件
2. 用户可在侧边栏选择档位或自定义
3. 默认值合理（轻件8元、中件20元、重件50元）
4. 向后兼容：不填时使用当前默认值

---

## 2. 系统设计

### 2.1 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `src/config.py` | **修改** | `get_profit_defaults()` 增加 `shipping_tiers` 配置 |
| `src/calculator.py` | **修改** | `calculate_profit()` 支持 `shipping_tier` 参数 |
| `app.py` | **修改** | 侧边栏增加运费档位选择器 |

### 2.2 运费档位定义

```python
SHIPPING_TIERS = {
    "light":  {"label": "轻件 <500g",  "cny": 8.0},
    "medium": {"label": "中件 500g-2kg", "cny": 20.0},
    "heavy":  {"label": "重件 >2kg",   "cny": 50.0},
    "custom": {"label": "自定义",       "cny": None},
}
```

### 2.3 侧边栏UI

```python
shipping_tier = st.selectbox(
    "📦 运费档位",
    options=list(SHIPPING_TIERS.keys()),
    format_func=lambda k: SHIPPING_TIERS[k]["label"],
)
if shipping_tier == "custom":
    shipping_cny = st.number_input("自定义运费(元)", value=15.0)
else:
    shipping_cny = SHIPPING_TIERS[shipping_tier]["cny"]
```

---

## 3. 验收标准

- [ ] 侧边栏显示运费档位选择器
- [ ] 选择档位后利润自动重新计算
- [ ] 轻件/中件/重件默认值合理
- [ ] 自定义档位可手动输入
- [ ] 不选择时使用当前默认值（向后兼容）
- [ ] 所有现有测试通过
