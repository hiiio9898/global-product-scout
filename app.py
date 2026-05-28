"""
Streamlit 主程序入口 — 外贸 AI 选品助手（Global Product Scout）。

提供"数据获取 → AI 分析 → 结果展示"一站式选品体验。
数据源采用两级策略：优先读取 data/products.json → 降级到实时抓取（仅接受 live 数据）。
内置 SQLite 历史记录：每次分析自动保存，支持多条件筛选和 CSV 导出。

用法：
    streamlit run app.py
"""

import sys
import os
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import pandas as pd
import json

from src.config import get_config, get_llm_config, LLM_PROVIDERS
from src.scraper import fetch_amazon_best_sellers
from src.analyzer import analyze_products
from src.database import (
    init_db,
    save_products,
    get_all_products,
    get_product_count,
    export_csv,
)

# ============================================================
# 页面配置
# ============================================================

st.set_page_config(
    page_title="外贸 AI 选品助手",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# 侧边栏 — 配置区
# ============================================================

def render_sidebar(source_info: dict | None = None):
    """渲染侧边栏 — 页面导航、数据源状态和 API 配置。"""
    st.sidebar.title("⚙️ 设置")

    # ---- 页面导航 ----
    page = st.sidebar.radio(
        "📌 页面导航",
        options=["🔍 实时选品", "📚 历史记录"],
        help="实时选品：抓取并分析当前 Amazon 热销产品\n历史记录：查看过去保存的分析结果",
    )

    st.sidebar.divider()

    # 数据源选择器（仅实时选品页显示）
    if "实时选品" in page:
        st.sidebar.selectbox(
            "选择数据源",
            options=["Amazon Best Sellers"],
            disabled=False,
            help="当前支持 Amazon US 站 Best Sellers 首页实时抓取。",
        )

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
    current_provider_idx = provider_keys.index(llm_cfg["provider"]) if llm_cfg["provider"] in provider_keys else 0

    selected_provider = st.sidebar.selectbox(
        "AI 供应商",
        options=provider_keys,
        format_func=lambda k: provider_names[k],
        index=current_provider_idx,
        key="llm_provider_select",
    )

    # 模型选择（根据供应商动态更新）
    available_models = LLM_PROVIDERS[selected_provider]["models"]
    current_model = llm_cfg["model"] if llm_cfg["model"] in available_models else available_models[0]
    selected_model = st.sidebar.selectbox(
        "模型",
        options=available_models,
        index=available_models.index(current_model),
        key="llm_model_select",
    )

    # 供应商切换后更新 session_state 并 rerun
    if selected_provider != llm_cfg["provider"] or selected_model != llm_cfg["model"]:
        st.session_state["llm_provider"] = selected_provider
        st.session_state["llm_model"] = selected_model
        st.rerun()

    # API 配置状态显示
    provider_name = LLM_PROVIDERS[llm_cfg["provider"]]["name"]
    model_name = llm_cfg["model"]
    if llm_cfg["configured"]:
        st.sidebar.caption(f"✅ {provider_name} {model_name}")
    else:
        st.sidebar.caption(f"⚠️ {provider_name} 未配置（使用模拟分析）")
        api_key_env = LLM_PROVIDERS[llm_cfg["provider"]]["api_key_key"]
        st.sidebar.info(
            f"💡 在 `.env` 文件中配置 `{api_key_env}`\n"
            f"即可启用 {provider_name} AI 分析。"
        )

    # ---- 数据库状态 ----
    count = get_product_count()
    st.sidebar.caption(f"📦 历史记录：{count} 条产品数据")

    return llm_cfg["configured"], page


# ============================================================
# ==================== 实时选品页面 ============================
# ============================================================

def _render_live_page(api_ok: bool):
    """渲染实时选品页面（原有功能 + 分析后自动保存到数据库）。"""

    st.title("🔍 外贸 AI 选品助手")
    st.markdown(
        "🚀 智能抓取 Amazon 热销产品数据，AI 深度分析竞争力与利润潜力，"
        "帮你找到下一个爆款！"
    )
    st.divider()

    # ---- 开始分析按钮 ----
    btn_disabled = st.session_state.get("analyzing", False)
    if st.button("🚀 开始分析", type="primary", use_container_width=True, disabled=btn_disabled):
        st.session_state.analyzing = True
        try:
            # 第一步：获取数据（优先 JSON，降级到实时）
            with st.spinner("📡 正在获取 Amazon Best Sellers 热销数据..."):
                products, source_info = _load_products()
                st.session_state.products = products
                st.session_state.source_info = source_info
                st.session_state.step = "loaded"

            # 加载数据后立即 rerun，让侧边栏及时显示数据源状态
            st.rerun()

        except RuntimeError as e:
            st.session_state.analyzing = False
            st.error(f"❌ {str(e)}")
            st.info(
                "💡 请在本机执行 `python daily_scrape.py`，"
                "然后将 `data/products.json` 提交并推送到 GitHub，"
                "Streamlit Cloud 便会展示真实数据。"
            )
        except Exception as e:
            st.error(f"❌ 出错了：{str(e)}")
            st.info("🔧 请检查网络连接和 `.env` 配置文件后重试。")

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
                saved_count = save_products(st.session_state.products, results)
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
        elif source_type == "live":
            caption = f"数据来源：Amazon Best Sellers（实时抓取）| 更新时间：{ts}"
        st.caption(caption)

        df = pd.DataFrame(st.session_state.products)
        df_display = df.rename(columns={
            "rank": "排名", "title": "产品名称", "price": "价格 (USD)",
            "rating": "评分 ⭐", "num_reviews": "评论数", "category": "类目",
        })
        display_columns = ["排名", "产品名称", "价格 (USD)", "评分 ⭐", "评论数", "类目"]
        available_cols = [c for c in display_columns if c in df_display.columns]
        st.dataframe(
            df_display[available_cols], use_container_width=True, hide_index=True,
            column_config={
                "排名": st.column_config.NumberColumn(format="%d"),
                "价格 (USD)": st.column_config.NumberColumn(format="$%.2f"),
                "评分 ⭐": st.column_config.NumberColumn(format="%.1f"),
            },
        )

    # ---- AI 分析卡片 ----
    if st.session_state.step == "analyzed" and st.session_state.results:
        st.subheader("🤖 AI 选品分析结果")
        st.caption("五维度量化评估：市场容量 · 竞争程度 · 利润潜力 · 新手友好度 · 季节性风险")

        for i, r in enumerate(st.session_state.results):
            verdict = r.get("final_verdict", "cautious")
            verdict_label_map = {
                "recommended": "🟢 推荐入手", "cautious": "🟡 谨慎评估",
                "not_recommended": "🔴 不推荐",
            }
            verdict_label = verdict_label_map.get(verdict, "⚪ 未知")

            is_raw = r.get("parse_error", False)
            title_text = r.get("title", f"产品 #{i+1}")
            expander_label = (
                f"⚠️ 解析异常 #{i+1} {title_text[:50]}…"
                if is_raw else f"{verdict_label} #{i+1} {title_text[:55]}…"
            )

            with st.expander(expander_label, expanded=(i == 0)):
                if is_raw:
                    st.warning("⚠️ AI 返回格式异常，以下为原始文本：")
                    st.text_area("原始响应", value=r.get("raw_text", ""), height=200,
                                 disabled=True, key=f"raw_{i}")
                    continue

                verdict_reason = r.get("verdict_reason", "")
                if verdict == "recommended":
                    st.success(f"✅ **推荐入手** — {verdict_reason}")
                elif verdict == "cautious":
                    st.warning(f"⚠️ **谨慎评估** — {verdict_reason}")
                else:
                    st.error(f"❌ **不推荐** — {verdict_reason}")

                dims = [
                    ("📊 市场容量", "market_capacity"),
                    ("⚔️ 竞争程度", "competition"),
                    ("💰 利润潜力", "profit_potential"),
                    ("🎓 新手友好", "beginner_friendly"),
                    ("🌡️ 季节风险", "seasonality_risk"),
                ]
                cols = st.columns(5)
                for col, (label, key) in zip(cols, dims):
                    dim_data = r.get(key, {})
                    score_val = dim_data.get("score", 0) if isinstance(dim_data, dict) else 0
                    reason_val = dim_data.get("reason", "") if isinstance(dim_data, dict) else str(dim_data)
                    with col:
                        dc = "inverse" if key in ("competition", "seasonality_risk") else "normal"
                        st.metric(
                            label=label, value=f"{score_val}/10",
                            delta=reason_val[:40] + ("…" if len(reason_val) > 40 else ""),
                            delta_color=dc,
                        )

                with st.expander("📝 查看详细分析文本", expanded=False):
                    for label, key in dims:
                        dim_data = r.get(key, {})
                        score_val = dim_data.get("score", 0) if isinstance(dim_data, dict) else 0
                        reason_val = dim_data.get("reason", "") if isinstance(dim_data, dict) else str(dim_data)
                        st.caption(f"**{label}** ({score_val}/10)")
                        st.text(reason_val)

    # ---- 空闲状态 ----
    elif st.session_state.step == "idle":
        st.info(
            "👈 点击上方醒目的 **「🚀 开始分析」** 按钮，\n\n"
            "系统将为你：\n"
            "1. � **优先读取** `data/products.json` 中的产品数据\n"
            "2. 🤖 从市场容量、竞争程度、利润潜力、新手友好度、季节性风险五个维度量化评分\n"
            "3. 📊 给出 🟢推荐 / 🟡谨慎 / 🔴不推荐 的明确 verdict\n"
            "4. 💾 自动保存分析结果到历史数据库，方便后续回顾\n\n"
            "💡 若 JSON 文件不存在，会尝试实时抓取 Amazon；若均不可用，请运行 `python daily_scrape.py` 生成数据。"
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
            elif source_type == "live":
                st.markdown("### 🎉 当前使用 Amazon 实时数据")
                st.markdown("分析结果已自动保存，可在「📚 历史记录」页面查看和导出。")

    # ---- 页脚 ----
    st.divider()
    st.caption(
        "⚠️ **免责声明：** 分析结果仅供参考，不构成投资建议。"
        " | Global Product Scout v0.2.0"
    )


# ============================================================
# ==================== 历史记录页面 ============================
# ============================================================

def _render_history_page():
    """渲染历史记录页面 — 查询、筛选、导出过往分析结果。"""

    st.title("📚 历史分析记录")
    st.markdown("浏览和筛选过往的产品分析记录，支持多条件筛选和 CSV 导出。")

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

    st.divider()

    # ---- 筛选控件 ----
    with st.container(border=True):
        st.markdown("### 🔍 筛选条件")
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

    # 从 DB 或 session state 读取数据
    if total_count > 0:
        products = get_all_products(filters=filters)
    else:
        # Cloud 端：使用 session state 数据，手动筛选
        products = st.session_state.history_data
        if verdict_options:
            products = [p for p in products
                        if p.get("analysis", {}).get("final_verdict") in verdict_options]
        if min_capacity > 1:
            products = [p for p in products
                        if (p.get("analysis", {}).get("market_capacity", {}) or {}).get("score", 0) >= min_capacity]
        if min_price > 0:
            products = [p for p in products if (p.get("price") or 0) >= min_price]
        if max_price < 1000:
            products = [p for p in products if (p.get("price") or 0) <= max_price]
        reverse = sort_order == "DESC"
        if sort_by == "price":
            products.sort(key=lambda p: p.get("price") or 0, reverse=reverse)
        elif sort_by == "rank":
            products.sort(key=lambda p: p.get("rank") or 0, reverse=reverse)
        else:
            products.sort(key=lambda p: p.get("scrape_time") or "", reverse=reverse)

    st.divider()

    if not products:
        st.warning("没有符合当前筛选条件的历史记录。请调整筛选条件后重试。")
        return

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

    # ---- 数据表格 ----
    st.subheader("📋 历史产品列表")
    table_data = []
    for p in products:
        analysis = p.get("analysis", {})
        table_data.append({
            "标题": (p.get("title", "") or "")[:60],
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

    st.dataframe(
        pd.DataFrame(table_data), use_container_width=True, hide_index=True,
        column_config={
            "判定": st.column_config.TextColumn(width="small"),
            "分析时间": st.column_config.TextColumn(width="medium"),
        },
    )

    # ---- 查看单条详情 ----
    with st.expander("🔍 点击展开查看某条记录的完整分析 JSON", expanded=False):
        selected_idx = st.selectbox(
            "选择产品",
            options=range(len(products)),
            format_func=lambda i: f"#{i+1} {(products[i].get('title', '') or '')[:60]}",
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
    st.caption(" | Global Product Scout v0.2.0 | 数据来源：历史分析记录 |")


# ============================================================
# 辅助函数
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
    3. 实时抓取返回 cache/mock 时丢弃数据并抛出异常

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

    # 实时抓取也失败 → 丢弃 cache/mock，提示用户
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
if "实时选品" in page:
    _render_live_page(api_ok)
elif "历史记录" in page:
    _render_history_page()
