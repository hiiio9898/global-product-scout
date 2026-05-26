"""
工具函数模块 - 提供通用辅助功能。
"""


def format_number(num: int) -> str:
    """将大数字格式化为易读形式，如 12345 -> "12.3k"。"""
    if num >= 1_000_000:
        return f"{num / 1_000_000:.1f}M"
    if num >= 1_000:
        return f"{num / 1_000:.1f}k"
    return str(num)
