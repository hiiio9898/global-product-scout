"""
路线 2 探针：undetected-chromedriver + Clash 代理抓 Lazada/eBay。

目的：验证 UC 的浏览器指纹能否绕过 Akamai（Lazada）/ eBay 反爬，
拿到 window.pageData 或产品卡片。成功 → 走 Lazada 全流程；
失败 → 报告结果，让用户决定。

用法：
    python scripts/probe_uc.py            # 测 Lazada SG + eBay US
    python scripts/probe_uc.py lazada     # 只测 Lazada
    python scripts/probe_uc.py ebay        # 只测 eBay

实测结果（2026-07）：失败 —— 免费 Clash 出口是机房 IP（43.128.57.235 腾讯 HK），
被 Akamai（Lazada）/eBay 在网络层封死（Lazada 返 captcha 页无 window.pageData，
eBay 返 1.9KB 空页）。UC 仅伪装浏览器指纹、无法绕过 IP 层封禁。
结论：免费约束下 IP 是死结，与 patchright 同一根因。本脚本作为诊断证据归档。
"""

import sys
import time
import re
import json

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

PROXY = "127.0.0.1:7897"
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

TARGETS = {
    "lazada": {
        "url": "https://www.lazada.sg/catalog/?q=clothing",
        "wait_selector": "[data-... ], div[data-tracking='product-card']",
        "probe": "window.pageData",
    },
    "ebay": {
        "url": "https://www.ebay.com/sch/i.html?_nkw=bluetooth+speaker&_sop=12",
        "wait_selector": "li.s-item",
        "probe": "li.s-item",
    },
}


def make_driver():
    options = uc.ChromeOptions()
    options.binary_location = CHROME_PATH
    options.add_argument(f"--proxy-server=http://{PROXY}")
    options.add_argument("--lang=en-US,en")
    options.add_argument("--window-size=1366,900")
    options.add_argument("--disable-blink-features=AutomationControlled")
    # headless 更易被检测，这里用有头（可改 --headless=new 测）
    # options.add_argument("--headless=new")
    driver = uc.Chrome(options=options, version_main=149)
    return driver


def probe_lazada(driver):
    url = TARGETS["lazada"]["url"]
    print(f"\n[Lazada] GET {url}")
    driver.get(url)
    time.sleep(6)  # 让 Akamai 跑完
    html = driver.page_source
    print(f"[Lazada] page_source length = {len(html)}")

    # 看是否被 Akamai 拦（典型特征：标题/正文含 "robot"/"verify"/"access denied"）
    lower = html.lower()
    blocked_markers = ["access denied", "robot check", "are you human", "verify you are human", "captcha"]
    hits = [m for m in blocked_markers if m in lower]
    if hits:
        print(f"[Lazada] 检测到拦截标记: {hits}")

    # window.pageData 提取
    m = re.search(r'window\.pageData\s*=\s*(\{.*?\});\s*</script>', html, re.DOTALL)
    if not m:
        m = re.search(r'window\.pageData\s*=\s*(\{.*?\});', html, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
            items = data.get("mods", {}).get("listItems", [])
            print(f"[Lazada] window.pageData 解析成功，listItems = {len(items)}")
            if items:
                print("[Lazada] 第一个产品字段:")
                print(json.dumps(items[0], indent=2, ensure_ascii=False)[:1200])
                return True, len(items)
        except Exception as e:
            print(f"[Lazada] JSON 解析失败: {e}")
    else:
        print("[Lazada] 未找到 window.pageData")

    # CSS 回退
    cards = driver.find_elements(By.CSS_SELECTOR, "a[href*='/products']")
    print(f"[Lazada] CSS a[href*='/products'] 数量 = {len(cards)}")
    return False, len(cards)


def probe_ebay(driver):
    url = TARGETS["ebay"]["url"]
    print(f"\n[eBay] GET {url}")
    driver.get(url)
    try:
        WebDriverWait(driver, 12).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "li.s-item"))
        )
    except Exception:
        print("[eBay] 等待 li.s-item 超时")
    time.sleep(2)
    html = driver.page_source
    print(f"[eBay] page_source length = {len(html)}")

    lower = html.lower()
    blocked_markers = ["access denied", "robot check", "verify", "captcha", "whoa there"]
    hits = [m for m in blocked_markers if m in lower]
    if hits:
        print(f"[eBay] 检测到拦截标记: {hits}")

    cards = driver.find_elements(By.CSS_SELECTOR, "li.s-item")
    print(f"[eBay] li.s-item 数量 = {len(cards)}")
    if cards:
        first = cards[0].text.strip().replace("\n", " | ")[:300]
        print(f"[eBay] 第一个卡片文本: {first}")
    return len(cards) > 0, len(cards)


def main():
    targets = sys.argv[1:] if len(sys.argv) > 1 else ["lazada", "ebay"]
    print(f"代理: http={PROXY} (出口 43.128.57.235 腾讯HK)")
    print(f"Chrome: {CHROME_PATH}")
    print(f"目标: {targets}")

    driver = make_driver()
    driver.set_page_load_timeout(40)
    results = {}
    try:
        if "lazada" in targets:
            ok, n = probe_lazada(driver)
            results["lazada"] = (ok, n)
        if "ebay" in targets:
            ok, n = probe_ebay(driver)
            results["ebay"] = (ok, n)
    finally:
        driver.quit()

    print("\n========== 汇总 ==========")
    for k, (ok, n) in results.items():
        flag = "OK" if ok else "FAIL"
        print(f"  {k}: {flag} (n={n})")


if __name__ == "__main__":
    main()
