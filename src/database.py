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

import csv
import json
import os
import sqlite3
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
    source          TEXT DEFAULT 'amazon_best_sellers'
);
"""


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
    db_path: Optional[str] = None,
) -> int:
    """
    批量保存产品数据及分析结果到数据库。

    Args:
        products:         产品字典列表（来自 scraper）
        analysis_results: 分析结果字典列表（来自 analyzer），与 products 按索引一一对应
        source:           数据来源标识，如 'amazon_best_sellers'
        db_path:          数据库路径，默认从配置读取

    Returns:
        本次保存的产品数量
    """
    if db_path is None:
        cfg = get_config()
        db_path = cfg["database_path"]

    init_db(db_path)

    conn = sqlite3.connect(db_path)
    try:
        for i, product in enumerate(products):
            # 获取对应的分析结果（按索引匹配）
            analysis = analysis_results[i] if i < len(analysis_results) else {}
            analysis_json = json.dumps(analysis, ensure_ascii=False)

            conn.execute(
                """
                INSERT INTO products
                    (title, price, rating, num_reviews, rank, category,
                     analysis_json, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )
        conn.commit()
        return len(products)
    finally:
        conn.close()


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

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # 返回类字典行
    try:
        rows = conn.execute(
            "SELECT * FROM products ORDER BY scrape_time DESC"
        ).fetchall()

        # 转为普通字典列表，同时解析 analysis_json
        results = []
        for row in rows:
            product = dict(row)
            # 解析 JSON 分析结果
            try:
                analysis = json.loads(product.get("analysis_json", "{}"))
            except (json.JSONDecodeError, TypeError):
                analysis = {}
            product["analysis"] = analysis

            # 应用 Python 层筛选（JSON 字段无法在 SQL 中直接筛选）
            if not _match_filters(product, filters):
                continue

            results.append(product)

        # 排序
        sort_by = filters.get("sort_by", "scrape_time")
        sort_order = filters.get("sort_order", "DESC")
        reverse = sort_order.upper() == "DESC"

        if sort_by == "price":
            results.sort(
                key=lambda p: _safe_float(p.get("price", "0")),
                reverse=reverse,
            )
        elif sort_by == "rank":
            results.sort(
                key=lambda p: p.get("rank", 9999),
                reverse=not reverse,  # rank 越小越好
            )
        elif sort_by == "scrape_time":
            results.sort(
                key=lambda p: p.get("scrape_time", ""),
                reverse=reverse,
            )
        else:
            results.sort(
                key=lambda p: p.get("scrape_time", ""),
                reverse=True,
            )

        # 限制条数
        limit = filters.get("limit")
        if limit and limit > 0:
            results = results[:limit]

        return results

    finally:
        conn.close()


def _match_filters(product: dict, filters: dict) -> bool:
    """检查单个产品是否满足所有筛选条件。"""
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

    # 价格区间
    min_price = filters.get("min_price")
    max_price = filters.get("max_price")
    price = _safe_float(product.get("price", "0"))
    if min_price is not None and price < min_price:
        return False
    if max_price is not None and price > max_price:
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


def get_latest_products(db_path: Optional[str] = None) -> list[dict]:
    """
    获取最近一次抓取的产品列表（按 scrape_time 分组，取最新批次）。

    返回的产品包含以下字段：
        title, price, rating, num_reviews, rank, category, scrape_time
    不包含 analysis_json（分析结果）。

    Returns:
        产品字典列表，按 rank 排序。
    """
    if db_path is None:
        cfg = get_config()
        db_path = cfg["database_path"]

    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        # 获取最新的 scrape_time
        latest_time_row = conn.execute(
            "SELECT scrape_time FROM products ORDER BY scrape_time DESC LIMIT 1"
        ).fetchone()
        if not latest_time_row:
            return []
        latest_time = latest_time_row["scrape_time"]

        # 获取该批次的所有产品
        rows = conn.execute(
            "SELECT title, price, rating, num_reviews, rank, category, scrape_time "
            "FROM products WHERE scrape_time = ? "
            "ORDER BY rank",
            (latest_time,),
        ).fetchall()

        # 转为字典列表
        return [
            {
                "title": row["title"],
                "price": _safe_float(row["price"]),
                "rating": _safe_float(row["rating"]),
                "num_reviews": int(row["num_reviews"] or "0"),
                "rank": int(row["rank"] or 0),
                "category": row["category"] or "",
                "scrape_time": row["scrape_time"],
            }
            for row in rows
        ]
    finally:
        conn.close()
