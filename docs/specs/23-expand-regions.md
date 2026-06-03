# Spec 23：扩展地区站点支持

**版本**：v1.0
**状态**：📋 待实现
**创建日期**：2026-06-03

---

## 1. 需求描述

### 1.1 背景
当前仅支持 US/UK/JP/DE 四个地区，缺少法国、意大利、西班牙、加拿大、澳洲等热门跨境电商市场。

### 1.2 核心需求
1. Amazon 新增：FR/IT/ES/CA/AU
2. eBay 新增：AU/CA
3. 每个地区配置完整的域名、货币、汇率

---

## 2. 系统设计

### 2.1 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `src/platforms.py` | **修改** | PLATFORMS 字典新增地区条目 |

### 2.2 新增地区配置

```python
# Amazon 新增地区
"fr": {"name": "法国", "domain": "amazon.fr", "currency": "EUR", "exchange_rate": 7.85},
"it": {"name": "意大利", "domain": "amazon.it", "currency": "EUR", "exchange_rate": 7.85},
"es": {"name": "西班牙", "domain": "amazon.es", "currency": "EUR", "exchange_rate": 7.85},
"ca": {"name": "加拿大", "domain": "amazon.ca", "currency": "CAD", "exchange_rate": 5.30},
"au": {"name": "澳洲", "domain": "amazon.com.au", "currency": "AUD", "exchange_rate": 4.80},

# eBay 新增地区
"au": {"name": "澳洲", "domain": "www.ebay.com.au", "currency": "AUD", "exchange_rate": 4.80},
"ca": {"name": "加拿大", "domain": "www.ebay.ca", "currency": "CAD", "exchange_rate": 5.30},
```

---

## 3. 验收标准

- [ ] 侧边栏地区选择器显示新增地区
- [ ] 选择新地区后抓取对应站点
- [ ] 利润计算使用正确汇率
- [ ] 所有现有测试通过
