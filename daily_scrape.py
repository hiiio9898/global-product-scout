"""
每日定时抓取脚本 — 独立于 Streamlit 运行，支持多平台。

工作流程：
    1. 遍历 PLATFORMS 注册表中所有平台（或通过 --platforms 指定）
    2. 对每个平台动态加载抓取函数，按默认地区抓取产品
    3. 调用 src.analyzer.analyze_products() 进行 AI 分析
    4. 调用 src.database.save_products() 保存到 SQLite（含平台/地区/货币元数据）
    5. 导出 products.json 供 Streamlit Cloud 使用

用法：
    python daily_scrape.py                        # 抓取所有平台
    python daily_scrape.py --platforms amazon ebay # 仅抓取指定平台
    python daily_scrape.py --list                  # 列出所有可用平台
    python daily_scrape.py --skip-analysis         # 跳过 AI 分析（仅抓取）

依赖：
    配置通过 .env 文件或环境变量读取（同 Streamlit 本地开发方式）。
    云端运行（如 GitHub Actions）通过 secrets 注入环境变量。
"""

print("=== daily_scrape.py started ===")

import importlib
import json
import sys
import os
import argparse
from datetime import datetime, timezone

# 将项目根目录加入 Python 路径，使 from src.xxx 能正常导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.platforms import PLATFORMS, get_platform_info, get_region_info, get_available_platform_choices
from src.config import get_llm_config
from src.analyzer import analyze_products
from src.database import save_products, get_product_count, get_latest_products


# ============================================================
# 动态加载抓取函数
# ============================================================

def _load_scraper_func(module_path: str, func_name: str):
    """
    动态导入抓取模块并返回指定函数。

    Args:
        module_path: 模块路径，如 "src.scraper"
        func_name:   函数名，如 "fetch_amazon_best_sellers"

    Returns:
        可调用的抓取函数
    """
    module = importlib.import_module(module_path)
    func = getattr(module, func_name, None)
    if func is None:
        raise AttributeError(f"模块 {module_path} 中未找到函数 {func_name}")
    return func


# ============================================================
# 单平台抓取
# ============================================================

def scrape_platform(platform_key: str, region_key: str = None) -> tuple[list[dict], dict]:
    """
    抓取指定平台的产品数据。

    Args:
        platform_key: 平台标识，如 "amazon"
        region_key:   地区代码，如 "us"。为 None 时使用平台默认地区

    Returns:
        (products_list, source_info_dict)
    """
    platform = get_platform_info(platform_key)
    if region_key is None:
        region_key = platform.get("default_region", "us")

    region = get_region_info(platform_key, region_key)
    scraper_func = _load_scraper_func(platform["scraper_module"], platform["scraper_func"])

    icon = platform.get("icon", "📦")
    name = platform.get("name", platform_key)
    print(f"\n{icon} 抓取 {name} ({region['name']})...")

    try:
        products, source_info = scraper_func(region=region_key)
        src = source_info.get("source", "unknown")
        ts = source_info.get("timestamp", "")
        status = "实时抓取 ✅" if src == "live" else ("本地缓存 💾" if src == "cache" else "不可用 ❌")
        print(f"  数据来源：{src} ({status})")
        print(f"  获取产品：{len(products)} 个")
        if ts:
            print(f"  时间戳：{ts}")
        return products, source_info
    except Exception as e:
        print(f"  ❌ 抓取失败：{e}")
        return [], {"source": "error", "error": str(e)}


# ============================================================
# 主流程
# ============================================================

def main():
    """主流程：多平台抓取 → 分析 → 存库 → 导出 JSON。"""
    # 解析命令行参数
    parser = argparse.ArgumentParser(description="Global Product Scout 每日自动抓取")
    parser.add_argument(
        "--platforms", nargs="+", default=None,
        help="指定要抓取的平台（如 amazon ebay aliexpress），默认抓取全部"
    )
    parser.add_argument(
        "--list", action="store_true",
        help="列出所有可用平台后退出"
    )
    parser.add_argument(
        "--skip-analysis", action="store_true",
        help="跳过 AI 分析（仅抓取并保存原始数据）"
    )
    parser.add_argument(
        "--regions", nargs="+", default=None,
        help="指定要抓取的地区（如 us uk jp de），默认仅抓取各平台默认地区"
    )
    parser.add_argument(
        "--all-regions", action="store_true",
        help="抓取所有平台的所有地区站点（耗时较长）"
    )
    args = parser.parse_args()

    # 列出可用平台
    if args.list:
        print("\n可用平台：")
        for key, info in PLATFORMS.items():
            icon = info.get("icon", "📦")
            name = info.get("name", key)
            regions = ", ".join(r["name"] for r in info["regions"].values())
            mode = info.get("scrape_mode", "fetcher_first")
            print(f"  {icon} {key:12s} — {name} ({regions}) [{mode}]")
        return

    start_time = datetime.now(timezone.utc)

    print("=" * 60)
    print("  Global Product Scout — 每日自动抓取")
    print(f"  开始时间：{start_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 60)

    # 确定要抓取的平台列表
    if args.platforms:
        target_platforms = []
        for p in args.platforms:
            if p in PLATFORMS:
                target_platforms.append(p)
            else:
                print(f"⚠️  未知平台 '{p}'，跳过。可用平台：{list(PLATFORMS.keys())}")
        if not target_platforms:
            print("❌ 没有有效的目标平台，终止执行。")
            sys.exit(1)
    else:
        # 默认只抓 available=True 的平台；被机房IP封死的平台跳过（可用 --platforms 强测）
        target_platforms = get_available_platform_choices()
        _skipped = [
            f"{PLATFORMS[k]['name']}（{PLATFORMS[k].get('unavailable_reason', '不可用')}）"
            for k in PLATFORMS
            if k not in target_platforms
        ]
        if _skipped:
            print(f"⏭️  跳过不可用平台：{', '.join(_skipped)}")

    print(f"\n📋 目标平台：{', '.join(target_platforms)}")

    # AI 配置检查
    if not args.skip_analysis:
        llm_cfg = get_llm_config()
        api_ok = bool(llm_cfg["api_key"])
        provider = llm_cfg.get("provider", "unknown")
        model = llm_cfg.get("model", "unknown")
        print(f"\n🤖 AI 分析配置：{provider}/{model}")
        print(f"  API Key：{'已配置 ✅' if api_ok else '未配置 ⚠️（将降级为模拟分析）'}")

    # ---------- 构建 (platform, region) 任务列表 ----------
    tasks = []
    for platform_key in target_platforms:
        platform = get_platform_info(platform_key)
        if args.all_regions:
            # 抓取该平台所有地区
            for rk in platform["regions"]:
                tasks.append((platform_key, rk))
        elif args.regions:
            # 仅抓取用户指定的地区（需该平台支持）
            for rk in args.regions:
                if rk in platform["regions"]:
                    tasks.append((platform_key, rk))
                else:
                    print(f"  ⚠️  {platform_key} 不支持地区 '{rk}'，跳过")
        else:
            # 默认：仅抓取各平台默认地区
            tasks.append((platform_key, platform.get("default_region", "us")))

    print(f"\n📋 抓取任务：{len(tasks)} 个站点")

    # ---------- 逐站点抓取 + 分析 + 保存 ----------
    total_saved = 0
    total_products = 0
    platform_summary = []

    for platform_key, region_key in tasks:
        platform = get_platform_info(platform_key)
        icon = platform.get("icon", "📦")
        name = platform.get("name", platform_key)
        region = get_region_info(platform_key, region_key)
        region_name = region.get("name", region_key)
        currency = region.get("currency", "USD")
        label = f"{name} {region_name}"

        # 第一步：抓取
        products, source_info = scrape_platform(platform_key, region_key)

        if not products:
            platform_summary.append(f"  {icon} {label}：0 个产品 ❌")
            continue

        total_products += len(products)

        # 第二步：AI 分析
        if args.skip_analysis:
            results = [{}] * len(products)
            print(f"  ⏭  跳过 AI 分析（--skip-analysis）")
        else:
            print(f"  🤖 AI 分析 {label} 产品...")
            results = analyze_products(products)
            print(f"  分析完成：{len(results)} 个产品")
            verdict_counts = {}
            for r in results:
                v = r.get("final_verdict", "unknown")
                verdict_counts[v] = verdict_counts.get(v, 0) + 1
            for v, count in sorted(verdict_counts.items()):
                emoji = {"recommended": "🟢", "cautious": "🟡", "not_recommended": "🔴"}.get(v, "⚪")
                print(f"    {emoji} {v}：{count} 个")

        # 第三步：保存到数据库
        source_label = source_info.get("source", "unknown")
        source_tag = f"{platform_key}_{region_key}_{source_label}"
        saved = save_products(
            products, results,
            source=source_tag,
            platform=platform_key,
            region=region_key,
            currency=currency,
        )
        total_saved += saved
        platform_summary.append(f"  {icon} {label}：{saved} 个产品 ✅")
        print(f"  💾 已保存 {saved} 条到数据库")

    # ---------- 导出 JSON ----------
    print(f"\n📄 导出 products.json...")
    latest_products = get_latest_products()
    if latest_products:
        json_path = os.path.join(os.path.dirname(__file__), "data", "products.json")
        os.makedirs(os.path.dirname(json_path), exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(latest_products, f, ensure_ascii=False, indent=2)
        print(f"  📄 已导出 products.json，包含 {len(latest_products)} 个产品")
    else:
        print(f"  ⚠️  数据库中无产品记录，跳过导出")

    # ---------- 完成汇总 ----------
    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
    db_total = get_product_count()

    print("\n" + "=" * 60)
    print("  ✅ 每日抓取完成")
    print("  ─────────────────────────────────────")
    for line in platform_summary:
        print(line)
    print("  ─────────────────────────────────────")
    print(f"  本次保存：{total_saved} 条（共 {total_products} 个产品）")
    print(f"  累计记录：{db_total} 条")
    print(f"  ⏱  总耗时：{elapsed:.1f} 秒")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ 脚本执行失败：{e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
