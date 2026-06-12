# Spec 27：产品URL与图片展示

**版本**：v1.0
**状态**：📋 待实现
**创建日期**：2026-06-10

---

## 1. 需求描述

### 1.1 背景
products.json 中没有产品URL和图片URL，用户无法点击进入原页面验证产品，也无法分享给供应商。eBay/Alibaba scraper已有url/image字段，但Amazon scraper未提取。

### 1.2 核心需求
1. 所有scraper提取产品URL和图片URL
2. 分析卡片中展示产品缩略图
3. 产品标题可点击跳转到原页面
4. products.json导出包含url和image字段

---

## 2. 系统设计

### 2.1 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `src/scraper.py` | **修改** | `_parse_product_card()` 提取产品URL和图片URL |
| `src/scraper_search.py` | **修改** | 同上 |
| `src/database.py` | **修改** | `save_products()` 保存url/image字段；`get_latest_products()` 导出 |
| `app.py` | **修改** | 分析卡片展示缩略图+可点击标题 |

### 2.2 Amazon URL提取

```python
# _parse_product_card() 中
link_elem = card.css("a.a-link-normal").first
if link_elem:
    href = link_elem.attrib.get("href", "")
    if href.startswith("/"):
        href = f"https://www.amazon.com{href}"
    product["url"] = href

img_elem = card.css("img").first
if img_elem:
    product["image"] = img_elem.attrib.get("src", "")
```

### 2.3 数据库Schema

```sql
ALTER TABLE products ADD COLUMN url TEXT DEFAULT '';
ALTER TABLE products ADD COLUMN image TEXT DEFAULT '';
```

---

## 3. 验收标准

- [ ] Amazon scraper提取url和image
- [ ] eBay/Alibaba scraper的url/image正确保存到DB
- [ ] 分析卡片展示产品缩略图
- [ ] 产品标题可点击跳转
- [ ] products.json包含url和image字段
- [ ] 所有现有测试通过
