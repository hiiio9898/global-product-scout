# Spec 4：1688 比价

**版本**：v1.0
**状态**：✅ 已实现并验收通过
**最后更新**：2026-05-28

---

## 1. 需求描述

### 1.1 背景
跨境选品最经典的套利模型是"亚马逊 vs 1688 同款价差"。用户在查看产品分析时，希望能一键查看该产品在 1688 上的参考采购价，快速判断利润空间。

### 1.2 核心需求
1. 新建 `src/scraper_1688.py`，实现 `search_1688(keyword)` 函数
2. 使用产品标题关键词在 1688 搜索，提取前 3 个结果的价格
3. 返回价格区间（最低价～最高价）
4. 在 `app.py` 的产品 expander 中新增"🔍 查看1688参考价"按钮

### 1.3 反爬风险评估

| 风险 | 级别 | 应对 |
|------|------|------|
| 1688 页面为 JavaScript 动态渲染 | 🔴 高 | requests 无法获取完整 HTML，需降级 |
| IP 频率限制 | 🟡 中 | 请求间隔 3-5 秒，单次最多 3 个产品 |
| 验证码/登录墙 | 🔴 高 | 捕获异常，返回友好提示 |

**关键决策**：由于 1688 使用 JS 动态渲染，纯 requests 方案**大概率无法直接抓取**。Spec 采用"尝试 → 失败降级"策略：先用 requests 尝试，失败后返回提示信息，不影响主流程。

---

## 2. 系统设计

### 2.1 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `src/scraper_1688.py` | **新建** | 1688 搜索比价模块 |
| `app.py` | **修改** | 产品 expander 内新增"🔍 查看1688参考价"按钮 |

### 2.2 模块设计

```python
# src/scraper_1688.py

def search_1688(keyword: str, max_results: int = 3) -> dict:
    """
    在 1688 上搜索产品，返回价格区间。

    Args:
        keyword:     搜索关键词（产品标题）
        max_results: 最多返回几个结果

    Returns:
        {
            "success": bool,           # 是否成功
            "keyword": str,            # 搜索关键词
            "results": list[dict],     # 搜索结果列表
            "price_range": {
                "min": float,          # 最低价
                "max": float,          # 最高价
            },
            "error": str | None,       # 失败时的错误信息
        }
    """
```

### 2.3 UI 设计

产品 expander 内，利润试算区域下方：

```python
if st.button("🔍 查看1688参考价", key=f"1688_{i}"):
    with st.spinner("正在搜索 1688..."):
        result = search_1688(product_title[:30])  # 截取前 30 字作为关键词
    if result["success"]:
        st.caption(f"1688 参考价区间：¥{result['price_range']['min']:.2f} ~ ¥{result['price_range']['max']:.2f}")
        for item in result["results"]:
            st.caption(f"  • {item['title'][:40]} — ¥{item['price']}")
    else:
        st.warning(f"⚠️ {result['error']}")
```

---

## 3. 接口定义

### 3.1 `src/scraper_1688.py`

```python
def search_1688(keyword: str, max_results: int = 3) -> dict:
    """
    搜索 1688 并返回价格区间。

    使用 requests + BeautifulSoup 尝试抓取。
    1688 为 JS 动态渲染页面，requests 可能无法获取完整数据。
    失败时返回 success=False 和错误提示。

    Returns:
        {
            "success": bool,
            "keyword": str,
            "results": [{"title": str, "price": float, "moq": str}],
            "price_range": {"min": float, "max": float},
            "error": str | None,
        }
    """
```

**实现策略**：
1. 构造搜索 URL：`https://s.1688.com/selloffer/offer_search.htm?keywords={keyword}`
2. 设置真实浏览器 User-Agent + Cookie
3. 使用 requests 请求
4. 尝试解析 HTML（可能为空或被拦截）
5. 失败时返回 `{"success": False, "error": "1688 页面需要 JavaScript 渲染，暂时无法自动获取。建议手动搜索..."}`

---

## 4. 验收标准

| # | 验收条件 | 验证方法 |
|---|---------|---------|
| 1 | `search_1688()` 函数可正常调用 | 单元测试 |
| 2 | 成功时返回正确结构 | 模拟测试 |
| 3 | 失败时返回 success=False + 友好提示 | 模拟网络错误 |
| 4 | 产品 expander 内有"🔍 查看1688参考价"按钮 | UI 验证 |
| 5 | 点击按钮后显示结果或提示 | UI 验证 |
| 6 | 不影响主分析流程 | 主流程不受影响 |
| 7 | `python -m py_compile src/scraper_1688.py` 通过 | 终端执行 |
| 8 | `python -m py_compile app.py` 通过 | 终端执行 |

---

## 5. 不在本次范围内

- Selenium/Playwright 浏览器自动化抓取
- 1688 登录态维持
- 批量比价（所有产品同时查询）
- 采购成本自动填入利润计算器
