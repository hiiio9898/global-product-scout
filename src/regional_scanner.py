"""
全地区热销榜扫描引擎 — Spec 34。

遍历所有平台 × 地区的 Best Sellers 热销榜，跨地区聚合出热门产品排行。

核心流程：
    1. 遍历 (platform, region) 组合（默认全平台全地区，共 18 站点）
    2. 对每个组合调用各平台的 scraper_func（fetch_xxx_best_sellers）抓取热销榜
    3. aggregate_hot_products 按 title 归组，统计上榜地区数 + 累计评论数，算热度分
    4. 返回跨地区热门产品排行

设计要点：
    复用各平台已有的 scraper_func 和 platforms.PLATFORMS 注册表，
    不重写抓取逻辑；单站点失败不中断整体扫描。

使用方式：
    from src.regional_scanner import scan_all_regions, aggregate_hot_products
"""

from __future__ import annotations

import importlib
import math
from datetime import datetime, timezone

from .platforms import PLATFORMS


# ============================================================
# 动态加载抓取函数（与 daily_scrape._load_scraper_func 同模式）
# ============================================================

def _load_scraper_func(module_path: str, func_name: str):
    """动态导入抓取模块并返回指定函数。"""
    module = importlib.import_module(module_path)
    func = getattr(module, func_name, None)
    if func is None:
        raise AttributeError(f"模块 {module_path} 中未找到函数 {func_name}")
    return func


def _norm_title(title: str) -> str:
    """标题归一化，用于跨地区去重（小写 + 折叠空白）。"""
    return " ".join((title or "").lower().split())


# ============================================================
# 全地区扫描
# ============================================================

def scan_all_regions(
    platforms: list[str] | None = None,
    progress_callback=None,
    max_per_region: int = 20,
) -> dict:
    """
    扫描所有（或指定）平台 × 地区的 Best Sellers 热销榜。

    Args:
        platforms:         平台 key 列表，None 表示扫描全部平台
        progress_callback: 进度回调 (done, total, label)，用于驱动 UI 进度条
        max_per_region:    预留参数（热销榜为固定榜单，当前不截断）

    Returns:
        {
            "scan_time": str,         # ISO 时间戳
            "total_sites": int,       # 总站点数
            "success_sites": int,     # 成功站点数
            "products": list[dict],   # 全部抓到的产品（每个标注 platform/region/currency）
            "errors": list[tuple],    # [(platform, region, error_str), ...]
        }

    说明：
        - 各平台 scraper_func 签名为 scraper_func(region=...) → (products, source_info)
        - 单站点异常 → 记入 errors，继续下一站，不中断
    """
    target_platforms = platforms if platforms else list(PLATFORMS.keys())

    # 构建 (platform, region) 任务清单
    tasks = []
    for pk in target_platforms:
        if pk not in PLATFORMS:
            continue
        for rk in PLATFORMS[pk]["regions"]:
            tasks.append((pk, rk))

    total = len(tasks)
    all_products: list[dict] = []
    errors: list[tuple] = []
    success_sites = 0

    for i, (pk, rk) in enumerate(tasks):
        pf = PLATFORMS[pk]
        label = f"{pf.get('icon', '📦')} {pf.get('name', pk)} {rk.upper()}"
        if progress_callback:
            try:
                progress_callback(i, total, label)
            except Exception:
                pass  # 进度回调异常不影响扫描

        try:
            scraper_func = _load_scraper_func(pf["scraper_module"], pf["scraper_func"])
            products, source_info = scraper_func(region=rk)
            if products:
                region_info = PLATFORMS[pk]["regions"][rk]
                currency = region_info.get("currency", "USD")
                for p in products:
                    # 每字段单独标注，避免覆盖抓取器原有字段
                    try:
                        p["platform"] = pk
                        p["region"] = rk
                        p["currency"] = currency
                    except Exception:
                        pass
                all_products.extend(products)
                success_sites += 1
        except Exception as e:
            errors.append((pk, rk, str(e)))

    if progress_callback:
        try:
            progress_callback(total, total, "扫描完成")
        except Exception:
            pass

    return {
        "scan_time": datetime.now(timezone.utc).isoformat(),
        "total_sites": total,
        "success_sites": success_sites,
        "products": all_products,
        "errors": errors,
    }


# ============================================================
# 跨地区热度聚合
# ============================================================

def aggregate_hot_products(products: list[dict], top_n: int = 50) -> list[dict]:
    """
    跨地区聚合去重 + 热度排行。

    按 title 归组（归一化后相同视为同一产品），统计：
        - region_count: 上榜地区数（越多越通用）
        - total_reviews: 累计评论数（体现需求量）
        - hotness: region_count × 10 + log10(total_reviews + 1) × 5

    Args:
        products: scan_all_regions 返回的 products 列表
        top_n:    返回前 N 个

    Returns:
        [{"title", "platforms", "regions", "region_count",
          "total_reviews", "hotness", "sample"}, ...]
        按 hotness 降序，sample 为该产品首个出现的完整样本（含价格/图片/链接）。
    """
    groups: dict[str, dict] = {}

    for p in products:
        title = p.get("title", "") or ""
        key = _norm_title(title)
        if not key:
            continue

        if key not in groups:
            groups[key] = {
                "title": title,
                "platforms": set(),
                "regions": set(),
                "total_reviews": 0,
                "sample": None,
            }
        g = groups[key]
        g["platforms"].add(p.get("platform", ""))
        g["regions"].add(p.get("region", ""))

        # 评论数累加（容错）
        try:
            g["total_reviews"] += int(float(p.get("num_reviews", 0) or 0))
        except (ValueError, TypeError):
            pass

        # 保留第一个样本（含价格/图片/链接等完整信息）
        if g["sample"] is None:
            g["sample"] = p

    ranked = []
    for g in groups.values():
        region_count = len(g["regions"])
        reviews = g["total_reviews"]
        hotness = region_count * 10 + math.log10(reviews + 1) * 5
        ranked.append({
            "title": g["title"],
            "platforms": sorted(x for x in g["platforms"] if x),
            "regions": sorted(x for x in g["regions"] if x),
            "region_count": region_count,
            "total_reviews": reviews,
            "hotness": round(hotness, 1),
            "sample": g["sample"] or {},
        })

    ranked.sort(key=lambda x: x["hotness"], reverse=True)
    return ranked[:top_n]
