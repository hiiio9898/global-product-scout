# SKILL.md

本项目的 AI 协作技能系统说明。**AI 协作的完整硬规则见 [AGENTS.md](AGENTS.md)（唯一真源）**。

---

## 技能目录

项目使用两套 skill 目录，按优先级递减：

| 目录 | 用途 | Git 追踪 |
|------|------|----------|
| `.claude/skills/` | 项目专属工作流 skill（提交到仓库，团队共享） | ✅ 是 |
| `.agents/skills/` | 本地扩展 skill（含通用编程规范，不提交） | ❌ 否（.gitignore） |

---

## 项目专属技能（`.claude/skills/`）

| 技能 | 触发场景 | 简介 |
|------|----------|------|
| **init-project** | 初始化项目、搭建骨架 | 创建完整目录结构、核心文件、配置模板 |
| **add-data-source** | 新增抓取源 | 调研网站 → 创建爬虫 → 注册 PLATFORMS → 实现计算器 → 测试 |
| **add-analysis-type** | 新增分析维度 | 设计数据结构 → 更新 AI Prompt → 前端展示 → 测试 |
| **add-platform-calculator** | 新增平台利润计算器 | @register_calculator → 标准 dict → platforms.py 配置 |
| **add-streamlit-page** | 新增 Streamlit 页面 | 创建 _render 函数 → 路由 → session_state |
| **migrate-database** | 数据库 Schema 迁移 | ALTER TABLE + try/except → CREATE INDEX |
| **fix-scraper** | 抓取失效/网站改版 | 查 platforms.py 定位 → 更新选择器 → 增强容错 |
| **minimalist-architect** | 代码重构/功能审查/砍功能 | 冗余检测 → UX 毒性分析 → Kill/Keep/Merge |
| **file-encoding-guard** | 写入/修改任何文件时 | 防乱码：强制 UTF-8 无 BOM + LF，禁止 PowerShell 默认编码 |

## 通用编程规范（`.agents/skills/`，仅本地）

code-documentation、database-design、doc-coauthoring、karpathy-guidelines、python-skills 等，写代码时叠加使用。

---

## 标准开发工作流

1. **接到需求** → 先读 AGENTS.md + SKILL.md，识别改动范围
2. **匹配 skill** → 任务匹配时先调 skill 再动手（项目约定）
3. **编码** → 优先用 mock 数据，避免依赖网络/真实 API
4. **验证** → `streamlit run app.py` 无 import 错误 + `pytest tests/` + `python -m py_compile`
5. **同步配置** → 新增配置项必须更新 `.env.example` 和 `src/config.py`
6. **交付** → 说明改了什么、为什么、风险点

---

## 核心架构范式

项目采用**注册表驱动**，三个字典决定一切：

- **`PLATFORMS`**（`src/platforms.py`）：平台注册表，加新平台 = 一条字典 + scraper + calculator
- **`LLM_PROVIDERS`**（`src/config.py`）：AI 供应商注册表，`ACTIVATE_PROVIDER` 切换
- **`@register_calculator`**（`src/calculator.py`）：利润计算器装饰器注册

详见 [CLAUDE.md](CLAUDE.md) 的架构章节。
