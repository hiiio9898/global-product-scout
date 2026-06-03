# Spec 19：指数退避重试

**版本**：v1.0
**状态**：📋 待实现
**创建日期**：2026-06-03

---

## 1. 需求描述

### 1.1 背景
`src/analyzer.py` 中 AI 分析失败后固定 2 秒重试，在 API 服务高峰期容易连续失败。应改为指数退避策略。

### 1.2 核心需求
1. 重试间隔从固定 2s 改为指数退避：2s → 4s → 8s
2. 429 限流时使用更长退避（10s → 20s）
3. 记录重试次数，用户可看到

---

## 2. 系统设计

### 2.1 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `src/analyzer.py` | **修改** | `_analyze_batch()` 重试逻辑改为指数退避 |

### 2.2 重试策略

```python
import time
import random

MAX_RETRIES = 2
BASE_DELAY = 2  # 秒

for attempt in range(MAX_RETRIES + 1):
    try:
        response = client.chat.completions.create(...)
        break
    except Exception as e:
        if attempt == MAX_RETRIES:
            raise
        delay = BASE_DELAY * (2 ** attempt) + random.uniform(0, 1)
        if "429" in str(e):
            delay = 10 * (2 ** attempt)  # 限流时用更长退避
        time.sleep(delay)
```

---

## 3. 验收标准

- [ ] 首次失败等待 ~2s，第二次 ~4s
- [ ] 429 限流时等待 ~10s
- [ ] 最多重试 2 次后报错
- [ ] 所有现有测试通过
