# Spec 2：自动化 CI/CD

**版本**：v1.0
**状态**：✅ 已实现并验收通过
**最后更新**：2026-05-28

---

## 1. 需求描述

### 1.1 背景
当前工作流需要手动运行 `python daily_scrape.py` → 手动 `git add/commit/push`。用户希望完全自动化：每天定时抓取 + 分析 + 自动提交 products.json 到 GitHub，Streamlit Cloud 检测到推送后自动重新部署。

### 1.2 核心需求
1. GitHub Actions 每天定时运行 `daily_scrape.py`
2. 抓取成功后自动 `git commit` + `git push` products.json 回仓库
3. 支持 `workflow_dispatch` 手动触发
4. 敏感信息通过 GitHub Secrets 注入

### 1.3 现状
- `.github/workflows/daily_scrape.yml` 已存在，但**缺少自动提交步骤**
- 当前 workflow 只运行抓取 + 上传 artifact，不自动 push 回仓库
- `daily_scrape.py` 已在第 4 步导出 `data/products.json`

---

## 2. 系统设计

### 2.1 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `.github/workflows/daily_scrape.yml` | **重写** | 新增 git commit + push 步骤 |
| `daily_scrape.py` | **微调** | 新增 `--dry-run` 参数支持（可选） |

### 2.2 Workflow 架构

```
定时触发（每天 UTC 06:00）
或手动触发（workflow_dispatch）
        ↓
checkout 代码
        ↓
安装 Python + 依赖
        ↓
运行 python daily_scrape.py
（抓取 → 分析 → 存库 → 导出 products.json）
        ↓
配置 git（GitHub Actions Bot）
        ↓
git add data/products.json
        ↓
git commit -m "Auto-update: products YYYY-MM-DD"
        ↓
git push（使用 GITHUB_TOKEN）
        ↓
Streamlit Cloud 检测到推送 → 自动重新部署
```

### 2.3 Git 配置方案

使用 GitHub Actions 内置的 `GITHUB_TOKEN` 授权推送：

```yaml
- name: Commit and push products.json
  run: |
    git config user.name "github-actions[bot]"
    git config user.email "github-actions[bot]@users.noreply.github.com"
    git add data/products.json
    # 仅在有变更时提交
    git diff --cached --quiet || git commit -m "Auto-update: products $(date -u +%Y-%m-%d)"
    git push
```

---

## 3. 接口定义

### 3.1 `.github/workflows/daily_scrape.yml` — 重写

```yaml
name: Daily Scrape

on:
  schedule:
    - cron: '0 6 * * *'  # 每天 UTC 06:00（北京时间 14:00）
  workflow_dispatch:       # 手动触发

permissions:
  contents: write          # 需要写权限来 push

jobs:
  scrape:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python 3.10
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run daily scrape
        env:
          ACTIVATE_PROVIDER: ${{ secrets.ACTIVATE_PROVIDER }}
          ACTIVATE_MODEL: ${{ secrets.ACTIVATE_MODEL }}
          DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
          DEEPSEEK_BASE_URL: ${{ secrets.DEEPSEEK_BASE_URL }}
          MIMO_API_KEY: ${{ secrets.MIMO_API_KEY }}
          MIMO_BASE_URL: ${{ secrets.MIMO_BASE_URL }}
          AMAZON_BEST_SELLERS_URL: ${{ secrets.AMAZON_BEST_SELLERS_URL }}
          SCRAPE_DELAY_SECONDS: '2'
          DATABASE_PATH: data/products.db
        run: python daily_scrape.py

      - name: Commit and push products.json
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data/products.json
          git diff --cached --quiet || git commit -m "Auto-update: products $(date -u +%Y-%m-%d)"
          git push
```

---

## 4. 需要在 GitHub Secrets 中配置的值

| Secret | 说明 | 必填 |
|--------|------|------|
| `ACTIVATE_PROVIDER` | 当前供应商（deepseek/mimo） | ✅ |
| `ACTIVATE_MODEL` | 当前模型名 | ✅ |
| `DEEPSEEK_API_KEY` | DeepSeek API Key | 使用 DeepSeek 时必填 |
| `DEEPSEEK_BASE_URL` | DeepSeek Base URL | 使用 DeepSeek 时必填 |
| `MIMO_API_KEY` | MiMo API Key | 使用 MiMo 时必填 |
| `MIMO_BASE_URL` | MiMo Base URL | 使用 MiMo 时必填 |
| `AMAZON_BEST_SELLERS_URL` | 抓取目标 URL | ✅ |

---

## 5. 验收标准

| # | 验收条件 | 验证方法 |
|---|---------|---------|
| 1 | workflow 语法正确 | `yamllint` 或 GitHub Actions 预检 |
| 2 | `daily_scrape.py` 在 Actions 中可正常运行 | 手动触发 workflow_dispatch |
| 3 | products.json 自动 commit + push | 查看 GitHub 仓库 commit 历史 |
| 4 | 无变更时不产生空 commit | `git diff --cached --quiet \|\| git commit` |
| 5 | Streamlit Cloud 在推送后自动更新 | 推送后打开应用验证 |
| 6 | Secrets 不泄露到日志 | workflow 未直接 echo 敏感值 |

---

## 6. 不在本次范围内

- 多平台抓取（AliExpress/Shopee）
- 失败通知（邮件/Slack/Discord）
- 多分支策略（main/staging）
- CI/CD 中的 AI 分析加速（如缓存模型）
