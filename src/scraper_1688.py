"""
1688 比价模块 — 搜索 1688 获取参考采购价。

反爬风险较高（JS 动态渲染 + IP 限制），
采用"尝试 → 失败降级"策略：
    1. 使用 requests 尝试抓取搜索结果
    2. 失败时返回友好提示，不影响主流程

用法：
    from src.scraper_1688 import search_1688
    result = search_1688("water bottle")
"""

import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

# 请求间隔（秒），避免触发 1688 反爬
_REQUEST_DELAY = 3

# 真实浏览器 User-Agent
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


def search_1688(keyword: str, max_results: int = 3) -> dict:
    """
    在 1688 上搜索产品，返回价格区间。

    Args:
        keyword:     搜索关键词（通常为产品标题的前 30 字）
        max_results: 最多返回几个结果

    Returns:
        {
            "success": bool,
            "keyword": str,
            "results": [{"title": str, "price": float, "moq": str}],
            "price_range": {"min": float, "max": float} | None,
            "error": str | None,
        }
    """
    if not keyword or not keyword.strip():
        return {
            "success": False,
            "keyword": keyword,
            "results": [],
            "price_range": None,
            "error": "搜索关键词为空",
        }

    keyword = keyword.strip()[:50]  # 限制长度

    # 请求间隔
    time.sleep(_REQUEST_DELAY)

    try:
        url = f"https://s.1688.com/selloffer/offer_search.htm?keywords={keyword}"
        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

        resp = requests.get(url, headers=headers, timeout=15)

        # 检查响应
        if resp.status_code != 200:
            return {
                "success": False,
                "keyword": keyword,
                "results": [],
                "price_range": None,
                "error": f"1688 返回状态码 {resp.status_code}，可能被反爬拦截",
            }

        # 检查是否被重定向到登录页
        if "login" in resp.url.lower() or "passport" in resp.url.lower():
            return {
                "success": False,
                "keyword": keyword,
                "results": [],
                "price_range": None,
                "error": "1688 要求登录，暂时无法自动获取",
            }

        # 尝试解析 HTML
        soup = BeautifulSoup(resp.text, "html.parser")

        # 1688 搜索结果的多种选择器
        results = []

        # 尝试方案 1：直接解析搜索结果卡片
        cards = soup.select(
            ".sm-offer-item, .offer-list-row, "
            "[class*='offer-item'], [class*='card-container']"
        )

        for card in cards[:max_results]:
            title_el = card.select_one(
                "[class*='title'], [class*='subject'], "
                "a[href*='detail.1688.com']"
            )
            price_el = card.select_one(
                "[class*='price'], [class*='price-element']"
            )
            moq_el = card.select_one(
                "[class*='quantity'], [class*='moq']"
            )

            if title_el and price_el:
                title_text = title_el.get_text(strip=True)[:80]
                price_text = price_el.get_text(strip=True)
                price = _extract_price(price_text)
                moq = moq_el.get_text(strip=True) if moq_el else ""

                if price and price > 0:
                    results.append({
                        "title": title_text,
                        "price": price,
                        "moq": moq,
                    })

        # 尝试方案 2：从页面 JSON 数据中提取
        if not results:
            scripts = soup.find_all("script")
            for script in scripts:
                text = script.string or ""
                # 查找包含价格信息的 JSON 片段
                price_matches = re.findall(r'"price"[:\s]*"?([\d.]+)"?', text)
                title_matches = re.findall(r'"subject"[:\s]*"([^"]+)"', text)
                if price_matches and title_matches:
                    for i in range(min(len(price_matches), len(title_matches), max_results)):
                        try:
                            results.append({
                                "title": title_matches[i][:80],
                                "price": float(price_matches[i]),
                                "moq": "",
                            })
                        except (ValueError, IndexError):
                            continue

        if results:
            prices = [r["price"] for r in results]
            return {
                "success": True,
                "keyword": keyword,
                "results": results,
                "price_range": {
                    "min": round(min(prices), 2),
                    "max": round(max(prices), 2),
                },
                "error": None,
            }
        else:
            # 解析成功但无结果
            return {
                "success": False,
                "keyword": keyword,
                "results": [],
                "price_range": None,
                "error": (
                    "未在 1688 搜索结果中找到价格信息。"
                    "1688 页面为 JS 动态渲染，部分数据可能无法通过请求获取。"
                    f"建议手动搜索：https://s.1688.com/selloffer/offer_search.htm?keywords={keyword}"
                ),
            }

    except requests.Timeout:
        return {
            "success": False,
            "keyword": keyword,
            "results": [],
            "price_range": None,
            "error": "请求超时，1688 服务器响应过慢",
        }
    except requests.RequestException as e:
        return {
            "success": False,
            "keyword": keyword,
            "results": [],
            "price_range": None,
            "error": f"网络请求失败：{str(e)[:50]}",
        }
    except Exception as e:
        return {
            "success": False,
            "keyword": keyword,
            "results": [],
            "price_range": None,
            "error": f"解析失败：{str(e)[:50]}",
        }


def _extract_price(text: str) -> Optional[float]:
    """从价格文本中提取数字。"""
    if not text:
        return None
    # 匹配 ¥12.50 或 12.50 或 12-15 等格式
    match = re.search(r'(\d+\.?\d*)', text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return None
