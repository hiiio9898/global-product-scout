"""
配置模块 — 支持双源加载：优先 Streamlit secrets，回退 .env 文件。

在本地开发时使用 .env 文件（python-dotenv），
部署到 Streamlit Cloud 时自动使用 Settings → Secrets 中的配置。
"""

import os
from dotenv import load_dotenv

# 加载 .env 文件（本地开发用，云端用 st.secrets）
load_dotenv()

# 项目根目录（用于拼接 DB 等相对路径）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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


def get_config() -> dict:
    """
    读取全部配置项，返回字典。

    优先级：
        1. Streamlit Cloud secrets（st.secrets）
        2. 进程环境变量（本地 .env 文件通过 python-dotenv 加载）

    Keys:
        deepseek_api_key, deepseek_model, scrape_delay,
        amazon_url, database_path
    """
    return {
        # DeepSeek API
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
