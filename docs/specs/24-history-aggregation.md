# Spec 24：历史数据聚合查询

**版本**：v1.0
**状态**：📋 待实现
**创建日期**：2026-06-03

---

## 1. 需求描述

### 1.1 背景
无法回答"某个品类过去一个月评分变化趋势"、"本月推荐产品数"等聚合查询。

### 1.2 核心需求
1. 品类趋势查询：某关键词产品的排名/评分变化
2. 平台统计：各平台产品数、推荐率、平均评分
3. 时间范围筛选：按日期范围查看历史数据

---

## 2. 系统设计

### 2.1 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `src/database.py` | **修改** | 新增聚合查询函数 |
| `app.py` | **修改** | 历史记录页面新增趋势视图 |

### 2.2 新增函数

```python
def get_platform_stats(platform: str, days: int = 30) -> dict:
    """获取指定平台最近 N 天的统计数据。"""
    # 返回：{ total, recommended, avg_capacity, avg_profit }

def get_category_trend(keyword: str, days: int = 30) -> list:
    """获取关键词相关产品的趋势数据。"""
    # 返回：[{ scrape_time, avg_price, avg_rating, count }]

def get_date_range_products(start_date: str, end_date: str) -> list:
    """获取指定日期范围内的产品数据。"""
```

---

## 3. 验收标准

- [ ] 侧边栏可选择时间范围（7天/30天/90天/全部）
- [ ] 平台统计显示产品数、推荐率、平均评分
- [ ] 品类趋势显示折线图
- [ ] 所有现有测试通过
