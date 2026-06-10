# fix-scraper — 修复抓取失效

## 触发条件
- 用户报告抓取返回空数据或解析异常
- 抓取到的数据字段缺失（如价格全是 None）
- 网站改版导致选择器失效
- 爬虫抛出异常或超时

## 工作流

### 1. 定位目标爬虫文件
**先查 `src/platforms.py` 确定要修改的文件**，不要假设所有爬虫在 `src/scraper.py`：

| 平台 | 爬虫文件 | 爬取函数 |
|------|----------|----------|
| Amazon | `src/scraper.py` | `fetch_amazon_best_sellers()` |
| Amazon搜索 | `src/scraper_search.py` | `search_amazon()` |
| eBay | `src/scraper_ebay.py` | `fetch_ebay_best_sellers()` |
| Alibaba | `src/scraper_alibaba.py` | `fetch_alibaba_best_sellers()` |
| 1688比价 | `src/scraper_1688.py` | `search_1688_hybrid()` |

函数命名模式：公开 `fetch_<platform>_best_sellers()` → 私有 `_scrape_<platform>_best_sellers()`

### 2. 问题定位
确认具体症状：
- **完全无法抓取**（HTTP 错误/超时）→ 检查 URL、反爬策略、`scrapling_adapter` 降级是否生效
- **能抓取但数据为空**（选择器失效）→ 检查 CSS 选择器
- **部分字段缺失**（价格/标题/评分）→ 检查字段解析逻辑
- **缓存数据过期** → 检查 `data/cache/*.json` 的时间戳

### 3. 分析目标网站变更
访问目标网站当前页面，对比已知选择器：
- HTML 结构变化（容器 ID/Class 变更）
- 产品卡片组件重构
- 价格格式变化（货币符号、小数点格式）
- 评分展示方式变化（图标替换文字）
- 反爬升级（新增验证码、JS 渲染）

### 4. 更新抓取逻辑
在对应的平台爬虫文件中修复：
```python
def _scrape_<platform>_best_sellers(url, ...):
    response = fetch_page(url)  # 通过 scrapling_adapter

    # 更新 CSS 选择器（优先保留旧选择器作为 fallback）
    items = response.css("新选择器") or response.css("旧选择器")

    for item in items:
        try:
            title = item.css("标题选择器::text").get("").strip()
        except Exception:
            title = ""
        # ... 每个字段单独 try/except
```

**关键规则：**
- 所有抓取通过 `from .scrapling_adapter import fetch_page` 调用
- 优先保留旧选择器作为 fallback（网站可能 A/B 测试）
- 每个字段单独 `try/except`，避免一个字段失败导致整条记录丢失
- 新增字段缺失计数日志，便于监控
- 产品数据返回 `list[dict]`，无 `Product` dataclass

### 5. 检查 Scrapling 降级策略
如果问题是"被拦截"，检查 `src/scrapling_adapter.py`：
- `fetcher_first` 模式：Fetcher 被拦截会自动降级到 StealthyFetcher
- 如需强制 StealthyFetcher，在爬虫中调用 `fetch_page(url, stealth=True)`
- 检查 `src/utils.py` 的 `is_blocked()` 关键词列表是否需要更新

### 6. 更新缓存
确认 `save_json_cache()` 正确保存修复后的数据：
```python
from .utils import save_json_cache
save_json_cache(cache_path, products)  # 抓取成功后更新缓存
```

### 7. 测试验证
```bash
# 语法检查
python -m py_compile src/scraper_<platform>.py

# 运行测试
pytest tests/

# 手动验证抓取
python daily_scrape.py --platforms <platform>

# 验证 Streamlit 界面
streamlit run app.py
```

### 8. 交付说明
告知用户：
- 网站变更的具体内容
- 修改了哪些选择器/解析逻辑
- 修复的可靠性评估（是否可能再次失效）
- 建议的后续措施（如增加监控、考虑 API 接入）

## 注意事项
- 修复时保持向后兼容，不删除现有字段
- 优先保证缓存降级正常，确保抓取失败时有兜底数据
- 如网站反爬大幅升级，建议评估是否切换为官方 API
- 不执行与修复无关的其他改动
- 如涉及 1688 模块（`scraper_1688.py`），注意其三级降级架构：真实抓取 → AI 估算 → 本地规则
