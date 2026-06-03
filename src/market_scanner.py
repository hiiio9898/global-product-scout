"""
市场扫描引擎 — 批量扫描多平台×多地区的市场数据，计算蓝海指数。

核心流程：
    1. 遍历 (platform, region) 组合
    2. 对每个组合调用搜索函数获取产品列表
    3. 调用 AI 分析该市场的竞争格局
    4. 计算蓝海指数
    5. 生成跨市场对比报告

使用方式：
    from src.market_scanner import scan_market, calculate_blue_ocean_score
"""

from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone

from .platforms import PLATFORMS, get_platform_info, get_region_info


# ============================================================
# 蓝海指数计算
# ============================================================

def calculate_blue_ocean_score(analysis: dict) -> float:
    """
    计算蓝海指数。

    蓝海指数 = 需求 × 0.4 + (10 - 竞争) × 0.35 + 利润 × 0.25

    需求高 + 竞争低 + 利润好 = 蓝海

    Args:
        analysis: AI 分析结果字典（含 market_capacity, competition, profit_potential）

    Returns:
        蓝海指数 0-10（越高越蓝海）
    """
    demand = _get_dim_score(analysis, "market_capacity")
    competition = _get_dim_score(analysis, "competition")
    profit = _get_dim_score(analysis, "profit_potential")

    score = demand * 0.4 + (10 - competition) * 0.35 + profit * 0.25
    return round(min(max(score, 0), 10), 1)


def _get_dim_score(analysis: dict, key: str) -> float:
    """从分析结果中提取维度评分。"""
    dim = analysis.get(key, {})
    if isinstance(dim, dict):
        try:
            return float(dim.get("score", 5))
        except (ValueError, TypeError):
            return 5.0
    return 5.0


def classify_competition(score: float) -> str:
    """将竞争分数转为等级标签。"""
    if score <= 3:
        return "low"
    elif score <= 6:
        return "medium"
    else:
        return "high"


def classify_demand(score: float) -> str:
    """将需求分数转为等级标签。"""
    if score >= 7:
        return "high"
    elif score >= 4:
        return "medium"
    else:
        return "low"


# ============================================================
# 单市场扫描
# ============================================================

def scan_single_market(
    keyword: str,
    platform: str,
    region: str,
    max_results: int = 20,
) -> dict:
    """
    扫描单个平台+地区的市场数据。

    Args:
        keyword: 搜索关键词
        platform: 平台标识（如 "amazon"）
        region: 地区代码（如 "us"）
        max_results: 最大结果数

    Returns:
        {
            "platform": "amazon",
            "region": "us",
            "region_name": "美国站",
            "products": [...],
            "product_count": 20,
            "avg_price": 25.99,
            "avg_rating": 4.3,
            "source": "live",
            "error": None,
        }
    """
    pf_info = get_platform_info(platform)
    region_info = get_region_info(platform, region)
    region_name = region_info.get("name", region)

    result = {
        "platform": platform,
        "region": region,
        "region_name": region_name,
        "products": [],
        "product_count": 0,
        "avg_price": 0.0,
        "avg_rating": 0.0,
        "source": "unknown",
        "error": None,
    }

    try:
        # 动态加载搜索函数
        search_mod = importlib.import_module(pf_info["search_module"])
        search_func = getattr(search_mod, pf_info["search_func"])
        search_result = search_func(keyword, region=region, max_results=max_results)

        if search_result.get("success"):
            products = search_result.get("results", [])
            result["products"] = products
            result["product_count"] = len(products)
            result["source"] = search_result.get("source", "unknown")

            # 计算平均价格和评分
            prices = []
            ratings = []
            for p in products:
                try:
                    prices.append(float(p.get("price", 0) or 0))
                except (ValueError, TypeError):
                    pass
                try:
                    ratings.append(float(p.get("rating", 0) or 0))
                except (ValueError, TypeError):
                    pass

            result["avg_price"] = round(sum(prices) / len(prices), 2) if prices else 0
            result["avg_rating"] = round(sum(ratings) / len(ratings), 1) if ratings else 0
        else:
            result["error"] = search_result.get("error", "搜索失败")

    except Exception as e:
        result["error"] = str(e)

    return result


# ============================================================
# 批量市场扫描
# ============================================================

def scan_market(
    keyword: str,
    platforms: list[str],
    regions: list[str],
    progress_callback=None,
    max_results: int = 20,
) -> dict:
    """
    批量扫描指定关键词在多个平台×地区的市场数据。

    Args:
        keyword: 搜索关键词
        platforms: 平台列表（如 ["amazon", "ebay"]）
        regions: 地区列表（如 ["us", "uk", "de"]）
        progress_callback: 进度回调 (done, total, current_label)
        max_results: 每个市场最大结果数

    Returns:
        {
            "keyword": str,
            "scan_time": str,
            "total_markets": int,
            "markets": [scan_single_market results...],
        }
    """
    # 构建所有 (platform, region) 组合
    combos = []
    for pf in platforms:
        for rg in regions:
            # 检查该平台是否支持该地区
            pf_info = get_platform_info(pf)
            if rg in pf_info.get("regions", {}):
                combos.append((pf, rg))

    total = len(combos)
    markets = []

    for i, (pf, rg) in enumerate(combos):
        label = f"{PLATFORMS[pf]['icon']} {PLATFORMS[pf]['name']} {rg.upper()}"
        if progress_callback:
            progress_callback(i, total, label)

        market_result = scan_single_market(keyword, pf, rg, max_results)
        markets.append(market_result)

    if progress_callback:
        progress_callback(total, total, "扫描完成")

    return {
        "keyword": keyword,
        "scan_time": datetime.now(timezone.utc).isoformat(),
        "total_markets": total,
        "markets": markets,
    }


# ============================================================
# 趋势预测
# ============================================================

def predict_trend(trend_data: list[dict]) -> dict:
    """
    基于历史数据预测产品趋势。

    使用简单线性回归分析价格/排名/评论的变化方向。

    Args:
        trend_data: 历史趋势数据列表（来自 database.get_trend_data()）
                    每条含 {scrape_time, price, rank, num_reviews}

    Returns:
        {
            "price_trend": "rising" | "falling" | "stable",
            "price_change_pct": float,       # 价格变化百分比
            "rank_trend": "improving" | "declining" | "stable",
            "rank_change": int,              # 排名变化（正=提升）
            "review_growth_rate": float,     # 评论增速（条/天）
            "prediction": str,               # AI 可读的趋势描述
            "confidence": "high" | "medium" | "low",
        }
    """
    if not trend_data or len(trend_data) < 2:
        return {
            "price_trend": "unknown",
            "price_change_pct": 0,
            "rank_trend": "unknown",
            "rank_change": 0,
            "review_growth_rate": 0,
            "prediction": "历史数据不足，无法预测趋势",
            "confidence": "low",
        }

    # 提取数值序列
    prices = []
    ranks = []
    reviews = []
    for d in trend_data:
        try:
            prices.append(float(d.get("price", 0) or 0))
        except (ValueError, TypeError):
            prices.append(None)
        try:
            ranks.append(float(d.get("rank", 0) or 0))
        except (ValueError, TypeError):
            ranks.append(None)
        try:
            reviews.append(float(d.get("num_reviews", 0) or 0))
        except (ValueError, TypeError):
            reviews.append(None)

    # 过滤 None 值
    valid_prices = [p for p in prices if p is not None and p > 0]
    valid_ranks = [r for r in ranks if r is not None and r > 0]
    valid_reviews = [r for r in reviews if r is not None]

    # 价格趋势
    price_trend = "stable"
    price_change_pct = 0.0
    if len(valid_prices) >= 2:
        price_change_pct = ((valid_prices[-1] - valid_prices[0]) / valid_prices[0]) * 100
        if price_change_pct > 5:
            price_trend = "rising"
        elif price_change_pct < -5:
            price_trend = "falling"

    # 排名趋势
    rank_trend = "stable"
    rank_change = 0
    if len(valid_ranks) >= 2:
        rank_change = int(valid_ranks[0] - valid_ranks[-1])  # 正=排名提升
        if rank_change > 3:
            rank_trend = "improving"
        elif rank_change < -3:
            rank_trend = "declining"

    # 评论增速
    review_growth_rate = 0.0
    if len(valid_reviews) >= 2:
        total_growth = valid_reviews[-1] - valid_reviews[0]
        # 假设每个数据点间隔约 1 天
        review_growth_rate = round(total_growth / max(len(valid_reviews) - 1, 1), 1)

    # 置信度
    data_points = len(trend_data)
    if data_points >= 5:
        confidence = "high"
    elif data_points >= 3:
        confidence = "medium"
    else:
        confidence = "low"

    # 生成预测描述
    prediction_parts = []
    if price_trend == "rising":
        prediction_parts.append(f"价格上涨 {price_change_pct:.1f}%")
    elif price_trend == "falling":
        prediction_parts.append(f"价格下降 {abs(price_change_pct):.1f}%")
    else:
        prediction_parts.append("价格稳定")

    if rank_trend == "improving":
        prediction_parts.append(f"排名提升 {rank_change} 位")
    elif rank_trend == "declining":
        prediction_parts.append(f"排名下降 {abs(rank_change)} 位")
    else:
        prediction_parts.append("排名稳定")

    if review_growth_rate > 0:
        prediction_parts.append(f"评论日增 {review_growth_rate:.0f} 条")

    prediction = "，".join(prediction_parts)

    return {
        "price_trend": price_trend,
        "price_change_pct": round(price_change_pct, 1),
        "rank_trend": rank_trend,
        "rank_change": rank_change,
        "review_growth_rate": review_growth_rate,
        "prediction": prediction,
        "confidence": confidence,
    }


# ============================================================
# 时间回顾分析
# ============================================================

def build_retrospective(trend_data: list[dict]) -> dict:
    """
    构建产品的时间回顾分析数据。

    Args:
        trend_data: 历史趋势数据（来自 database.get_trend_data()）

    Returns:
        {
            "period": "2026-05-01 ~ 2026-06-03",
            "data_points": 10,
            "price": {
                "start": 25.99, "end": 27.99, "min": 23.99, "max": 29.99,
                "change_pct": 7.7,
            },
            "rank": {
                "start": 15, "end": 8, "best": 5, "worst": 22,
                "change": 7,
            },
            "reviews": {
                "start": 1200, "end": 1580, "growth": 380,
                "growth_rate": 12.7,
            },
        }
    """
    if not trend_data or len(trend_data) < 1:
        return {"period": "无数据", "data_points": 0}

    def _safe_float(val):
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    prices = [_safe_float(d.get("price")) for d in trend_data]
    ranks = [_safe_float(d.get("rank")) for d in trend_data]
    reviews = [_safe_float(d.get("num_reviews")) for d in trend_data]
    times = [str(d.get("scrape_time", ""))[:10] for d in trend_data]

    valid_prices = [p for p in prices if p and p > 0]
    valid_ranks = [r for r in ranks if r and r > 0]
    valid_reviews = [r for r in reviews if r is not None]

    period = f"{times[0]} ~ {times[-1]}" if times else "无数据"

    result = {
        "period": period,
        "data_points": len(trend_data),
    }

    if valid_prices:
        result["price"] = {
            "start": valid_prices[0],
            "end": valid_prices[-1],
            "min": min(valid_prices),
            "max": max(valid_prices),
            "change_pct": round(((valid_prices[-1] - valid_prices[0]) / valid_prices[0]) * 100, 1),
        }

    if valid_ranks:
        result["rank"] = {
            "start": int(valid_ranks[0]),
            "end": int(valid_ranks[-1]),
            "best": int(min(valid_ranks)),
            "worst": int(max(valid_ranks)),
            "change": int(valid_ranks[0] - valid_ranks[-1]),
        }

    if valid_reviews and len(valid_reviews) >= 2:
        growth = valid_reviews[-1] - valid_reviews[0]
        result["reviews"] = {
            "start": int(valid_reviews[0]),
            "end": int(valid_reviews[-1]),
            "growth": int(growth),
            "growth_rate": round(growth / max(len(valid_reviews) - 1, 1), 1),
        }

    return result
