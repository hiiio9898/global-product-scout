# init-project — 初始化项目结构

## 触发条件
- 用户要求"初始化项目"、"搭建项目骨架"、"从零开始创建项目"
- 新仓库首次开发

## 工作流

### 1. 确认项目配置
- 读取 `AGENTS.md` 获取项目定位、技术栈和目录结构约定
- 确认用户需求：是否需要全部模块，或仅核心骨架

### 2. 创建目录结构
按 `AGENTS.md` 中定义的结构创建：
```
/
├── AGENTS.md
├── SKILL.md
├── .env.example
├── .gitignore
├── requirements.txt
├── app.py
├── src/
│   ├── __init__.py
│   ├── config.py
│   ├── scraper.py
│   ├── analyzer.py
│   └── utils.py
├── tests/
│   ├── __init__.py
│   └── test_basic.py
├── docs/
│   └── CHANGELOG.md
└── .claude/skills/
```

### 3. 生成核心文件
按以下顺序生成：
1. `.env.example` — 所有配置项及说明
2. `.gitignore` — Python 标准忽略 + `.env` + `.streamlit/secrets.toml`
3. `requirements.txt` — 依赖清单
4. `src/config.py` — 配置读取（通过 `python-dotenv`）
5. `src/utils.py` — 工具函数（重试、日志、类型转换）
6. `src/scraper.py` — 抓取模块（含 mock 数据）
7. `src/analyzer.py` — DeepSeek 分析模块（含 mock 分析）
8. `app.py` — Streamlit 主程序入口
9. `tests/test_basic.py` — 基础测试（使用 mock 数据）

### 4. 验证
- 每个文件创建后执行 `python -m py_compile <file>` 确认无语法错误
- 运行 `pytest tests/` 确认测试通过
- 提示用户复制 `.env.example` 为 `.env` 并填入 API Key

### 5. 交付说明
告知用户：
- 创建了哪些文件
- 下一步需要做什么（配置 `.env`、运行 `streamlit run app.py`）
- 可能的风险点

## 注意事项
- 所有代码注释使用中文，变量名/函数名使用英文
- 优先使用 mock 数据，确保离线可运行
- 不执行 `git commit` 等远端操作
