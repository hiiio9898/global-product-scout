# migrate-database — 数据库 Schema 迁移

## 触发条件
- 需要为 `products` 表新增字段
- 需要创建新表（如 `market_scans`、`favorites`）
- 需要新增索引优化查询性能
- 用户要求"添加数据库字段"、"建新表"等

## 核心架构

数据库模块 `src/database.py` 采用**幂等初始化 + ALTER TABLE 增量迁移**模式：
- `init_db()` — 幂等初始化，多次调用安全
- `_CREATE_*_SQL` — 建表 SQL 常量命名约定
- `ALTER TABLE ADD COLUMN` + `try/except` — 增量加字段
- `CREATE INDEX IF NOT EXISTS` — 幂等建索引

## 工作流

### 1. 新增字段（ALTER TABLE 模式）
在 `src/database.py` 的 `init_db()` 函数中，找到字段迁移列表：
```python
# 兼容：为已有表新增字段（如不存在）
for col, default in [
    ("procurement_cost", "REAL DEFAULT 0.0"),
    ("asin", "TEXT DEFAULT ''"),
    ("platform", "TEXT DEFAULT 'amazon'"),
    ("region", "TEXT DEFAULT 'us'"),
    ("currency", "TEXT DEFAULT 'USD'"),
    # ↓ 在这里新增
    ("new_field", "TEXT DEFAULT ''"),
]:
    try:
        conn.execute(f"ALTER TABLE products ADD COLUMN {col} {default}")
    except sqlite3.OperationalError:
        pass  # 字段已存在，忽略
```

**规则：**
- 必须提供 `DEFAULT` 值，确保已有行不受影响
- `try/except sqlite3.OperationalError: pass` 是标准模式，不要改为其他异常处理
- 字段类型用 `TEXT` / `REAL` / `INTEGER` / `TIMESTAMP`

### 2. 新增建表 SQL
新建表时，定义 `_CREATE_<TABLE_NAME>_SQL` 常量：
```python
_CREATE_<TABLE_NAME>_SQL = """
CREATE TABLE IF NOT EXISTS <table_name> (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    column1         TEXT,
    column2         REAL DEFAULT 0.0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""
```

然后在 `init_db()` 中执行：
```python
conn.execute(_CREATE_<TABLE_NAME>_SQL)
```

**现有表参考：**
- `_CREATE_TABLE_SQL` → `products` 表
- `_CREATE_MARKET_SCANS_SQL` → `market_scans` 表
- `favorites` 表在 `_init_favorites_table()` 中惰性创建

### 3. 新增索引
在 `init_db()` 的索引列表中新增：
```python
for idx_sql in [
    "CREATE INDEX IF NOT EXISTS idx_products_platform_region ON products(platform, region, scrape_time DESC)",
    "CREATE INDEX IF NOT EXISTS idx_products_verdict ON products(platform, analysis_json)",
    "CREATE INDEX IF NOT EXISTS idx_favorites_title_platform ON favorites(title, platform)",
    # ↓ 在这里新增
    "CREATE INDEX IF NOT EXISTS idx_<table>_<cols> ON <table>(<columns>)",
]:
    try:
        conn.execute(idx_sql)
    except sqlite3.OperationalError:
        pass  # 索引已存在或表不存在
```

**索引命名约定：** `idx_<表名>_<列名>`

### 4. 更新数据访问函数
新增字段后，需要更新相关函数：
- `save_products()` — INSERT 语句中加入新字段
- `get_all_products()` / `query_products()` — SELECT 语句中加入新字段
- 如有新表，新增对应的 CRUD 函数

### 5. 测试验证
```bash
python -m py_compile src/database.py
pytest tests/

# 手动验证数据库
python -c "
from src.database import init_db, get_product_count
init_db()
print('产品数:', get_product_count())
"
```

### 6. 交付说明
告知用户：
- 新增了哪些字段/表/索引
- 默认值是什么
- 是否需要清理旧数据
- 对现有功能的影响

## 注意事项
- 所有迁移必须是**幂等**的（多次执行不出错）
- `ALTER TABLE` 不能删除列、不能修改列类型（SQLite 限制）
- 如需复杂迁移（重命名列、修改类型），需创建新表 → 复制数据 → 删除旧表 → 重命名
- `init_db()` 被 `_get_connection()` 自动调用，无需手动触发
- 90天数据清理逻辑在 `init_db()` 末尾，新表如需清理请自行添加
