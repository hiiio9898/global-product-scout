# add-streamlit-page — 新增 Streamlit 页面

## 触发条件
- 用户要求"新增页面"、"添加对比页"、"增加设置页"等
- 需要在 Streamlit 应用中添加新的功能页面

## 核心架构

页面系统由三部分组成：
1. **侧边栏导航** — `render_sidebar()` 中的 `st.sidebar.radio`
2. **页面渲染函数** — `_<page_name>_page()` 私有函数
3. **路由分发** — 底部 `if/elif` 链

## 工作流

### 1. 新增页面渲染函数
在 `app.py` 中创建新的渲染函数：
```python
def _render_<new_page>_page(api_ok: bool = True):
    """渲染 <新页面名> 页面。"""
    st.title("📄 <新页面标题>")

    # 页面逻辑...
    # 使用 st.columns / st.expander / st.metric 等组件

    # 如需侧边栏额外参数，在 render_sidebar() 中添加
```

**命名约定：** `_render_<功能名>_page()`

### 2. 添加侧边栏导航选项
在 `render_sidebar()` 函数中，找到 `st.sidebar.radio` 并新增选项：
```python
page = st.sidebar.radio(
    "📌 页面导航",
    options=[
        "📊 Dashboard",
        "🔍 实时选品",
        "🎯 指定选品",
        "🌐 市场扫描",
        "📚 历史记录",
        "🆕 新页面名",   # ← 新增
    ],
    help="...",  # 更新帮助文本
)
```

### 3. 添加路由分发
在 `app.py` 底部的路由 `if/elif` 链中新增：
```python
# 页面路由
if "Dashboard" in page:
    _render_dashboard_page()
elif "实时选品" in page:
    _render_live_page(api_ok)
elif "指定选品" in page:
    _render_targeted_page(api_ok)
elif "市场扫描" in page:
    _render_market_scanner_page(api_ok)
elif "历史记录" in page:
    _render_history_page()
elif "新页面名" in page:           # ← 新增
    _render_<new_page>_page(api_ok)
```

### 4. Session State 初始化（如需）
如新页面需要额外的 session_state 变量，在底部初始化块中添加：
```python
if "new_state_var" not in st.session_state:
    st.session_state.new_state_var = None
```

**现有 session_state 变量：**
| 变量 | 类型 | 说明 |
|------|------|------|
| `products` | list | 当前加载的产品列表 |
| `results` | list | 当前分析结果列表 |
| `source_info` | dict/None | 数据来源信息 |
| `step` | str | 当前步骤：`idle` → `loaded` → `analyzed` |
| `analyzing` | bool | 分析中锁定按钮 |
| `history_data` | list | 当前会话历史记录 |
| `selected_products` | list | 选中的产品索引 |
| `comparison_indices` | list | 对比模式下的产品索引 |
| `favorite_asins` | set | 已收藏产品 ASIN 集合 |
| `active_platform` | str | 当前激活的平台 |
| `active_region` | str | 当前激活的地区 |
| `active_tab` | str | 当前子标签页 |
| `market_scan_results` | dict/None | 市场扫描结果 |
| `page_config` | dict | 页面配置缓存 |

### 5. 复用共享组件
页面中可复用的现有组件函数：

| 函数 | 用途 | 位置 |
|------|------|------|
| `_render_analysis_summary_table(products, results)` | 五维分析摘要表格 | ~line 296 |
| `_render_1688_result(result_1688)` | 1688 比价结果卡片 | ~line 331 |
| `_render_radar_chart(dim_data, title)` | Plotly 五维雷达图 | ~line 361 |
| `_render_favorite_button(product, platform, key)` | 收藏按钮 | ~line 393 |
| `_render_comparison_view(products, indices)` | 产品对比视图 | ~line 418 |
| `_render_history_list(total_count)` | 历史记录列表 | ~line 2347 |

### 可用页面函数

当前已存在的页面函数（参考命名和 `api_ok` 用法）：

| 函数 | 说明 |
|------|------|
| `_render_dashboard_page()` | Dashboard：数据概览 + TOP5 推荐 |
| `_render_live_page(api_ok)` | 实时选品页 |
| `_render_targeted_page(api_ok)` | 指定选品页 |
| `_render_market_scanner_page(api_ok)` | 市场扫描页（含子模式路由） |
| `_render_keyword_scan_mode(api_ok)` | 关键词扫描子模式 |
| `_render_hot_aggregation_mode(api_ok)` | 热品聚合子模式 |
| `_render_history_page()` | 历史记录页 |
| `_render_favorites_tab()` | 收藏夹页 |

### 6. 测试验证
```bash
python -m py_compile app.py
streamlit run app.py  # 手动验证页面切换和功能
```

### 7. 交付说明
告知用户：
- 新增了哪些组件
- 侧边栏新增了什么参数
- session_state 变量变化
- 页面的功能说明

## 注意事项
- 路由使用 `"关键词" in page` 模式（`page` 是完整字符串如 `"📊 Dashboard"`）
- `api_ok` 参数由 `render_sidebar()` 返回，表示 API 密钥是否配置正确
- 页面函数使用 `@st.fragment` 可实现局部刷新（按需使用）
- 样式通过 `.streamlit/style.css` 全局控制，一般不需要页面级 CSS
- 不修改现有页面的功能逻辑
