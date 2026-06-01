# Spec 14：Scrapling 抓取引擎集成

**版本**：v1.0
**状态**：✅ 已完成
**最后更新**：2026-06-01
**依赖**：Scrapling v0.4.8（本地目录 Scrapling-main）

---

## 1. 需求描述

### 1.1 背景
当前项目的抓取层使用 requests + BeautifulSoup，辅以 Selenium 降级方案。存在以下痛点：
- 反爬能力脆弱：仅靠手动 User-Agent 轮换，Amazon/eBay/Alibaba 均可能被拦截
- Selenium 降级笨重：每次请求新建 Chrome 实例，无会话复用，无反检测能力
- 无自适应选择器：网站改版后所有 CSS 选择器需手动修复
- 1688 无法真实抓取：JS 动态渲染页面只能靠 AI 估算价格
- 各平台抓取器代码重复严重（session/cache/headers 各自维护一套）

Scrapling 是一个自适应 Python 网络爬虫框架，核心差异化优势：
- 三层抓取器：Fetcher（curl_cffi TLS 指纹模拟）→ DynamicFetcher（Playwright 浏览器）→ StealthyFetcher（Patchright 反检测浏览器）
- 自适应元素追踪：首次抓取保存元素结构指纹到 SQLite，网站改版后自动重新定位
- 内置代理轮换、重试策略、浏览器会话池

### 1.2 核心目标
将 Scrapling 融入 handpicked 项目，替代现有 requests/BS4/Selenium 抓取架构。

### 1.3 决策记录

| 决策项 | 选择 | 理由 |
|--------|------|------|
| 部署目标 | 仅本地运行 | Scrapling 浏览器依赖需要系统级 Chrome，Streamlit Cloud 不支持 |
| 集成范围 | 全平台同时改写 | 避免新旧代码混杂，一次性统一架构 |
| 安装方式 | pip install 本地包 | pip install -e ./Scrapling-main[all]，享受完整依赖管理 |
| 1688 策略 | StealthyFetcher 浏览器抓取 | 从 AI 估算升级为真实抓取 |
| 抓取策略 | Fetcher 优先 + StealthyFetcher 兜底 | 兼顾速度和成功率 |
| 自适应追踪 | 启用 | Scrapling 杀手级特性，网站改版时自动恢复选择器 |

---

## 2. 技术方案

### 2.1 架构设计

`
外部调用（scraper.py / scraper_search.py / scraper_ebay.py / ...）
    │
    ▼
scrapling_adapter.py（适配层 — 统一接口 + 降级策略 + 自适应存储 + 代理配置）
    │
    ├─ 第一层：Fetcher.get(url)              ← curl_cffi，快速，TLS 指纹模拟
    │   └─ 成功 → 返回 Response
    │   └─ 被拦截 → 降级
    │
    ├─ 第二层：StealthyFetcher.fetch(url)    ← Patchright 反检测浏览器
    │   └─ 成功 → 返回 Response
    │   └─ 失败 → 抛出异常
    │
    └─ 自适应存储：adaptive=True 时元素指纹自动保存到 SQLite
`

### 2.2 核心适配层 — src/scrapling_adapter.py（新建）

职责：
- 封装 Scrapling 三层抓取器，对外暴露统一的 etch_page() 接口
- 处理 Fetcher → StealthyFetcher 自动降级（被反爬拦截时）
- 管理自适应元素追踪的 SQLite 存储
- 代理配置读取与传递
- 错误映射为 handpicked 现有异常格式

核心接口：
`python
def fetch_page(url: str, stealth: bool = False, adaptive: bool = True, proxy: str | None = None) -> Response:
    """抓取页面，返回 Scrapling Response 对象。
    
    策略：stealth=False 时先用 Fetcher（快速），被拦截则自动升级 StealthyFetcher。
          stealth=True 时直接用 StealthyFetcher。
    """

def fetch_page_stealth(url: str, **kwargs) -> Response:
    """直接使用 StealthyFetcher 抓取（用于 1688 等强反爬站点）。"""

def fetch_page_dynamic(url: str, **kwargs) -> Response:
    """使用 DynamicFetcher 抓取（JS 渲染页面）。"""
`

自适应存储配置：
- 存储路径：data/adaptive_elements.db（SQLite）
- 每个平台使用独立的 adaptive_domain（amazon.com / ebay.com / 1688.com 等）
- 首次抓取自动记录元素结构指纹，后续抓取自动通过相似度算法重新定位

### 2.3 各平台抓取器改写

#### 改写模式（所有平台通用）

| 现有代码 | 替换为 |
|----------|--------|
| 
equests.Session().get(url) | etch_page(url) |
| BeautifulSoup(html, "html.parser") | 直接使用 Response（继承 Selector） |
| soup.select('div.xxx') | 
esponse.css('div.xxx') |
| elem.get_text(strip=True) | elem.text（TextHandler，自动 strip） |
| elem.select_one(sel) | elem.css(sel).first |
| elem.get('attr') | elem.attrib['attr'] 或 elem['attr'] |
| is_blocked(resp.text) | is_blocked(str(response.text)) |
| 
esp.status_code | 
esponse.status |

**关键约束**：公共 API（函数签名和返回格式）完全不变，app.py 和 daily_scrape.py 无需修改。

#### src/scraper.py — Amazon Best Sellers
- _scrape_amazon_best_sellers()：替换 requests 为 etch_page()
- 所有 _extract_* 函数：适配 Scrapling Selector API
- 保留缓存机制、公共接口、返回格式不变
- 选择器映射示例：
  `python
  # 旧：elem = card.select_one('div.zg-carousel-general-faceout a.a-link-normal span')
  # 新：elem = card.css('div.zg-carousel-general-faceout a.a-link-normal span').first
  # 旧：text = elem.get_text(strip=True)
  # 新：text = str(elem.text) if elem else ""
  `

#### src/scraper_search.py — Amazon 关键词搜索
- _scrape_amazon_search()：替换 requests 为 etch_page()
- 所有 _extract_search_* 函数：适配 Scrapling Selector API
- 保留搜索结果页特有的选择器

#### src/scraper_ebay.py — eBay
- _scrape_ebay_best_sellers()：替换 requests + Selenium 为 etch_page()（自动降级）
- _scrape_ebay_search()：同上
- **移除 Selenium 降级逻辑**（fetch_ebay_best_sellers 中的第二层 Selenium fallback）
- 移除对 selenium_helper 的 import 引用

#### src/scraper_alibaba.py — Alibaba 国际站
- _scrape_alibaba_search()：替换 requests 为 etch_page(stealth=True)（Alibaba 反爬较强，直接用 StealthyFetcher）

#### src/scraper_1688.py — 1688 比价（重大升级）
- 新增 _scrape_1688_search(keyword)：使用 etch_page_stealth() 抓取 1688 搜索结果
  - 1688 是 JS 动态渲染网站，必须用 StealthyFetcher（Patchright 浏览器）
  - 使用 wait_selector 等待产品列表加载
  - 解析搜索结果卡片：提取标题、价格、起批量、供应商信息
- 改写 search_1688_hybrid()：
  - 第一层：StealthyFetcher 真实抓取
  - 第二层：AI 估算（现有逻辑作为兜底）
- 保留 estimate_1688_price() 和 _local_estimate() 作为降级方案

### 2.4 删除 src/selenium_helper.py

Selenium helper 被 StealthyFetcher 完全替代：
- StealthyFetcher 基于 Patchright（Playwright 反检测补丁版）
- 内置 Canvas 噪声、WebRTC 屏蔽、Cloudflare Turnstile 解决
- 支持浏览器会话复用（比 Selenium 每次新建 driver 高效得多）
- scraper_ebay.py 中对 selenium_helper 的引用全部移除

### 2.5 配置更新

#### src/config.py 新增
`python
def get_scrapling_config() -> dict:
    """获取 Scrapling 抓取引擎配置。"""
    return {
        "proxy": _get_secret("SCRAPLING_PROXY", "") or None,
        "browser_timeout": int(_get_secret("SCRAPLING_BROWSER_TIMEOUT", "30000")),
        "adaptive_db": _get_secret("SCRAPLING_ADAPTIVE_DB",
            os.path.join(_PROJECT_ROOT, "data", "adaptive_elements.db")),
        "strategy": _get_secret("SCRAPLING_STRATEGY", "fetcher_first"),
    }
`

#### .env.example 新增
`env
# Scrapling 抓取引擎配置
# SCRAPLING_PROXY=http://user:pass@proxy:port
# SCRAPLING_PROXY_ROTATION=round-robin
SCRAPLING_BROWSER_TIMEOUT=30000
SCRAPLING_ADAPTIVE_DB=data/adaptive_elements.db
SCRAPLING_STRATEGY=fetcher_first
`

#### src/platforms.py 更新
- 新增 scrape_mode 字段（fetcher_first / stealth_only / dynamic_only）
- 新增 1688 平台注册条目

#### 
equirements.txt 更新
`
# 新增
scrapling[all]>=0.4.8
curl_cffi>=0.15.0
patchright==1.59.1
playwright==1.59.0
browserforge>=1.2.4

# 移除（被 Scrapling 替代）
# requests
# beautifulsoup4
# selenium
# webdriver-manager
`

---

## 3. 实施步骤（检查清单）

- [ ] **步骤 1**：环境安装
  - pip install -e "./Scrapling-main[all]"
  - scrapling install（安装浏览器依赖）
  - 验证 python -c "from scrapling import Fetcher, StealthyFetcher; print('OK')" 成功

- [ ] **步骤 2**：新增 src/scrapling_adapter.py（~200 行）
  - 实现 etch_page() / etch_page_stealth() / etch_page_dynamic()
  - Fetcher 优先 + StealthyFetcher 兜底降级逻辑
  - 自适应存储配置（adaptive=True + SQLite）
  - 代理配置读取
  - 错误映射

- [ ] **步骤 3**：更新 src/config.py（~20 行）
  - 新增 get_scrapling_config()

- [ ] **步骤 4**：更新 .env.example（~15 行）
  - 新增 Scrapling 配置项

- [ ] **步骤 5**：改写 src/scraper.py（~100 行改动）
  - requests → fetch_page()
  - BeautifulSoup Selector → Scrapling Selector
  - 验证 fetch_amazon_best_sellers() 公共 API 不变

- [ ] **步骤 6**：改写 src/scraper_search.py（~80 行改动）
  - 同步骤 5 模式

- [ ] **步骤 7**：改写 src/scraper_ebay.py（~120 行改动）
  - 移除 Selenium 降级逻辑
  - 移除 selenium_helper 引用
  - requests → fetch_page()

- [ ] **步骤 8**：改写 src/scraper_alibaba.py（~60 行改动）
  - requests → fetch_page(stealth=True)

- [ ] **步骤 9**：改写 src/scraper_1688.py（~200 行改动，重大升级）
  - 新增 _scrape_1688_search() 使用 StealthyFetcher
  - 改写 search_1688_hybrid() 为真实抓取优先 + AI 估算兜底
  - 保留 AI 估算作为降级方案

- [ ] **步骤 10**：删除 src/selenium_helper.py

- [ ] **步骤 11**：更新 src/platforms.py（~30 行改动）
  - 新增 scrape_mode 字段
  - 新增 1688 平台注册

- [ ] **步骤 12**：更新 
equirements.txt（~10 行改动）

- [ ] **步骤 13**：新增 	ests/test_scrapling_adapter.py（~150 行）
  - fetch_page() 返回 Response 对象
  - Fetcher → StealthyFetcher 降级
  - 反爬检测
  - 代理配置
  - 自适应存储创建
  - 全部失败时抛出异常

- [ ] **步骤 14**：更新 	ests/test_basic.py（~50 行改动）
  - Amazon 抓取器使用 Scrapling
  - eBay 抓取器无 selenium_helper 依赖
  - 所有抓取器返回标准格式

- [ ] **步骤 15**：更新 AGENTS.md（~30 行改动）
  - 硬规则新增 Scrapling 抓取引擎说明
  - 目录结构更新（新增 scrapling_adapter.py，删除 selenium_helper.py）

- [ ] **步骤 16**：更新 docs/CHANGELOG.md
  - 记录 Scrapling 集成变更

- [ ] **步骤 17**：验证
  - python -m py_compile src/scrapling_adapter.py 通过
  - python -m py_compile src/scraper.py 通过
  - python -m py_compile src/scraper_search.py 通过
  - python -m py_compile src/scraper_ebay.py 通过
  - python -m py_compile src/scraper_alibaba.py 通过
  - python -m py_compile src/scraper_1688.py 通过
  - pytest tests/ -v 全部通过
  - streamlit run app.py 启动无错误
  - 手动测试实时选品页面（Amazon 抓取）
  - 手动测试 1688 比价功能

---

## 4. 测试计划

### 4.1 单元测试（mock，不依赖网络）

`python
# tests/test_scrapling_adapter.py

class TestScraplingAdapter:
    def test_fetch_page_returns_response(self):
        """fetch_page() 返回 Scrapling Response 对象"""

    def test_fetch_page_stealth_fallback(self):
        """Fetcher 被拦截时自动降级到 StealthyFetcher"""

    def test_fetch_page_blocked_detection(self):
        """被反爬拦截时正确检测并降级"""

    def test_fetch_page_proxy_config(self):
        """代理配置正确传递给 Fetcher/StealthyFetcher"""

    def test_adaptive_storage_created(self):
        """adaptive=True 时创建 SQLite 存储文件"""

    def test_fetch_page_all_methods_fail(self):
        """所有抓取方式均失败时抛出 RuntimeError"""
`

### 4.2 更新现有测试

`python
# tests/test_basic.py 新增

class TestScraperWithScrapling:
    def test_amazon_scraper_uses_scrapling(self):
        """Amazon 抓取器使用 Scrapling 适配层"""

    def test_ebay_scraper_no_selenium(self):
        """eBay 抓取器不再依赖 selenium_helper"""

    def test_scraper_1688_real_scraping(self):
        """1688 抓取器支持真实浏览器抓取模式"""

    def test_all_scrapers_return_standard_format(self):
        """所有抓取器返回标准 (products, source_info) 格式"""
`

### 4.3 集成测试（需网络，手动运行）

`python
# tests/test_scrapling_integration.py

@pytest.mark.integration
class TestLiveScraping:
    def test_amazon_best_sellers_live(self):
        """真实抓取 Amazon Best Sellers（需要网络）"""

    def test_1688_search_live(self):
        """真实抓取 1688 搜索结果（需要网络 + 浏览器）"""
`

---

## 5. 风险与回退方案

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Scrapling 依赖冲突 | 安装失败 | 使用 pip install -e editable 模式，可随时切换回 requests |
| 1688 页面结构频繁变动 | 解析失败 | 自适应追踪 + AI 估算兜底 |
| StealthyFetcher 启动慢（~5s） | 用户体验 | Fetcher 优先策略，仅被拦截时降级 |
| 自适应存储 SQLite 增长 | 磁盘占用 | 设置定期清理过期指纹 |
| Scrapling API 版本变更 | 代码适配 | 适配层隔离变化，仅需修改 scrapling_adapter.py |

---

## 6. 假设与默认值

- Scrapling v0.4.8 API 与当前源码一致（已验证 Fetcher.get()、StealthyFetcher.fetch() 签名）
- 自适应追踪使用默认 SQLiteStorageSystem（data/adaptive_elements.db）
- 代理配置为可选（无代理时 Scrapling 使用直连）
- 1688 选择器需首次运行时手动验证和调整
- 现有 JSON 缓存机制完全保留，不受 Scrapling 影响
- Streamlit Cloud 部署不在本次范围内（仅本地运行）



