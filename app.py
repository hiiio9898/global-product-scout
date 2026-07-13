"""
Streamlit 主程序入口 — 外贸 AI 选品助手（Global Product Scout）。

提供"数据获取 → AI 分析 → 结果展示"一站式选品体验。
数据源采用两级策略：优先实时抓取 → 失败时降级到 data/products.json。

页面渲染逻辑已拆分到 src/ui/ 子包，本文件仅负责：
    1. 页面配置（set_page_config + CSS）
    2. Session State 初始化
    3. 数据库初始化
    4. 侧边栏渲染 + 页面路由

用法：
    streamlit run app.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st

from src.database import init_db
from src.ui.sidebar import render_sidebar
from src.ui.pages import (
    _render_dashboard_page,
    _render_live_page,
    _render_targeted_page,
    _render_market_scanner_page,
    _render_history_page,
)


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
# Session State 初始化
# ============================================================

if "products" not in st.session_state:
    st.session_state.products = []
if "results" not in st.session_state:
    st.session_state.results = []
if "source_info" not in st.session_state:
    st.session_state.source_info = None
if "step" not in st.session_state:
    st.session_state.step = "idle"
if "analyzing" not in st.session_state:
    st.session_state.analyzing = False
if "history_data" not in st.session_state:
    st.session_state.history_data = []

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
elif "市场扫描" in page:
    _render_market_scanner_page(api_ok)
elif "历史记录" in page:
    _render_history_page()
