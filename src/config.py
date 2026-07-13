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
        "models": ["mimo-v2.5", "mimo-v2.5-pro"],
        "default_model": "mimo-v2.5",
    },
    "glm": {
        "name": "智谱 GLM",
        "base_url_key": "GLM_BASE_URL",
        "api_key_key": "GLM_API_KEY",
        "models": ["glm-5.2", "glm-4-plus", "glm-4-flash"],
        "default_model": "glm-5.2",
    },
}


def _safe_int(value, default: int) -> int:
    """安全转换为 int，失败时返回默认值。"""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


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
    except Exception as e:
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
    provider = _get_secret("ACTIVATE_PROVIDER", "glm")
    if provider not in LLM_PROVIDERS:
        provider = "glm"

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
    except Exception as e:
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
        # AI 分析批次大小（Spec 16）
        "analysis_batch_size": _safe_int(_get_secret("ANALYSIS_BATCH_SIZE", "6"), 6),
    }


# ============================================================
# 利润计算默认参数（多平台支持）
# ============================================================

def get_profit_defaults(platform_key: str = None) -> dict:
    """
    返回利润计算的默认参数（支持多平台）。

    优先从平台注册表读取各平台默认参数，
    环境变量可覆盖（向后兼容）。

    Args:
        platform_key: 平台标识，如 "amazon"。
                     None 时回退到环境变量（向后兼容旧代码）。

    Returns:
        {
            "exchange_rate": float,      # 汇率
            "commission_pct": float,     # 佣金比例（0-1）— Amazon
            "ad_pct": float,             # 广告预算占比（0-1）— Amazon
            "shipping_cny": float,       # 头程运费（人民币/件）
            "procurement_cny": float,    # 采购成本（人民币/件），默认 0
            ... 其他平台特有参数
        }
    """
    # 尝试从平台注册表读取
    if platform_key:
        try:
            from .platforms import PLATFORMS
            if platform_key in PLATFORMS:
                pf = PLATFORMS[platform_key]
                region = pf["regions"][pf["default_region"]]
                profit_defaults = pf.get("profit_defaults", {})
                result = {
                    "exchange_rate": region["exchange_rate"],
                    "procurement_cny": 0.0,
                }
                result.update(profit_defaults)
                return result
        except (ImportError, KeyError):
            pass

    # 回退：环境变量（向后兼容）
    return {
        "exchange_rate": float(_get_secret("PROFIT_EXCHANGE_RATE", "7.24")),
        "commission_pct": float(_get_secret("PROFIT_COMMISSION_PCT", "0.15")),
        "ad_pct": float(_get_secret("PROFIT_AD_PCT", "0.10")),
        "shipping_cny": float(_get_secret("PROFIT_SHIPPING_CNY", "15.0")),
        "procurement_cny": 0.0,
    }


# ============================================================
# Scrapling 抓取引擎配置
# ============================================================

def get_scrapling_config() -> dict:
    """
    获取 Scrapling 抓取引擎配置。

    Returns:
        {
            "proxy": str | None,        # 代理地址
            "browser_timeout": int,     # 浏览器超时（毫秒）
            "adaptive_db": str,         # 自适应存储数据库路径
            "strategy": str,            # 抓取策略：fetcher_first / stealth_only / dynamic_only
        }
    """
    return {
        "proxy": _get_secret("SCRAPLING_PROXY", "") or None,
        "browser_timeout": int(_get_secret("SCRAPLING_BROWSER_TIMEOUT", "30000")),
        "adaptive_db": _get_secret(
            "SCRAPLING_ADAPTIVE_DB",
            os.path.join(_PROJECT_ROOT, "data", "adaptive_elements.db"),
        ),
        "strategy": _get_secret("SCRAPLING_STRATEGY", "fetcher_first"),
    }