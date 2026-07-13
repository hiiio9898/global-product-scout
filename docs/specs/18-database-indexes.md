# Spec 18：数据库索引优化

**版本**：v1.0
**状态**：✅ 已实现
**创建日期**：2026-06-03

---

## 1. 需求描述

### 1.1 背景
`src/database.py` 中频繁按 `(platform, region, scrape_time)` 组合查询，但无索引。当数据超过 1000 条时，历史记录页面加载明显变慢（>2s）。

### 1.2 核心需求
1. 为高频查询字段添加索引
2. 添加数据清理策略（保留最近 90 天）
3. 添加数据统计视图

---

## 2. 系统设计

### 2.1 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `src/database.py` | **修改** | `init_db()` 新增索引创建 + 数据清理 |

### 2.2 索引策略

```sql
-- 高频查询组合索引
CREATE INDEX IF NOT EXISTS idx_products_platform_region
    ON products(platform, region, scrape_time DESC);

-- 判定筛选索引
CREATE INDEX IF NOT EXISTS idx_products_verdict
    ON products(platform, final_verdict);

-- 收藏查询索引
CREATE INDEX IF NOT EXISTS idx_favorites_title_platform
    ON favorites(title, platform);

-- 数据清理：删除 90 天前的数据
DELETE FROM products WHERE scrape_time < datetime('now', '-90 days');
```

---

## 3. 验收标准

- [ ] `init_db()` 自动创建索引（幂等，不重复创建）
- [ ] 历史记录页面加载时间 < 1s（1000 条数据）
- [ ] 超过 90 天的旧数据自动清理
- [ ] 所有现有测试通过
