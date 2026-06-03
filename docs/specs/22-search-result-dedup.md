# Spec 22：搜索结果去重

**版本**：v1.0
**状态**：📋 待实现
**创建日期**：2026-06-03

---

## 1. 需求描述

### 1.1 背景
同一产品可能因不同变体（颜色/尺寸）在搜索结果中出现多次，占用分析配额。

### 1.2 核心需求
1. 按 ASIN 去重，仅保留评分最高的变体
2. 去重后显示"去重前 X 个 → 去重后 Y 个"

---

## 2. 系统设计

### 2.1 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `src/utils.py` | **修改** | 新增 `deduplicate_products()` 函数 |
| `app.py` | **修改** | `_render_targeted_page()` 中搜索完成后调用去重 |

### 2.2 去重逻辑

```python
def deduplicate_products(products: list) -> list:
    """按 ASIN 去重，保留评分最高的变体。"""
    seen = {}
    for p in products:
        asin = p.get("asin", "")
        if not asin:
            result.append(p)
            continue
        rating = float(p.get("rating", 0) or 0)
        if asin not in seen or rating > seen[asin][1]:
            seen[asin] = (p, rating)
    return [v[0] for v in seen.values()]
```

---

## 3. 验收标准

- [ ] 同一 ASIN 的多个变体只保留评分最高的
- [ ] 无 ASIN 的产品保留
- [ ] 去重前后数量差异显示在 UI 上
- [ ] 所有现有测试通过
