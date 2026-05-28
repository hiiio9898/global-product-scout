# Spec 1：采购成本持久化

**版本**：v1.0
**状态**：✅ 已实现并验收通过
**最后更新**：2026-05-28

---

## 1. 需求描述

### 1.1 背景
Spec 0-B 已实现利润计算器（侧边栏参数 + 产品卡片内利润试算），但用户输入的采购成本仅存在于 `st.session_state`，页面刷新或重新分析后丢失。需要将采购成本持久化到 SQLite 数据库。

### 1.2 核心需求
1. 数据库 products 表新增 `procurement_cost` 字段
2. 用户在产品 expander 内输入采购成本后，自动保存到数据库
3. 重新加载历史记录时，自动恢复之前保存的采购成本
4. 无额外 UI 变更（现有输入框不变）

---

## 2. 系统设计

### 2.1 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `src/database.py` | **修改** | products 表新增 `procurement_cost` 字段；新增 `save_procurement_cost()` 和 `get_procurement_cost()` |
| `app.py` | **修改** | 产品 expander 内 `st.number_input` 的 `value` 从数据库恢复；输入变更时调用 `save_procurement_cost()` |

### 2.2 数据库变更

```sql
-- 新增字段（ALTER TABLE，幂等）
ALTER TABLE products ADD COLUMN procurement_cost REAL DEFAULT 0.0;
```

### 2.3 数据流

```
用户在 expander 内输入采购成本
        ↓
st.number_input 的 value 变化（自动触发 rerun）
        ↓
调用 save_procurement_cost(title, scrape_time, procurement_cost)
        ↓
UPDATE products SET procurement_cost = ? WHERE title = ? AND scrape_time = ?
        ↓
下次加载时调用 get_procurement_cost(title, scrape_time) 恢复值
```

---

## 3. 接口定义

### 3.1 `src/database.py` — 新增函数

```python
def save_procurement_cost(
    title: str,
    scrape_time: str,
    procurement_cost: float,
    db_path: Optional[str] = None,
) -> bool:
    """
    保存单个产品的采购成本。

    Args:
        title:            产品标题
        scrape_time:      抓取时间（用于唯一标识同一次抓取）
        procurement_cost: 采购成本（人民币）
        db_path:          数据库路径

    Returns:
        True 如果保存成功，False 如果未找到匹配记录
    """

def get_procurement_cost(
    title: str,
    scrape_time: str,
    db_path: Optional[str] = None,
) -> float:
    """
    获取单个产品的已保存采购成本。

    Returns:
        采购成本（人民币），未找到返回 0.0
    """
```

### 3.2 `app.py` — 变更

在产品 expander 内的 `st.number_input` 中：
- `value` 从 `get_procurement_cost()` 恢复（而非硬编码 0.0）
- 使用 `st.number_input` 的 `on_change` 回调自动保存

---

## 4. 验收标准

| # | 验收条件 | 验证方法 |
|---|---------|---------|
| 1 | 数据库表包含 `procurement_cost` 字段 | 检查表结构 |
| 2 | 输入采购成本后自动保存 | 输入 → 检查数据库 |
| 3 | 重新加载后自动恢复 | 刷新页面 → 检查输入框值 |
| 4 | `python -m py_compile src/database.py` 通过 | 终端执行 |
| 5 | `python -m py_compile app.py` 通过 | 终端执行 |
| 6 | `daily_scrape.py` 不受影响 | 向后兼容 |

---

## 5. 不在本次范围内

- Cloud 端（SQLite ephemeral）的采购成本持久化（session state 已覆盖）
- 批量导入采购成本（如从 CSV/Excel）
- 采购成本与 1688 自动比价（阶段四功能）
