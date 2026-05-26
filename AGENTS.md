# AGENTS.md

本文件是「外贸 AI 选品工具」的 AI 协作规则唯一真源。

## 1. 项目定位
- 项目名称：Global Product Scout（全球产品侦察兵）
- 目标用户：跨境电商卖家、外贸创业者
- 核心功能：自动抓取多平台（亚马逊、速卖通等）热销/飙升产品数据，通过 DeepSeek 大模型分析产品潜力，提供选品建议。
- 技术栈：Python 3.10+、Streamlit（前端）、DeepSeek API（AI 分析）、Requests/BeautifulSoup（数据抓取）

## 2. 硬规则
- 不执行 `git commit`、`git push` 或任何远端操作，除非用户明确要求。
- 所有秘钥、API Key 必须通过 `.env` 文件加载，且 `.env` 不提交到 Git。
- 代码注释和文档使用中文，变量名、函数名使用英文。
- 新增功能必须同步更新 `.env.example` 文件。
- 抓取数据需遵守目标网站 robots.txt，并设置合理延迟，避免被封。
- DeepSeek 调用必须包含超时、重试和错误提示逻辑。
- 不做与当前任务无关的重构或"顺手优化"。

## 3. 目录结构
```
/
├── AGENTS.md
├── SKILL.md
├── .env.example
├── .gitignore
├── requirements.txt
├── app.py                  # Streamlit 主程序入口
├── src/
│   ├── __init__.py
│   ├── config.py           # 读取 .env 配置
│   ├── scraper.py          # 数据抓取模块（示例：亚马逊 Best Sellers）
│   ├── analyzer.py         # DeepSeek 分析模块
│   └── utils.py            # 工具函数
├── tests/
│   └── test_basic.py
└── docs/
    └── CHANGELOG.md
```

## 4. 常用命令
- 安装依赖：`pip install -r requirements.txt`
- 运行应用：`streamlit run app.py`
- 运行测试：`pytest tests/`
- 代码风格检查：`flake8 src/`

## 5. 开发工作流
1. 接到需求后，先阅读 AGENTS.md 和 SKILL.md，了解当前项目结构。
2. 识别改动范围（数据抓取 / 分析 / 前端界面 / 配置）。
3. 优先采用模拟数据（mock）进行开发和测试，避免依赖网络和真实 API。
4. 修改 `.env.example` 同步新增的配置项。
5. 交付时说明：改了什么、为什么、验证截图/日志、风险点（如网站反爬）。

## 6. 验证要求
- Streamlit 应用必须能启动且无 import 错误。
- 测试用例可使用模拟数据，无需真实调用 DeepSeek 或网络请求。
- 所有 python 文件可通过 `python -m py_compile` 编译检查。
- 如使用异步或协程，确保与 Streamlit 兼容（Streamlit 默认同步）。

## 7. 数据源与合规
- 示例数据源：Amazon Best Sellers（https://www.amazon.com/Best-Sellers/zgbs/）
- 抓取策略：只抓取首页榜单，每天最多一次。用户可在界面选择站点（需后续扩展）。
- 必须设置 User-Agent 和 Request 间延迟（1-2 秒）。
- 如果网站结构变动导致抓取失败，应向用户提示，并降级为展示旧数据或示例数据。

## 8. DeepSeek 集成
- 使用 OpenAI SDK 兼容模式调用 DeepSeek（base_url="https://api.deepseek.com"）
- 默认模型：deepseek-v4-flash/deepseek-v4-pro（后续要具备兼容更多模型能力）
- 分析 Prompt 模板存放在 `src/prompts.py` 中（后续添加），现在可内嵌在 analyzer.py 内。
- 分析任务需异步或长时间执行时，Streamlit 中应显示进度条。
