"""
UI 共享常量 — 页面版本、verdict 映射、分析维度等。
"""

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
    ("🌱 长期持久力", "longevity"),
]

# 长青度四档徽章（longevity.label → 展示文案）。unknown/缺失不显示。
LONGEVITY_LABEL_MAP = {
    "evergreen": "🟢 长青",
    "trending_up": "🟡 趋势",
    "fad": "🔴 爆品",
    "declining": "📉 夕阳",
}
