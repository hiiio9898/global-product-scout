"""
UI 共享组件 — 雷达图、收藏按钮、对比视图、产品加载等辅助函数。
从 app.py 拆分，各页面渲染函数共用。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import streamlit as st
import pandas as pd

from src.config import get_profit_defaults
from src.calculator import calculate_profit
from src.utils import safe_float
from src.database import (
    get_all_products,
    add_favorite,
    remove_favorite,
    is_favorite,
)
from src.platforms import get_region_info

from .constants import (
    VERDICT_LABEL_MAP,
    ANALYSIS_DIMS,
)

def _get_data_freshness(latest_time_str: str) -> tuple[str, str]:
    """
    判断数据新鲜度。

    Returns:
        (状态, 提示文本) — 状态取值 "ok"/"warn"/"error"/"unknown"
    """
    if not latest_time_str:
        return "error", "无数据"
    try:
        # 兼容多种时间格式
        ts = str(latest_time_str).replace("Z", "+00:00")
        if "+" not in ts and ts.endswith("UTC"):
            ts = ts.replace(" UTC", "+00:00")
        latest = datetime.fromisoformat(ts)
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        days = (now - latest).days
        if days <= 3:
            return "ok", f"✅ 数据更新于 {days} 天前"
        elif days <= 7:
            return "warn", f"⚠️ 数据已 {days} 天未更新，建议运行 daily_scrape.py"
        else:
            return "error", f"🔴 数据已 {days} 天未更新，产品排名可能已变化"
    except (ValueError, TypeError):
        return "unknown", "时间格式异常"




def _render_analysis_summary_table(products: list, results: list):
    """渲染分析结果速览表 — 在展开式卡片上方提供一览视图。"""
    summary_data = []
    for i, (p, r) in enumerate(zip(products, results)):
        verdict = r.get("final_verdict", "cautious")
        is_raw = r.get("parse_error", False)
        row = {
            "#": i + 1,
            "产品": (p.get("title_zh") or p.get("title", "") or "")[:50],
            "判定": "⚠️ 异常" if is_raw else VERDICT_LABEL_MAP.get(verdict, "⚪"),
            "价格": f"${float(p.get('price', 0) or 0):.2f}",
        }
        for label, key in ANALYSIS_DIMS:
            dim = r.get(key, {})
            row[label] = f"{dim.get('score', '-')}/10" if isinstance(dim, dict) else "-"
        summary_data.append(row)

    df = pd.DataFrame(summary_data)
    # 按判定排序：推荐 > 谨慎 > 不推荐 > 异常
    verdict_order = {"🟢 推荐入手": 0, "🟡 谨慎评估": 1, "🔴 不推荐": 2, "⚠️ 异常": 3}
    df["_sort"] = df["判定"].map(verdict_order).fillna(9)
    df = df.sort_values("_sort").drop(columns=["_sort"]).reset_index(drop=True)
    df.index = df.index + 1  # 从 1 开始编号

    st.dataframe(
        df, width="stretch", hide_index=False,
        column_config={
            "#": st.column_config.NumberColumn(width="small"),
            "产品": st.column_config.TextColumn(width="large"),
            "判定": st.column_config.TextColumn(width="small"),
            "价格": st.column_config.TextColumn(width="small"),
        },
    )




def _render_1688_result(result_1688: dict):
    """渲染 1688 比价结果（供多处复用）。"""
    if result_1688["success"]:
        pr = result_1688["price_range"]
        source = result_1688.get("source", "unknown")
        SOURCE_LABELS = {
            "1688_real": ("📦 1688 真实价格", "数据来自1688实时页面，可信度高"),
            "ai_estimate": ("🤖 AI 估算参考价", "价格由AI根据产品信息推估，仅供参考"),
            "local_estimate": ("📊 本地规则估算", "价格基于品类经验倍率计算，仅作参考"),
        }
        label, tooltip = SOURCE_LABELS.get(source, ("📦 参考价", ""))
        st.success(f"{label}：¥{pr['min']:.2f} ~ ¥{pr['max']:.2f}")
        if tooltip:
            st.caption(f"ℹ️ {tooltip}")
        for item in result_1688["results"]:
            title_1688 = item.get('title', '')
            price = item.get('price', 0)
            moq = item.get('moq', '')
            price_max = item.get('price_max', None)
            if price_max:
                st.caption(f"  • {title_1688} — ¥{price:.2f} ~ ¥{price_max:.2f} | {moq}")
            else:
                st.caption(f"  • {title_1688} — ¥{price:.2f} {moq}")
        if source == "1688_real" and result_1688.get("ai_estimate"):
            ai_pr = result_1688["ai_estimate"]
            st.caption(f"💡 AI 估算参考：¥{ai_pr['min']:.2f} ~ ¥{ai_pr['max']:.2f}")
    else:
        st.warning(f"⚠️ {result_1688.get('error', '比价失败')}")




def _render_radar_chart(dim_data: dict, title: str = ""):
    """渲染六维度雷达图（Plotly）。"""
    import plotly.graph_objects as go

    labels = [label for label, _ in ANALYSIS_DIMS]
    values = []
    for _, key in ANALYSIS_DIMS:
        dim = dim_data.get(key, {})
        values.append(dim.get("score", 0) if isinstance(dim, dict) else 0)

    # 闭合雷达图
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=values + [values[0]],
        theta=labels + [labels[0]],
        fill='toself',
        name=title or "产品",
        fillcolor='rgba(76, 175, 80, 0.2)',
        line=dict(color='#4CAF50', width=2),
    ))
    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 10], tickfont=dict(size=10)),
            angularaxis=dict(tickfont=dict(size=11)),
        ),
        showlegend=False,
        height=280,
        margin=dict(l=60, r=60, t=20, b=20),
    )
    st.plotly_chart(fig, width="stretch", key=f"radar_{title}_{hash(str(values))}")




def _render_favorite_button(
    title: str, platform: str, price: str = "", rating: str = "",
    num_reviews: str = "0", analysis_json: str = "{}", key_prefix: str = ""
):
    """渲染收藏/取消收藏按钮。返回当前收藏状态。"""
    fav_key = f"{title}_{platform}"
    cached = st.session_state.get(f"_fav_{fav_key}")
    if cached is None:
        cached = is_favorite(title, platform)
        st.session_state[f"_fav_{fav_key}"] = cached

    if cached:
        if st.button("⭐ 已收藏", key=f"{key_prefix}unfav_{hash(title)}", width="content"):
            remove_favorite(title, platform)
            st.session_state[f"_fav_{fav_key}"] = False
            st.rerun()
    else:
        if st.button("☆ 收藏", key=f"{key_prefix}fav_{hash(title)}", width="content"):
            add_favorite(title, platform, price, rating, num_reviews, analysis_json)
            st.session_state[f"_fav_{fav_key}"] = True
            st.rerun()

    return cached




def _render_comparison_view(products: list, indices: list[int]):
    """渲染产品对比视图。"""
    if len(indices) < 2:
        st.warning("请至少选择 2 个产品进行对比。")
        return

    selected = [products[i] for i in indices[:5]]  # 最多 5 个

    st.subheader("⚖️ 产品对比")

    # 构建对比表格
    rows = []

    # 基本信息
    rows.append(["产品标题"] + [(p.get("title", "") or "")[:40] for p in selected])
    rows.append(["价格"] + [f"${float(p.get('price', 0) or 0):.2f}" for p in selected])
    rows.append(["评分"] + [f"{p.get('rating', 'N/A')}" for p in selected])
    rows.append(["评论数"] + [f"{p.get('num_reviews', '0')}" for p in selected])

    # 六维度
    for label, key in ANALYSIS_DIMS:
        scores = []
        for p in selected:
            dim = p.get("analysis", {}).get(key, {})
            scores.append(f"{dim.get('score', '-')}/10" if isinstance(dim, dict) else "-")
        rows.append([label] + scores)

    # 判定
    verdicts = []
    for p in selected:
        v = p.get("analysis", {}).get("final_verdict", "")
        verdicts.append(VERDICT_LABEL_MAP.get(v, "⚪"))
    rows.append(["综合判定"] + verdicts)

    # 判定理由
    rows.append(["判定理由"] + [
        (p.get("analysis", {}).get("verdict_reason", "") or "")[:50] for p in selected
    ])

    # 转为 DataFrame
    col_names = [f"产品 {i+1}" for i in range(len(selected))]
    df = pd.DataFrame(rows, columns=["维度"] + col_names)

    st.dataframe(df, width="stretch", hide_index=True)


# ============================================================
# ==================== Dashboard 首页 ============================
# ============================================================



def _navigate_to(page: str, product: str = None):
    """按钮回调：切换页面。

    widget 绑定的 key（nav_page）只能在 on_click 回调中写入，
    回调在 widget 渲染前执行，因此这里是合法的。
    """
    st.session_state["nav_page"] = page
    if product is not None:
        st.session_state["goto_product"] = product




def _load_all_products() -> list:
    """加载全量产品数据 — 首页统一数据源。

    优先级：data/products.json（GitHub Actions 每日提交，Cloud 唯一完整来源）
            > 本地 SQLite（累积历史，本地开发补充）。
    """
    products = []
    json_path = os.path.join(os.path.dirname(__file__), "data", "products.json")
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                products = json.load(f) or []
        except (json.JSONDecodeError, OSError):
            products = []

    try:
        db_products = get_all_products()
    except Exception:
        db_products = []

    if db_products:
        seen = {(p.get("platform", ""), p.get("region", ""), p.get("title", "")) for p in products}
        for p in db_products:
            key = (p.get("platform", ""), p.get("region", ""), p.get("title", ""))
            if key not in seen:
                products.append(p)
                seen.add(key)

    return products





def _dim_score_of(p: dict, key: str) -> float:
    """从产品 analysis 取某个维度分数（0-10），缺失返回 5。"""
    dim = (p.get("analysis") or {}).get(key, {})
    if isinstance(dim, dict):
        try:
            return float(dim.get("score", 5) or 5)
        except (ValueError, TypeError):
            return 5.0
    return 5.0






def _render_beginner_picks(products: list):
    """渲染新手精选卡：产品名、一句话理由、利润卡、白话解读。

    筛选：final_verdict=recommended，按「新手友好度」降序（新手最该做的排最前）。
    """
    recommended = [
        p for p in products
        if (p.get("analysis") or {}).get("final_verdict") == "recommended"
    ]
    recommended.sort(
        key=lambda p: (_dim_score_of(p, "beginner_friendly"), _dim_score_of(p, "profit_potential")),
        reverse=True,
    )
    picks = recommended[:5]
    if not picks:
        st.info("📊 数据已就绪，但暂无推荐产品。运行新一轮分析获取建议。")
        st.button("🔍 开始新一轮分析", type="primary", key="goto_live_new", width="stretch",
                  on_click=_navigate_to, args=("实时选品",))
        return

    st.markdown(f"### 🏆 AI 帮你挑了 {len(picks)} 个最适合新手做的产品")
    st.caption("已按「新手友好度」排序 — 越靠前越适合零基础起步。")
    st.divider()

    for i, p in enumerate(picks, 1):
        analysis = p.get("analysis") or {}
        title = p.get("title_zh") or p.get("title") or f"产品 #{i}"
        try:
            price = safe_float(p.get("price"))
        except Exception:
            price = 0.0
        currency = p.get("currency", "USD")
        region = (p.get("region") or "us").upper()
        verdict_reason = analysis.get("verdict_reason", "")

        platform = p.get("platform", "amazon")
        profit_defaults = get_profit_defaults(platform)
        region_info = get_region_info(platform, p.get("region", "us"))
        profit_defaults = {**profit_defaults, "exchange_rate": region_info.get("exchange_rate", profit_defaults.get("exchange_rate", 7.24))}
        ai_cost = min(max(safe_float(analysis.get("estimated_cost_cny")), 0.0), 5000.0)
        try:
            profit = calculate_profit(price, profit_defaults, procurement_cny=ai_cost, platform=platform)
        except Exception:
            profit = {"net_profit_cny": 0.0, "margin_pct": 0.0}

        bf = _dim_score_of(p, "beginner_friendly")
        comp = _dim_score_of(p, "competition")
        longev = _dim_score_of(p, "longevity")
        bf_reason = ((analysis.get("beginner_friendly") or {}).get("reason") or "").strip()
        comp_reason = ((analysis.get("competition") or {}).get("reason") or "").strip()
        longev_reason = ((analysis.get("longevity") or {}).get("reason") or "").strip()

        with st.container(border=True):
            col_t, col_p = st.columns([5, 2])
            with col_t:
                st.markdown(f"**🟢 推荐 #{i}** {title}")
                if verdict_reason:
                    st.caption(f"💡 {verdict_reason}")
            with col_p:
                if price > 0:
                    st.markdown(f"💰 售价 **{price:.2f} {currency}** ({region})")

            if ai_cost > 0:
                np_ = profit.get("net_profit_cny", 0)
                margin = profit.get("margin_pct", 0)
                emoji = "🟢" if np_ > 0 else "🔴"
                st.markdown(
                    f"{emoji} **净利润 ¥{np_:.0f}/件** ｜ 利润率 **{margin:.0f}%**"
                    f" 〈采购 ¥{ai_cost:.0f} + 运费/佣金/广告〉"
                )
            else:
                st.caption("💰 点「查看完整分析」可手动填采购成本算利润")

            st.markdown("")
            if bf >= 7:
                st.markdown(f"✅ **适合新手**：{bf_reason}" if bf_reason else "✅ **适合新手**：门槛低、好上手")
            if comp >= 7:
                st.markdown(f"⚠️ **竞争激烈**：{comp_reason}" if comp_reason else "⚠️ **竞争激烈**：头部玩家多")
            elif comp <= 3:
                st.markdown(f"🟢 **竞争小**：{comp_reason}" if comp_reason else "🟢 **竞争小**：有蓝海空间")
            if longev >= 7:
                st.markdown(f"📈 **能长期做**：{longev_reason}" if longev_reason else "📈 **能长期做**：需求稳定")

            st.button(
                "查看完整分析 →",
                key=f"pick_detail_{i}",
                on_click=_navigate_to, args=("历史记录", title),
                help="查看六维度评分、判定理由、原始分析数据",
            )

    st.divider()
    col_more, col_market = st.columns(2)
    with col_more:
        if len(recommended) > len(picks):
            st.button(
                f"查看全部 {len(recommended)} 个推荐 →",
                key="goto_history_all",
                width="stretch",
                on_click=_navigate_to, args=("历史记录",),
            )
    with col_market:
        st.button("🔍 换个市场看看", key="goto_live_market", width="stretch",
                  on_click=_navigate_to, args=("实时选品",))




def _match_filters_simple(product: dict, filters: dict) -> bool:
    """简化的筛选条件匹配（用于 Python 层过滤）。"""
    analysis = product.get("analysis", {})

    # verdict 筛选
    verdicts = filters.get("verdicts")
    if verdicts:
        actual = analysis.get("final_verdict", "")
        if actual not in verdicts:
            return False

    # 市场容量
    min_cap = filters.get("min_capacity_score")
    if min_cap is not None and min_cap > 1:
        mc = analysis.get("market_capacity", {})
        if isinstance(mc, dict) and mc.get("score", 0) < min_cap:
            return False

    # 价格区间
    min_price = filters.get("min_price")
    max_price = filters.get("max_price")
    try:
        price = float(product.get("price", 0) or 0)
    except (ValueError, TypeError):
        price = 0.0
    if min_price is not None and min_price > 0 and price < min_price:
        return False
    if max_price is not None and max_price < 1000 and price > max_price:
        return False

    return True




def _dim_score(analysis: dict, key: str) -> str:
    """从分析结果提取维度评分字符串，如 '7/10'。"""
    dim = analysis.get(key, {})
    if isinstance(dim, dict) and dim.get("score"):
        return f"{dim['score']}/10"
    return "N/A"




def _verdict_emoji(verdict: str) -> str:
    """将 verdict 转为带 emoji 的展示字符串。"""
    return {
        "recommended": "🟢 推荐", "cautious": "🟡 谨慎",
        "not_recommended": "🔴 不推荐",
    }.get(verdict, verdict)
