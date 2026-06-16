# Spec 34：全网站地区扫描热门产品（全站热扫）

**版本**：v1.0
**状态**：✅ 已实现
**创建日期**：2026-06-16
**前置依赖**：Spec 8（多平台基础）、Spec 23（扩展地区）、Spec 25（市场扫描）

---

## 1. 需求描述

### 1.1 背景
项目已能按**关键词**扫描多地区（`market_scanner.scan_market`），`daily_scrape --all-regions` 也能抓取各平台各地区热销榜，但**缺少一个在界面上一键扫描全平台×全地区热销榜、聚合出跨地区热门产品排行的功能**。用户想"不输入关键词，直接看现在各地区都在卖什么爆款"。

### 1.2 目标
- 新增「全站热扫」页面：一键扫描所有平台（Amazon/eBay/Alibaba/AliExpress）× 所有地区（共 18 站点）的 Best Sellers 热销榜
- 跨地区**聚合去重 + 热度排行**（按上榜地区数 + 评论数），找出"多地区通用爆款"
- 进度可见（逐站点进度），结果可保存到数据库

### 1.3 用户故事
- 作为卖家，我想一键看到"当前欧美日各站点都在热销什么"，发现跨地区机会品类
- 我不想逐个平台逐个地区手动切换查看

### 1.4 边界约束
- 全量扫描 18 站点较慢（每站点含浏览器渲染），UI 须有进度反馈
- 抓取失败的单站点跳过、标注，**不中断整体扫描**
- 复用现有各平台 `scraper_func`（`fetch_xxx_best_sellers`），**不重写抓取逻辑**
- 遵循 AGENTS.md：抓取延迟、错误隔离、每字段 try/except

---

## 2. 系统设计

### 2.1 改动文件清单
| 文件 | 类型 | 说明 |
|------|------|------|
| `src/regional_scanner.py` | **新建** | 全地区热销榜扫描 + 跨地区热度聚合 |
| `app.py` | 修改 | 新增 `_render_global_scan_page` + 侧边栏导航 + 路由 |

### 2.2 数据流
```
一键扫描 → 遍历 PLATFORMS × regions
  每站: scraper_func(region) → best_sellers 列表（标注 platform/region）
聚合: 按 title 归组 → 统计上榜地区数 + 累计评论数 → 热度分
排行 → 展示 Top N 跨地区热门产品
（可选）save_products 落库
```

### 2.3 复用现有基础设施
- 抓取：复用 `daily_scrape._load_scraper_func` 模式 + 各平台 `scraper_func`
- 平台/地区：复用 `platforms.PLATFORMS`、`get_region_info`
- 存储：复用 `database.save_products`（可选，存原始抓取结果）
- 展示：复用 `app.py` 的表格/卡片组件

### 2.4 与现有功能区别
| 功能 | 输入 | 扫描方式 |
|------|------|----------|
| 指定选品（Spec 7）| 关键词 | 单平台单地区**搜索** |
| 市场扫描（Spec 25）| 关键词 | 多平台多地区**关键词搜索**（蓝海分析）|
| **全站热扫（本 spec）**| 无 | 多平台多地区**热销榜抓取**（发现爆款）|

---

## 3. 接口设计

### 3.1 `src/regional_scanner.py`
```python
def scan_all_regions(
    platforms: list[str] | None = None,
    progress_callback: callable | None = None,
    max_per_region: int = 20,
) -> dict
    """
    扫描所有(或指定)平台×地区的 Best Sellers。
    progress_callback(done, total, label) 驱动进度条。
    Returns: {
        "scan_time": str, "total_sites": int, "success_sites": int,
        "products": [...],          # 全部抓到的产品（带 platform/region 标注）
        "errors": [(platform, region, error), ...],
    }
    """

def aggregate_hot_products(products: list[dict], top_n: int = 50) -> list[dict]
    """
    跨地区聚合去重 + 热度排行。
    按 title 归组，统计上榜地区数 + 累计评论数，算热度分排序。
    Returns: [{
        "title", "platforms": [...], "regions": [...],
        "region_count", "total_reviews", "hotness",
        "sample": {首个出现的产品样本含价格/图片/链接}
    }, ...]
    """
```

### 3.2 热度算法（v1，简单可解释）
```
hotness = region_count × 10 + log10(total_reviews + 1) × 5
```
- 上榜地区数越多 → 越通用（跨地区爆款）
- 累计评论数 → 体现需求量

---

## 4. 错误处理
- 单站点抓取异常 → 记录到 `errors`，继续下一站，不中断
- 全部站点失败 → 返回空 `products` + 全部 `errors`，UI 提示检查网络/反爬
- 进度回调异常 → 忽略，不中断扫描

---

## 5. 验收标准
- [ ] 「全站热扫」页面在侧边栏可见，点击进入
- [ ] 一键扫描显示逐站点进度（如 "3/18 🟠 Amazon 英国站"）
- [ ] 扫描完成后展示跨地区热门产品 Top N 排行（标题/上榜地区/评论数/热度）
- [ ] 可选勾选保存到数据库（`save_products`）
- [ ] 部分站点失败时，成功的站点结果仍正常展示，失败站点列出
- [ ] `python -m py_compile src/regional_scanner.py` 通过

---

## 6. 实施计划
1. 新建 `src/regional_scanner.py`（`scan_all_regions` + `aggregate_hot_products`）
2. `app.py` 新增 `_render_global_scan_page`（扫描按钮 + 进度 + 排行展示）
3. 侧边栏导航加「全站热扫」+ 路由分发
4. 本地 streamlit 验证：扫描 + 聚合 + 展示

---

## 7. 未来扩展
- 热度趋势：连续多日扫描对比，发现"新晋爆款"
- 一键对 Top 热门产品批量做五维度 AI 分析
- 按类目分组展示热门品类
- 后台定时扫描（复用 GitHub Actions daily_scrape）
