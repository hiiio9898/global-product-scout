"""
Streamlit 主程序入口 — 外贸 AI 选品助手（Global Product Scout）。

提供"数据获取 → AI 分析 → 结果展示"一站式选品体验。
数据源采用两级策略：优先读取 data/products.json → 降级到实时抓取（仅接受 live 数据）。

用法：
    streamlit run app.py
"""

import sys
import os
import re
import tempfile
import importlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import pandas as pd
import json

from src.config import get_config, get_llm_config, get_profit_defaults, LLM_PROVIDERS, _get_secret
from src.scraper import fetch_amazon_best_sellers
from src.scraper_search import search_amazon
from src.analyzer import analyze_products, analyze_category_report
from src.calculator import calculate_profit, get_calculator
from src.scraper_1688 import search_1688_hybrid
from src.trends import get_trend_direction, get_trend_icon
from src.platforms import (
    PLATFORMS,
    get_platform_info,
    get_region_info,
    get_platform_choices,
    get_region_choices,
    get_active_platform,
    get_active_region,
)
from src.database import (
    init_db,
    save_products,
    get_all_products,
    get_product_count,
    export_csv,
    save_procurement_cost,
    get_procurement_cost,
    get_trend_data,
    query_products,
    get_platform_summary,
    add_favorite,
    remove_favorite,
    is_favorite,
    get_favorites,
)
from datetime import datetime, timezone

# ============================================================
# 页面配置
# ============================================================

st.set_page_config(
    page_title="Global Product Scout",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 加载自定义 CSS 主题
_css_path = os.path.join(os.path.dirname(__file__), ".streamlit", "style.css")
if os.path.exists(_css_path):
    with open(_css_path, "r", encoding="utf-8") as _f:
        st.markdown(f"<style>{_f.read()}</style>", unsafe_allow_html=True)

# ============================================================
# 模块级常量
# ============================================================

APP_VERSION = "v0.6.0"

VERDICT_LABEL_MAP = {
    "recommended": "🟢 推荐入手",
    "cautious": "🟡 谨慎评估",
    "not_recommended": "🔴 不推荐",
}

ANALYSIS_DIMS = [
    ("📊 市场容量", "market_capacity"),
    ("⚔️ 竞争程度", "competition"),
    ("💰 利润潜力", "profit_potential"),
    ("🎓 新手友好", "beginner_friendly"),
    ("🌡️ 季节风险", "seasonality_risk"),
]

# ============================================================
# 侧边栏 — 配置区
# ============================================================

def render_sidebar(source_info: dict | None = None):
    """渲染侧边栏 — 页面导航、数据源状态和 API 配置。"""
    st.sidebar.title("⚙️ 设置")

    # ---- 页面导航 ----
    page = st.sidebar.radio(
        "📌 页面导航",
        options=["📊 Dashboard", "🔍 实时选品", "🎯 指定选品", "📚 历史记录"],
        help="Dashboard：数据概览（自动按平台筛选）\n实时选品：抓取并分析当前平台热销产品\n指定选品：输入关键词深度分析特定品类\n历史记录：查看过去保存的分析结果",
    )

    st.sidebar.divider()

    # ---- 平台 + 地区联动选择器（仅实时/指定选品页显示） ----
    if "实时选品" in page or "指定选品" in page:
        st.sidebar.subheader("🛒 平台选择")

        # 平台选择
        platform_keys = get_platform_choices()
        platform_names = {
            k: f"{get_platform_info(k)['icon']} {get_platform_info(k)['name']}"
            for k in platform_keys
        }

        # 从 session_state 恢复，默认 amazon
        last_platform = st.session_state.get("active_platform", "amazon")
        if last_platform not in platform_keys:
            last_platform = "amazon"

        selected_platform = st.sidebar.selectbox(
            "🛒 选择平台",
            options=platform_keys,
            format_func=lambda k: platform_names[k],
            index=platform_keys.index(last_platform),
            key="selected_platform",
        )
        st.session_state["active_platform"] = selected_platform

        # 地区选择（联动平台）
        region_choices = get_region_choices(selected_platform)
        region_keys = [r[0] for r in region_choices]
        region_names = {r[0]: r[1] for r in region_choices}

        # 从 session_state 恢复，默认平台的 default_region
        pf_info = get_platform_info(selected_platform)
        default_region = pf_info.get("default_region", region_keys[0])
        last_region = st.session_state.get("active_region", default_region)
        if last_region not in region_keys:
            last_region = default_region

        selected_region = st.sidebar.selectbox(
            "🌍 选择地区",
            options=region_keys,
            format_func=lambda k: region_names.get(k, k),
            index=region_keys.index(last_region),
            key="selected_region",
        )
        st.session_state["active_region"] = selected_region

        # 数据源状态指示
        if source_info:
            src = source_info.get("source", "unknown")
            ts = source_info.get("timestamp", "")
            if src == "json":
                source_label = "📄 JSON 数据（本地采集）"
            elif src == "live":
                source_label = "📡 实时数据"
            else:
                source_label = "❌ 无数据"
            st.sidebar.caption(f"数据状态：{source_label}")
            if ts:
                st.sidebar.caption(f"⏰ {ts}")

    # ---- AI 模型选择器 ----
    llm_cfg = get_llm_config()
    st.sidebar.divider()
    st.sidebar.subheader("🤖 AI 模型")

    # 供应商选择
    provider_names = {k: v["name"] for k, v in LLM_PROVIDERS.items()}
    provider_keys = list(LLM_PROVIDERS.keys())

    # 从 session_state 恢复上次 UI 选择，否则从环境变量读取
    last_provider = st.session_state.get("llm_provider") or llm_cfg["provider"]
    last_model = st.session_state.get("llm_model") or llm_cfg["model"]

    current_provider_idx = provider_keys.index(last_provider) if last_provider in provider_keys else 0

    selected_provider = st.sidebar.selectbox(
        "AI 供应商",
        options=provider_keys,
        format_func=lambda k: provider_names[k],
        index=current_provider_idx,
        key="llm_provider_select",
    )

    # 模型选择（根据供应商动态更新）
    available_models = LLM_PROVIDERS[selected_provider]["models"]
    if last_model not in available_models:
        last_model = available_models[0]

    selected_model = st.sidebar.selectbox(
        "模型",
        options=available_models,
        index=available_models.index(last_model),
        key="llm_model_select",
    )

    # 仅更新 session_state，不做 st.rerun（避免打断按钮点击）
    st.session_state["llm_provider"] = selected_provider
    st.session_state["llm_model"] = selected_model

    # API 配置状态显示（直接读取所选供应商的 Key，避免 session_state 时序问题）
    provider_info = LLM_PROVIDERS[selected_provider]
    provider_name = provider_info["name"]
    # 直接从 st.secrets / .env 读取所选供应商的 API Key
    provider_api_key = _get_secret(provider_info["api_key_key"], "")
    if provider_api_key:
        st.sidebar.caption(f"✅ {provider_name} {selected_model}")
    else:
        st.sidebar.caption(f"⚠️ {provider_name} 未配置（使用模拟分析）")
        st.sidebar.info(
            f"💡 在 **Streamlit Secrets**（云端）或 `.env` 文件（本地）中\n"
            f"配置 `{provider_info['api_key_key']}` 即可启用 {provider_name} AI 分析。"
        )

    # ---- 💰 利润参数（可配置，平台自适应） ----
    st.sidebar.divider()
    with st.sidebar.expander("💰 利润参数（可配置）", expanded=False):
        # 根据当前平台读取默认参数
        active_pf = st.session_state.get("active_platform", "amazon")
        pf_info = get_platform_info(active_pf)
        active_region = st.session_state.get("active_region", pf_info.get("default_region", "us"))
        region_info = get_region_info(active_pf, active_region)
        profit_defaults = get_profit_defaults(active_pf)

        # 汇率（按地区站点自动适配）
        currency_label = region_info.get("currency", "USD")
        exchange_rate = st.number_input(
            f"汇率 (CNY/{currency_label})", min_value=0.01, max_value=20.0,
            value=float(profit_defaults["exchange_rate"]), step=0.01,
            help=f"1 {currency_label} 兑换多少人民币",
        )
        # 佣金比例（各平台标签不同）
        commission_label = {
            "amazon": "亚马逊佣金比例",
            "ebay": "eBay 成交费比例",
            "alibaba": "阿里巴巴佣金比例",
        }.get(active_pf, "平台佣金比例")
        commission_pct = st.slider(
            commission_label, min_value=0.0, max_value=0.50,
            value=float(profit_defaults.get("commission_pct", 0.15)), step=0.01,
            format="%.0f%%",
        )
        # 广告预算（Amazon 特有）
        if active_pf == "amazon":
            ad_pct = st.slider(
                "广告预算占比", min_value=0.0, max_value=0.50,
                value=float(profit_defaults.get("ad_pct", 0.10)), step=0.01,
                format="%.0f%%",
            )
        else:
            ad_pct = 0.0
        # 运费
        shipping_label = {
            "amazon": "FBA 头程运费 (¥/件)",
            "ebay": "国际运费 (¥/件)",
            "alibaba": "国际运费 (¥/件)",
        }.get(active_pf, "国际运费 (¥/件)")
        shipping_cny = st.number_input(
            shipping_label, min_value=0.0, max_value=200.0,
            value=float(profit_defaults.get("shipping_cny", 15.0)), step=1.0,
        )

    # 同步到 session_state 供计算器使用
    st.session_state["profit_defaults"] = {
        "exchange_rate": exchange_rate,
        "commission_pct": commission_pct,
        "ad_pct": ad_pct,
        "shipping_cny": shipping_cny,
        "procurement_cny": 0.0,
    }

    # ---- 数据库状态 ----
    count = get_product_count()
    st.sidebar.caption(f"📦 历史记录：{count} 条产品数据")

    return llm_cfg["configured"], page


# ============================================================
# UX 辅助函数（Spec 16）
# ============================================================

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
            "产品": (p.get("title", "") or "")[:50],
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
        source_label = {
            "1688_real": "📦 1688 真实价格",
            "ai_estimate": "🤖 AI 估算参考价",
            "local_estimate": "📊 本地规则估算",
        }.get(source, "📦 参考价")
        st.success(f"{source_label}：¥{pr['min']:.2f} ~ ¥{pr['max']:.2f}")
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
    """渲染五维度雷达图（Plotly）。"""
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

    # 五维度
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

def _render_dashboard_page():
    """渲染 Dashboard 首页 — 数据概览 + TOP5 推荐。"""

    st.title("📊 全球产品侦察兵 — 数据概览")
    st.markdown("一目了然掌握选品全局，快速定位高潜力产品。")
    st.divider()

    # 获取数据
    all_products = get_all_products()
    if not all_products:
        st.info(
            "📭 **暂无数据**\n\n"
            "请先切换到「🔍 实时选品」页面，点击「开始分析」运行一次分析，\n"
            "数据会自动保存到数据库并在此展示概览。"
        )
        return

    # ---- 指标计算 ----
    total = len(all_products)
    recommended = [p for p in all_products if p.get("analysis", {}).get("final_verdict") == "recommended"]
    rec_count = len(recommended)

    # Dashboard 平台筛选（Spec 16 P2）
    platform_set = {p.get("platform", "amazon") for p in all_products}
    if len(platform_set) > 1:
        platform_options = sorted(platform_set)
        platform_names = {
            k: f"{PLATFORMS.get(k, {}).get('icon', '❓')} {PLATFORMS.get(k, {}).get('name', k)}"
            for k in platform_options
        }
        selected_dash_platforms = st.multiselect(
            "🛒 筛选平台",
            options=platform_options,
            default=platform_options,
            format_func=lambda k: platform_names.get(k, k),
            key="dashboard_platforms",
        )
        if len(selected_dash_platforms) < len(platform_options):
            all_products = [p for p in all_products if p.get("platform", "amazon") in selected_dash_platforms]
            recommended = [p for p in all_products if p.get("analysis", {}).get("final_verdict") == "recommended"]
            total = len(all_products)
            rec_count = len(recommended)

    def _avg_score(key):
        scores = []
        for p in all_products:
            dim = p.get("analysis", {}).get(key, {})
            if isinstance(dim, dict) and "score" in dim:
                scores.append(dim["score"])
        return sum(scores) / len(scores) if scores else 0.0

    avg_capacity = _avg_score("market_capacity")
    avg_profit = _avg_score("profit_potential")

    # ---- 指标卡片 ----
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("📦 总产品数", total)
    c2.metric("🟢 推荐数", rec_count)
    c3.metric("📊 平均容量分", f"{avg_capacity:.1f}/10")
    c4.metric("💰 平均利润分", f"{avg_profit:.1f}/10")

    # 最近抓取时间 + 数据新鲜度
    latest_time = all_products[0].get("scrape_time", "")
    if latest_time:
        freshness_status, freshness_text = _get_data_freshness(latest_time)
        if freshness_status == "ok":
            st.caption(freshness_text)
        elif freshness_status == "warn":
            st.warning(freshness_text)
        elif freshness_status == "error":
            st.error(freshness_text)
        else:
            st.caption(f"最近抓取：{latest_time}")

    st.divider()

    # ---- TOP5 推荐产品 ----
    st.subheader("🏆 TOP 5 推荐产品")

    top5 = recommended[:5]
    if not top5:
        st.warning("暂无推荐产品。")
        return

    for i, p in enumerate(top5, 1):
        analysis = p.get("analysis", {})
        title = p.get("title", f"产品 #{i}")
        try:
            price = float(p.get("price", 0) or 0)
        except (ValueError, TypeError):
            price = 0.0
        try:
            rating = float(p.get("rating", 0) or 0)
        except (ValueError, TypeError):
            rating = 0.0
        capacity = analysis.get("market_capacity", {})
        cap_score = capacity.get("score", 0) if isinstance(capacity, dict) else 0
        cap_reason = capacity.get("reason", "") if isinstance(capacity, dict) else ""

        with st.container(border=True):
            col_title, col_score = st.columns([3, 1])
            with col_title:
                st.markdown(f"**🟢 推荐 #{i}** {title}")
                st.caption(f"💰 ${price:.2f} | ⭐ {rating} | 📊 容量 {cap_score}/10")
            with col_score:
                verdict_reason = analysis.get("verdict_reason", "")
                if verdict_reason:
                    st.caption(verdict_reason)

    # ---- 数据源分布 ----
    st.divider()
    st.subheader("📋 数据源分布")
    source_counts = {}
    for p in all_products:
        src = p.get("source", "unknown")
        source_counts[src] = source_counts.get(src, 0) + 1
    cols = st.columns(len(source_counts) or 1)
    for col, (src, count) in zip(cols, source_counts.items()):
        col.metric(f"{src}", count)


# ============================================================
# ==================== 实时选品页面 ============================
# ============================================================

def _render_live_page(api_ok: bool):
    """渲染实时选品页面（多平台版本 — 根据侧边栏选择的平台+地区自动适配）。"""

    # 获取当前平台配置
    platform = st.session_state.get("active_platform", "amazon")
    region = st.session_state.get("active_region", "us")
    pf_info = get_platform_info(platform)
    region_info = get_region_info(platform, region)
    pf_name = f"{pf_info['icon']} {pf_info['name']}"
    region_name = region_info["name"]
    currency = region_info.get("currency", "USD")

    st.title(f"🔍 Global Product Scout — {pf_name} {region_name}")
    st.markdown(
        f"🚀 智能抓取 **{pf_name} {region_name}** 热销产品数据，AI 深度分析竞争力与利润潜力，"
        "帮你找到下一个爆款！"
    )
    st.divider()

    # ---- 开始分析按钮 ----
    btn_disabled = st.session_state.get("analyzing", False)

    col_json, col_live = st.columns(2)
    with col_json:
        btn_json = st.button(
            "📄 分析 JSON 数据",
            type="primary",
            width="stretch",
            disabled=btn_disabled,
            help="读取 data/products.json 中已抓取的产品数据进行 AI 分析",
        )
    with col_live:
        btn_live = st.button(
            f"📡 实时抓取 {pf_name}",
            type="secondary",
            width="stretch",
            disabled=btn_disabled,
            help=f"从 {pf_name} {region_name} 实时抓取最新热销数据",
        )

    if btn_json:
        st.session_state.analyzing = True
        try:
            json_path = os.path.join(os.path.dirname(__file__), "data", "products.json")
            if not os.path.exists(json_path):
                st.session_state.analyzing = False
                st.error("❌ data/products.json 不存在")
                st.info(
                    "💡 请在本机执行 `python daily_scrape.py` 生成 JSON 文件，"
                    "然后将 `data/products.json` 提交并推送到 GitHub。"
                )
            else:
                with st.spinner("📄 正在读取 JSON 数据..."):
                    with open(json_path, "r", encoding="utf-8") as f:
                        products = json.load(f)
                    if not products:
                        st.session_state.analyzing = False
                        st.error("❌ JSON 文件中无产品数据")
                    else:
                        scrape_time = products[0].get("scrape_time", "")
                        st.session_state.products = products
                        st.session_state.source_info = {"source": "json", "timestamp": scrape_time}
                        st.session_state.step = "loaded"
                        st.rerun()
        except Exception as e:
            st.session_state.analyzing = False
            st.error(f"❌ 读取 JSON 失败：{str(e)}")

    if btn_live:
        st.session_state.analyzing = True
        try:
            with st.spinner(f"📡 正在实时抓取 {pf_name} {region_name} 热销数据..."):
                # 动态调用平台对应的抓取函数
                import importlib
                scraper_mod = importlib.import_module(pf_info["scraper_module"])
                scraper_func = getattr(scraper_mod, pf_info["scraper_func"])
                products, source_info = scraper_func(region=region)

                if source_info.get("source") not in ("live", "cache"):
                    st.session_state.analyzing = False
                    error_detail = source_info.get("error", "网站反爬拦截或页面不可用")
                    st.error(f"❌ 实时抓取 {pf_name} 失败")
                    st.warning(f"原因: {error_detail}")

                    platform = st.session_state.get("active_platform", "amazon")
                    st.info(
                        "💡 **推荐方案：**\n"
                        "1. 使用「📄 分析 JSON 数据」分析已有的产品数据\n"
                        "2. 使用「🎯 指定选品」通过关键词搜索产品\n"
                        "3. 在本机运行 `python daily_scrape.py` 更新数据后重新部署"
                    )
                else:
                    st.session_state.products = products
                    st.session_state.source_info = source_info
                    st.session_state.step = "loaded"
                    st.rerun()
        except Exception as e:
            st.session_state.analyzing = False
            st.error(f"❌ 实时抓取失败：{str(e)}")
            st.info("🔧 请检查网络连接后重试。")

    # ---- 数据显示（加载完成后显示，此时侧边栏已更新） ----
    if st.session_state.step in ("loaded", "analyzed") and st.session_state.products:
        src_info = st.session_state.source_info or {}
        src_type = src_info.get("source", "")
        ts = src_info.get("timestamp", "")
        if src_type == "json":
            st.success(f"📄 已加载 JSON 文件数据！共 {len(st.session_state.products)} 个热销产品\n\n⏰ 抓取时间：{ts}")
        elif src_type == "live":
            st.success(f"✅ 实时抓取成功！已获取 {len(st.session_state.products)} 个热销产品\n\n⏰ 数据更新时间：{ts}")

        # 第二步：AI 分析（如果还未开始）
        if st.session_state.step == "loaded":
            with st.status("🤖 AI 正在深度分析产品竞争力与利润潜力...", expanded=False) as status:
                progress_bar = st.progress(0, text="准备分析...")
                total = len(st.session_state.products)

                def _on_progress(done, total_count):
                    pct = min(done / total_count, 1.0)
                    progress_bar.progress(pct, text=f"分析进度：{done}/{total_count}")

                results = analyze_products(
                    st.session_state.products,
                    progress_callback=_on_progress,
                )
                st.session_state.results = results
                st.session_state.step = "analyzed"
                progress_bar.empty()
                status.update(label="✅ AI 分析完成！", state="complete")

            # 第三步：保存到数据库
            db_ok = True
            try:
                saved_count = save_products(
                    st.session_state.products, results,
                    platform=platform, region=region, currency=currency,
                )
                st.caption(f"💾 已保存 {saved_count} 条分析记录到历史数据库")
            except Exception:
                db_ok = False
                st.caption("⚠️ 数据库保存失败，但分析结果仍可在当前页面查看")

            # 同步保存到 session state（Cloud 端 SQLite 不持久化的后备方案）
            for p, r in zip(st.session_state.products, results):
                record = dict(p)
                record["analysis"] = r
                record["scrape_time"] = r.get("scrape_time", p.get("scrape_time", ""))
                st.session_state.history_data.append(record)

            if not api_ok:
                llm_info = get_llm_config()
                provider_name = llm_info["provider_name"]
                api_key_env = LLM_PROVIDERS[llm_info["provider"]]["api_key_key"]
                st.info(
                    f"💡 **提示：** 当前使用的是本地模拟分析引擎。\n\n"
                    f"想获得更精准的 AI 分析？只需在项目根目录的 `.env` 文件中配置 "
                    f"`{api_key_env}=你的Key`，就能解锁 {provider_name} AI 分析能力！"
                )
            else:
                llm_info = get_llm_config()
                st.success(f"✅ 分析完成！{llm_info['provider_name']} AI 已为你深度评估每个产品的选品潜力。")

            # 生成品类综合报告（实时选品页）
            try:
                category_report = analyze_category_report(
                    f"{pf_name} {region_name} 热销产品",
                    st.session_state.products,
                )
                st.session_state.live_category = category_report
            except Exception:
                st.session_state.live_category = None

            st.session_state.analyzing = False
            st.rerun()

    # ---- 产品榜单表格 ----
    if st.session_state.step in ("loaded", "analyzed") and st.session_state.products:
        st.subheader("📋 热销产品榜单")

        src = st.session_state.source_info or {}
        source_type = src.get("source", "unknown")
        ts = src.get("timestamp", "")
        if source_type == "json":
            caption = f"数据来源：JSON 文件 | 抓取时间：{ts}"
        else:
            platform = st.session_state.get("active_platform", "amazon")
            pf_info = get_platform_info(platform)
            pf_name = f"{pf_info['icon']} {pf_info['name']}"
            caption = f"数据来源：{pf_name}（实时抓取）| 更新时间：{ts}"
        st.caption(caption)

        df = pd.DataFrame(st.session_state.products)
        df_display = df.rename(columns={
            "rank": "排名", "title": "产品名称", "price": "价格 (USD)",
            "rating": "评分 ⭐", "num_reviews": "评论数", "category": "类目",
        })
        display_columns = ["排名", "产品名称", "价格 (USD)", "评分 ⭐", "评论数", "类目"]
        available_cols = [c for c in display_columns if c in df_display.columns]
        st.dataframe(
            df_display[available_cols], width="stretch", hide_index=True,
            column_config={
                "排名": st.column_config.NumberColumn(format="%d"),
                "价格 (USD)": st.column_config.NumberColumn(format="$%.2f"),
                "评分 ⭐": st.column_config.NumberColumn(format="%.1f"),
            },
        )

    # ---- AI 分析卡片 ----
    if st.session_state.step == "analyzed" and st.session_state.results:
        # 品类综合报告（实时选品页）
        live_cat = st.session_state.get("live_category")
        if live_cat and not live_cat.get("error"):
            st.subheader("📊 品类综合报告")
            st.markdown(f"**📝 市场概况：** {live_cat.get('category_overview', '')}")
            col_r1, col_r2, col_r3 = st.columns(3)
            with col_r1:
                st.metric("📈 市场规模", live_cat.get("market_size", "N/A"))
            with col_r2:
                comp = live_cat.get("competition_level", "unknown")
                comp_label = {"low": "🟢 低竞争", "medium": "🟡 中等竞争", "high": "🔴 高竞争"}.get(comp, "⚪ 未知")
                st.metric("⚔️ 竞争程度", comp_label)
            with col_r3:
                st.metric("💰 价格分布", live_cat.get("price_distribution", "N/A"))
            if live_cat.get("entry_suggestion"):
                st.info(f"💡 **入场建议：** {live_cat['entry_suggestion']}")
            if live_cat.get("differentiation"):
                st.info(f"🎯 **差异化方向：** {live_cat['differentiation']}")
            st.divider()

        st.subheader("🤖 AI 选品分析结果")
        st.caption("五维度量化评估：市场容量 · 竞争程度 · 利润潜力 · 新手友好度 · 季节性风险")

        # 速览表（Spec 16 P0）
        with st.expander("📊 分析结果速览表（点击展开）", expanded=True):
            _render_analysis_summary_table(st.session_state.products, st.session_state.results)

        # 批量采购成本（Spec 16 P1）
        with st.expander("💰 批量设置采购成本（可选）", expanded=False):
            col_bulk, col_apply = st.columns([3, 1])
            with col_bulk:
                bulk_cost = st.number_input(
                    "统一采购成本 (¥/件)",
                    min_value=0.0, max_value=1000.0, value=0.0, step=1.0,
                    key="bulk_procurement",
                    help="输入后点击「应用」，将覆盖所有产品的采购成本",
                )
            with col_apply:
                st.write("")
                st.write("")
                if st.button("✅ 应用到全部", width="stretch", disabled=bulk_cost <= 0):
                    for idx in range(len(st.session_state.products)):
                        st.session_state[f"procurement_{idx}"] = bulk_cost
                    st.success(f"✅ 已将 ¥{bulk_cost:.0f}/件 应用到 {len(st.session_state.products)} 个产品")
                    st.rerun()

        for i, r in enumerate(st.session_state.results):
            verdict = r.get("final_verdict", "cautious")
            verdict_label = VERDICT_LABEL_MAP.get(verdict, "⚪ 未知")

            is_raw = r.get("parse_error", False)
            title_text = r.get("title", f"产品 #{i+1}")
            expander_label = (
                f"⚠️ 解析异常 #{i+1} {title_text[:40]}{'…' if len(title_text) > 40 else ''}"
                if is_raw else f"{verdict_label} #{i+1} {title_text[:40]}{'…' if len(title_text) > 40 else ''}"
            )

            with st.expander(expander_label, expanded=(i == 0)):
                st.caption(f"📦 **完整标题：** {title_text}")
                if is_raw:
                    verdict_reason = r.get("verdict_reason", "")
                    st.warning(f"⚠️ AI 返回格式异常 — {verdict_reason}")
                    raw = r.get("raw_text", "")
                    if raw:
                        # 智能截断：过长的原始文本只显示前 2000 字符
                        display_text = raw[:2000] + ("..." if len(raw) > 2000 else "")
                        st.text_area(
                            "原始响应（用于调试）",
                            value=display_text, height=200,
                            disabled=True, key=f"raw_{i}",
                        )
                    else:
                        st.info("💡 原始响应为空，可能是 AI 供应商返回了空内容。请检查 API 配置或稍后重试。")
                    continue

                verdict_reason = r.get("verdict_reason", "")
                if verdict == "recommended":
                    st.success(f"✅ **推荐入手** — {verdict_reason}")
                elif verdict == "cautious":
                    st.warning(f"⚠️ **谨慎评估** — {verdict_reason}")
                else:
                    st.error(f"❌ **不推荐** — {verdict_reason}")

                dims = ANALYSIS_DIMS
                cols = st.columns(5)
                for col, (label, key) in zip(cols, dims):
                    dim_data = r.get(key, {})
                    score_val = dim_data.get("score", 0) if isinstance(dim_data, dict) else 0
                    reason_val = dim_data.get("reason", "") if isinstance(dim_data, dict) else str(dim_data)
                    with col:
                        dc = "inverse" if key in ("competition", "seasonality_risk") else "normal"
                        st.metric(
                            label=label, value=f"{score_val}/10",
                            delta=reason_val,
                            delta_color=dc,
                            help=reason_val,
                        )

                # 雷达图（Spec 16 P3）
                _render_radar_chart(r, title_text[:30])

                # 收藏按钮（Spec 16 P3）
                pf = st.session_state.get("active_platform", "amazon")
                analysis_json = json.dumps(r, ensure_ascii=False)
                _product_price = st.session_state.products[i].get("price", 0) or 0
                _render_favorite_button(
                    title_text, pf,
                    price=str(_product_price), rating=str(st.session_state.products[i].get("rating", "")),
                    analysis_json=analysis_json, key_prefix=f"live_{i}_",
                )

                with st.expander("📝 查看详细分析文本", expanded=False):
                    for label, key in ANALYSIS_DIMS:
                        dim_data = r.get(key, {})
                        score_val = dim_data.get("score", 0) if isinstance(dim_data, dict) else 0
                        reason_val = dim_data.get("reason", "") if isinstance(dim_data, dict) else str(dim_data)
                        st.caption(f"**{label}** ({score_val}/10)")
                        st.text(reason_val)

                # ---- 📈 Google Trends 趋势 ----
                if st.button("📈 查询 Google Trends 趋势", key=f"trend_{i}", width="stretch"):
                    trend_keyword = title_text.split(" - ")[0].split(",")[0][:30].strip()
                    with st.spinner(f"正在查询趋势：{trend_keyword}..."):
                        trend = get_trend_direction(trend_keyword)
                    if trend["available"]:
                        icon = get_trend_icon(trend["direction"])
                        st.success(f"📈 趋势：{icon} | 当前热度 {trend['interest']} | 平均 {trend['avg_interest']}")
                    else:
                        st.warning(f"⚠️ {trend['error']}")

                # ---- 💰 利润试算 ----
                st.divider()
                st.markdown("**💰 利润试算**")

                defaults = st.session_state.get("profit_defaults", get_profit_defaults())
                product_price = st.session_state.products[i].get("price", 0) or 0
                product_title = st.session_state.products[i].get("title", "")
                product_scrape_time = st.session_state.products[i].get("scrape_time", "")

                # 从数据库恢复已保存的采购成本
                saved_cost = 0.0
                if product_title and product_scrape_time:
                    try:
                        saved_cost = get_procurement_cost(product_title, product_scrape_time)
                    except Exception:
                        pass  # 数据库不可用时忽略

                col_input, col_result = st.columns([1, 2])
                with col_input:
                    procurement = st.number_input(
                        "预估采购成本 (¥/件)",
                        min_value=0.0, max_value=1000.0,
                        value=saved_cost, step=1.0,
                        key=f"procurement_{i}",
                        help="从 1688 等平台采购的单件成本，输入后自动保存",
                    )

                # 保存采购成本到数据库（仅非零值）
                if procurement > 0 and product_title and product_scrape_time:
                    try:
                        save_procurement_cost(product_title, product_scrape_time, procurement)
                    except Exception:
                        pass  # 数据库不可用时忽略

                profit_result = calculate_profit(
                    price_usd=product_price,
                    defaults=defaults,
                    procurement_cny=procurement,
                    platform=st.session_state.get("active_platform", "amazon"),
                )

                with col_result:
                    if profit_result["has_procurement"]:
                        margin = profit_result["margin_pct"]
                        if margin >= 30:
                            margin_delta = "normal"
                            margin_status = "🟢 利润可观"
                        elif margin >= 15:
                            margin_delta = "off"
                            margin_status = "🟡 利润一般"
                        else:
                            margin_delta = "inverse"
                            margin_status = "🔴 利润微薄"

                        r1, r2, r3 = st.columns(3)
                        r1.metric(
                            "净利",
                            f"¥{profit_result['net_profit_cny']:.2f}",
                            delta=f"${profit_result['net_profit_usd']:.2f}",
                        )
                        r2.metric(
                            "毛利率",
                            f"{margin}%",
                            delta=margin_status,
                            delta_color=margin_delta,
                        )
                        r3.metric(
                            "总成本",
                            f"¥{profit_result['total_cost_cny']:.2f}",
                        )
                    else:
                        st.caption("👆 请输入采购成本以计算利润")

                # ---- 🔍 1688 比价（混合策略：AI 估算 + 真实抓取） ----
                _1688_cache_key = f"price_1688_{product_title}"
                cached_1688 = st.session_state.get(_1688_cache_key)

                if st.button("🔍 查看1688参考价", key=f"1688_{i}", width="stretch"):
                    search_keyword = product_title[:30]
                    price_usd = float(product_price) if product_price else 0.0
                    with st.spinner(f"正在获取参考价：{search_keyword}..."):
                        result_1688 = search_1688_hybrid(product_title, price_usd)
                    st.session_state[_1688_cache_key] = result_1688
                    cached_1688 = result_1688

                # 显示 1688 结果（新查询或缓存）
                if cached_1688:
                    _render_1688_result(cached_1688)

    # ---- 空闲状态 ----
    elif st.session_state.step == "idle":
        json_exists = os.path.exists(os.path.join(os.path.dirname(__file__), "data", "products.json"))
        st.info(
            "👈 选择上方按钮开始分析：\n\n"
            f"1. 📄 **分析 JSON 数据** {'（可用 ✅）' if json_exists else '（❌ 文件不存在）'}\n"
            "2. 📡 **实时抓取** — 尝试从 Amazon 抓取最新数据\n\n"
            "系统将为你：\n"
            "1. 📄 或 📡 获取产品数据\n"
            "2. 🤖 从市场容量、竞争程度、利润潜力、新手友好度、季节性风险五个维度量化评分\n"
            "3. 📊 给出 🟢推荐 / 🟡谨慎 / 🔴不推荐 的明确 verdict\n"
            "4. 💾 自动保存分析结果到历史数据库，方便后续回顾"
        )

    # ---- 底部提示 ----
    if st.session_state.step == "analyzed":
        st.divider()
        src = st.session_state.source_info or {}
        source_type = src.get("source", "unknown")
        with st.container(border=True):
            if source_type == "json":
                st.markdown("### 📄 当前使用 JSON 文件数据")
                st.markdown("数据来自 `data/products.json`，由每周抓取脚本生成。")
            else:
                platform = st.session_state.get("active_platform", "amazon")
                pf_info = get_platform_info(platform)
                pf_name = f"{pf_info['icon']} {pf_info['name']}"
                st.markdown(f"### 🎉 当前使用 {pf_name} 实时数据")
                st.markdown("分析结果已自动保存，可在「📚 历史记录」页面查看和导出。")

    # ---- 页脚 ----
    st.divider()
    st.caption(
        "⚠️ **免责声明：** 分析结果仅供参考，不构成投资建议。"
        f" | Global Product Scout {APP_VERSION}"
    )


# ============================================================
# ==================== 指定选品页面 ============================
# ============================================================

def _render_targeted_page(api_ok: bool):
    """
    渲染指定选品页面 — 关键词搜索 → AI 分析 → 品类报告。

    流程：
        1. 用户输入关键词 + 可选筛选
        2. 点击「🔍 搜索分析」按钮
        3. 展示品类综合报告
        4. 展示搜索结果列表 + 每个产品的五维度分析
        5. Top 3 产品提供 1688 比价 + 利润试算
    """
    st.title("🎯 指定选品 — 关键词深度分析")
    st.markdown(
        "输入你想调研的产品关键词，AI 将搜索热销平台并生成品类综合报告 + Top 3 推荐。"
    )
    st.divider()

    # ---- 输入区域 ----
    with st.container(border=True):
        col_kw, col_btn = st.columns([3, 1])
        with col_kw:
            keyword = st.text_input(
                "🔍 搜索关键词",
                value=st.session_state.get("targeted_keyword", ""),
                placeholder="例：portable blender, cat toys, yoga mat",
                help="输入英文关键词效果最佳，支持多个单词组合",
            )
        with col_btn:
            st.write("")  # 占位对齐
            st.write("")  # 占位对齐
            search_clicked = st.button(
                "🚀 搜索分析",
                type="primary",
                width="stretch",
                disabled=not keyword.strip(),
            )

        # 可选筛选
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            filter_min_price = st.number_input(
                "💰 最低价格 (USD)", min_value=0.0, value=0.0, step=5.0,
                help="过滤低于此价格的产品（0 = 不限）",
            )
        with col_f2:
            filter_max_price = st.number_input(
                "💰 最高价格 (USD)", min_value=0.0, value=0.0, step=5.0,
                help="过滤高于此价格的产品（0 = 不限）",
            )

        # 搜索前提示
        st.caption("⏱️ 预估耗时：搜索 ~10 秒 + AI 分析 ~30-60 秒（取决于产品数量）")

    # ---- 搜索触发 ----
    if search_clicked and keyword.strip():
        st.session_state.targeted_keyword = keyword.strip()
        st.session_state.targeted_step = "searching"
        st.session_state.targeted_results = None
        st.session_state.targeted_category = None
        st.session_state.targeted_analysis = None
        # 保存价格筛选参数
        st.session_state.targeted_min_price = filter_min_price
        st.session_state.targeted_max_price = filter_max_price
        st.rerun()

    # ---- 搜索执行 ----
    if st.session_state.get("targeted_step") == "searching":
        kw = st.session_state.targeted_keyword

        # 动态加载平台对应的搜索函数
        platform = st.session_state.get("active_platform", "amazon")
        region = st.session_state.get("active_region", "us")
        pf_info = get_platform_info(platform)
        pf_name = f"{pf_info['icon']} {pf_info['name']}"

        with st.status(f"📡 正在搜索 {pf_name}...", expanded=False) as status:
            search_mod = importlib.import_module(pf_info["search_module"])
            search_func = getattr(search_mod, pf_info["search_func"])
            search_result = search_func(kw, region=region, max_results=20)

            if search_result["success"]:
                products = search_result["results"]
                source = search_result["source"]

                # 价格筛选（搜索后过滤）
                min_p = st.session_state.get("targeted_min_price", 0.0)
                max_p = st.session_state.get("targeted_max_price", 0.0)
                if min_p > 0 or max_p > 0:
                    filtered = []
                    for p in products:
                        try:
                            price = float(p.get("price", 0) or 0)
                        except (ValueError, TypeError):
                            price = 0.0
                        if min_p > 0 and price < min_p:
                            continue
                        if max_p > 0 and price > max_p:
                            continue
                        filtered.append(p)
                    if len(filtered) < len(products):
                        st.caption(f"💰 价格筛选：{len(products)} → {len(filtered)} 个产品（${min_p:.0f}-${max_p:.0f}）")
                    products = filtered

                st.session_state.targeted_results = products
                st.session_state.targeted_source = source
                st.session_state.targeted_scrape_time = search_result.get("scrape_time", "")

                status.update(
                    label=f"✅ 搜索完成 — 找到 {len(products)} 个产品",
                    state="complete",
                )
            else:
                st.session_state.targeted_results = []
                st.session_state.targeted_step = "idle"
                status.update(label="❌ 搜索失败", state="error")
                st.error(f"❌ 搜索失败：{search_result.get('error', '未知错误')}")
                st.info(
                    "💡 **建议：**\n"
                    "- 检查网络连接\n"
                    "- 更换关键词重试（英文效果最佳）\n"
                    "- 尝试切换其他平台（如 eBay、Alibaba）\n"
                    "- Cloud 环境 IP 可能被反爬拦截，可使用「📄 分析 JSON 数据」替代"
                )
                return

        # 搜索成功 → 开始 AI 分析
        if st.session_state.targeted_results:
            st.session_state.targeted_step = "analyzing"
            st.rerun()

    # ---- AI 分析执行 ----
    if st.session_state.get("targeted_step") == "analyzing":
        products = st.session_state.targeted_results
        kw = st.session_state.targeted_keyword
        platform = st.session_state.get("active_platform", "amazon")
        region = st.session_state.get("active_region", "us")
        pf_info = get_platform_info(platform)

        # 并行：五维度分析 + 品类报告
        with st.status("🤖 AI 正在深度分析...", expanded=False) as status:
            progress_bar = st.progress(0, text="准备分析...")

            def _on_progress(done, total_count):
                pct = min(done / total_count, 1.0)
                progress_bar.progress(pct, text=f"产品分析进度：{done}/{total_count}")

            # 五维度分析（复用现有批量分析）
            analysis_results = analyze_products(
                products,
                progress_callback=_on_progress,
            )
            st.session_state.targeted_analysis = analysis_results

            progress_bar.empty()

            # 品类综合报告
            status.update(label="📊 正在生成品类报告...", state="running")
            category_report = analyze_category_report(kw, products)
            st.session_state.targeted_category = category_report

            status.update(label="✅ 分析完成！", state="complete")

        # 保存到数据库
        try:
            source_tag = f"{platform}_search"
            save_products(
                products, analysis_results,
                source=source_tag, platform=platform, region=region,
            )
        except Exception:
            pass  # 非阻塞

        # 保存到 session history
        for p, r in zip(products, analysis_results):
            record = dict(p)
            record["analysis"] = r
            record["source"] = source_tag
            record["platform"] = platform
            record["scrape_time"] = st.session_state.get("targeted_scrape_time", "")
            st.session_state.history_data.append(record)

        st.session_state.targeted_step = "done"
        st.rerun()

    # ---- 结果展示 ----
    if st.session_state.get("targeted_step") == "done":
        products = st.session_state.targeted_results
        analysis = st.session_state.targeted_analysis
        category = st.session_state.targeted_category
        kw = st.session_state.targeted_keyword
        source = st.session_state.get("targeted_source", "unknown")

        if not products:
            st.warning("未找到相关产品，请尝试其他关键词。")
            return

        # ---- 数据来源提示 ----
        st.success(f"✅ 搜索「{kw}」找到 {len(products)} 个产品")

        # ---- 品类综合报告 ----
        st.divider()
        st.subheader("📊 品类综合报告")

        if category and not category.get("error"):
            # 市场概况
            st.markdown(f"**📝 市场概况：** {category.get('category_overview', '')}")

            col_r1, col_r2, col_r3 = st.columns(3)
            with col_r1:
                st.metric("📈 市场规模", category.get("market_size", "N/A"))
            with col_r2:
                comp = category.get("competition_level", "unknown")
                comp_label = {"low": "🟢 低竞争", "medium": "🟡 中等竞争", "high": "🔴 高竞争"}.get(comp, "⚪ 未知")
                st.metric("⚔️ 竞争程度", comp_label)
            with col_r3:
                st.metric("💰 价格分布", category.get("price_distribution", "N/A"))

            # 入场建议
            if category.get("entry_suggestion"):
                st.info(f"💡 **入场建议：** {category['entry_suggestion']}")
            if category.get("differentiation"):
                st.info(f"🎯 **差异化方向：** {category['differentiation']}")

            # 风险因素
            risks = category.get("risk_factors", [])
            if risks:
                with st.expander("⚠️ 风险因素", expanded=False):
                    for risk in risks:
                        st.caption(f"• {risk}")
        elif category and category.get("error"):
            st.warning(f"⚠️ 品类报告生成失败：{category['error']}")
        else:
            st.info("💡 配置 AI API Key 后可生成品类综合报告")

        # ---- Top 3 推荐 ----
        st.divider()
        st.subheader("🏆 Top 3 推荐产品")

        top3 = category.get("top3", []) if category and not category.get("error") else []
        if top3:
            cols = st.columns(3)
            for i, rec in enumerate(top3):
                with cols[i]:
                    with st.container(border=True):
                        rank = rec.get("rank", i + 1)
                        score = rec.get("score", 0)
                        title = rec.get("title", f"产品 #{rank}")
                        reason = rec.get("reason", "")

                        st.markdown(f"### 🥇 #{rank}")
                        st.markdown(f"**{title}**")
                        st.metric("综合评分", f"{score}/10")
                        st.caption(reason)

                        # 在产品列表中找到对应产品
                        matched_product = None
                        matched_analysis = None
                        for j, p in enumerate(products):
                            if p["title"] == title:
                                matched_product = p
                                if analysis and j < len(analysis):
                                    matched_analysis = analysis[j]
                                break

                        if matched_product:
                            price = matched_product.get("price", 0)
                            st.caption(f"💰 ${price:.2f} | ⭐ {matched_product.get('rating', 0)} | 💬 {matched_product.get('num_reviews', 0):,}")

                            # 1688 比价按钮
                            if st.button("🔍 1688 比价", key=f"targeted_1688_{i}", width="stretch"):
                                price_usd = float(price) if price else 0.0
                                with st.spinner("正在获取参考价..."):
                                    result_1688 = search_1688_hybrid(title, price_usd)
                                if result_1688["success"]:
                                    pr = result_1688["price_range"]
                                    src_1688 = result_1688.get("source", "unknown")
                                    label_1688 = {
                                        "1688_real": "📦 1688 真实价格",
                                        "ai_estimate": "🤖 AI 估算参考价",
                                        "local_estimate": "📊 本地规则估算",
                                    }.get(src_1688, "📦 参考价")
                                    st.success(f"{label_1688}：¥{pr['min']:.2f} ~ ¥{pr['max']:.2f}")
                                else:
                                    st.warning(result_1688.get("error", "比价失败"))

                            # 利润试算按钮
                            if st.button("💰 利润试算", key=f"targeted_profit_{i}", width="stretch"):
                                st.session_state[f"show_profit_targeted_{i}"] = True

                        # 利润试算展开
                        if st.session_state.get(f"show_profit_targeted_{i}") and matched_product:
                            defaults = st.session_state.get("profit_defaults", get_profit_defaults())
                            procurement = st.number_input(
                                "预估采购成本 (¥/件)",
                                min_value=0.0, max_value=1000.0, value=0.0, step=1.0,
                                key=f"targeted_procurement_{i}",
                            )
                            if procurement > 0:
                                profit_result = calculate_profit(
                                    price_usd=float(matched_product.get("price", 0) or 0),
                                    defaults=defaults,
                                    procurement_cny=procurement,
                                    platform=st.session_state.get("active_platform", "amazon"),
                                )
                                if profit_result["has_procurement"]:
                                    margin = profit_result["margin_pct"]
                                    margin_status = "🟢 利润可观" if margin >= 30 else ("🟡 利润一般" if margin >= 15 else "🔴 利润微薄")
                                    st.metric("净利", f"¥{profit_result['net_profit_cny']:.2f}")
                                    st.metric("毛利率", f"{margin}% — {margin_status}")

        # ---- 搜索结果完整列表 ----
        st.divider()
        st.subheader("📋 搜索结果列表")

        # 排序选项（Spec 16 P1）
        col_sort, _ = st.columns([1, 3])
        with col_sort:
            sort_option = st.selectbox(
                "排序方式",
                options=["默认（搜索排名）", "价格从低到高", "价格从高到低", "评分从高到低", "评论数从多到少"],
                key="targeted_sort",
            )

        # 排序逻辑
        sorted_products = list(products)
        if sort_option == "价格从低到高":
            sorted_products.sort(key=lambda p: float(p.get("price", 0) or 0))
        elif sort_option == "价格从高到低":
            sorted_products.sort(key=lambda p: float(p.get("price", 0) or 0), reverse=True)
        elif sort_option == "评分从高到低":
            sorted_products.sort(key=lambda p: float(p.get("rating", 0) or 0), reverse=True)
        elif sort_option == "评论数从多到少":
            sorted_products.sort(key=lambda p: int(p.get("num_reviews", 0) or 0), reverse=True)

        df = pd.DataFrame(sorted_products)
        df_display = df.rename(columns={
            "rank": "排名", "title": "产品名称", "price": "价格 (USD)",
            "rating": "评分 ⭐", "num_reviews": "评论数", "category": "类目",
        })
        display_columns = ["排名", "产品名称", "价格 (USD)", "评分 ⭐", "评论数"]
        available_cols = [c for c in display_columns if c in df_display.columns]
        st.dataframe(
            df_display[available_cols], width="stretch", hide_index=True,
            column_config={
                "排名": st.column_config.NumberColumn(format="%d"),
                "价格 (USD)": st.column_config.NumberColumn(format="$%.2f"),
                "评分 ⭐": st.column_config.NumberColumn(format="%.1f"),
            },
        )

        # ---- 每个产品的五维度分析 ----
        if analysis:
            st.divider()
            st.subheader("🤖 AI 五维度详细分析")

            # 速览表（Spec 16 P0）
            with st.expander("📊 分析结果速览表（点击展开）", expanded=True):
                _render_analysis_summary_table(products, analysis)

            for i, r in enumerate(analysis):
                verdict = r.get("final_verdict", "cautious")
                verdict_label = VERDICT_LABEL_MAP.get(verdict, "⚪ 未知")
                title_text = r.get("title", f"产品 #{i+1}")

                with st.expander(f"{verdict_label} #{i+1} {title_text[:40]}{'…' if len(title_text) > 40 else ''}", expanded=False):
                    st.caption(f"📦 **完整标题：** {title_text}")
                    verdict_reason = r.get("verdict_reason", "")
                    if verdict == "recommended":
                        st.success(f"✅ **推荐入手** — {verdict_reason}")
                    elif verdict == "cautious":
                        st.warning(f"⚠️ **谨慎评估** — {verdict_reason}")
                    else:
                        st.error(f"❌ **不推荐** — {verdict_reason}")

                    dims = ANALYSIS_DIMS
                    cols = st.columns(5)
                    for col, (label, key) in zip(cols, dims):
                        dim_data = r.get(key, {})
                        score_val = dim_data.get("score", 0) if isinstance(dim_data, dict) else 0
                        reason_val = dim_data.get("reason", "") if isinstance(dim_data, dict) else str(dim_data)
                        with col:
                            dc = "inverse" if key in ("competition", "seasonality_risk") else "normal"
                            st.metric(
                                label=label, value=f"{score_val}/10",
                                delta=reason_val,
                                delta_color=dc,
                                help=reason_val,
                            )

        # ---- 重新搜索按钮 ----
        st.divider()
        if st.button("🔄 重新搜索", width="stretch"):
            st.session_state.targeted_step = "idle"
            st.session_state.targeted_results = None
            st.session_state.targeted_category = None
            st.session_state.targeted_analysis = None
            st.rerun()

    # ---- 空闲状态 ----
    elif st.session_state.get("targeted_step", "idle") == "idle":
        st.info(
            "👈 输入关键词开始搜索分析：\n\n"
            "1. 🔍 输入英文产品关键词（如 `portable blender`）\n"
            "2. 🚀 点击「搜索分析」按钮\n"
            "3. 📊 查看品类综合报告 + Top 3 推荐\n"
            "4. 💰 对推荐产品查看 1688 比价和利润试算\n\n"
            "**热门品类参考：** bluetooth speaker, yoga mat, cat toys, "
            "kitchen organizer, phone case, LED strip lights"
        )


# ============================================================
# ==================== 历史记录页面 ============================
# ============================================================

def _render_history_page():
    """渲染历史记录页面 — 多平台增强版（筛选、统计、跨平台对比、导出）。"""

    st.title("📚 历史分析记录")

    total_count = get_product_count()
    session_count = len(st.session_state.history_data)

    # 如果 DB 和 session 都为空 → 提示
    if total_count == 0 and session_count == 0:
        st.info(
            "📭 **暂无历史记录**\n\n"
            "请先切换到「🔍 实时选品」页面，点击「开始分析」按钮运行一次分析。\n"
            "分析结果会在当前会话中保存，方便随时回顾。"
        )
        return

    # Cloud 端提示：SQLite 不持久化
    if total_count == 0 and session_count > 0:
        st.info(
            "💡 **当前为会话内历史记录** — Streamlit Cloud 上数据不会长期保持。\n\n"
            "如需永久保存，请在本地运行 `python daily_scrape.py` "
            "并将 `data/products.json` 提交到 GitHub。"
        )

    # ---- Tabs ----
    tab_list, tab_trend, tab_compare, tab_fav = st.tabs([
        "📚 历史记录", "📈 产品趋势", "⚖️ 跨平台对比", "⭐ 已收藏"
    ])

    with tab_list:
        _render_history_list(total_count)

    with tab_trend:
        _render_trend_page()

    with tab_compare:
        _render_cross_platform_tab()

    with tab_fav:
        _render_favorites_tab()


def _render_trend_page():
    """渲染产品趋势页面。"""
    st.markdown("### 📈 产品趋势分析")
    st.caption("对比同一产品在不同抓取时间的排名、价格、评论数变化")

    total_count = get_product_count()
    if total_count == 0:
        st.info("暂无数据，请先运行分析。")
        return

    # 获取唯一产品列表
    products = get_all_products()
    unique_titles = sorted({p.get("title", "") for p in products if p.get("title")})

    if not unique_titles:
        st.info("暂无可追踪的产品。")
        return

    selected_title = st.selectbox(
        "选择产品",
        options=unique_titles,
        format_func=lambda t: t[:50] + "…" if len(t) > 50 else t,
        help="选择一个产品查看其历史趋势变化",
    )

    if not selected_title:
        return

    # 获取趋势数据
    trend_data = get_trend_data(title=selected_title)

    if len(trend_data) < 2:
        st.warning("该产品仅有一次抓取记录，至少需要两次抓取才能显示趋势。")
        if trend_data:
            st.json(dict(trend_data[0]))
        return

    # 转为 DataFrame
    df = pd.DataFrame(trend_data)
    df["scrape_time"] = pd.to_datetime(df["scrape_time"])
    df["rank"] = pd.to_numeric(df["rank"], errors="coerce")
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["num_reviews"] = pd.to_numeric(df["num_reviews"], errors="coerce")

    # 排名变化曲线
    st.markdown("#### 📊 排名变化")
    st.line_chart(df.set_index("scrape_time")["rank"])

    # 价格变化曲线
    st.markdown("#### 💰 价格变化")
    st.line_chart(df.set_index("scrape_time")["price"])

    # 评论数变化曲线
    st.markdown("#### 💬 评论数变化")
    st.line_chart(df.set_index("scrape_time")["num_reviews"])

    # 趋势总结（数值从 SQLite 返回为字符串，需转换为数字）
    first = trend_data[0]
    last = trend_data[-1]
    first_rank = float(first.get("rank") or 0)
    last_rank = float(last.get("rank") or 0)
    first_price = float(first.get("price") or 0)
    last_price = float(last.get("price") or 0)
    first_reviews = float(first.get("num_reviews") or 0)
    last_reviews = float(last.get("num_reviews") or 0)

    rank_change = first_rank - last_rank
    price_change = last_price - first_price
    review_change = last_reviews - first_reviews

    st.markdown("#### 📋 趋势总结")
    c1, c2, c3 = st.columns(3)
    c1.metric(
        "排名变化", f"#{int(last_rank)}",
        delta=f"{'↑' if rank_change > 0 else '↓'} {abs(int(rank_change))} 位" if rank_change != 0 else "无变化",
        delta_color="normal" if rank_change > 0 else "inverse",
    )
    c2.metric(
        "价格变化", f"${last_price:.2f}",
        delta=f"{'↑' if price_change > 0 else '↓'} ${abs(price_change):.2f}",
    )
    c3.metric(
        "评论数变化", f"{int(last_reviews):,}",
        delta=f"{'↑' if review_change > 0 else '↓'} {abs(int(review_change)):,}",
    )


def _render_history_list(total_count: int):
    """渲染历史记录列表（多平台增强版 — 平台/地区筛选 + 统计仪表盘）。"""

    # ---- 多平台筛选器 ----
    with st.container(border=True):
        st.markdown("### 🔍 筛选条件")

        # 第一行：平台 + 地区
        col_plat, col_region = st.columns(2)
        with col_plat:
            platform_keys = get_platform_choices()
            platform_options = list(platform_keys)
            selected_platforms = st.multiselect(
                "🛒 平台",
                options=platform_options,
                default=platform_options,
                format_func=lambda k: f"{PLATFORMS[k]['icon']} {PLATFORMS[k]['name']}",
            )
        with col_region:
            # 根据选中平台动态更新地区列表
            available_regions = []
            for pf in selected_platforms:
                for rk, rv in PLATFORMS[pf]["regions"].items():
                    label = f"{PLATFORMS[pf]['icon']} {rv['name']}"
                    if label not in available_regions:
                        available_regions.append(label)
            selected_regions = st.multiselect(
                "🌍 地区",
                options=available_regions,
                default=available_regions,
            )

        # 第二行：判定 + 容量 + 排序
        col1, col2, col3 = st.columns(3)
        with col1:
            verdict_options = st.multiselect(
                "综合判定",
                options=["recommended", "cautious", "not_recommended"],
                default=["recommended", "cautious"],
                format_func=lambda v: {
                    "recommended": "🟢 推荐", "cautious": "🟡 谨慎",
                    "not_recommended": "🔴 不推荐",
                }.get(v, v),
            )

        with col2:
            min_capacity = st.slider(
                "市场容量最低评分", min_value=1, max_value=10, value=1, step=1,
            )

        with col3:
            sort_option = st.selectbox(
                "排序方式",
                options=["最新优先", "价格从高到低", "价格从低到高", "排名靠前"],
            )

        col_p1, col_p2 = st.columns(2)
        with col_p1:
            min_price = st.number_input("最低价格 (USD)", min_value=0.0, value=0.0, step=5.0)
        with col_p2:
            max_price = st.number_input("最高价格 (USD)", min_value=0.0, value=1000.0, step=5.0)

        st.caption(f"📦 数据库共 {total_count} 条记录")

    # ---- 构建筛选条件并查询 ----
    sort_map = {
        "最新优先": ("scrape_time", "DESC"),
        "价格从高到低": ("price", "DESC"),
        "价格从低到高": ("price", "ASC"),
        "排名靠前": ("rank", "ASC"),
    }
    sort_by, sort_order = sort_map.get(sort_option, ("scrape_time", "DESC"))

    # 使用新的多条件查询
    if total_count > 0:
        products = query_products(
            platforms=selected_platforms if len(selected_platforms) < len(platform_options) else None,
            regions=None,
            min_margin=None,
            keyword=None,
        )
        # 应用旧版筛选
        filters = {}
        if verdict_options:
            filters["verdicts"] = verdict_options
        if min_capacity > 1:
            filters["min_capacity_score"] = min_capacity
        if min_price > 0:
            filters["min_price"] = min_price
        if max_price < 1000:
            filters["max_price"] = max_price
        filters["sort_by"] = sort_by
        filters["sort_order"] = sort_order

        products = [p for p in products if _match_filters_simple(p, filters)]

        # 地区筛选（Python 层）
        if selected_regions and len(selected_regions) < len(available_regions):
            # 构建 (platform, region_display) 匹配集合
            region_set = set(selected_regions)
            products = [
                p for p in products
                if f"{PLATFORMS.get(p.get('platform', 'amazon'), {}).get('icon', '❓')} "
                   f"{PLATFORMS.get(p.get('platform', 'amazon'), {}).get('regions', {}).get(p.get('region', 'us'), {}).get('name', '')}"
                   in region_set
            ]
    else:
        products = st.session_state.history_data
        if verdict_options:
            products = [p for p in products
                        if p.get("analysis", {}).get("final_verdict") in verdict_options]
        if min_price > 0:
            products = [p for p in products if (p.get("price") or 0) >= min_price]
        if max_price < 1000:
            products = [p for p in products if (p.get("price") or 0) <= max_price]

    st.divider()

    if not products:
        st.warning("没有符合当前筛选条件的历史记录。请调整筛选条件后重试。")
        return

    # ---- 统计仪表盘 ----
    _render_stats_dashboard(products, selected_platforms)

    st.divider()

    # ---- 统计摘要 ----
    st.caption(f"筛选结果：{len(products)} 条记录")
    rec = sum(1 for p in products if p.get("analysis", {}).get("final_verdict") == "recommended")
    cau = sum(1 for p in products if p.get("analysis", {}).get("final_verdict") == "cautious")
    nrc = sum(1 for p in products if p.get("analysis", {}).get("final_verdict") == "not_recommended")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🟢 推荐", rec)
    c2.metric("🟡 谨慎", cau)
    c3.metric("🔴 不推荐", nrc)
    c4.metric("📦 总计", len(products))

    # ---- 数据表格（含分页和对比） ----
    st.subheader("📋 历史产品列表")

    # 分页（Spec 16 P3）
    PAGE_SIZE = 50
    total_items = len(products)
    if total_items > PAGE_SIZE:
        total_pages = (total_items + PAGE_SIZE - 1) // PAGE_SIZE
        col_page, col_info = st.columns([1, 3])
        with col_page:
            page_num = st.number_input(
                "页码", min_value=1, max_value=total_pages, value=1, step=1,
                key="history_page",
            )
        with col_info:
            st.caption(f"共 {total_items} 条记录，{total_pages} 页（每页 {PAGE_SIZE} 条）")
        start = (page_num - 1) * PAGE_SIZE
        end = start + PAGE_SIZE
        page_products = products[start:end]
    else:
        page_products = products

    table_data = []
    for p in page_products:
        analysis = p.get("analysis", {})
        table_data.append({
            "标题": p.get("title", "") or "",
            "价格(USD)": p.get("price", ""),
            "评分": p.get("rating", ""),
            "排名": p.get("rank", ""),
            "类目": p.get("category", ""),
            "市场容量": _dim_score(analysis, "market_capacity"),
            "竞争程度": _dim_score(analysis, "competition"),
            "利润潜力": _dim_score(analysis, "profit_potential"),
            "新手友好": _dim_score(analysis, "beginner_friendly"),
            "季节风险": _dim_score(analysis, "seasonality_risk"),
            "判定": _verdict_emoji(analysis.get("final_verdict", "")),
            "分析时间": p.get("scrape_time", ""),
        })

    df_display = pd.DataFrame(table_data)
    selection = st.dataframe(
        df_display, width="stretch", hide_index=True,
        column_config={
            "判定": st.column_config.TextColumn(width="small"),
            "分析时间": st.column_config.TextColumn(width="medium"),
        },
        selection_mode="multi-row",
        on_select="rerun",
    )

    # 产品对比按钮（Spec 16 P3）
    if selection and hasattr(selection, 'selection') and selection.selection.rows:
        selected_rows = selection.selection.rows
        if len(selected_rows) >= 2:
            # 映射回全局索引
            if total_items > PAGE_SIZE:
                global_indices = [start + idx for idx in selected_rows if start + idx < total_items]
            else:
                global_indices = selected_rows
            if st.button(f"⚖️ 对比选中的 {len(global_indices)} 个产品", width="stretch"):
                _render_comparison_view(products, global_indices)

    # ---- 查看单条详情 ----
    with st.expander("🔍 点击展开查看某条记录的完整分析 JSON", expanded=False):
        selected_idx = st.selectbox(
            "选择产品",
            options=range(len(products)),
            format_func=lambda i: f"#{i+1} {(products[i].get('title', '') or '')[:50]}{'…' if len((products[i].get('title', '') or '')) > 50 else ''}",
            help="选择产品查看详情分析",
        )
        if selected_idx is not None:
            st.json(products[selected_idx].get("analysis", {}))

    # ---- 导出 CSV ----
    st.divider()
    if st.button("📥 导出当前筛选结果为 CSV", type="secondary"):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8-sig"
        ) as tmp:
            exported = export_csv(tmp.name, filters=filters)
            tmp_path = tmp.name
        if exported > 0:
            with open(tmp_path, "rb") as f:
                st.download_button(
                    label="📥 点击下载 CSV 文件",
                    data=f.read(),
                    file_name="global_product_scout_export.csv",
                    mime="text/csv",
                )
            os.unlink(tmp_path)
            st.success(f"✅ 已导出 {exported} 条记录")
        else:
            st.warning("没有数据可导出")

    # 页脚
    st.divider()
    st.caption(f" | Global Product Scout {APP_VERSION} | 数据来源：多平台历史分析记录 |")


# ============================================================
# 多平台增强辅助函数（Spec 12）
# ============================================================

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


def _render_stats_dashboard(products: list[dict], selected_platforms: list[str]):
    """渲染数据统计仪表盘。"""
    st.subheader("📈 数据统计")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("总产品数", len(products))

    with col2:
        platform_counts = {}
        for p in products:
            pf = p.get("platform", "amazon")
            platform_counts[pf] = platform_counts.get(pf, 0) + 1
        st.metric("平台覆盖", f"{len(platform_counts)} 个平台")

    with col3:
        margins = []
        for p in products:
            analysis = p.get("analysis", {})
            m = analysis.get("margin_pct")
            if m is not None:
                margins.append(m)
        if margins:
            avg_margin = sum(margins) / len(margins)
            st.metric("平均毛利率", f"{avg_margin:.1f}%")
        else:
            st.metric("平均毛利率", "N/A", help="输入采购成本后才能计算毛利率")

    with col4:
        profitable = sum(
            1 for p in products
            if p.get("analysis", {}).get("is_profitable", False)
        )
        if profitable > 0:
            pct = (profitable / len(products) * 100) if products else 0
            st.metric("盈利产品占比", f"{pct:.0f}%")
        else:
            st.metric("盈利产品占比", "N/A", help="输入采购成本后才能计算盈利情况")
        st.metric("盈利产品占比", f"{pct:.0f}%")

    # 各平台产品数量柱状图
    if platform_counts:
        chart_data = pd.DataFrame(
            list(platform_counts.items()),
            columns=["平台", "产品数"],
        )
        # 添加平台名称
        chart_data["平台名"] = chart_data["平台"].apply(
            lambda k: f"{PLATFORMS.get(k, {}).get('icon', '❓')} {PLATFORMS.get(k, {}).get('name', k)}"
        )
        st.bar_chart(chart_data.set_index("平台名")["产品数"])


def _render_cross_platform_tab():
    """渲染跨平台对比 Tab。"""
    st.subheader("⚖️ 跨平台对比")
    st.caption("对比各平台的平均售价、利润率、费用结构等指标")

    # 获取所有产品数据
    all_products = query_products()
    if not all_products:
        st.info("📭 暂无数据，请先运行分析。")
        return

    # 检测是否只有一个平台数据（Spec 16 P2）
    platform_set = {p.get("platform", "amazon") for p in all_products}
    if len(platform_set) < 2:
        st.warning(
            f"💡 当前仅有 **{len(platform_set)} 个平台** 的数据，跨平台对比效果有限。\n\n"
            "请先在「🔍 实时选品」页面抓取其他平台的数据，"
            "或运行 `python daily_scrape.py` 一次性抓取所有平台。"
        )

    # 按平台分组统计
    platform_stats = {}
    for p in all_products:
        pf = p.get("platform", "amazon")
        analysis = p.get("analysis", {})
        if pf not in platform_stats:
            platform_stats[pf] = {
                "prices": [], "margins": [], "commissions": [],
                "shippings": [], "count": 0,
            }
        try:
            price = float(p.get("price", 0) or 0)
        except (ValueError, TypeError):
            price = 0.0
        platform_stats[pf]["prices"].append(price)
        margin = analysis.get("margin_pct")
        if margin is not None:
            platform_stats[pf]["margins"].append(margin)
        platform_stats[pf]["count"] += 1

    # 构建对比表格
    comparison_data = []
    for pf, stats in platform_stats.items():
        pf_info = PLATFORMS.get(pf, {})
        avg_price = sum(stats["prices"]) / len(stats["prices"]) if stats["prices"] else 0
        avg_margin = sum(stats["margins"]) / len(stats["margins"]) if stats["margins"] else 0
        comparison_data.append({
            "平台": f"{pf_info.get('icon', '❓')} {pf_info.get('name', pf)}",
            "产品数": stats["count"],
            "平均售价(USD)": round(avg_price, 2),
            "平均毛利率%": round(avg_margin, 1),
        })

    if comparison_data:
        df = pd.DataFrame(comparison_data)
        st.dataframe(
            df, width="stretch", hide_index=True,
            column_config={
                "平均售价(USD)": st.column_config.NumberColumn(format="$%.2f"),
                "平均毛利率%": st.column_config.NumberColumn(format="%.1f%%"),
            },
        )

        # 毛利率对比柱状图
        if len(comparison_data) >= 2:
            st.subheader("📊 毛利率对比")
            chart_df = pd.DataFrame(comparison_data)
            st.bar_chart(chart_df.set_index("平台")["平均毛利率%"])

    # 产品详情表格
    st.subheader("📋 全平台产品列表")
    table_data = []
    for p in all_products:
        pf = p.get("platform", "amazon")
        pf_info = PLATFORMS.get(pf, {})
        analysis = p.get("analysis", {})
        table_data.append({
            "平台": f"{pf_info.get('icon', '')} {pf_info.get('name', pf)}",
            "标题": (p.get("title", "") or "")[:60],
            "价格": p.get("price", ""),
            "判定": _verdict_emoji(analysis.get("final_verdict", "")),
            "分析时间": p.get("scrape_time", ""),
        })

    if table_data:
        st.dataframe(
            pd.DataFrame(table_data), width="stretch", hide_index=True,
        )


# ============================================================
# 已收藏 Tab（Spec 16 P3）
# ============================================================

def _render_favorites_tab():
    """渲染已收藏产品 Tab。"""
    st.subheader("⭐ 已收藏产品")

    favorites = get_favorites()
    if not favorites:
        st.info("📭 暂无收藏产品。\n\n在「🔍 实时选品」或「🎯 指定选品」页面分析产品后，点击 ☆ 收藏按钮即可标记感兴趣的产品。")
        return

    st.caption(f"共 {len(favorites)} 个收藏产品")

    for i, fav in enumerate(favorites):
        title = fav.get("title", "")
        platform = fav.get("platform", "amazon")
        pf_info = PLATFORMS.get(platform, {})
        pf_icon = pf_info.get("icon", "❓")
        pf_name = pf_info.get("name", platform)
        price = fav.get("price", "")
        rating = fav.get("rating", "")
        analysis = fav.get("analysis", {})
        verdict = analysis.get("final_verdict", "")
        verdict_label = VERDICT_LABEL_MAP.get(verdict, "⚪")

        with st.container(border=True):
            col_info, col_action = st.columns([5, 1])
            with col_info:
                st.markdown(f"{pf_icon} **{verdict_label}** {title}")
                st.caption(f"💰 ${price} | ⭐ {rating} | 平台：{pf_name}")
            with col_action:
                if st.button("🗑️ 取消收藏", key=f"del_fav_{i}", width="stretch"):
                    remove_favorite(title, platform)
                    # 清除缓存
                    cache_key = f"_fav_{title}_{platform}"
                    if cache_key in st.session_state:
                        del st.session_state[cache_key]
                    st.rerun()

            # 展开查看分析详情
            if analysis and not analysis.get("parse_error"):
                with st.expander(f"📊 查看分析详情 — {title[:40]}", expanded=False):
                    verdict_reason = analysis.get("verdict_reason", "")
                    if verdict_reason:
                        st.caption(f"💡 {verdict_reason}")

                    cols = st.columns(5)
                    for col, (label, key) in zip(cols, ANALYSIS_DIMS):
                        dim = analysis.get(key, {})
                        score = dim.get("score", "-") if isinstance(dim, dict) else "-"
                        with col:
                            st.metric(label, f"{score}/10")


# ============================================================
# 原有辅助函数
# ============================================================

def _dim_score(analysis: dict, key: str) -> str:
    """从分析结果提取维度评分字符串，如 '7/10'。"""
    dim = analysis.get(key, {})
    if isinstance(dim, dict):
        return f"{dim.get('score', '')}/10"
    return ""


def _verdict_emoji(verdict: str) -> str:
    """将 verdict 转为带 emoji 的展示字符串。"""
    return {
        "recommended": "🟢 推荐", "cautious": "🟡 谨慎",
        "not_recommended": "🔴 不推荐",
    }.get(verdict, verdict)


def _load_products():
    """
    两级数据策略：
    1. 优先读取 data/products.json（适用于 Streamlit Cloud 离线部署）
    2. 失败则实时抓取 Amazon，仅接受 source='live' 的结果
    3. 实时抓取返回 cache/unavailable 时丢弃数据并抛出异常

    Returns:
        (products, source_info) 元组

    Raises:
        RuntimeError: JSON 和实时抓取均不可用时
    """
    json_path = os.path.join(os.path.dirname(__file__), "data", "products.json")

    # ---- 第一级：JSON 文件 ----
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                products = json.load(f)
            if products and len(products) > 0:
                scrape_time = products[0].get("scrape_time", "")
                return products, {"source": "json", "timestamp": scrape_time}
        except Exception:
            pass  # 读取失败，降级到实时抓取

    # ---- 第二级：实时抓取（仅接受 live） ----
    products, source_info = fetch_amazon_best_sellers()
    if source_info.get("source") == "live":
        return products, source_info

    # 实时抓取也失败 → 丢弃 cache/unavailable，提示用户
    raise RuntimeError(
        "实时抓取失败，请先运行 daily_scrape.py 并推送 products.json"
    )


# ============================================================
# 模块入口 — Session State 初始化 + 页面路由
# ============================================================

if "products" not in st.session_state:
    st.session_state.products = []
if "results" not in st.session_state:
    st.session_state.results = []
if "source_info" not in st.session_state:
    st.session_state.source_info = None
if "step" not in st.session_state:
    st.session_state.step = "idle"  # idle → loaded → analyzed
if "analyzing" not in st.session_state:
    st.session_state.analyzing = False  # 分析中锁定按钮
if "history_data" not in st.session_state:
    st.session_state.history_data = []  # 当前会话的历史记录（Cloud 端替代 SQLite）

# 初始化数据库（幂等）
init_db()

# 渲染侧边栏并获取页面选择
api_ok, page = render_sidebar(st.session_state.source_info)

# 页面路由
if "Dashboard" in page:
    _render_dashboard_page()
elif "实时选品" in page:
    _render_live_page(api_ok)
elif "指定选品" in page:
    _render_targeted_page(api_ok)
elif "历史记录" in page:
    _render_history_page()
