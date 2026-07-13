"""
页面渲染 — Dashboard、实时选品、指定选品、市场扫描、历史记录等。
从 app.py 拆分，通过 app.py 路由调用。
"""

from __future__ import annotations

import json
import os
import importlib
import tempfile

import streamlit as st
import pandas as pd

from src.config import get_llm_config, get_profit_defaults, LLM_PROVIDERS
from src.analyzer import analyze_products, analyze_category_report
from src.calculator import calculate_profit
from src.scraper_1688 import search_1688_hybrid
from src.trends import get_trend_direction, get_trend_icon
from src.utils import deduplicate_products
from src.market_scanner import (
    scan_market,
    calculate_blue_ocean_score,
    classify_competition,
    predict_trend,
    build_retrospective,
)
from src.translator import (
    contains_chinese,
    is_translation_enabled,
    translate_keyword,
    translate_product_titles,
)
from src.platforms import (
    PLATFORMS,
    get_platform_info,
    get_region_info,
    get_platform_choices,
    get_available_platform_choices,
)
from src.database import (
    save_products,
    get_all_products,
    get_product_count,
    export_csv,
    save_procurement_cost,
    get_procurement_cost,
    get_trend_data,
    query_products,
    remove_favorite,
    get_favorites,
)

from .constants import (
    APP_VERSION,
    VERDICT_LABEL_MAP,
    ANALYSIS_DIMS,
    LONGEVITY_LABEL_MAP,
)
from .components import (
    _render_analysis_summary_table,
    _render_1688_result,
    _render_radar_chart,
    _render_favorite_button,
    _render_comparison_view,
    _navigate_to,
    _load_all_products,
    _render_beginner_picks,
    _match_filters_simple,
    _dim_score,
    _verdict_emoji,
)


def _render_dashboard_page():
    """新手首页 — 一打开就看到「该卖什么 + 能赚多少 + 适不适合你」。"""
    st.title("🎯 今日选品")
    st.markdown("AI 已从每日热销数据里帮你挑出最适合新手起步的产品。")

    all_products = _load_all_products()

    if not all_products:
        st.warning("📊 还没有选品数据。先抓一次数据，AI 才能帮你挑产品。")
        with st.container(border=True):
            st.markdown("#### 🚀 3 步开始你的第一次选品")
            st.markdown("1. 点下方按钮，抓取 Amazon 最新热销品（约 1 分钟）  \n"
                        "2. AI 自动分析每个产品（约 1-2 分钟）  \n"
                        "3. 回到本页，看 AI 帮你挑的好产品")
            st.button("🔍 立即抓取数据", type="primary", key="goto_live_first", width="stretch",
                      on_click=_navigate_to, args=("实时选品",))
        st.divider()
        with st.expander("🧭 想搜特定品类？", expanded=False):
            st.markdown("如果你心里已经有想做的东西（比如「猫玩具」），可以直接搜：")
            st.button("🎯 关键词选品", key="goto_targeted_empty", width="stretch",
                      on_click=_navigate_to, args=("指定选品",))
        return

    latest_time = all_products[0].get("scrape_time", "") if all_products else ""
    if latest_time:
        st.caption(f"📅 数据更新于 {latest_time} ｜ 共 {len(all_products)} 个产品 ｜ 来源：每日自动抓取")

    st.divider()
    _render_beginner_picks(all_products)
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

    # ---- 获取数据按钮（Spec 32：统一入口） ----
    btn_disabled = st.session_state.get("analyzing", False)

    col_btn, col_hint = st.columns([2, 3])
    with col_btn:
        btn_get = st.button(
            "🔍 获取数据",
            type="primary",
            width="stretch",
            disabled=btn_disabled,
            help="优先实时抓取最新数据，失败时降级到每日自动更新数据",
        )
    with col_hint:
        json_path = os.path.join(os.path.dirname(__file__), "data", "products.json")
        json_exists = os.path.exists(json_path)
        if json_exists:
            st.caption("📡 优先实时抓取（失败时用每日更新数据兜底）")
        else:
            st.caption("📡 将实时抓取最新数据")

    if btn_get:
        st.session_state.analyzing = True
        loaded = False
        # 重置标题翻译标记（新数据需要重新翻译）
        st.session_state["live_titles_translated"] = False

        # 第一步：优先实时抓取（最新数据）
        try:
            with st.spinner(f"📡 正在实时抓取 {pf_name} {region_name} 热销数据..."):
                import importlib
                scraper_mod = importlib.import_module(pf_info["scraper_module"])
                scraper_func = getattr(scraper_mod, pf_info["scraper_func"])
                products, source_info = scraper_func(region=region)

            if source_info.get("source") in ("live", "cache"):
                st.session_state.products = products
                st.session_state.source_info = source_info
                st.session_state.step = "loaded"
                loaded = True
                st.rerun()
            else:
                # 实时抓取失败 → 降级到每日数据
                error_detail = source_info.get("error", "网站反爬拦截或页面不可用")
                st.caption(f"实时抓取失败（{str(error_detail)[:60]}），尝试每日更新数据...")
        except Exception as e:
            st.caption(f"实时抓取异常（{str(e)[:60]}），尝试每日更新数据...")

        # 第二步：降级到每日自动更新数据（products.json）
        if not loaded and json_exists:
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    products = json.load(f)
                if products:
                    # 按当前平台+地区筛选
                    filtered = [
                        p for p in products
                        if p.get("platform", "amazon") == platform
                        and p.get("region", "us") == region
                    ]
                    if filtered:
                        scrape_time = filtered[0].get("scrape_time", "")
                        st.session_state.products = filtered
                        st.session_state.source_info = {"source": "daily_update", "timestamp": scrape_time}
                        st.session_state.step = "loaded"
                        loaded = True
                        st.rerun()
                    else:
                        st.info(f"每日数据中也没有 {pf_name} {region_name} 的产品。")
            except Exception as e:
                st.caption(f"读取每日数据失败：{str(e)[:80]}")

        # 两种方式都失败
        if not loaded:
            st.session_state.analyzing = False
            st.error(f"❌ 获取 {pf_name} {region_name} 数据失败")
            st.info(
                "💡 **推荐方案：**\n"
                "1. 稍后重试（可能是网站反爬临时拦截）\n"
                "2. 使用「🎯 指定选品」通过关键词搜索产品\n"
                "3. 在本机运行 `python daily_scrape.py` 更新数据"
            )

    # ---- 数据显示（加载完成后显示，此时侧边栏已更新） ----
    if st.session_state.step in ("loaded", "analyzed") and st.session_state.products:
        src_info = st.session_state.source_info or {}
        src_type = src_info.get("source", "")
        ts = src_info.get("timestamp", "")
        if src_type in ("json", "daily_update"):
            st.success(f"📊 已加载每日更新数据！共 {len(st.session_state.products)} 个热销产品\n\n⏰ 抓取时间：{ts}")
        elif src_type == "live":
            st.success(f"📡 实时抓取成功！已获取 {len(st.session_state.products)} 个热销产品\n\n⏰ 数据更新时间：{ts}")
        elif src_type == "cache":
            st.info(f"💾 使用本地缓存数据！共 {len(st.session_state.products)} 个产品\n\n⏰ 缓存时间：{ts}")

        # 第二步：AI 分析（流式渲染，Spec 21）
        if st.session_state.step == "loaded":
            total = len(st.session_state.products)
            if total == 0:
                st.warning("无产品可分析，请先获取数据。")
                st.session_state.step = "idle"
            else:
                # 标题翻译：英文标题 → 中文（仅一次，Spec 33）
                if not st.session_state.get("live_titles_translated"):
                    titles = [p.get("title", "") for p in st.session_state.products]
                    need_translation = any(contains_chinese(t) is False and t.strip() for t in titles)
                    if need_translation:
                        with st.status("🌐 正在翻译产品标题...", expanded=False) as tstatus:
                            zh_titles = translate_product_titles(titles)
                            translated_count = 0
                            for p, zh in zip(st.session_state.products, zh_titles):
                                if zh and zh != p.get("title"):
                                    p["title_zh"] = zh
                                    translated_count += 1
                            st.session_state["live_titles_translated"] = True
                            if translated_count > 0:
                                st.toast(f"已翻译 {translated_count} 个产品标题为中文", icon="🌐")
                            tstatus.update(
                                label=f"✅ 已翻译 {translated_count} 个产品标题",
                                state="complete",
                            )
                    else:
                        st.session_state["live_titles_translated"] = True

                with st.status("AI 正在深度分析产品竞争力与利润潜力...", expanded=False) as status:
                    progress_bar = st.progress(0, text="准备分析...")
                    # 预创建空容器用于流式渲染
                    result_containers = [st.empty() for _ in range(total)]

                    def _on_progress(done, total_count):
                        pct = min(done / total_count, 1.0)
                        progress_bar.progress(pct, text=f"分析进度：{done}/{total_count}")

                    def _on_batch_complete(done, total_count, batch_results):
                        """每批完成后立即渲染该批产品卡片（Spec 21 流式更新）。"""
                        start_idx = done - len(batch_results)
                        for j, r in enumerate(batch_results):
                            idx = start_idx + j
                            if idx < len(result_containers):
                                verdict = r.get("final_verdict", "unknown")
                                emoji = {"recommended": "🟢", "cautious": "🟡", "not_recommended": "🔴"}.get(verdict, "⚪")
                                title = r.get("title", f"#{idx+1}")[:40]
                                result_containers[idx].caption(f"{emoji} {title}")

                    results = analyze_products(
                        st.session_state.products,
                        progress_callback=_on_progress,
                        on_complete_callback=_on_batch_complete,
                    )
                    st.session_state.results = results
                    st.session_state.step = "analyzed"
                    progress_bar.empty()
                    # 清除流式预览容器
                    for c in result_containers:
                        c.empty()
                    status.update(label="✅ AI 分析完成！", state="complete")

            # 第三步：保存到数据库
            db_ok = True
            try:
                saved_count = save_products(
                    st.session_state.products, st.session_state.results,
                    platform=platform, region=region, currency=currency,
                )
                st.caption(f"💾 已保存 {saved_count} 条分析记录到历史数据库")
            except Exception:
                db_ok = False
                st.caption("⚠️ 数据库保存失败，但分析结果仍可在当前页面查看")

            # 同步保存到 session state（Cloud 端 SQLite 不持久化的后备方案）
            for p, r in zip(st.session_state.products, st.session_state.results):
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
        # Spec 33：优先用中文标题 title_zh 显示
        if "title_zh" in df.columns:
            df["title"] = df["title_zh"].where(df["title_zh"].notna() & (df["title_zh"] != ""), df.get("title"))
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
        st.caption("六维度量化评估：市场容量 · 竞争程度 · 利润潜力 · 新手友好度 · 季节性风险 · 长期持久力")

        # 批量采购成本（Spec 16 P1）
        with st.expander("批量设置采购成本（可选）", expanded=False):
            col_bulk, col_apply = st.columns([3, 1])
            with col_bulk:
                bulk_cost = st.number_input(
                    "统一采购成本 (¥/件)",
                    min_value=0.0, max_value=5000.0, value=0.0, step=1.0,
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
            # 长青度徽章：与 verdict 并排，让用户一眼区分"长青可长期做" vs "阶段性爆品"
            longevity_label = LONGEVITY_LABEL_MAP.get(
                (r.get("longevity") or {}).get("label", ""), ""
            )

            is_raw = r.get("parse_error", False)
            # Spec 33：优先显示中文标题 title_zh
            product_data_t = st.session_state.products[i] if i < len(st.session_state.products) else {}
            title_zh = product_data_t.get("title_zh")
            title_en = r.get("title", f"产品 #{i+1}")
            title_text = title_zh or title_en
            badge = verdict_label + (f"  {longevity_label}" if longevity_label else "")
            expander_label = (
                f"⚠️ 解析异常 #{i+1} {title_text[:40]}{'…' if len(title_text) > 40 else ''}"
                if is_raw else f"{badge} #{i+1} {title_text[:40]}{'…' if len(title_text) > 40 else ''}"
            )

            with st.expander(expander_label, expanded=(i == 0)):
                # 产品图片 + 标题（Spec 27）
                product_data = st.session_state.products[i] if i < len(st.session_state.products) else {}
                product_url = product_data.get("url") or ""
                product_image = product_data.get("image") or ""

                col_img, col_info = st.columns([1, 4])
                with col_img:
                    if product_image and isinstance(product_image, str):
                        try:
                            st.image(product_image, width=120)
                        except Exception:
                            st.caption("（图片加载失败）")
                with col_info:
                    if product_url:
                        st.markdown(f"📦 **[{title_text}]({product_url})**")
                    else:
                        st.caption(f"📦 **完整标题：** {title_text}")
                    # 中英对照（Spec 33）
                    if title_zh and title_en != title_zh:
                        st.caption(f"🌐 {title_en}")
                if is_raw:
                    verdict_reason = r.get("verdict_reason", "")
                    st.warning(f"⚠️ AI 返回格式异常 — {verdict_reason}")
                    continue

                verdict_reason = r.get("verdict_reason", "")
                if verdict == "recommended":
                    st.success(f"✅ **推荐入手** — {verdict_reason}")
                elif verdict == "cautious":
                    st.warning(f"⚠️ **谨慎评估** — {verdict_reason}")
                else:
                    st.error(f"❌ **不推荐** — {verdict_reason}")

                dims = ANALYSIS_DIMS
                cols = st.columns(len(ANALYSIS_DIMS))
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
                        # AI估算标注（Spec 28）
                        if key == "market_capacity" and reason_val:
                            st.caption("🔍 AI估算")

                # AI 趋势预判 + 参考采购价（自动嵌入）
                trend_dir = r.get("trend_direction", "unknown")
                trend_reason = r.get("trend_reason", "")
                est_cost = r.get("estimated_cost_cny", 0)

                trend_icon_map = {"rising": "📈", "stable": "➡️", "declining": "📉"}
                trend_icon = trend_icon_map.get(trend_dir, "❓")
                trend_label = {
                    "rising": "上升趋势",
                    "stable": "稳定",
                    "declining": "下降趋势",
                    "unknown": "未知"
                }.get(trend_dir, "未知")

                if trend_dir != "unknown" or est_cost > 0:
                    st.divider()
                    col_trend, col_cost = st.columns(2)
                    with col_trend:
                        st.markdown(f"**{trend_icon} 趋势：** {trend_label}")
                        if trend_reason:
                            st.caption(f"💡 {trend_reason}")
                    with col_cost:
                        if est_cost > 0:
                            st.markdown(f"**🏭 参考采购价：** ¥{est_cost:.0f}")
                            st.caption("AI 估算（基于品类分析）")
                        else:
                            st.markdown("**🏭 参考采购价：** 未估算")
                            st.caption("可点击下方验证按钮获取 1688 价格")

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

                with st.expander("查看详细分析文本", expanded=False):
                    for label, key in ANALYSIS_DIMS:
                        dim_data = r.get(key, {})
                        score_val = dim_data.get("score", 0) if isinstance(dim_data, dict) else 0
                        reason_val = dim_data.get("reason", "") if isinstance(dim_data, dict) else str(dim_data)
                        st.caption(f"**{label}** ({score_val}/10)")
                        st.text(reason_val)

                # ---- 📈 Google Trends 验证（降为二级操作） ----
                with st.expander("🔍 验证趋势（可选）", expanded=False):
                    if st.button("📈 查询 Google Trends 详细数据", key=f"trend_{i}", width="stretch"):
                        trend_keyword = title_text.split(" - ")[0].split(",")[0][:30].strip()
                        with st.spinner(f"正在查询趋势：{trend_keyword}..."):
                            trend = get_trend_direction(trend_keyword)
                        if trend["available"]:
                            icon = get_trend_icon(trend["direction"])
                            st.success(f"📈 趋势：{icon} | 当前热度 {trend['interest']} | 平均 {trend['avg_interest']}")
                            # 展示12个月趋势图（Spec 31）
                            from src.trends import get_trend_timeseries
                            ts = get_trend_timeseries(trend_keyword)
                            if ts["available"] and ts["dates"]:
                                import plotly.express as px
                                fig = px.line(
                                    x=ts["dates"], y=ts["values"],
                                    title=f"Google Trends: {trend_keyword}",
                                    labels={"x": "日期", "y": "搜索热度"},
                                )
                                fig.update_layout(height=250, margin=dict(l=40, r=20, t=40, b=40))
                                st.plotly_chart(fig, width="stretch")
                        else:
                            st.warning(f"⚠️ {trend['error']}")

                # ---- 💰 利润试算 ----
                st.divider()
                st.markdown("**💰 利润试算**")

                # 利润参数配置（内联折叠）
                with st.expander("⚙️ 利润参数配置", expanded=False):
                    active_pf = st.session_state.get("active_platform", "amazon")
                    pf_info = get_platform_info(active_pf)
                    active_region = st.session_state.get("active_region", pf_info.get("default_region", "us"))
                    region_info = get_region_info(active_pf, active_region)
                    profit_defaults = get_profit_defaults(active_pf)

                    # 汇率
                    currency_label = region_info.get("currency", "USD")
                    exchange_rate = st.number_input(
                        f"汇率 (CNY/{currency_label})", min_value=0.01, max_value=20.0,
                        value=float(profit_defaults["exchange_rate"]), step=0.01,
                        key=f"exchange_rate_{i}",
                        help=f"1 {currency_label} 兑换多少人民币",
                    )
                    # 佣金比例
                    commission_label = {
                        "amazon": "亚马逊佣金比例",
                        "ebay": "eBay 成交费比例",
                        "tiktok": "TikTok 佣金比例",
                    }.get(active_pf, "平台佣金比例")
                    commission_pct = st.slider(
                        commission_label, min_value=0.0, max_value=0.50,
                        value=float(profit_defaults.get("commission_pct", 0.15)), step=0.01,
                        format="%.0f%%",
                        key=f"commission_{i}",
                    )
                    # 广告预算（Amazon 特有）
                    if active_pf == "amazon":
                        ad_pct = st.slider(
                            "广告预算占比", min_value=0.0, max_value=0.50,
                            value=float(profit_defaults.get("ad_pct", 0.10)), step=0.01,
                            format="%.0f%%",
                            key=f"ad_pct_{i}",
                        )
                    else:
                        ad_pct = 0.0
                    # 运费分档
                    SHIPPING_TIERS = {
                        "light":  {"label": "轻件 <500g",   "cny": 8.0},
                        "medium": {"label": "中件 500g-2kg", "cny": 20.0},
                        "heavy":  {"label": "重件 >2kg",     "cny": 50.0},
                        "custom": {"label": "自定义",        "cny": None},
                    }
                    shipping_tier = st.selectbox(
                        "运费档位",
                        options=list(SHIPPING_TIERS.keys()),
                        format_func=lambda k: SHIPPING_TIERS[k]["label"],
                        index=1,
                        key=f"shipping_tier_{i}",
                    )
                    if shipping_tier == "custom":
                        shipping_cny = st.number_input(
                            "自定义运费 (¥/件)", min_value=0.0, max_value=200.0,
                            value=float(profit_defaults.get("shipping_cny", 15.0)), step=1.0,
                            key=f"shipping_cny_{i}",
                        )
                    else:
                        shipping_cny = SHIPPING_TIERS[shipping_tier]["cny"]

                    # 同步到 session_state
                    st.session_state["profit_defaults"] = {
                        "exchange_rate": exchange_rate,
                        "commission_pct": commission_pct,
                        "ad_pct": ad_pct,
                        "shipping_cny": shipping_cny,
                        "procurement_cny": 0.0,
                    }

                defaults = st.session_state.get("profit_defaults", get_profit_defaults())
                product_price = st.session_state.products[i].get("price", 0) or 0
                product_title = st.session_state.products[i].get("title", "")
                product_scrape_time = st.session_state.products[i].get("scrape_time", "")

                # 从数据库恢复已保存的采购成本，如果没有则使用 AI 估算价
                saved_cost = 0.0
                if product_title and product_scrape_time:
                    try:
                        saved_cost = get_procurement_cost(product_title, product_scrape_time)
                    except Exception:
                        pass  # 数据库不可用时忽略

                # 如果没有保存的成本，使用 AI 估算价作为默认值
                ai_est_cost = r.get("estimated_cost_cny", 0) or 0
                # 统一转 float：min_value/step 都是 float，value 若为 int 0（AI 未给估算价）
                # 会触发 StreamlitMixedNumericTypesError（新版 Streamlit 强校验）
                default_procurement = float(saved_cost if saved_cost > 0 else ai_est_cost)
                # 夹到 number_input 的 [0, 5000] 区间，防止 AI 给出/DB 存了 >max 的值
                # 触发 StreamlitValueAboveMaxError（贵价品如 AirPods Pro 采购价可能 >1000）
                default_procurement = min(max(default_procurement, 0.0), 5000.0)

                # 1688 验证回填：widget 绑了 key 后不能直接赋值 session_state，
                # 必须在 number_input 渲染前注入（记忆：Streamlit Widget Key 坑）
                _pending_key = f"_pending_procurement_{i}"
                if _pending_key in st.session_state:
                    st.session_state[f"procurement_{i}"] = st.session_state.pop(_pending_key)

                col_input, col_result = st.columns([1, 2])
                with col_input:
                    procurement = st.number_input(
                        "预估采购成本 (¥/件)",
                        min_value=0.0, max_value=5000.0,
                        value=default_procurement, step=1.0,
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
                            margin_status = "利润可观"
                            st.success(f"利润可观（毛利率 {margin}%）")
                        elif margin >= 15:
                            margin_delta = "off"
                            margin_status = "利润尚可"
                            st.info(f"利润尚可（毛利率 {margin}%）")
                        elif margin >= 0:
                            margin_delta = "inverse"
                            margin_status = "利润微薄"
                            st.warning(f"利润微薄（毛利率 {margin}%）— 需要优化成本结构")
                        else:
                            margin_delta = "inverse"
                            margin_status = "利润为负"
                            st.error(f"利润为负（毛利率 {margin}%）— 建议放弃该产品")

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

                # ---- 🔍 1688 验证（降为二级操作） ----
                _1688_cache_key = f"price_1688_{product_title}"
                cached_1688 = st.session_state.get(_1688_cache_key)

                with st.expander("🔍 验证1688价格（可选）", expanded=False):
                    if st.button("🔍 用1688真实价格验证", key=f"1688_{i}", width="stretch"):
                        search_keyword = product_title[:30]
                        price_usd = float(product_price) if product_price else 0.0
                        with st.spinner(f"正在获取参考价：{search_keyword}..."):
                            result_1688 = search_1688_hybrid(product_title, price_usd)
                        st.session_state[_1688_cache_key] = result_1688
                        cached_1688 = result_1688
                        # 自动回填采购成本（Spec 26）
                        if result_1688.get("success") and result_1688.get("price_range"):
                            pr = result_1688["price_range"]
                            mid_price = (pr.get("min", 0) + pr.get("max", 0)) / 2
                            if mid_price > 0:
                                # 不能直接写 procurement_{i}（widget 已渲染会抛 StreamlitAPIException），
                                # 写入 pending key，rerun 后由 number_input 渲染前注入
                                st.session_state[f"_pending_procurement_{i}"] = mid_price
                                st.toast(f"✅ 已自动填入采购成本: ¥{mid_price:.2f}", icon="✅")
                                st.rerun()

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
            "2. 🤖 从市场容量、竞争程度、利润潜力、新手友好度、季节性风险、长期持久力六个维度量化评分\n"
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
        4. 展示搜索结果列表 + 每个产品的六维度分析
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
                placeholder="例：便携式榨汁机 / portable blender / cat toys",
                help="支持中文，自动翻译为英文搜索；搜索后可用价格滑块筛选",
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

        # 搜索前提示
        st.caption("⏱️ 预估耗时：搜索 ~10 秒 + AI 分析 ~30-60 秒（取决于产品数量）")

    # ---- 搜索触发 ----
    if search_clicked and keyword.strip():
        st.session_state.targeted_keyword = keyword.strip()
        st.session_state.targeted_step = "searching"
        st.session_state.targeted_results = None
        st.session_state.targeted_category = None
        st.session_state.targeted_analysis = None
        st.rerun()

    # ---- 搜索执行 ----
    if st.session_state.get("targeted_step") == "searching":
        kw = st.session_state.targeted_keyword

        # 动态加载平台对应的搜索函数
        platform = st.session_state.get("active_platform", "amazon")
        region = st.session_state.get("active_region", "us")
        pf_info = get_platform_info(platform)
        pf_name = f"{pf_info['icon']} {pf_info['name']}"

        # 关键词翻译（Spec 33）：含中文且开启翻译 → 翻成英文再搜
        kw_display = kw   # 展示用（含原中文 → 英文提示）
        kw_search = kw    # 实际搜索用（英文）
        translated_keyword_info = None  # 记录翻译信息供摘要卡片用
        if (
            st.session_state.get("translation_enabled", is_translation_enabled())
            and contains_chinese(kw)
        ):
            with st.status("🌐 正在翻译关键词...", expanded=True):
                tr = translate_keyword(kw)
                if tr["success"] and tr.get("translated") and tr["translated"] != kw:
                    kw_search = tr["translated"]
                    kw_display = f"{kw} → {kw_search}"
                    translated_keyword_info = (kw, kw_search)
                    st.success(f"✅ 关键词已翻译：{kw} → **{kw_search}**")
                    st.toast(f"已翻译: {kw} → {kw_search}", icon="🌐")

        with st.status(f"📡 正在搜索 {pf_name}...", expanded=False) as status:
            search_mod = importlib.import_module(pf_info["search_module"])
            search_func = getattr(search_mod, pf_info["search_func"])
            search_result = search_func(kw_search, region=region, max_results=20)

            if search_result["success"]:
                products = search_result["results"]
                source = search_result["source"]

                # 去重：按 ASIN 保留评分最高的变体
                original_count = len(products)
                products = deduplicate_products(products)
                if len(products) < original_count:
                    st.caption(f"🔄 去重：{original_count} → {len(products)} 个产品（按 ASIN 去除重复变体）")

                # 产品标题翻译（Spec 33）：英文标题 → 中文，存 title_zh
                translated_titles_count = 0
                if st.session_state.get("translation_enabled", is_translation_enabled()) and products:
                    with st.status("🌐 正在翻译产品标题...", expanded=True):
                        titles = [p.get("title", "") for p in products]
                        zh_titles = translate_product_titles(titles)
                        for p, zh in zip(products, zh_titles):
                            if zh and zh != p.get("title"):
                                p["title_zh"] = zh
                                translated_titles_count += 1
                        if translated_titles_count > 0:
                            st.success(f"✅ 已将 {translated_titles_count} 个产品标题翻译为中文")
                            st.toast(f"已翻译 {translated_titles_count} 个标题为中文", icon="📝")

                # 记录翻译摘要信息（供结果区摘要卡片展示）
                st.session_state.targeted_translation_info = {
                    "keyword": translated_keyword_info,
                    "titles_count": translated_titles_count,
                }

                st.session_state.targeted_results = products
                st.session_state.targeted_source = source
                st.session_state.targeted_scrape_time = search_result.get("scrape_time", "")
                st.session_state.targeted_keyword_display = kw_display

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

        # 并行：六维度分析 + 品类报告
        with st.status("AI 正在深度分析...", expanded=False) as status:
            progress_bar = st.progress(0, text="准备分析...")

            def _on_progress(done, total_count):
                pct = min(done / total_count, 1.0)
                progress_bar.progress(pct, text=f"产品分析进度：{done}/{total_count}")

            # 六维度分析（复用现有批量分析）
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
        st.success(f"✅ 搜索「{st.session_state.get('targeted_keyword_display', kw)}」找到 {len(products)} 个产品")

        # ---- 翻译摘要卡片（Spec 33 增强） ----
        tr_info = st.session_state.get("targeted_translation_info")
        if tr_info and (tr_info.get("keyword") or tr_info.get("titles_count")):
            with st.container(border=True):
                kw_tr = tr_info.get("keyword")
                tc = tr_info.get("titles_count", 0)
                parts = []
                if kw_tr:
                    parts.append(f"🌐 搜索词已翻译：**{kw_tr[0]}** → **{kw_tr[1]}**")
                if tc > 0:
                    parts.append(f"📝 已将 **{tc}** 个产品标题翻译为中文")
                st.markdown("  \n".join(parts))

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
                with st.expander("风险因素", expanded=False):
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
                            # Spec 33：显示中文标题（若有）
                            zh = matched_product.get("title_zh")
                            if zh and zh != title:
                                st.caption(f"🇨🇳 {zh}")
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
                                    # 自动回填采购成本（Spec 26）
                                    mid_price = (pr.get("min", 0) + pr.get("max", 0)) / 2
                                    if mid_price > 0:
                                        st.session_state[f"targeted_procurement_{i}"] = mid_price
                                        st.toast(f"✅ 已自动填入: ¥{mid_price:.2f}", icon="✅")
                                        st.rerun()
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
                                min_value=0.0, max_value=5000.0, value=0.0, step=1.0,
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
                                    if margin >= 30:
                                        st.success(f"利润可观（毛利率 {margin}%）")
                                    elif margin >= 15:
                                        st.info(f"利润尚可（毛利率 {margin}%）")
                                    elif margin >= 0:
                                        st.warning(f"利润微薄（毛利率 {margin}%）— 需要优化成本结构")
                                    else:
                                        st.error(f"利润为负（毛利率 {margin}%）— 建议放弃该产品")
                                    st.metric("净利", f"¥{profit_result['net_profit_cny']:.2f}")

        # ---- 搜索结果完整列表 ----
        st.divider()
        st.subheader("📋 搜索结果列表")

        # 价格滑块筛选（搜索后，Spec：先搜后筛）
        prices = []
        for p in products:
            try:
                pr = float(p.get("price", 0) or 0)
                if pr > 0:
                    prices.append(pr)
            except (ValueError, TypeError):
                pass
        filtered_products = products
        if prices and len(prices) >= 2:
            p_min, p_max = min(prices), max(prices)
            # 向上取整到 5 的倍数，滑块更顺手
            ceil_max = int((p_max // 5 + 1) * 5)
            price_range = st.slider(
                "💰 价格范围 (USD)",
                min_value=0.0, max_value=float(ceil_max),
                value=(0.0, float(ceil_max)), step=1.0,
                help="拖动筛选价格区间，实时过滤结果列表",
            )
            filtered_products = [
                p for p in products
                if price_range[0] <= float(p.get("price", 0) or 0) <= price_range[1]
            ]
            if len(filtered_products) < len(products):
                st.caption(f"💰 价格筛选：{len(products)} → {len(filtered_products)} 个产品")
        elif prices:
            st.caption(f"💰 价格范围：${min(prices):.2f} - ${max(prices):.2f}")

        products = filtered_products

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

        # 构造展示行（Spec 33：优先用中文标题 title_zh）
        display_rows = []
        for p in sorted_products:
            row = dict(p)
            row["产品名称"] = p.get("title_zh") or p.get("title", "")
            display_rows.append(row)
        df = pd.DataFrame(display_rows)
        df_display = df.rename(columns={
            "rank": "排名", "price": "价格 (USD)",
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

        # ---- 每个产品的六维度分析 ----
        if analysis:
            st.divider()
            st.subheader("🤖 AI 六维度详细分析")

            # 速览表（Spec 16 P0）
            with st.expander("分析结果速览表（点击展开）", expanded=True):
                _render_analysis_summary_table(products, analysis)

            for i, r in enumerate(analysis):
                verdict = r.get("final_verdict", "cautious")
                verdict_label = VERDICT_LABEL_MAP.get(verdict, "⚪ 未知")
                # 长青度徽章
                longevity_label = LONGEVITY_LABEL_MAP.get(
                    (r.get("longevity") or {}).get("label", ""), ""
                )
                # Spec 33：优先显示中文标题（产品上的 title_zh）
                prod_i = products[i] if i < len(products) else {}
                title_zh = prod_i.get("title_zh")
                title_en = r.get("title", f"产品 #{i+1}")
                title_text = title_zh or title_en
                badge = verdict_label + (f"  {longevity_label}" if longevity_label else "")

                with st.expander(f"{badge} #{i+1} {title_text[:40]}{'…' if len(title_text) > 40 else ''}", expanded=False):
                    st.caption(f"📦 **完整标题：** {title_text}")
                    if title_zh and title_en != title_zh:
                        st.caption(f"🔤 *English:* {title_en}")
                    verdict_reason = r.get("verdict_reason", "")
                    if verdict == "recommended":
                        st.success(f"✅ **推荐入手** — {verdict_reason}")
                    elif verdict == "cautious":
                        st.warning(f"⚠️ **谨慎评估** — {verdict_reason}")
                    else:
                        st.error(f"❌ **不推荐** — {verdict_reason}")

                    dims = ANALYSIS_DIMS
                    cols = st.columns(len(ANALYSIS_DIMS))
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
            "1. 🔍 输入产品关键词，**中文或英文均可**（如 `便携式榨汁机` 或 `portable blender`）\n"
            "2. 🚀 点击「搜索分析」按钮\n"
            "3. 📊 查看品类综合报告 + Top 3 推荐\n"
            "4. 💰 对推荐产品查看 1688 比价和利润试算\n\n"
            "**热门品类参考：** 便携式榨汁机、瑜伽垫、猫玩具、蓝牙音箱、手机壳、LED 灯带"
        )



# ============================================================
# ==================== 市场扫描页面 ===========================
# ============================================================



def _render_market_scanner_page(api_ok: bool):
    """渲染市场扫描页面 — 批量扫描多平台×多地区，找出蓝海市场。"""

    st.title("🌐 市场机会扫描")
    st.markdown("输入关键词扫描多平台多地区蓝海市场，或聚合热销榜单发现爆款趋势。")
    st.divider()

    # ---- 扫描模式选择 ----
    scan_mode = st.radio(
        "扫描模式",
        ["🔍 关键词扫描", "🔥 热销聚合"],
        horizontal=True,
        key="scan_mode_select",
    )

    if scan_mode == "🔍 关键词扫描":
        _render_keyword_scan_mode(api_ok)
    else:
        _render_hot_aggregation_mode(api_ok)




def _render_keyword_scan_mode(api_ok: bool):
    """关键词扫描模式 — 输入关键词扫描多平台多地区。"""
    # ---- 输入区域 ----
    with st.container(border=True):
        col_kw, col_btn = st.columns([3, 1])
        with col_kw:
            keyword = st.text_input(
                "🔍 搜索关键词",
                value=st.session_state.get("scan_keyword", ""),
                placeholder="例：portable blender, cat toys, yoga mat",
                help="输入英文关键词效果最佳",
                key="scan_keyword_input",
            )
        with col_btn:
            st.write("")
            st.write("")
            scan_clicked = st.button(
                "🌐 开始扫描",
                type="primary",
                width="stretch",
                disabled=not keyword.strip(),
                key="scan_start_btn",
            )

        # 平台选择
        platform_keys = get_available_platform_choices()
        platform_names = {k: f"{PLATFORMS[k]['icon']} {PLATFORMS[k]['name']}" for k in platform_keys}
        selected_platforms = st.multiselect(
            "🛒 扫描平台",
            options=platform_keys,
            default=platform_keys[:2],
            format_func=lambda k: platform_names[k],
            key="scan_platforms_select",
        )

        # 地区选择
        all_regions = set()
        for pf in selected_platforms:
            pf_info = get_platform_info(pf)
            for rk in pf_info.get("regions", {}).keys():
                all_regions.add(rk)
        region_options = sorted(all_regions)
        region_labels = {}
        for pf in selected_platforms:
            for rk, rv in get_platform_info(pf).get("regions", {}).items():
                label = f"{rv['name']} ({rk})"
                if label not in region_labels:
                    region_labels[rk] = label
        selected_regions = st.multiselect(
            "🌍 扫描地区",
            options=region_options,
            default=region_options[:4],
            format_func=lambda k: region_labels.get(k, k.upper()),
            key="scan_regions_select",
        )

        # 预估耗时
        combo_count = len(selected_platforms) * len(selected_regions)
        if combo_count > 0:
            est_seconds = combo_count * 30
            st.caption(f"⏱️ 预估耗时：{combo_count} 个市场 × ~30秒 ≈ {est_seconds // 60} 分钟")

    # ---- 扫描触发 ----
    if scan_clicked and keyword.strip() and selected_platforms and selected_regions:
        st.session_state.scan_keyword = keyword.strip()
        st.session_state.scan_platforms = selected_platforms
        st.session_state.scan_regions = selected_regions
        st.session_state.scan_step = "scanning"
        st.session_state.scan_results = None
        st.session_state.scan_report = None
        st.rerun()

    # ---- 扫描执行 ----
    if st.session_state.get("scan_step") == "scanning":
        kw = st.session_state.scan_keyword
        platforms = st.session_state.scan_platforms
        regions = st.session_state.scan_regions

        with st.status("正在扫描市场...", expanded=True) as status:
            progress_bar = st.progress(0, text="准备扫描...")

            def _on_progress(done, total, label):
                pct = min(done / total, 1.0) if total > 0 else 0
                progress_bar.progress(pct, text=f"扫描进度：{done}/{total} — {label}")

            results = scan_market(kw, platforms, regions, progress_callback=_on_progress)
            st.session_state.scan_results = results

            progress_bar.empty()
            status.update(label="✅ 扫描完成！", state="complete")

        # 扫描完成后，计算蓝海指数并排序（Spec 25）
        markets = results.get("markets", [])
        for m in markets:
            if not m.get("error") and m.get("products"):
                # 从该市场的产品分析结果计算蓝海指数
                products = m["products"]
                # 聚合各维度平均分
                dim_sums = {"market_capacity": 0, "competition": 0, "profit_potential": 0}
                dim_counts = 0
                for p in products:
                    analysis = p.get("analysis", {})
                    if analysis and not analysis.get("parse_error"):
                        for key in dim_sums:
                            dim = analysis.get(key, {})
                            if isinstance(dim, dict) and dim.get("score"):
                                dim_sums[key] += dim["score"]
                        dim_counts += 1
                if dim_counts > 0:
                    avg_analysis = {k: {"score": v / dim_counts} for k, v in dim_sums.items()}
                    m["blue_ocean_score"] = calculate_blue_ocean_score(avg_analysis)
                    m["competition_level"] = classify_competition(dim_sums["competition"] / dim_counts)
                else:
                    m["blue_ocean_score"] = 0.0
                    m["competition_level"] = "unknown"
            else:
                m["blue_ocean_score"] = 0.0
                m["competition_level"] = "unknown"

        st.session_state.scan_step = "scanned"
        st.rerun()

    # ---- 结果展示 ----
    if st.session_state.get("scan_step") in ("scanned", "done"):
        results = st.session_state.scan_results
        if not results:
            st.warning("无扫描结果。")
            return

        keyword = results.get("keyword", "")
        markets = results.get("markets", [])
        valid_markets = [m for m in markets if not m.get("error")]
        failed_markets = [m for m in markets if m.get("error")]

        st.success(f"✅ 扫描「{keyword}」完成 — {len(valid_markets)}/{len(markets)} 个市场成功")

        if failed_markets:
            with st.expander(f"⚠️ {len(failed_markets)} 个市场扫描失败", expanded=False):
                for m in failed_markets:
                    st.caption(f"❌ {PLATFORMS.get(m['platform'], {}).get('icon', '')} {m.get('region_name', m['region'])} — {m.get('error', '未知错误')}")

        # ---- 蓝海指数排行榜 ----
        if valid_markets:
            st.divider()
            st.subheader("🏆 蓝海指数排行榜")
            st.caption("基于产品数量、平均价格、平均评分综合评估市场机会")

            # 按产品数量降序（产品多=需求大，作为基础排序）
            sorted_markets = sorted(valid_markets, key=lambda m: m.get("product_count", 0), reverse=True)

            for i, m in enumerate(sorted_markets):
                pf_icon = PLATFORMS.get(m["platform"], {}).get("icon", "")
                pf_name = PLATFORMS.get(m["platform"], {}).get("name", m["platform"])
                region_name = m.get("region_name", m["region"].upper())
                count = m.get("product_count", 0)
                avg_price = m.get("avg_price", 0)
                avg_rating = m.get("avg_rating", 0)

                # 蓝海指数（Spec 25）：从AI分析结果计算
                blue_ocean = m.get("blue_ocean_score", 0.0)
                competition_level = m.get("competition_level", "unknown")

                col_rank, col_info, col_stats = st.columns([0.5, 2, 3])
                with col_rank:
                    st.markdown(f"### #{i+1}")
                with col_info:
                    st.markdown(f"**{pf_icon} {pf_name} — {region_name}**")
                    st.caption(f"产品数：{count} | 竞争度：{competition_level}")
                with col_stats:
                    c1, c2, c3 = st.columns(3)
                    c1.metric("平均价格", f"${avg_price:.2f}")
                    c2.metric("平均评分", f"{avg_rating:.1f}")
                    c3.metric("蓝海指数", f"{blue_ocean}/10")

        # ---- 竞争热度矩阵 ----
        if len(valid_markets) >= 2:
            st.divider()
            st.subheader("📊 竞争热度矩阵")

            # 构建矩阵数据
            matrix_data = []
            for m in valid_markets:
                pf_name = PLATFORMS.get(m["platform"], {}).get("name", m["platform"])
                region_name = m.get("region_name", m["region"].upper())
                count = m.get("product_count", 0)
                avg_price = m.get("avg_price", 0)

                if count >= 15:
                    demand = "high"
                elif count >= 8:
                    demand = "medium"
                else:
                    demand = "low"

                if avg_price >= 30:
                    margin = "high"
                elif avg_price >= 15:
                    margin = "medium"
                else:
                    margin = "low"

                matrix_data.append({
                    "平台": pf_name,
                    "地区": region_name,
                    "产品数": count,
                    "平均价格": f"${avg_price:.2f}",
                    "需求热度": {"high": "🟢 高", "medium": "🟡 中", "low": "🔴 低"}[demand],
                    "利润空间": {"high": "🟢 高", "medium": "🟡 中", "low": "🔴 低"}[margin],
                })

            df_matrix = pd.DataFrame(matrix_data)
            st.dataframe(df_matrix, width="stretch", hide_index=True)

        # ---- 可视化图表（Spec 34 增强市场扫描） ----
        if len(valid_markets) >= 2:
            st.divider()
            st.subheader("📈 市场机会可视化")
            import plotly.express as px

            chart_rows = []
            for m in valid_markets:
                pf_name = PLATFORMS.get(m["platform"], {}).get("name", m["platform"])
                region_name = m.get("region_name", m["region"].upper())
                chart_rows.append({
                    "市场": f"{pf_name} {region_name}",
                    "蓝海指数": m.get("blue_ocean_score", 0) or 0,
                    "产品数": m.get("product_count", 0),
                    "平均价格": m.get("avg_price", 0) or 0,
                    "平均评分": m.get("avg_rating", 0) or 0,
                    "竞争度": m.get("competition_level", "unknown"),
                })
            cdf = pd.DataFrame(chart_rows)

            c1, c2 = st.columns(2)
            with c1:
                # 蓝海指数排行柱状图
                ranked_cdf = cdf.sort_values("蓝海指数", ascending=True)
                fig = px.bar(ranked_cdf, x="蓝海指数", y="市场", orientation="h",
                             title="蓝海指数排行", color="蓝海指数",
                             color_continuous_scale="Viridis")
                fig.update_layout(height=max(300, len(ranked_cdf) * 28),
                                  margin=dict(l=20, r=20, t=40, b=20), yaxis_title="")
                st.plotly_chart(fig, width="stretch")
            with c2:
                # 竞争程度分布饼图
                comp_count = cdf["竞争度"].value_counts().reset_index()
                comp_count.columns = ["竞争度", "市场数"]
                fig = px.pie(comp_count, names="竞争度", values="市场数",
                             title="竞争程度分布")
                fig.update_layout(height=300, margin=dict(l=20, r=20, t=40, b=20))
                st.plotly_chart(fig, width="stretch")

            # 价格 vs 蓝海指数散点图
            price_cdf = cdf[cdf["平均价格"] > 0]
            if not price_cdf.empty:
                fig = px.scatter(price_cdf, x="平均价格", y="蓝海指数", size="产品数",
                                 hover_name="市场", title="价格 vs 蓝海指数（气泡=产品数）",
                                 color="蓝海指数", color_continuous_scale="Plasma")
                fig.update_layout(height=300, margin=dict(l=20, r=20, t=40, b=20))
                st.plotly_chart(fig, width="stretch")

        # ---- 跨市场 AI 分析 ----
        if len(valid_markets) >= 2 and api_ok:
            st.divider()
            st.subheader("🤖 AI 跨市场分析")
            st.caption("基于扫描数据，AI 给出最佳市场推荐和入场策略")

            if st.button("🔍 生成 AI 分析报告", key="scan_ai_btn", type="primary"):
                with st.status("AI 正在分析...", expanded=False) as status:
                    from src.analyzer import analyze_market_comparison
                    report = analyze_market_comparison(keyword, valid_markets)
                    st.session_state.scan_report = report
                    status.update(label="✅ AI 分析完成！", state="complete")
                st.rerun()

        # 展示 AI 报告
        report = st.session_state.get("scan_report")
        if report and report.get("success"):
            best = report.get("best_market", {})
            if best:
                pf = best.get("platform", "")
                rg = best.get("region", "")
                pf_name = PLATFORMS.get(pf, {}).get("name", pf)
                st.info(f"🏆 **最佳市场推荐：** {PLATFORMS.get(pf, {}).get('icon', '')} {pf_name} {rg.upper()} — {best.get('reason', '')}")

            # Top 3 机会
            top3 = report.get("top3_opportunities", [])
            if top3:
                cols = st.columns(min(len(top3), 3))
                for i, opp in enumerate(top3[:3]):
                    with cols[i]:
                        pf = opp.get("platform", "")
                        rg = opp.get("region", "")
                        pf_name = PLATFORMS.get(pf, {}).get("name", pf)
                        score = opp.get("blue_ocean_score", 0)
                        with st.container(border=True):
                            st.markdown(f"**#{opp.get('rank', i+1)} {PLATFORMS.get(pf, {}).get('icon', '')} {pf_name} {rg.upper()}**")
                            st.metric("蓝海指数", f"{score}/10")
                            st.caption(opp.get("reason", ""))

            # 入场策略
            strategy = report.get("entry_strategy", "")
            if strategy:
                st.markdown(f"**💡 入场策略：** {strategy}")

            # 风险因素
            risks = report.get("risk_factors", [])
            if risks:
                with st.expander("风险因素", expanded=False):
                    for risk in risks:
                        st.caption(f"• {risk}")

        elif report and not report.get("success"):
            st.warning(f"⚠️ AI 分析失败：{report.get('error', '未知错误')}")

        # ---- 预测与回顾（基于历史数据） ----
        st.divider()
        st.subheader("📈 趋势预测与时间回顾")
        st.caption("基于数据库中的历史数据，分析产品的价格/排名/评论变化趋势")

        all_products = get_all_products()
        if all_products:
            unique_titles = sorted({p.get("title", "") for p in all_products if p.get("title")})
            if unique_titles:
                selected_title = st.selectbox(
                    "选择产品查看趋势",
                    options=unique_titles,
                    format_func=lambda t: t[:50],
                    key="scan_trend_select",
                )

                if selected_title:
                    trend_data = get_trend_data(title=selected_title)

                    if trend_data and len(trend_data) >= 2:
                        # 时间回顾
                        retro = build_retrospective(trend_data)
                        if retro.get("price"):
                            st.markdown(f"**📅 回顾周期：** {retro['period']}（{retro['data_points']} 个数据点）")
                            c1, c2, c3 = st.columns(3)
                            with c1:
                                p = retro["price"]
                                st.metric("价格变化", f"${p['end']:.2f}", delta=f"{p['change_pct']:+.1f}%")
                            with c2:
                                r = retro.get("rank", {})
                                if r:
                                    st.metric("排名变化", f"#{r['end']}", delta=f"{r['change']:+d} 位")
                            with c3:
                                rv = retro.get("reviews", {})
                                if rv:
                                    st.metric("评论增长", f"+{rv['growth']}", delta=f"{rv['growth_rate']:.0f}/天")

                        # 趋势预测
                        prediction = predict_trend(trend_data)
                        if prediction.get("prediction"):
                            confidence = prediction.get("confidence", "low")
                            conf_label = {"high": "🟢 高置信", "medium": "🟡 中置信", "low": "🔴 低置信"}[confidence]
                            st.info(f"📈 **趋势预测：** {prediction['prediction']}（{conf_label}）")

                        # 价格趋势图
                        import plotly.graph_objects as go
                        df_trend = pd.DataFrame(trend_data)
                        df_trend["scrape_time"] = pd.to_datetime(df_trend["scrape_time"])

                        fig = go.Figure()
                        fig.add_trace(go.Scatter(
                            x=df_trend["scrape_time"],
                            y=pd.to_numeric(df_trend["price"], errors="coerce"),
                            mode="lines+markers",
                            name="价格",
                            line=dict(color="#FF5E00", width=2),
                        ))
                        fig.update_layout(
                            title="价格变化趋势",
                            xaxis_title="时间",
                            yaxis_title="价格 (USD)",
                            height=300,
                            margin=dict(l=40, r=20, t=40, b=40),
                        )
                        st.plotly_chart(fig, width="stretch")
                    else:
                        st.info("该产品历史数据不足（至少需要 2 次抓取记录），请先运行实时选品或指定选品。")
        else:
            st.info("暂无历史数据。请先在「实时选品」或「指定选品」页面运行一次分析。")

        # ---- 重新扫描 ----
        st.divider()
        if st.button("🔄 重新扫描", key="scan_retry_btn"):
            st.session_state.scan_step = "idle"
            st.session_state.scan_results = None
            st.session_state.scan_report = None
            st.rerun()

    # ---- 空闲状态 ----
    elif st.session_state.get("scan_step", "idle") == "idle":
        st.info(
            "👈 输入关键词，选择平台和地区，点击「开始扫描」：\n\n"
            "1. 🔍 输入英文产品关键词\n"
            "2. 🛒 选择要扫描的平台\n"
            "3. 🌍 选择要扫描的地区\n"
            "4. 🌐 点击「开始扫描」\n\n"
            "**热门品类参考：** portable blender, cat toys, yoga mat, "
            "kitchen organizer, phone case, LED strip lights"
        )





def _render_hot_aggregation_mode(api_ok: bool):
    """热销聚合模式 — 扫描常用平台/地区的热销榜单，发现爆款趋势。"""
    st.markdown("### 🔥 热销聚合模式")
    st.markdown("基于你常用的平台和地区，聚合热销榜单发现跨市场爆款。")

    with st.container(border=True):
        # 自动推荐常用平台/地区（基于上次选择或默认）
        last_platforms = st.session_state.get("hot_agg_platforms", ["amazon", "ebay"])
        platform_keys = get_available_platform_choices()
        platform_names = {k: f"{PLATFORMS[k]['icon']} {PLATFORMS[k]['name']}" for k in platform_keys}

        _agg_label = "🛒 聚合平台（目前仅 Amazon 可用）" if len(platform_keys) < 2 else "🛒 聚合平台（建议 2-4 个）"
        selected_platforms = st.multiselect(
            _agg_label,
            options=platform_keys,
            default=[p for p in last_platforms if p in platform_keys] or platform_keys[:2],
            format_func=lambda k: platform_names[k],
            key="hot_agg_platforms_select",
        )
        st.session_state.hot_agg_platforms = selected_platforms

        # 地区选择（限制在常用地区）
        all_regions = set()
        for pf in selected_platforms:
            pf_info = get_platform_info(pf)
            for rk in pf_info.get("regions", {}).keys():
                all_regions.add(rk)
        region_options = sorted(all_regions)
        region_labels = {}
        for pf in selected_platforms:
            for rk, rv in get_platform_info(pf).get("regions", {}).items():
                label = f"{rv['name']} ({rk})"
                if label not in region_labels:
                    region_labels[rk] = label

        last_regions = st.session_state.get("hot_agg_regions", region_options[:3])
        selected_regions = st.multiselect(
            "🌍 聚合地区（建议 2-5 个，过多会耗时）",
            options=region_options,
            default=[r for r in last_regions if r in region_options] or region_options[:3],
            format_func=lambda k: region_labels.get(k, k.upper()),
            key="hot_agg_regions_select",
        )
        st.session_state.hot_agg_regions = selected_regions

        # 返回热门产品数
        top_n = st.number_input(
            "返回热门产品数",
            min_value=10, max_value=50, value=20, step=10,
            help="聚合后展示热度最高的前 N 个产品",
        )

        save_to_db = st.checkbox(
            "扫描后保存到数据库",
            value=False,
            help="把抓取的产品存入 products 表（供历史记录查看）",
        )

        combo_count = len(selected_platforms) * len(selected_regions)
        if combo_count > 0:
            est_seconds = combo_count * 30
            st.caption(f"⏱️ 预估耗时：{combo_count} 个市场 × ~30秒 ≈ {est_seconds // 60} 分钟")

        scan_clicked = st.button(
            "🚀 开始聚合扫描",
            type="primary",
            width="stretch",
            key="hot_agg_scan_btn",
        )

    # ---- 扫描触发 ----
    if scan_clicked and selected_platforms and selected_regions:
        st.session_state.hot_agg_platforms = selected_platforms
        st.session_state.hot_agg_regions = selected_regions
        st.session_state.hot_agg_top_n = top_n
        st.session_state.hot_agg_save_db = save_to_db
        st.session_state.hot_agg_step = "scanning"
        st.rerun()

    # ---- 扫描执行 ----
    if st.session_state.get("hot_agg_step") == "scanning":
        platforms = st.session_state.hot_agg_platforms
        regions = st.session_state.hot_agg_regions
        top_n = st.session_state.hot_agg_top_n
        save_to_db = st.session_state.hot_agg_save_db

        from src.regional_scanner import scan_all_regions, aggregate_hot_products

        with st.status("🌍 正在聚合扫描热销榜单...", expanded=True) as status:
            progress_bar = st.progress(0, text="准备扫描...")

            def _on_progress(done, total, label):
                pct = min(done / total, 1.0) if total > 0 else 0
                progress_bar.progress(pct, text=f"扫描进度：{done}/{total} — {label}")

            # 扫描选定平台的全部地区热销榜，再按选定地区过滤
            scan_result = scan_all_regions(platforms=platforms, progress_callback=_on_progress)
            all_products = scan_result.get("products", [])
            if regions:
                all_products = [p for p in all_products if p.get("region") in regions]

            ranked = aggregate_hot_products(all_products, top_n=top_n)

            progress_bar.empty()
            status.update(
                label=f"✅ 聚合完成（{len(all_products)} 个产品 → {len(ranked)} 个热门）",
                state="complete",
            )

        # 可选保存到数据库
        if save_to_db and all_products:
            try:
                from collections import defaultdict
                groups = defaultdict(list)
                for p in all_products:
                    key = (p.get("platform", "amazon"), p.get("region", "us"), p.get("currency", "USD"))
                    groups[key].append(p)
                saved_total = 0
                for (pf, rg, cur), plist in groups.items():
                    saved_total += save_products(
                        plist, [{}] * len(plist),
                        source=f"hot_agg_{pf}_{rg}", platform=pf, region=rg, currency=cur,
                    )
                st.success(f"💾 已保存 {saved_total} 条到数据库")
            except Exception as e:
                st.warning(f"保存数据库失败：{e}")

        st.session_state.hot_agg_step = "done"
        st.session_state.hot_agg_results = ranked
        st.rerun()

    # ---- 结果展示 ----
    if st.session_state.get("hot_agg_step") == "done":
        ranked = st.session_state.get("hot_agg_results", [])
        if not ranked:
            st.info("未找到热门产品。请尝试调整平台/地区选择。")
            return

        st.markdown(f"### 🏆 Top {len(ranked)} 热门产品")
        st.caption("按热度评分排序 = 上榜地区数 × 10 + log10(累计评论数) × 5")

        # 构建展示数据
        display_data = []
        for item in ranked:
            sample = item.get("sample", {})
            display_data.append({
                "排名": len(display_data) + 1,
                "产品": item.get("title", "")[:40],
                "热度": item.get("hotness", 0),
                "上榜地区数": item.get("region_count", 0),
                "平台": ", ".join(item.get("platforms", [])),
                "参考价": f"${sample.get('price', 0):.2f}" if sample.get("price") else "-",
            })

        import pandas as pd
        df = pd.DataFrame(display_data)
        st.dataframe(df, width="stretch", hide_index=True)

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
    tab_list, tab_fav = st.tabs([
        "📚 分析记录", "⭐ 已收藏"
    ])

    with tab_list:
        _render_history_list(total_count)

    with tab_fav:
        _render_favorites_tab()




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
    # 来自 Dashboard 的跳转：自动展开并定位产品
    goto_title = st.session_state.pop("goto_product", None)
    goto_idx = None
    if goto_title:
        for idx, p in enumerate(products):
            if p.get("title", "") == goto_title:
                goto_idx = idx
                break

    with st.expander("单条记录详情", expanded=goto_idx is not None):
        default_idx = goto_idx if goto_idx is not None else 0
        selected_idx = st.selectbox(
            "选择产品",
            options=range(len(products)),
            index=min(default_idx, len(products) - 1) if products else 0,
            format_func=lambda i: f"#{i+1} {(products[i].get('title', '') or '')[:45]}",
            help="选择产品查看详情分析",
            key="history_detail_select",
        )
        if selected_idx is not None:
            p = products[selected_idx]
            a = p.get("analysis", {})

            # 基本信息
            verdict = a.get("final_verdict", "")
            verdict_label = {"recommended": "🟢 推荐", "cautious": "🟡 谨慎", "not_recommended": "🔴 不推荐"}.get(verdict, verdict)
            st.markdown(f"**{verdict_label}** — {a.get('verdict_reason', '无判定理由')}")

            # 六维度评分
            dim_cols = st.columns(len(ANALYSIS_DIMS))
            for col, (label, key) in zip(dim_cols, ANALYSIS_DIMS):
                dim = a.get(key, {})
                score = dim.get("score", "-") if isinstance(dim, dict) else "-"
                reason = dim.get("reason", "") if isinstance(dim, dict) else ""
                with col:
                    st.metric(label, f"{score}/10")
                    if reason:
                        st.caption(reason)

            # 新手起步清单（仅推荐产品显示 — 回答新手"看完数据然后呢"）
            if verdict == "recommended":
                st.markdown("")
                st.markdown("##### 🚀 新手起步清单")
                st.caption("决定做这个产品？按这个顺序走，少踩坑：")
                st.markdown(
                    "1. **找货源**：去 1688 搜同类产品，对比 AI 估算的采购价（¥"
                    f"{a.get('estimated_cost_cny') or '?'}）和真实报价\n"
                    "2. **算清首单成本**：采购价 × 起订量 + 头程运费 + 平台开店费\n"
                    "3. **小批量试单**：先拿 20-50 件试水，验证市场反应再加大\n"
                    "4. **准备 Listing**：拍产品图、写标题和五点描述（参考这个品的卖点）"
                )
            # 原始 JSON（折叠查看）
            with st.expander("查看原始 JSON", expanded=False):
                st.json(a)

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
                if st.button("🗑️", key=f"del_fav_{i}", help="取消收藏"):
                    remove_favorite(title, platform)
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

                    cols = st.columns(len(ANALYSIS_DIMS))
                    for col, (label, key) in zip(cols, ANALYSIS_DIMS):
                        dim = analysis.get(key, {})
                        score = dim.get("score", "-") if isinstance(dim, dict) else "-"
                        with col:
                            st.metric(label, f"{score}/10")


# ============================================================
# 原有辅助函数
# ============================================================

