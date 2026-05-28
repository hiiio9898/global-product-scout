"""
配置模块 — 支持双源加载：优先 Streamlit secrets，回退 .env 文件。

在本地开发时使用 .env 文件（python-dotenv），
部署到 Streamlit Cloud 时自动使用 Settings → Secrets 中的配置。

多模型支持：
    通过 ACTIVATE_PROVIDER + ACTIVATE_MODEL 选择供应商和模型，
    各供应商独立配置 API_KEY + BASE_URL。
"""

import os
from dotenv import load_dotenv

# 加载 .env 文件（本地开发用，云端用 st.secrets）
load_dotenv()

# 项目根目录（用于拼接 DB 等相对路径）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ============================================================
# AI 供应商注册表
# ============================================================

LLM_PROVIDERS = {
    "deepseek": {
        "name": "DeepSeek",
        "base_url_key": "DEEPSEEK_BASE_URL",
        "api_key_key": "DEEPSEEK_API_KEY",
        "models": ["deepseek-v4-flash", "deepseek-v4-pro"],
        "default_model": "deepseek-v4-flash",
    },
    "mimo": {
        "name": "小米 MiMo",
        "base_url_key": "MIMO_BASE_URL",
        "api_key_key": "MIMO_API_KEY",
        "models": ["mimo-v2.5-pro", "mimo-v2-pro"],
        "default_model": "mimo-v2.5-pro",
    },
    "openai": {
        "name": "OpenAI",
        "base_url_key": "OPENAI_BASE_URL",
        "api_key_key": "OPENAI_API_KEY",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"],
        "default_model": "gpt-4o-mini",
    },
}


def _get_secret(key: str, default: str = "") -> str:
    """
    读取配置项，优先级：st.secrets > os.environ（.env）。

    在 Streamlit 环境中运行时，先尝试从 st.secrets 读取；
    不具备 Streamlit 运行环境（如测试、命令行脚本）时，
    静默回退到进程环境变量（包含 .env 加载的内容）。
    """
    try:
        import streamlit as st
        # st.secrets 可能不存在（未在 Streamlit 上下文中），
        # 也可能不包含该 key，两种情况都静默回退。
        if hasattr(st, "secrets") and st.secrets:
            value = st.secrets.get(key)
            if value is not None:
                return str(value)
    except (ImportError, RuntimeError, Exception):
        pass
    # 回退：os.environ（.env 或系统环境变量）
    return os.getenv(key, default)


def get_llm_config() -> dict:
    """
    获取当前激活的 LLM 供应商配置。

    读取 ACTIVATE_PROVIDER 环境变量确定供应商，
    读取 ACTIVATE_MODEL 环境变量确定模型，
    自动拼接对应的 API_KEY 和 BASE_URL。

    优先读取 st.session_state 中的 UI 选择（侧边栏切换），
    然后回退到环境变量。

    Returns:
        {
            "provider": str,          # 供应商标识，如 "deepseek"
            "provider_name": str,     # 显示名称，如 "DeepSeek"
            "model": str,             # 模型名，如 "deepseek-v4-flash"
            "api_key": str,           # API Key
            "base_url": str,          # API Base URL
            "configured": bool,       # 是否已配置（api_key 非空）
        }
    """
    # 1. 读取供应商
    provider = _get_secret("ACTIVATE_PROVIDER", "deepseek")
    if provider not in LLM_PROVIDERS:
        provider = "deepseek"

    provider_info = LLM_PROVIDERS[provider]

    # 2. 读取 API Key 和 Base URL
    api_key = _get_secret(provider_info["api_key_key"], "")
    base_url = _get_secret(provider_info["base_url_key"], "")

    # 3. 读取模型（优先 session_state UI 选择）
    model = provider_info["default_model"]
    try:
        import streamlit as st
        if hasattr(st, "session_state"):
            if "llm_model" in st.session_state and st.session_state.llm_model:
                selected_model = st.session_state.llm_model
                if selected_model in provider_info["models"]:
                    model = selected_model
            # 如果用户在 UI 切换了供应商，覆盖环境变量
            if "llm_provider" in st.session_state and st.session_state.llm_provider:
                ui_provider = st.session_state.llm_provider
                if ui_provider in LLM_PROVIDERS:
                    provider = ui_provider
                    provider_info = LLM_PROVIDERS[provider]
                    api_key = _get_secret(provider_info["api_key_key"], "")
                    base_url = _get_secret(provider_info["base_url_key"], "")
    except (ImportError, RuntimeError, Exception):
        pass

    # 4. 如果没有 session_state，读取 ACTIVATE_MODEL 环境变量
    if model == provider_info["default_model"]:
        env_model = _get_secret("ACTIVATE_MODEL", "")
        if env_model and env_model in provider_info["models"]:
            model = env_model

    return {
        "provider": provider,
        "provider_name": provider_info["name"],
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
        "configured": bool(api_key),
    }


def get_config() -> dict:
    """
    读取全部配置项，返回字典（向后兼容）。

    优先级：
        1. Streamlit Cloud secrets（st.secrets）
        2. 进程环境变量（本地 .env 文件通过 python-dotenv 加载）

    Keys:
        deepseek_api_key, deepseek_model, scrape_delay,
        amazon_url, database_path
    """
    return {
        # DeepSeek API（向后兼容，daily_scrape.py 仍在使用）
        "deepseek_api_key": _get_secret("DEEPSEEK_API_KEY", ""),
        "deepseek_model": _get_secret("DEEPSEEK_MODEL", "deepseek-chat"),
        # 抓取配置
        "scrape_delay": float(_get_secret("SCRAPE_DELAY_SECONDS", "2")),
        "amazon_url": _get_secret(
            "AMAZON_BEST_SELLERS_URL",
            "https://www.amazon.com/Best-Sellers/zgbs/",
        ),
        # 数据库配置
        "database_path": _get_secret(
            "DATABASE_PATH",
            os.path.join(_PROJECT_ROOT, "data", "products.db"),
        ),
    }


# ============================================================
# 利润计算默认参数
# ============================================================

def get_profit_defaults() -> dict:
    """
    返回利润计算的默认参数。

    用户可在侧边栏修改这些值，修改后存入 st.session_state。
    计算器模块 calculator.py 使用这些参数进行利润计算。

    Returns:
        {
            "exchange_rate": float,      # 汇率 CNY/USD
            "commission_pct": float,     # 亚马逊佣金比例（0-1）
            "ad_pct": float,             # 广告预算占比（0-1）
            "shipping_cny": float,       # 头程运费（人民币/件）
            "procurement_cny": float,    # 采购成本（人民币/件），默认 0（需用户填写）
        }
    """
    return {
        "exchange_rate": float(_get_secret("PROFIT_EXCHANGE_RATE", "7.24")),
        "commission_pct": float(_get_secret("PROFIT_COMMISSION_PCT", "0.15")),
        "ad_pct": float(_get_secret("PROFIT_AD_PCT", "0.10")),
        "shipping_cny": float(_get_secret("PROFIT_SHIPPING_CNY", "15.0")),
        "procurement_cny": 0.0,
    }
