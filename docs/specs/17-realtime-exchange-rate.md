# Spec 17：实时汇率集成

**版本**：v1.0
**状态**：📋 待实现
**创建日期**：2026-06-03

---

## 1. 需求描述

### 1.1 背景
当前汇率硬编码在 `src/platforms.py` 的 `PLATFORMS` 字典中（如 USD → 7.24 CNY），实际 CNY/USD 波动范围 6.8-8.0。利润计算结果可能偏差 6% 以上，对高单价产品影响显著。

### 1.2 目标
利润计算使用接近实时的汇率数据，提升成本估算准确性。

### 1.3 核心需求
1. 集成免费汇率 API（如 OpenExchangeRates 或 exchangerate-api.com）
2. 每天自动更新一次汇率，缓存到本地
3. 离线时降级使用硬编码默认值
4. 侧边栏显示当前汇率来源和更新时间

---

## 2. 系统设计

### 2.1 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `src/exchange_rate.py` | **新建** | 汇率获取模块（API 调用 + 本地缓存 + 降级） |
| `src/config.py` | **修改** | 新增 `EXCHANGE_RATE_API_KEY` 配置项 |
| `src/platforms.py` | **修改** | `get_region_info()` 中汇率优先从实时数据读取 |
| `app.py` | **修改** | 侧边栏显示汇率状态 |
| `.env.example` | **修改** | 新增 `EXCHANGE_RATE_API_KEY` 占位 |

### 2.2 数据流

```
应用启动 / 首次使用利润计算
    ↓
exchange_rate.py: get_rate(from='USD', to='CNY')
    ↓
检查本地缓存（data/exchange_rates.json）
    ↓
缓存有效（<24h）→ 返回缓存值
    ↓
缓存过期 → 调用免费 API（exchangerate-api.com，无 Key 每月 1500 次）
    ↓
API 成功 → 更新缓存 → 返回新值
API 失败 → 降级使用 PLATFORMS 中硬编码值 → 返回默认值
```

### 2.3 缓存策略

```python
# data/exchange_rates.json
{
    "base": "USD",
    "rates": {"CNY": 7.24, "EUR": 0.92, "GBP": 0.79, ...},
    "updated_at": "2026-06-03T10:00:00Z",
    "source": "exchangerate-api.com"
}
```

### 2.4 降级策略

| 场景 | 行为 |
|------|------|
| 无 API Key + 无缓存 | 使用 `platforms.py` 硬编码值 |
| 有 API Key + 无缓存 | 调用 API，失败则降级 |
| 有 API Key + 有缓存 | 缓存 <24h 直接用，>24h 刷新 |
| API 限流（429） | 保留上次缓存，标记 `stale` |

---

## 3. 验收标准

- [ ] 应用启动时自动加载汇率缓存
- [ ] 侧边栏显示"汇率：1 USD = X.XX CNY（更新于 X 小时前）"
- [ ] 离线环境下应用不崩溃，使用默认汇率
- [ ] 利润计算结果使用实时汇率
- [ ] 所有现有测试通过
