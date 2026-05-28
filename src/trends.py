"""
Google Trends 趋势查询模块 — 可选增强功能。

使用 pytrends 库查询关键词的搜索热度趋势，
判断趋势方向（上升/平稳/下降）。

注意：
    - pytrends 已归档（2025-04-17），未来可能失效
    - 频率限制：每次查询间隔 5 秒
    - 网络要求：需能访问 Google
    - 失败时返回 available=False，不影响主流程
"""

import time

# 默认间隔（秒）
_QUERY_DELAY = 5


def get_trend_direction(keyword: str) -> dict:
    """
    查询关键词的 Google Trends 趋势方向。

    Args:
        keyword: 搜索关键词（如 "water bottle"）

    Returns:
        {
            "direction": str,      # "rising" | "stable" | "declining"
            "interest": int,       # 最近一周兴趣值 (0-100)
            "avg_interest": float,  # 3 个月平均兴趣值
            "available": bool,     # 是否成功获取数据
            "error": str | None,   # 失败时的错误信息
        }
    """
    if not keyword or not keyword.strip():
        return _no_data("关键词为空")

    keyword = keyword.strip()[:50]

    try:
        from pytrends.request import TrendReq

        # 请求间隔
        time.sleep(_QUERY_DELAY)

        pytrends = TrendReq(hl="en-US", tz=360, timeout=(10, 25))
        pytrends.build_payload(
            [keyword],
            cat=0,
            timeframe="today 3-m",
            geo="US",
        )

        # 获取兴趣随时间变化的数据
        df = pytrends.interest_over_time()

        if df is None or df.empty:
            return _no_data(f"未找到 '{keyword}' 的趋势数据")

        if keyword not in df.columns:
            return _no_data(f"未找到 '{keyword}' 的趋势数据")

        values = df[keyword].values

        # 计算趋势方向
        recent = values[-4:] if len(values) >= 4 else values
        avg = float(values.mean())

        if avg == 0:
            direction = "stable"
        elif recent.mean() > avg * 1.2:
            direction = "rising"
        elif recent.mean() < avg * 0.8:
            direction = "declining"
        else:
            direction = "stable"

        return {
            "direction": direction,
            "interest": int(recent.mean()),
            "avg_interest": round(avg, 1),
            "available": True,
            "error": None,
        }

    except ImportError:
        return _no_data("pytrends 未安装，请运行: pip install pytrends")
    except Exception as e:
        error_msg = str(e)[:100]
        return _no_data(f"Google Trends 查询失败：{error_msg}")


def _no_data(error: str) -> dict:
    """返回无数据的结果。"""
    return {
        "direction": "unknown",
        "interest": 0,
        "avg_interest": 0.0,
        "available": False,
        "error": error,
    }


def get_trend_icon(direction: str) -> str:
    """将趋势方向转为图标。"""
    return {
        "rising": "📈 上升",
        "stable": "➡️ 平稳",
        "declining": "📉 下降",
    }.get(direction, "❓ 未知")
