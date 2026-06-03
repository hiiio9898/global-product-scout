# Spec 21：流式 UI 更新

**版本**：v1.0
**状态**：📋 待实现
**创建日期**：2026-06-03

---

## 1. 需求描述

### 1.1 背景
用户点击"开始分析"后，必须等所有产品分析完才能看到结果。30 个产品要等 3-5 分钟，体验差。

### 1.2 核心需求
1. 分析完一个产品就立即渲染一个卡片，而非等全部完成
2. 用户第一时间看到第一个推荐产品
3. 进度条仍然显示整体进度

---

## 2. 系统设计

### 2.1 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `app.py` | **修改** | `_render_live_page()` 和 `_render_targeted_page()` 中分析流程改为逐个渲染 |

### 2.2 实现策略

当前流程：
```
analyze_products() → 等待全部完成 → 渲染所有卡片
```

改为：
```
analyze_products(callback) → 每完成一个 → callback 立即渲染该卡片
```

### 2.3 技术要点

`analyze_products()` 已有 `progress_callback(done, total)` 参数。扩展为完成回调：
```python
def analyze_products(products, progress_callback=None, on_complete_callback=None):
    for i, batch in enumerate(batches):
        results = _analyze_batch(batch)
        for r in results:
            all_results.append(r)
            if on_complete_callback:
                on_complete_callback(i * batch_size + j, len(products), r)
        progress_callback(...)
```

---

## 3. 验收标准

- [ ] 第一个产品分析完成后立即显示卡片
- [ ] 进度条正常更新
- [ ] 所有产品分析完成后显示完整列表
- [ ] 所有现有测试通过
