"""
数据库模块 — SQLite 数据持久化与历史记录查询。

数据库文件：data/products.db（自动创建 data 目录）
表结构：
    products — 存储每次抓取的产品数据及其 AI 分析结果。
    分析结果以完整 JSON 字符串存储在 analysis_json 字段中，
    便于后续还原完整分析内容或导出。

主要函数：
    init_db()            — 初始化数据库和表（幂等）
    save_products()      — 批量保存产品与分析结果
    get_all_products()   — 查询历史记录（支持筛选）
    export_csv()         — 导出 CSV 文件
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
from contextlib import contextmanager
from typing import Optional

from .config import get_config


# ============================================================
# 建表 SQL
# ============================================================

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS products (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT,
    price           TEXT,
    rating          TEXT,
    num_reviews     TEXT,
    rank            INTEGER,
    category        TEXT,
    analysis_json   TEXT,
    scrape_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source          TEXT DEFAULT 'amazon_best_sellers',
    procurement_cost REAL DEFAULT 0.0,
    platform        TEXT DEFAULT 'amazon',
    region          TEXT DEFAULT 'us',
    currency        TEXT DEFAULT 'USD'
);
"""

_CREATE_MARKET_SCANS_SQL = """
CREATE TABLE IF NOT EXISTS market_scans (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword         TEXT,
    scan_time       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    platforms       TEXT,
    regions         TEXT,
    results_json    TEXT,
    best_market     TEXT,
    blue_ocean_score REAL
);
"""


# ============================================================
# 数据库连接上下文管理器
# ============================================================

@contextmanager
def _get_connection(db_path: Optional[str] = None):
    """
    SQLite 连接上下文管理器 — 自动提交/关闭，异常时回滚。

    用法：
        with _get_connection() as conn:
            conn.execute(...)
    """
    if db_path is None:
        cfg = get_config()
        db_path = cfg["database_path"]
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ============================================================
# 数据库初始化
# ============================================================

def init_db(db_path: Optional[str] = None) -> None:
    """
    初始化数据库 — 创建 data 目录和 products 表（如不存在）。

    幂等操作：多次调用不会重复创建或报错。
    """
    if db_path is None:
        cfg = get_config()
        db_path = cfg["database_path"]

    # 确保目录存在
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_CREATE_TABLE_SQL)
        # 兼容：为已有表新增字段（如不存在）
        for col, default in [
            ("procurement_cost", "REAL DEFAULT 0.0"),
            ("asin", "TEXT DEFAULT ''"),
            ("platform", "TEXT DEFAULT 'amazon'"),
            ("region", "TEXT DEFAULT 'us'"),
            ("currency", "TEXT DEFAULT 'USD'"),
        ]:
            try:
                conn.execute(f"ALTER TABLE products ADD COLUMN {col} {default}")
            except sqlite3.OperationalError:
                pass  # 字段已存在，忽略

        # 创建索引（幂等，IF NOT EXISTS）
        for idx_sql in [
            "CREATE INDEX IF NOT EXISTS idx_products_platform_region ON products(platform, region, scrape_time DESC)",
            "CREATE INDEX IF NOT EXISTS idx_products_verdict ON products(platform, analysis_json)",
            "CREATE INDEX IF NOT EXISTS idx_favorites_title_platform ON favorites(title, platform)",
        ]:
            try:
                conn.execute(idx_sql)
            except sqlite3.OperationalError:
                pass  # 索引已存在或表不存在

        # 数据清理：删除 90 天前的数据
        try:
            conn.execute(
                "DELETE FROM products WHERE scrape_time < datetime('now', '-90 days')"
            )
        except sqlite3.OperationalError:
            pass  # 表不存在时忽略

        # 创建市场扫描表
        conn.execute(_CREATE_MARKET_SCANS_SQL)

        conn.commit()
    finally:
        conn.close()


# ============================================================
# 数据保存
# ============================================================

def save_products(
    products: list[dict],
    analysis_results: list[dict],
    source: str = "amazon_best_sellers",
    platform: str = "amazon",
    region: str = "us",
    currency: str = "USD",
    db_path: Optional[str] = None,
) -> int:
    """
    批量保存产品数据及分析结果到数据库。

    Args:
        products:         产品字典列表（来自 scraper）
        analysis_results: 分析结果字典列表（来自 analyzer），与 products 按索引一一对应
        source:           数据来源标识，如 'amazon_best_sellers'
        platform:         平台标识，如 'amazon'
        region:           地区代码，如 'us'
        currency:         货币代码，如 'USD'
        db_path:          数据库路径，默认从配置读取

    Returns:
        本次保存的产品数量
    """
    with _get_connection(db_path) as conn:
        for i, product in enumerate(products):
            analysis = analysis_results[i] if i < len(analysis_results) else {}
            analysis_json = json.dumps(analysis, ensure_ascii=False)

            conn.execute(
                """
                INSERT INTO products
                    (title, price, rating, num_reviews, rank, category,
                     analysis_json, source, asin, platform, region, currency)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    product.get("title", ""),
                    str(product.get("price", "")),
                    str(product.get("rating", "")),
                    str(product.get("num_reviews", "")),
                    product.get("rank", 0),
                    product.get("category", ""),
                    analysis_json,
                    source,
                    product.get("asin", ""),
                    platform,
                    region,
                    currency,
                ),
            )
        return len(products)


# ============================================================
# 历史数据查询
# ============================================================

def get_all_products(
    filters: Optional[dict] = None,
    db_path: Optional[str] = None,
) -> list[dict]:
    """
    查询历史产品记录，支持多条件筛选。

    Args:
        filters: 筛选条件字典，支持以下键：
            - verdicts:  final_verdict 值列表，如 ["recommended", "cautious"]
            - min_capacity_score:  市场容量最低评分 (1-10)
            - min_price:  最低价格（美元）
            - max_price:  最高价格（美元）
            - sort_by:    排序字段，默认 'scrape_time'
            - sort_order: 'ASC' 或 'DESC'，默认 'DESC'
            - limit:      最大返回条数
        db_path: 数据库路径

    Returns:
        产品字典列表，每个字典包含产品字段 + 解析后的分析字段。
    """
    if filters is None:
        filters = {}
    if db_path is None:
        cfg = get_config()
        db_path = cfg["database_path"]

    init_db(db_path)

    # 构建 SQL WHERE 子句 — 将简单筛选下推到 SQL 层
    conditions = []
    params = []

    platform_filter = filters.get("platform")
    if platform_filter:
        conditions.append("platform = ?")
        params.append(platform_filter)

    region_filter = filters.get("region")
    if region_filter:
        conditions.append("region = ?")
        params.append(region_filter)

    min_price = filters.get("min_price")
    if min_price is not None:
        conditions.append("CAST(price AS REAL) >= ?")
        params.append(min_price)

    max_price = filters.get("max_price")
    if max_price is not None:
        conditions.append("CAST(price AS REAL) <= ?")
        params.append(max_price)

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    # 排序
    sort_by = filters.get("sort_by", "scrape_time")
    sort_order = filters.get("sort_order", "DESC").upper()
    allowed_sort = {"scrape_time", "price", "rank"}
    if sort_by not in allowed_sort:
        sort_by = "scrape_time"
    order_clause = f"ORDER BY {sort_by} {sort_order}"

    # 限制条数
    limit = filters.get("limit")
    limit_clause = f"LIMIT {int(limit)}" if limit and limit > 0 else ""

    sql = f"SELECT * FROM products WHERE {where_clause} {order_clause} {limit_clause}"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql, params).fetchall()

        results = []
        for row in rows:
            product = dict(row)
            try:
                analysis = json.loads(product.get("analysis_json", "{}"))
            except (json.JSONDecodeError, TypeError):
                analysis = {}
            product["analysis"] = analysis

            # JSON 内嵌字段只能在 Python 层筛选
            if not _match_filters(product, filters):
                continue

            results.append(product)

        return results

    finally:
        conn.close()


def _match_filters(product: dict, filters: dict) -> bool:
    """检查单个产品是否满足 JSON 内嵌字段的筛选条件（SQL 无法处理的部分）。"""
    analysis = product.get("analysis", {})

    # final_verdict 筛选
    verdicts = filters.get("verdicts")
    if verdicts:
        actual_verdict = analysis.get("final_verdict", "")
        if actual_verdict not in verdicts:
            return False

    # 市场容量最低评分
    min_cap = filters.get("min_capacity_score")
    if min_cap is not None:
        mc = analysis.get("market_capacity", {})
        if isinstance(mc, dict):
            if mc.get("score", 0) < min_cap:
                return False

    return True


def _safe_float(value) -> float:
    """安全转换为 float，失败返回 0.0。"""
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


# ============================================================
# CSV 导出
# ============================================================

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
    if db_path is None:
        cfg = get_config()
        db_path = cfg["database_path"]

    init_db(db_path)

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            "UPDATE products SET procurement_cost = ? WHERE title = ? AND scrape_time = ?",
            (procurement_cost, title, scrape_time),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_procurement_cost(
    title: str,
    scrape_time: str,
    db_path: Optional[str] = None,
) -> float:
    """
    获取单个产品的已保存采购成本。

    Args:
        title:       产品标题
        scrape_time: 抓取时间
        db_path:     数据库路径

    Returns:
        采购成本（人民币），未找到返回 0.0
    """
    if db_path is None:
        cfg = get_config()
        db_path = cfg["database_path"]

    init_db(db_path)

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT procurement_cost FROM products WHERE title = ? AND scrape_time = ?",
            (title, scrape_time),
        ).fetchone()
        if row:
            return float(row[0] or 0.0)
    finally:
        conn.close()
    return 0.0


def get_trend_data(
    asin: str = None,
    title: str = None,
    db_path: Optional[str] = None,
) -> list[dict]:
    """
    获取单个产品的趋势数据（按时间排序）。

    Args:
        asin:   产品 ASIN（优先匹配）
        title:  产品标题（ASIN 为空时回退到标题匹配）
        db_path: 数据库路径

    Returns:
        按 scrape_time 升序排列的数据列表。
    """
    if db_path is None:
        cfg = get_config()
        db_path = cfg["database_path"]

    init_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if asin:
            rows = conn.execute(
                "SELECT scrape_time, price, rank, num_reviews, rating "
                "FROM products WHERE asin = ? ORDER BY scrape_time ASC",
                (asin,),
            ).fetchall()
        elif title:
            rows = conn.execute(
                "SELECT scrape_time, price, rank, num_reviews, rating "
                "FROM products WHERE title = ? ORDER BY scrape_time ASC",
                (title,),
            ).fetchall()
        else:
            return []

        return [dict(row) for row in rows]
    finally:
        conn.close()


def export_csv(
    filepath: str,
    filters: Optional[dict] = None,
    db_path: Optional[str] = None,
) -> int:
    """
    将历史产品数据导出为 CSV 文件。

    CSV 包含以下列：
        标题, 价格, 评分, 评论数, 排名, 类目,
        市场容量, 竞争程度, 利润潜力, 新手友好度, 季节性风险,
        综合判定, 判定理由, 抓取时间

    Args:
        filepath: 导出 CSV 的文件路径
        filters:  筛选条件（同 get_all_products），传 None 导出全部
        db_path:  数据库路径

    Returns:
        导出的记录条数
    """
    products = get_all_products(filters=filters, db_path=db_path)

    if not products:
        return 0

    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        # 表头
        writer.writerow([
            "标题", "价格(USD)", "评分", "评论数", "排名", "类目",
            "市场容量", "竞争程度", "利润潜力", "新手友好度", "季节性风险",
            "综合判定", "判定理由", "抓取时间",
        ])
        # 数据行
        for p in products:
            analysis = p.get("analysis", {})
            writer.writerow([
                p.get("title", ""),
                p.get("price", ""),
                p.get("rating", ""),
                p.get("num_reviews", ""),
                p.get("rank", ""),
                p.get("category", ""),
                _dim_score_str(analysis, "market_capacity"),
                _dim_score_str(analysis, "competition"),
                _dim_score_str(analysis, "profit_potential"),
                _dim_score_str(analysis, "beginner_friendly"),
                _dim_score_str(analysis, "seasonality_risk"),
                analysis.get("final_verdict", ""),
                analysis.get("verdict_reason", ""),
                p.get("scrape_time", ""),
            ])

    return len(products)


def _dim_score_str(analysis: dict, key: str) -> str:
    """从分析结果中提取维度评分字符串，如 '7/10'。"""
    dim = analysis.get(key, {})
    if isinstance(dim, dict):
        score = dim.get("score", "")
        return f"{score}/10" if score else ""
    return ""


# ============================================================
# 辅助查询
# ============================================================

def get_product_count(db_path: Optional[str] = None) -> int:
    """返回数据库中产品总数。"""
    if db_path is None:
        cfg = get_config()
        db_path = cfg["database_path"]

    init_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT COUNT(*) FROM products").fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def get_platform_stats(platform: str, days: int = 30, db_path: Optional[str] = None) -> dict:
    """
    获取指定平台最近 N 天的统计数据。

    Args:
        platform: 平台标识（如 "amazon"）
        days: 统计天数（默认 30 天）

    Returns:
        {
            "total": int,
            "recommended": int,
            "cautious": int,
            "not_recommended": int,
            "avg_capacity": float,
            "avg_profit": float,
        }
    """
    if db_path is None:
        cfg = get_config()
        db_path = cfg["database_path"]

    init_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT analysis_json FROM products
            WHERE platform = ?
              AND scrape_time >= datetime('now', ?)
            """,
            (platform, f"-{days} days"),
        ).fetchall()

        stats = {
            "total": len(rows),
            "recommended": 0,
            "cautious": 0,
            "not_recommended": 0,
            "avg_capacity": 0.0,
            "avg_profit": 0.0,
        }
        cap_scores = []
        profit_scores = []

        for (analysis_json,) in rows:
            if not analysis_json:
                continue
            try:
                a = json.loads(analysis_json)
            except (json.JSONDecodeError, TypeError):
                continue
            verdict = a.get("final_verdict", "")
            if verdict == "recommended":
                stats["recommended"] += 1
            elif verdict == "cautious":
                stats["cautious"] += 1
            elif verdict == "not_recommended":
                stats["not_recommended"] += 1

            cap = a.get("market_capacity", {})
            if isinstance(cap, dict) and "score" in cap:
                cap_scores.append(cap["score"])
            profit = a.get("profit_potential", {})
            if isinstance(profit, dict) and "score" in profit:
                profit_scores.append(profit["score"])

        if cap_scores:
            stats["avg_capacity"] = round(sum(cap_scores) / len(cap_scores), 1)
        if profit_scores:
            stats["avg_profit"] = round(sum(profit_scores) / len(profit_scores), 1)

        return stats
    finally:
        conn.close()


def get_category_trend(keyword: str, days: int = 30, db_path: Optional[str] = None) -> list[dict]:
    """
    获取关键词相关产品的趋势数据（按天聚合）。

    Args:
        keyword: 搜索关键词
        days: 查询天数（默认 30 天）

    Returns:
        [{"date": "2026-06-01", "avg_price": 25.99, "avg_rating": 4.2, "count": 5}, ...]
    """
    if db_path is None:
        cfg = get_config()
        db_path = cfg["database_path"]

    init_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT scrape_time, price, rating, title FROM products
            WHERE title LIKE ?
              AND scrape_time >= datetime('now', ?)
            ORDER BY scrape_time
            """,
            (f"%{keyword}%", f"-{days} days"),
        ).fetchall()

        # 按日期分组
        daily = {}
        for scrape_time, price, rating, title in rows:
            date = str(scrape_time)[:10]  # YYYY-MM-DD
            if date not in daily:
                daily[date] = {"prices": [], "ratings": []}
            try:
                daily[date]["prices"].append(float(price))
            except (ValueError, TypeError):
                pass
            try:
                daily[date]["ratings"].append(float(rating))
            except (ValueError, TypeError):
                pass

        result = []
        for date in sorted(daily.keys()):
            d = daily[date]
            avg_price = round(sum(d["prices"]) / len(d["prices"]), 2) if d["prices"] else 0
            avg_rating = round(sum(d["ratings"]) / len(d["ratings"]), 1) if d["ratings"] else 0
            result.append({
                "date": date,
                "avg_price": avg_price,
                "avg_rating": avg_rating,
                "count": len(d["prices"]),
            })

        return result
    finally:
        conn.close()


def get_latest_products(db_path: Optional[str] = None) -> list[dict]:
    """
    获取最近一次各平台的产品数据（取每个平台的最新批次）。

    返回的产品包含以下字段：
        title, price, rating, num_reviews, rank, category, scrape_time,
        platform, region, currency

    Returns:
        产品字典列表，按 platform + rank 排序。
    """
    if db_path is None:
        cfg = get_config()
        db_path = cfg["database_path"]

    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        # 取每个平台的最新 scrape_time
        platform_times = conn.execute(
            "SELECT platform, MAX(scrape_time) as latest_time "
            "FROM products GROUP BY platform"
        ).fetchall()
        if not platform_times:
            return []

        # 按平台取最新批次的产品
        all_products = []
        for row in platform_times:
            platform = row["platform"]
            latest_time = row["latest_time"]
            products = conn.execute(
                "SELECT title, price, rating, num_reviews, rank, category, "
                "scrape_time, platform, region, currency "
                "FROM products WHERE platform = ? AND scrape_time = ? "
                "ORDER BY rank",
                (platform, latest_time),
            ).fetchall()
            all_products.extend(
                {
                    "title": p["title"],
                    "price": _safe_float(p["price"]),
                    "rating": _safe_float(p["rating"]),
                    "num_reviews": int(p["num_reviews"] or "0"),
                    "rank": int(p["rank"] or 0),
                    "category": p["category"] or "",
                    "scrape_time": p["scrape_time"],
                    "platform": p["platform"] or "amazon",
                    "region": p["region"] or "us",
                    "currency": p["currency"] or "USD",
                }
                for p in products
            )

        return all_products
    finally:
        conn.close()


# ============================================================
# 多平台增强查询（Spec 12）
# ============================================================

def query_products(
    platforms: list[str] = None,
    regions: list[str] = None,
    date_range: tuple = None,
    min_margin: float = None,
    keyword: str = None,
    limit: int = 500,
    db_path: Optional[str] = None,
) -> list[dict]:
    """
    多条件查询历史产品（支持平台、地区、时间范围等筛选）。

    Args:
        platforms:  平台列表，如 ["amazon", "aliexpress"]
        regions:    地区列表，如 ["us", "sg"]
        date_range: 时间范围 (start_date, end_date)
        min_margin: 最低毛利率
        keyword:    标题关键词搜索
        limit:      返回数量上限
        db_path:    数据库路径

    Returns:
        产品字典列表（包含分析结果）
    """
    if db_path is None:
        cfg = get_config()
        db_path = cfg["database_path"]

    init_db(db_path)

    conditions = []
    params = []

    if platforms:
        placeholders = ",".join(["?"] * len(platforms))
        conditions.append(f"platform IN ({placeholders})")
        params.extend(platforms)

    if regions:
        placeholders = ",".join(["?"] * len(regions))
        conditions.append(f"region IN ({placeholders})")
        params.extend(regions)

    if date_range and len(date_range) == 2:
        conditions.append("scrape_time BETWEEN ? AND ?")
        start_str = date_range[0].isoformat() if hasattr(date_range[0], 'isoformat') else str(date_range[0])
        end_str = date_range[1].isoformat() if hasattr(date_range[1], 'isoformat') else str(date_range[1])
        params.extend([start_str, end_str])

    if keyword:
        conditions.append("title LIKE ?")
        params.append(f"%{keyword}%")

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    sql = f"SELECT * FROM products WHERE {where_clause} ORDER BY scrape_time DESC LIMIT ?"
    params.append(limit)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql, params).fetchall()
        results = []
        for row in rows:
            product = dict(row)
            # 解析分析结果
            try:
                analysis = json.loads(product.get("analysis_json", "{}"))
            except (json.JSONDecodeError, TypeError):
                analysis = {}
            product["analysis"] = analysis

            # 从分析结果中提取利润信息供筛选使用
            product["margin_pct"] = analysis.get("margin_pct", -999)
            product["is_profitable"] = analysis.get("is_profitable", False)

            results.append(product)

        # 毛利率筛选（Python 层过滤）
        if min_margin is not None and min_margin > -50:
            results = [p for p in results if p.get("margin_pct", -999) >= min_margin]

        return results
    finally:
        conn.close()


def get_platform_summary(db_path: Optional[str] = None) -> dict:
    """
    获取各平台的数据摘要统计。

    Returns:
        {
            "amazon": {"count": 36, "regions": ["us", "uk"], "latest": "2025-01-15"},
            ...
        }
    """
    if db_path is None:
        cfg = get_config()
        db_path = cfg["database_path"]

    init_db(db_path)

    conn = sqlite3.connect(db_path)
    try:
        # 检查 platform 列是否存在
        try:
            rows = conn.execute(
                "SELECT platform, region, COUNT(*) as cnt, MAX(scrape_time) as latest "
                "FROM products GROUP BY platform, region ORDER BY platform, region"
            ).fetchall()
        except sqlite3.OperationalError:
            # 旧数据库可能没有 platform 列
            return {}

        summary = {}
        for row in rows:
            pf = row[0] or "amazon"
            if pf not in summary:
                summary[pf] = {"count": 0, "regions": [], "latest": ""}
            summary[pf]["count"] += row[1]
            region = row[1] or "us"
            if region not in summary[pf]["regions"]:
                summary[pf]["regions"].append(region)
            latest = row[3] or ""
            if latest > summary[pf]["latest"]:
                summary[pf]["latest"] = latest
        return summary
    finally:
        conn.close()


# ============================================================
# 产品收藏功能（Spec 16）
# ============================================================

_CREATE_FAVORITES_SQL = """
CREATE TABLE IF NOT EXISTS favorites (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT NOT NULL,
    platform      TEXT DEFAULT 'amazon',
    price         TEXT,
    rating        TEXT,
    num_reviews   TEXT DEFAULT '0',
    analysis_json TEXT,
    notes         TEXT DEFAULT '',
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(title, platform)
);
"""


def _init_favorites_table(db_path: str) -> None:
    """确保 favorites 表存在（幂等）。"""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_CREATE_FAVORITES_SQL)
        conn.commit()
    finally:
        conn.close()


def add_favorite(
    title: str,
    platform: str = "amazon",
    price: str = "",
    rating: str = "",
    num_reviews: str = "0",
    analysis_json: str = "{}",
    notes: str = "",
    db_path: Optional[str] = None,
) -> bool:
    """
    添加产品到收藏（UPSERT：已存在则更新）。

    Returns:
        True 如果操作成功
    """
    if db_path is None:
        cfg = get_config()
        db_path = cfg["database_path"]
    _init_favorites_table(db_path)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO favorites (title, platform, price, rating, num_reviews, analysis_json, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(title, platform) DO UPDATE SET
                price=excluded.price, rating=excluded.rating,
                num_reviews=excluded.num_reviews, analysis_json=excluded.analysis_json,
                notes=excluded.notes
            """,
            (title, platform, price, rating, num_reviews, analysis_json, notes),
        )
        conn.commit()
        return True
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def remove_favorite(
    title: str,
    platform: str = "amazon",
    db_path: Optional[str] = None,
) -> bool:
    """取消收藏。返回 True 如果删除成功。"""
    if db_path is None:
        cfg = get_config()
        db_path = cfg["database_path"]
    _init_favorites_table(db_path)

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            "DELETE FROM favorites WHERE title = ? AND platform = ?",
            (title, platform),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def is_favorite(
    title: str,
    platform: str = "amazon",
    db_path: Optional[str] = None,
) -> bool:
    """检查产品是否已收藏。"""
    if db_path is None:
        cfg = get_config()
        db_path = cfg["database_path"]
    _init_favorites_table(db_path)

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT 1 FROM favorites WHERE title = ? AND platform = ?",
            (title, platform),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def get_favorites(
    platform: Optional[str] = None,
    db_path: Optional[str] = None,
) -> list[dict]:
    """获取收藏列表。可选按平台筛选。"""
    if db_path is None:
        cfg = get_config()
        db_path = cfg["database_path"]
    _init_favorites_table(db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if platform:
            rows = conn.execute(
                "SELECT * FROM favorites WHERE platform = ? ORDER BY created_at DESC",
                (platform,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM favorites ORDER BY created_at DESC"
            ).fetchall()

        results = []
        for row in rows:
            item = dict(row)
            try:
                item["analysis"] = json.loads(item.get("analysis_json", "{}"))
            except (json.JSONDecodeError, TypeError):
                item["analysis"] = {}
            results.append(item)
        return results
    finally:
        conn.close()


# ============================================================
# 市场扫描结果存储（Spec 25）
# ============================================================

def save_market_scan(
    keyword: str,
    platforms: list[str],
    regions: list[str],
    results: dict,
    best_market: str = "",
    blue_ocean_score: float = 0.0,
    db_path: Optional[str] = None,
) -> int:
    """
    保存市场扫描结果到数据库。

    Returns:
        插入记录的 ID
    """
    if db_path is None:
        cfg = get_config()
        db_path = cfg["database_path"]

    init_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            """
            INSERT INTO market_scans (keyword, platforms, regions, results_json, best_market, blue_ocean_score)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                keyword,
                json.dumps(platforms, ensure_ascii=False),
                json.dumps(regions, ensure_ascii=False),
                json.dumps(results, ensure_ascii=False),
                best_market,
                blue_ocean_score,
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_market_scans(
    keyword: Optional[str] = None,
    limit: int = 20,
    db_path: Optional[str] = None,
) -> list[dict]:
    """
    获取历史市场扫描记录。

    Args:
        keyword: 可选关键词筛选
        limit: 最大返回条数

    Returns:
        扫描记录列表
    """
    if db_path is None:
        cfg = get_config()
        db_path = cfg["database_path"]

    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if keyword:
            rows = conn.execute(
                "SELECT * FROM market_scans WHERE keyword LIKE ? ORDER BY scan_time DESC LIMIT ?",
                (f"%{keyword}%", limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM market_scans ORDER BY scan_time DESC LIMIT ?",
                (limit,),
            ).fetchall()

        results = []
        for row in rows:
            item = dict(row)
            try:
                item["results"] = json.loads(item.get("results_json", "{}"))
            except (json.JSONDecodeError, TypeError):
                item["results"] = {}
            try:
                item["platforms_list"] = json.loads(item.get("platforms", "[]"))
            except (json.JSONDecodeError, TypeError):
                item["platforms_list"] = []
            try:
                item["regions_list"] = json.loads(item.get("regions", "[]"))
            except (json.JSONDecodeError, TypeError):
                item["regions_list"] = []
            results.append(item)
        return results
    finally:
        conn.close()
