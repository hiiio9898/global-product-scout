"""
Selenium 降级抓取模块 — 共享无头浏览器抓取功能。

当 requests 方式被反爬拦截时，使用 Selenium 绕过检测。
所有平台的 scraper 可以共享此模块进行降级抓取。

使用方式：
    from src.selenium_helper import fetch_page_html, fetch_page_soup
"""

from __future__ import annotations

import time
import random
from typing import Optional

from bs4 import BeautifulSoup


def _create_driver():
    """创建 Chrome 实例，自动下载匹配的 ChromeDriver。"""
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from webdriver_manager.chrome import ChromeDriverManager

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--lang=en-US,en")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(60)
    return driver


def fetch_page_html(url: str, wait_seconds: float = 5.0) -> Optional[str]:
    """
    使用 Selenium 获取页面 HTML 源码。

    Args:
        url:           要抓取的 URL
        wait_seconds:  页面加载后等待秒数（等待 JS 渲染）

    Returns:
        HTML 字符串，失败返回 None
    """
    driver = None
    try:
        driver = _create_driver()
        driver.get(url)
        time.sleep(wait_seconds + random.uniform(1.0, 3.0))

        # 滚动页面以触发懒加载
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 3);")
        time.sleep(1.0)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight * 2 / 3);")
        time.sleep(1.0)

        return driver.page_source
    except Exception as e:
        print(f"[selenium_helper] 抓取失败 {url}: {e}")
        return None
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def fetch_page_soup(url: str, wait_seconds: float = 5.0) -> Optional[BeautifulSoup]:
    """
    使用 Selenium 获取 BeautifulSoup 对象。

    Args:
        url:           要抓取的 URL
        wait_seconds:  页面加载后等待秒数

    Returns:
        BeautifulSoup 对象，失败返回 None
    """
    html = fetch_page_html(url, wait_seconds)
    if html:
        return BeautifulSoup(html, "html.parser")
    return None
