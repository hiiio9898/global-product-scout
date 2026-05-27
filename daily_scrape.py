"""
每日定时抓取脚本 — 独立于 Streamlit 运行。

工作流程：
    1. 调用 src.scraper.fetch_amazon_best_sellers() 获取产品数据
       （三层降级：实时抓取 → 本地缓存 → 模拟数据）
    2. 调用 src.analyzer.analyze_products() 进行 AI 分析
       （有 DEEPSEEK_API_KEY 时用 DeepSeek，否则模拟分析）
    3. 调用 src.database.save_products() 保存到 SQLite

用法：
    python daily_scrape.py

依赖：
    配置通过 .env 文件或环境变量读取（同 Streamlit 本地开发方式）。
    云端运行（如 GitHub Actions）通过 secrets 注入环境变量。
"""

import sys
import os
from datetime import datetime, timezone

# 将项目根目录加入 Python 路径，使 from src.xxx 能正常导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.config import get_config
from src.scraper import fetch_amazon_best_sellers
from src.analyzer import analyze_products
from src.database import save_products, get_product_count


def main():
    """主流程：抓取 → 分析 → 存库 → 输出统计。"""
    start_time = datetime.now(timezone.utc)

    print("=" * 60)
    print("  Global Product Scout — 每日自动抓取")
    print(f"  开始时间：{start_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 60)

    # ---------- 第一步：抓取数据 ----------
    print("\n📡 第 1 步：抓取 Amazon Best Sellers 数据...")
    products, source_info = fetch_amazon_best_sellers()
    src = source_info.get("source", "unknown")
    ts = source_info.get("timestamp", "")
    print(f"  数据来源：{src}")
    print(f"  ├─ 来源说明："
          f"{'实时抓取 ✅' if src == 'live' else ('本地缓存 💾' if src == 'cache' else '模拟数据 📋')}")
    print(f"  └─ 获取产品：{len(products)} 个")
    if ts:
        print(f"     时间戳：{ts}")

    if not products:
        print("❌ 未获取到任何产品，终止执行。")
        sys.exit(1)

    # ---------- 第二步：AI 分析 ----------
    cfg = get_config()
    api_ok = bool(cfg["deepseek_api_key"])
    print(f"\n🤖 第 2 步：AI 分析产品...")
    print(f"  DeepSeek API：{'已配置 ✅' if api_ok else '未配置，使用模拟分析 ⚠️'}")
    results = analyze_products(products)
    print(f"  分析完成：{len(results)} 个产品")
    verdict_counts = {}
    for r in results:
        v = r.get("final_verdict", "unknown")
        verdict_counts[v] = verdict_counts.get(v, 0) + 1
    for v, count in sorted(verdict_counts.items()):
        emoji = {"recommended": "🟢", "cautious": "🟡", "not_recommended": "🔴"}.get(v, "⚪")
        print(f"  {emoji} {v}：{count} 个")

    # ---------- 第三步：保存到数据库 ----------
    print(f"\n💾 第 3 步：保存到数据库...")
    saved = save_products(products, results)
    total = get_product_count()
    print(f"  本次保存：{saved} 条")
    print(f"  累计记录：{total} 条")

    # ---------- 完成 ----------
    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
    print("\n" + "=" * 60)
    print(f"  ✅ 抓取完成，共保存 {saved} 条产品")
    print(f"  ⏱  总耗时：{elapsed:.1f} 秒")
    print("=" * 60)


if __name__ == "__main__":
    main()
