"""
侧边栏 — API 配置、模型切换、数据源显示。
"""

from __future__ import annotations

import streamlit as st

from src.config import get_llm_config, LLM_PROVIDERS, _get_secret
from src.database import get_product_count
from src.platforms import (
    PLATFORMS,
    get_available_platform_choices,
    get_platform_info,
    get_region_choices,
)

def render_sidebar(source_info: dict | None = None):
    """渲染侧边栏 — 页面导航和数据源状态。"""
    st.sidebar.title("🌍 Global Product Scout")

    # ---- 页面导航 ----
    # 新手引导：标注主功能 vs 进阶（不改 radio 选项值，保持与 _navigate_to 跳转兼容）
    st.sidebar.markdown("📍 **常用**：今日推荐 / 抓取选品 / 我的选品")
    page = st.sidebar.radio(
        "导航",
        options=["Dashboard", "实时选品", "指定选品", "市场扫描", "历史记录"],
        key="nav_page",
        help="新手从「Dashboard」开始\n实时选品：抓取热销榜做分析\n指定选品/市场扫描：进阶功能\n历史记录：看历史和收藏",
    )
    st.sidebar.caption("💡 进阶：「指定选品」「市场扫描」")

    st.sidebar.divider()

    # ---- 平台 + 地区联动选择器（仅实时/指定选品页显示） ----
    if "实时选品" in page or "指定选品" in page:
        st.sidebar.subheader("平台选择")

        # 平台选择
        platform_keys = get_available_platform_choices()
        platform_names = {
            k: get_platform_info(k)['name']
            for k in platform_keys
        }

        # 从 session_state 恢复，默认 amazon
        last_platform = st.session_state.get("active_platform", "amazon")
        if last_platform not in platform_keys:
            last_platform = "amazon"

        selected_platform = st.sidebar.selectbox(
            "选择平台",
            options=platform_keys,
            format_func=lambda k: platform_names[k],
            index=platform_keys.index(last_platform),
            key="selected_platform",
        )

        # 标注不可用平台（让用户知道为何只剩 Amazon，自维护）
        _unavailable = [
            PLATFORMS[k]["name"]
            for k in get_available_platform_choices(available_only=False)
            if not PLATFORMS[k].get("available", True)
        ]
        if _unavailable:
            st.sidebar.caption(
                f"ℹ️ {' / '.join(_unavailable)} 暂不可用（机房IP被封，免费代理访问不了）"
            )

        # 检测平台是否变化 → 重置地区到新平台默认值
        if selected_platform != last_platform:
            pf_info_new = get_platform_info(selected_platform)
            st.session_state["active_region"] = pf_info_new.get("default_region", "us")
            # 清除地区 selectbox 的 widget 状态，强制重渲染
            if "selected_region" in st.session_state:
                del st.session_state["selected_region"]

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
            "选择地区",
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
            if src in ("json", "daily_update"):
                source_label = "数据已加载"
            elif src == "live":
                source_label = "实时数据"
            else:
                source_label = "无数据"
            st.sidebar.caption(f"数据状态：{source_label}")
            if ts:
                st.sidebar.caption(f"{ts}")

    # ---- AI 模型选择器（折叠面板，大多数人只设一次） ----
    llm_cfg = get_llm_config()
    provider_info = LLM_PROVIDERS.get(llm_cfg["provider"], {})
    provider_name = provider_info.get("name", llm_cfg["provider"])
    provider_api_key = _get_secret(provider_info.get("api_key_key", ""), "")
    status_text = f"🤖 {provider_name} / {llm_cfg['model']}" if provider_api_key else f"🤖 {provider_name} — 未配置"

    with st.sidebar.expander(status_text, expanded=False):
        provider_names = {k: v["name"] for k, v in LLM_PROVIDERS.items()}
        provider_keys = list(LLM_PROVIDERS.keys())

        last_provider = st.session_state.get("llm_provider") or llm_cfg["provider"]
        last_model = st.session_state.get("llm_model") or llm_cfg["model"]

        current_provider_idx = provider_keys.index(last_provider) if last_provider in provider_keys else 0

        selected_provider = st.selectbox(
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

        st.selectbox(
            "模型",
            options=available_models,
            index=available_models.index(last_model),
            key="llm_model_select",
        )

        st.session_state["llm_provider"] = selected_provider
        st.session_state["llm_model"] = st.session_state.get("llm_model_select", last_model)

        # API 配置状态
        provider_info_cur = LLM_PROVIDERS[selected_provider]
        provider_api_key_cur = _get_secret(provider_info_cur["api_key_key"], "")
        if provider_api_key_cur:
            st.caption(f"✅ {provider_info_cur['name']} API 已配置")
        else:
            st.caption(f"⚠️ {provider_info_cur['name']} 未配置（使用模拟分析）")

    # ---- 数据库状态 ----
    count = get_product_count()
    st.sidebar.caption(f"历史记录：{count} 条产品数据")

    # ---- 汇率状态 ----
    try:
        from src.exchange_rate import get_rate_status
        rate_info = get_rate_status()
        if rate_info["age_hours"] < 24:
            st.sidebar.caption(f"💱 1 USD = {rate_info['rate']:.2f} CNY（{rate_info['age_hours']:.0f}h 前更新）")
        else:
            st.sidebar.caption(f"💱 1 USD = {rate_info['rate']:.2f} CNY（使用默认汇率）")
    except Exception:
        pass

    return llm_cfg["configured"], page


# ============================================================
# UX 辅助函数（Spec 16）
# ============================================================

