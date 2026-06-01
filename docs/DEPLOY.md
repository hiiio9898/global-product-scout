# 部署备忘录

本文档记录项目部署到各平台时需要配置的事项，每次部署前请逐项确认。

---

## 一、GitHub Actions 自动抓取

### 1.1 概述
`.github/workflows/daily_scrape.yml` 每天北京时间 14:00 自动运行 `daily_scrape.py`，也可手动触发。

### 1.2 需要在 GitHub 仓库设置的 Secrets

路径：GitHub 仓库 → Settings → Secrets and variables → Actions → **New repository secret**

| Secret 名称 | 示例值 | 说明 |
|-------------|--------|------|
| `ACTIVATE_PROVIDER` | `mimo` | AI 供应商（deepseek / mimo / openai） |
| `ACTIVATE_MODEL` | `mimo-v2.5` | AI 模型 |
| `MIMO_API_KEY` | `sk-xxxxxxxxxxxxxxxx` | MiMo API 密钥（按所选供应商填写） |
| `MIMO_BASE_URL` | `https://api.xiaomimimo.com/v1` | MiMo API 地址 |
| `SCRAPLING_BROWSER_TIMEOUT` | `30000` | Scrapling 浏览器超时（毫秒） |
| `AMAZON_BEST_SELLERS_URL` | `https://www.amazon.com/Best-Sellers/zgbs/` | Amazon 抓取目标 URL（可选） |

> ⚠️ 不配置 API Key 的话，分析会降级为本地模拟分析。

### 1.3 手动触发
1. GitHub 仓库 → **Actions** → 左侧选 **Daily Scrape**
2. 点击 **Run workflow** → **Run workflow**
3. 运行结束后可下载 `data/products.db` 产物

---

## 二、Streamlit Cloud 部署

### 2.1 数据更新工作流（JSON 方案）

#### 完整流程
```bash
# 1. 本地每周运行一次抓取脚本
python daily_scrape.py

# 输出：
# - 抓取 Amazon Best Sellers 首页榜单（约 36 个产品）
# - 保存到 SQLite 数据库（data/products.db，不提交）
# - 导出 products.json（data/products.json，**可提交到 Git**）

# 2. 提交 JSON 数据到 GitHub
git add data/products.json
git commit -m "Update products"
git push

# 3. 云端自动更新
# - Streamlit Cloud 监测到新推送 → 自动重新部署
# - 用户打开应用 → 看到最新抓取的真实产品 + AI 分析
# - 数据来源显示：`数据来源：JSON 文件 | 抓取时间：YYYY-MM-DD HH:MM:SS`
```

#### 两级数据策略
应用采用简洁的两级数据加载策略：

```
data/products.json 存在？ ──是──→ 📄 JSON 数据（本地采集）
        │
        否
        ↓
   实时抓取 Amazon ──成功──→ 📡 实时数据
        │
        失败
        ↓
   ❌ 抛出异常 → 提示用户运行 daily_scrape.py
```

- **第一级**（推荐）：读取 `data/products.json`（Streamlit Cloud 无需数据库）
- **第二级**：实时抓取 Amazon，仅接受 `source='live'` 的结果
- 抓取返回 cache/mock 时**丢弃数据**，直接报错引导用户
- 错误提示："请在本机执行 `python daily_scrape.py`，然后将 `data/products.json` 提交并推送到 GitHub"

### 2.2 部署方式
1. 打开 https://streamlit.io/cloud
2. 用 GitHub 账号登录
3. 点击 **New app** → 选择本仓库和 `app.py` → **Deploy**

### 2.3 Secrets 配置

**⚠️ 注意：Streamlit Cloud 用 `secrets.toml` 而不是 `.env`！**

路径：App Settings → **Secrets**（粘贴以下内容）

```toml
# AI 供应商配置
ACTIVATE_PROVIDER = "mimo"
ACTIVATE_MODEL = "mimo-v2.5"
MIMO_API_KEY = "你的真实key"
MIMO_BASE_URL = "https://api.xiaomimimo.com/v1"

# 抓取配置
AMAZON_BEST_SELLERS_URL = "https://www.amazon.com/Best-Sellers/zgbs/"
SCRAPE_DELAY_SECONDS = "2"
SCRAPLING_BROWSER_TIMEOUT = "30000"
SCRAPLING_STRATEGY = "fetcher_first"

# 数据库
DATABASE_PATH = "data/products.db"
```

> 📝 本地的 `.streamlit/secrets.toml` 文件已加入 `.gitignore`，**不会上传到 GitHub**。
> 它仅供你本地参考格式，在 Streamlit Cloud 上需要**手动粘贴**到 Secrets 面板。

### 2.4 Streamlit Cloud 自动安装的依赖

| 文件 | 内容 |
|------|------|
| `requirements.txt` | Python 包（streamlit, openai, scrapling, pandas 等） |
| `packages.txt` | 系统级依赖（Chromium 浏览器，Scrapling StealthyFetcher 需要） |
| `runtime.txt` | Python 版本（`3.12`） |

> 📝 Scrapling 的 StealthyFetcher 需要 Chromium 浏览器。Streamlit Cloud 通过 `packages.txt` 安装 `chromium-browser`。

---

## 三、本地开发配置

### 3.1 首次克隆后
```bash
# 1. 克隆仓库
git clone https://github.com/hiiio9898/global-product-scout.git
cd global-product-scout

# 2. 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # macOS/Linux

# 3. 安装依赖
pip install -r requirements.txt

# 4. 复制并填写 .env
cp .env.example .env
# 编辑 .env，填入 AI 供应商的 API_KEY

# 5. 运行
streamlit run app.py
```

### 3.2 .env 模板（见 .env.example）
```bash
# AI 供应商
ACTIVATE_PROVIDER=mimo
ACTIVATE_MODEL=mimo-v2.5
MIMO_API_KEY=sk-你的真实key
MIMO_BASE_URL=https://api.xiaomimimo.com/v1

# 抓取配置
AMAZON_BEST_SELLERS_URL=https://www.amazon.com/Best-Sellers/zgbs/
SCRAPE_DELAY_SECONDS=2
SCRAPLING_BROWSER_TIMEOUT=30000
SCRAPLING_STRATEGY=fetcher_first

# 数据库
DATABASE_PATH=data/products.db
```

### 3.3 Scrapling 注意事项

- Scrapling 首次运行会自动下载浏览器内核（约 200MB），请确保网络通畅
- 阿里巴巴抓取需要 StealthyFetcher（Patchright），会自动启动 Chromium 浏览器
- 如遇浏览器启动失败，检查系统是否安装了 Chromium/Chrome
- `SCRAPLING_STRATEGY` 可选值：`fetcher_first`（默认）、`stealth_only`、`dynamic_only`

---

## 四、各平台密钥对照速查

| 配置项 | 本地 `.env` | Streamlit Cloud Secrets | GitHub Actions Secrets |
|--------|-------------|------------------------|------------------------|
| `ACTIVATE_PROVIDER` | ✅ 手动填写 | ✅ 手动粘贴 | ✅ 手动添加 |
| `ACTIVATE_MODEL` | ✅ 手动填写 | ✅ 手动粘贴 | ✅ 手动添加 |
| `MIMO_API_KEY` (或对应供应商) | ✅ 手动填写 | ✅ 手动粘贴 | ✅ 手动添加 |
| `MIMO_BASE_URL` (或对应供应商) | ✅ 手动填写 | ✅ 手动粘贴 | ✅ 手动添加 |
| `AMAZON_BEST_SELLERS_URL` | 可选（有默认值） | 可选 | 可选 |
| `SCRAPE_DELAY_SECONDS` | 可选（默认 2） | 可选 | 可选 |
| `SCRAPLING_BROWSER_TIMEOUT` | 可选（默认 30000） | 可选 | 可选 |
| `SCRAPLING_STRATEGY` | 可选（默认 fetcher_first） | 可选 | 可选 |
| `DATABASE_PATH` | 可选（默认 data/products.db） | 可选 | 可选 |

---

## 五、多平台部署说明

### 5.1 当前支持的平台

| 平台 | 抓取模式 | 说明 |
|------|---------|------|
| Amazon 🟠 | fetcher_first | Fetcher 优先，被拦截降级 StealthyFetcher |
| eBay 🔵 | fetcher_first | 同上 |
| Alibaba 🟠 | stealth_only | 必须使用 StealthyFetcher（JS 动态渲染） |

### 5.2 Scrapling 抓取引擎

本项目使用 [Scrapling](https://github.com/D4Vinci/Scrapling) 作为统一抓取引擎，替代了早期的 requests + BeautifulSoup 方案。

**三层抓取器**：
1. **Fetcher**（curl_cffi）— 快速 HTTP 请求，内置 TLS 指纹模拟
2. **StealthyFetcher**（Patchright）— 反检测浏览器，处理 JS 渲染和 Cloudflare
3. **DynamicFetcher** — 动态页面抓取（预留）

**自动降级策略**：
- `fetcher_first`（默认）：先用 Fetcher，被拦截自动降级 StealthyFetcher
- `stealth_only`：直接用 StealthyFetcher（阿里巴巴等强反爬站点）

### 5.3 daily_scrape.py 多平台

> ⚠️ 当前 `daily_scrape.py` 仅抓取 Amazon 平台，多平台适配待开发（见中期规划）。

---

## 六、常见问题

### Q: 为什么 Streamlit Cloud 显示"未配置 API Key"？
A: 检查 App Settings → Secrets 是否已粘贴 TOML 格式的配置内容（**不是** `.env` 的 `KEY=VALUE` 格式）。

### Q: GitHub Actions 抓取失败？
A: 检查 Settings → Secrets → Actions 中是否已添加对应的 API Key（如 `MIMO_API_KEY`）。注意 GitHub Secrets 名称必须**完全一致**（包括大小写）。

### Q: 如何查看 GitHub Actions 运行日志？
A: 仓库 → Actions → 点击具体 run → 展开 "Run daily scrape" → 查看输出。

### Q: Scrapling 首次运行很慢？
A: Scrapling 首次运行需要下载浏览器内核（约 200MB），后续运行会使用缓存。Streamlit Cloud 首次部署时也会触发下载。

### Q: 阿里巴巴抓取失败？
A: 阿里巴巴使用 StealthyFetcher（需要 Chromium 浏览器）。检查：1) `packages.txt` 是否包含 `chromium-browser`；2) 系统是否有足够内存（浏览器实例需要 ~500MB）；3) 是否被反爬拦截（等待几分钟后重试）。

### Q: 如何切换 AI 供应商？
A: 修改 `ACTIVATE_PROVIDER` 和 `ACTIVATE_MODEL`，并填写对应供应商的 API_KEY。支持 deepseek / mimo / openai 三个供应商。
