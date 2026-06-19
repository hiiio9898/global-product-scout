#!/usr/bin/env python
"""
站点失败诊断工具 — 用关键词检索每个 平台×地区，报告哪些站点可用/失败。

用法:
    python scripts/diagnose_sites.py                # 默认关键词 clothing
    python scripts/diagnose_sites.py "衣服"          # 中文自动翻译为英文
    python scripts/diagnose_sites.py "yoga mat" --json   # 额外存 JSON 报告

输出:
    - 终端表格：平台 | 地区 | 状态 | 产品数 | 耗时 | 错误
    - 汇总：成功率 + 失败站点清单
    - 可选 data/site_diagnosis.json
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone

# 把项目根目录加入 sys.path，便于 import src.*
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.platforms import PLATFORMS


# ============================================================
# 搜索调用封装（兼容 dict / tuple 两种返回 + 不同参数名）
# ============================================================

def _call_search(platform_key: str, search_func, keyword: str, region: str, limit: int):
    """
    调用平台搜索函数，归一化为统一 dict。

    各平台签名差异：
        amazon:     search_amazon(keyword, max_results=, region=)  → dict
        ebay:       search_ebay(keyword, region=, max_results=)    → dict
        aliexpress: search_aliexpress(keyword, region=, max_products=) → tuple(products, source_info)
        tiktok:     search_tiktok(keyword, region=, max_results=)  → dict

    返回统一形态：
        {"success": bool, "results": list, "error": str|None, "source": str}
    """
    # AliExpress 用 max_products，其余用 max_results
    if platform_key == "aliexpress":
        raw = search_func(keyword, region=region, max_products=limit)
    else:
        # 全部用 kwargs，规避 amazon 位置参数顺序差异
        raw = search_func(keyword, region=region, max_results=limit)

    # 归一化返回
    if isinstance(raw, tuple) and len(raw) == 2:
        products, source_info = raw
        source_info = source_info or {}
        src = source_info.get("source", "unknown")
        err = source_info.get("error")
        success = bool(products) and src != "unavailable" and not err
        return {"success": success, "results": products or [], "error": err, "source": src}

    if isinstance(raw, dict):
        return {
            "success": bool(raw.get("success")),
            "results": raw.get("results") or [],
            "error": raw.get("error"),
            "source": raw.get("source", "unknown"),
        }

    # 未知形态
    return {"success": False, "results": [], "error": f"未知返回形态: {type(raw)}", "source": "unknown"}


# ============================================================
# 关键词翻译（可选，best-effort）
# ============================================================

def _maybe_translate(keyword: str) -> tuple[str, str | None]:
    """含中文则尝试翻译为英文。返回 (实际搜索词, 翻译说明|None)。"""
    try:
        from src.translator import contains_chinese, translate_keyword
    except Exception:
        return keyword, None

    if not contains_chinese(keyword):
        return keyword, None

    tr = translate_keyword(keyword)
    if tr.get("success") and tr.get("translated") and tr["translated"] != keyword:
        return tr["translated"], f"{keyword} → {tr['translated']}"
    return keyword, f"(翻译失败，用原文 {keyword} 搜索)"


# ============================================================
# 主诊断流程
# ============================================================

def diagnose(keyword: str, limit: int = 5, timeout_per_site: int = 90):
    """对每个 平台×地区 跑关键词搜索，返回结果列表。"""
    search_kw, note = _maybe_translate(keyword)
    if note:
        print(f"🌐 关键词处理：{note}\n")

    rows = []
    total_sites = 0
    for pk, pf in PLATFORMS.items():
        regions = pf.get("regions", {})
        for rk in regions:
            total_sites += 1
            region_name = regions[rk].get("name", rk)
            label = f"{pf.get('icon','')} {pf.get('name', pk)} {region_name} ({rk})"
            print(f"  ⏳ 测试 {label} ...", end=" ", flush=True)
            t0 = time.time()
            entry = {
                "platform": pk,
                "platform_name": pf.get("name", pk),
                "region": rk,
                "region_name": region_name,
                "status": "pending",
                "product_count": 0,
                "duration_sec": 0,
                "error": None,
                "source": None,
            }
            try:
                mod = importlib.import_module(pf["search_module"])
                func = getattr(mod, pf["search_func"])
                result = _call_search(pk, func, search_kw, rk, limit)
                entry["duration_sec"] = round(time.time() - t0, 1)
                entry["product_count"] = len(result["results"])
                entry["source"] = result["source"]
                if result["success"] and result["results"]:
                    entry["status"] = "ok"
                    print(f"✅ {entry['product_count']} 个产品 ({entry['duration_sec']}s)")
                elif result["error"]:
                    entry["status"] = "blocked" if ("反爬" in str(result["error"]) or "拦截" in str(result["error"])) else "error"
                    entry["error"] = str(result["error"])[:120]
                    print(f"❌ {entry['status']}: {entry['error'][:60]}")
                else:
                    entry["status"] = "empty"
                    entry["error"] = "搜索返回 0 个产品"
                    print(f"⚠️ 0 产品")
            except Exception as e:
                entry["duration_sec"] = round(time.time() - t0, 1)
                entry["status"] = "error"
                entry["error"] = f"{type(e).__name__}: {str(e)[:120]}"
                print(f"❌ 异常: {entry['error'][:60]}")
            rows.append(entry)
    return rows, total_sites


def print_summary(rows, total_sites, keyword):
    """打印汇总报告。"""
    ok = [r for r in rows if r["status"] == "ok"]
    blocked = [r for r in rows if r["status"] == "blocked"]
    errored = [r for r in rows if r["status"] == "error"]
    empty = [r for r in rows if r["status"] == "empty"]

    print("\n" + "=" * 70)
    print(f"📋 诊断汇总 — 关键词「{keyword}」（共 {total_sites} 个站点）")
    print("=" * 70)
    print(f"  ✅ 可用：{len(ok)} 个")
    print(f"  🚫 反爬拦截：{len(blocked)} 个")
    print(f"  ❌ 报错：{len(errored)} 个")
    print(f"  ⚠️  空结果：{len(empty)} 个")
    print(f"  成功率：{len(ok)/total_sites*100:.0f}%" if total_sites else "")

    failed = blocked + errored + empty
    if failed:
        print("\n🚨 失败站点清单（建议人工复核是否删除）：")
        for r in failed:
            print(f"  - {r['platform_name']} {r['region_name']} ({r['platform']}/{r['region']}): "
                  f"[{r['status']}] {r['error'] or ''}")

    # 明细表
    print("\n📊 明细：")
    print(f"  {'平台':<14} {'地区':<10} {'状态':<8} {'产品数':<6} {'耗时':<6} 错误")
    for r in rows:
        status_emoji = {"ok": "✅", "blocked": "🚫", "error": "❌", "empty": "⚠️"}.get(r["status"], "?")
        print(f"  {r['platform_name']:<14} {r['region_name']:<10} {status_emoji} {r['status']:<6} "
              f"{r['product_count']:<6} {r['duration_sec']:<5} {r['error'] or ''}")


def main():
    parser = argparse.ArgumentParser(description="站点失败诊断工具")
    parser.add_argument("keyword", nargs="?", default="clothing", help="搜索关键词（中文自动翻译）")
    parser.add_argument("--limit", type=int, default=5, help="每站最多抓几个产品（默认 5，省时间）")
    parser.add_argument("--json", action="store_true", help="额外保存 JSON 报告到 data/site_diagnosis.json")
    args = parser.parse_args()

    print(f"🔍 开始诊断，关键词「{args.keyword}」，每站限 {args.limit} 个产品\n")
    rows, total = diagnose(args.keyword, limit=args.limit)

    print_summary(rows, total, args.keyword)

    if args.json:
        report = {
            "keyword": args.keyword,
            "scan_time": datetime.now(timezone.utc).isoformat(),
            "total_sites": total,
            "rows": rows,
        }
        out_path = os.path.join(_PROJECT_ROOT, "data", "site_diagnosis.json")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n💾 JSON 报告已保存：{out_path}")


if __name__ == "__main__":
    main()
