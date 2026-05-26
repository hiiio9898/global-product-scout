"""
配置模块 - 使用 python-dotenv 加载 .env 文件，提供全局配置访问。
"""

import os
from dotenv import load_dotenv

load_dotenv()

# 项目根目录（用于拼接默认相对路径）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_config() -> dict:
    """读取环境变量，返回配置字典。包含 API、抓取、数据库等全部配置。"""
    return {
        # DeepSeek API
        "deepseek_api_key": os.getenv("DEEPSEEK_API_KEY", ""),
        "deepseek_model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        # 抓取配置
        "scrape_delay": float(os.getenv("SCRAPE_DELAY_SECONDS", "2")),
        "amazon_url": os.getenv(
            "AMAZON_BEST_SELLERS_URL",
            "https://www.amazon.com/Best-Sellers/zgbs/",
        ),
        # 数据库配置
        "database_path": os.getenv(
            "DATABASE_PATH",
            os.path.join(_PROJECT_ROOT, "data", "products.db"),
        ),
    }
