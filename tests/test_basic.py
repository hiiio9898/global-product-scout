"""
基础测试用例 — 覆盖配置、抓取、分析、工具函数四个核心模块。

运行方法：
    pytest tests/test_basic.py -v
    或：
    python tests/test_basic.py

所有测试均使用模拟数据，不依赖网络或真实 API Key。
"""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch
from src.scraper import (
    fetch_amazon_best_sellers,
    _load_cache,
    _save_cache,
)
from src.analyzer import (
    analyze_products,
    _parse_ai_response,
    _validate_result,
)
from src.config import get_config
from src.utils import (
    format_number,
    parse_price,
    parse_rating,
    parse_review_count,
    is_blocked,
    USER_AGENTS,
)


# ============================================================
# 测试用内联模拟数据
# ============================================================

SAMPLE_PRODUCTS = [
    {
        "title": "Portable Bluetooth Speaker",
        "price": 29.99,
        "rating": 4.5,
        "num_reviews": 15000,
        "rank": 1,
        "category": "Electronics",
        "asin": "B0CKLXYZ1A",
        "url": "https://www.amazon.com/dp/B0CKLXYZ1A",
    },
    {
        "title": "Wireless Earbuds Pro",
        "price": 49.99,
        "rating": 4.3,
        "num_reviews": 28000,
        "rank": 2,
        "category": "Electronics",
        "asin": "B0CKLXYZ2B",
        "url": "https://www.amazon.com/dp/B0CKLXYZ2B",
    },
    {
        "title": "USB-C Fast Charging Cable",
        "price": 9.99,
        "rating": 4.7,
        "num_reviews": 50000,
        "rank": 3,
        "category": "Accessories",
        "asin": "B0CKLXYZ3C",
        "url": "https://www.amazon.com/dp/B0CKLXYZ3C",
    },
    {
        "title": "Laptop Stand Aluminum",
        "price": 34.99,
        "rating": 4.1,
        "num_reviews": 8200,
        "rank": 4,
        "category": "Office",
        "asin": "B0CKLXYZ4D",
        "url": "https://www.amazon.com/dp/B0CKLXYZ4D",
    },
    {
        "title": "LED Desk Lamp Dimmable",
        "price": 22.99,
        "rating": 4.6,
        "num_reviews": 12000,
        "rank": 5,
        "category": "Home & Kitchen",
        "asin": "B0CKLXYZ5E",
        "url": "https://www.amazon.com/dp/B0CKLXYZ5E",
    },
]

# 模拟 AI 返回的完整 JSON
SAMPLE_AI_RESPONSE = json.dumps({
    "market_capacity": {"score": 8, "reason": "市场容量大，需求持续增长"},
    "competition": {"score": 5, "reason": "中等竞争，头部品牌集中"},
    "profit_potential": {"score": 7, "reason": "利润空间可观，FBA 费用可控"},
    "beginner_friendly": {"score": 9, "reason": "入手门槛低，供应链成熟"},
    "seasonality_risk": {"score": 2, "reason": "无明显季节波动"},
    "final_verdict": "recommended",
    "verdict_reason": "综合评分高，市场前景好，适合新手入场",
})


class TestConfig:
    """配置模块测试 — 验证 .env 加载和默认值。"""

    def test_get_config_returns_dict(self):
        """get_config() 返回字典且包含所有必要键。"""
        cfg = get_config()
        assert isinstance(cfg, dict)
        for key in ["deepseek_api_key", "deepseek_model", "scrape_delay", "amazon_url"]:
            assert key in cfg, f"缺少配置键: {key}"

    def test_config_default_values(self):
        """验证无 .env 文件时配置默认值正确。"""
        cfg = get_config()
        assert cfg["deepseek_model"] == "deepseek-chat"
        assert cfg["scrape_delay"] == 2.0
        assert "amazon.com" in cfg["amazon_url"]


class TestScraper:
    """数据抓取模块测试 — 验证返回格式、字段完整性、缓存机制。"""

    def test_fetch_returns_tuple(self):
        """fetch_amazon_best_sellers() 返回 (products, source_info) 元组。"""
        products, source_info = fetch_amazon_best_sellers()
        assert isinstance(products, list)
        assert isinstance(source_info, dict)
        assert "source" in source_info
        assert "timestamp" in source_info
        assert source_info["source"] in ("live", "cache", "unavailable")

    def test_sample_products_have_required_fields(self):
        """模拟数据中每个产品必须包含必要字段且类型正确。"""
        for p in SAMPLE_PRODUCTS:
            assert "title" in p
            assert "price" in p
            assert "rating" in p
            assert "num_reviews" in p
            assert "rank" in p
            assert "category" in p
            assert isinstance(p["title"], str) and p["title"]
            assert isinstance(p["price"], (int, float)) and p["price"] > 0
            assert 1.0 <= p["rating"] <= 5.0
            assert isinstance(p["num_reviews"], int) and p["num_reviews"] > 0
            assert isinstance(p["rank"], int) and p["rank"] >= 1

    def test_cache_write_and_read(self):
        """缓存写入后可成功读取，且数据一致。"""
        _save_cache(SAMPLE_PRODUCTS)
        cached = _load_cache()
        assert cached is not None
        assert len(cached) == len(SAMPLE_PRODUCTS)
        assert cached[0]["title"] == SAMPLE_PRODUCTS[0]["title"]


class TestAnalyzer:
    """分析模块测试 — 五维度评分结构 + 降级 + JSON 解析容错。"""

    # ---- 结构校验（通过 _parse_ai_response 测试） ----

    def test_parse_ai_response_returns_five_dimensions(self):
        """AI 响应解析后应包含 market_capacity 等 5 个维度。"""
        result = _parse_ai_response(SAMPLE_AI_RESPONSE, "Test Bluetooth Speaker")
        dims = [
            "market_capacity", "competition", "profit_potential",
            "beginner_friendly", "seasonality_risk",
        ]
        for dim in dims:
            assert dim in result, f"缺少维度: {dim}"
            assert isinstance(result[dim], dict), f"{dim} 应为字典"
            assert "score" in result[dim], f"{dim} 缺少 score"
            assert "reason" in result[dim], f"{dim} 缺少 reason"
            assert 1 <= result[dim]["score"] <= 10, f"{dim} score 超出范围"

    def test_parse_ai_response_has_verdict(self):
        """AI 响应解析后必须包含 final_verdict 和 verdict_reason。"""
        result = _parse_ai_response(SAMPLE_AI_RESPONSE, "Test Pillow")
        assert result["final_verdict"] in ("recommended", "cautious", "not_recommended")
        assert isinstance(result["verdict_reason"], str) and len(result["verdict_reason"]) > 0

    def test_title_preserved(self):
        """分析结果中的 title 应与输入一致。"""
        result = _parse_ai_response(SAMPLE_AI_RESPONSE, "Unique Product XYZ")
        assert result["title"] == "Unique Product XYZ"

    # ---- 无 API Key 降级 ----

    def test_analyze_products_no_api_key(self):
        """无 API Key 时返回错误提示结果，数量与输入一致。"""
        mock_cfg = {"api_key": "", "base_url": "", "model": "test"}
        with patch("src.analyzer.get_llm_config", return_value=mock_cfg):
            results = analyze_products(SAMPLE_PRODUCTS[:3])
        assert len(results) == 3
        for r in results:
            assert "title" in r
            assert "final_verdict" in r
            # 无 API Key 时返回 cautious verdict + 错误信息
            assert r["final_verdict"] == "cautious"
            assert r.get("parse_error") is True

    # ---- JSON 解析容错 ----

    def test_parse_valid_json(self):
        """正确格式的 JSON 应成功解析。"""
        result = _parse_ai_response(SAMPLE_AI_RESPONSE, "Test Product")
        assert result["title"] == "Test Product"
        assert result["final_verdict"] == "recommended"
        assert result["market_capacity"]["score"] == 8

    def test_parse_markdown_wrapped_json(self):
        """被 ```json 包裹的 JSON 应正确清洗后解析。"""
        wrapped = '```json\n{"market_capacity":{"score":7,"reason":"t"},"competition":{"score":4,"reason":"t"},"profit_potential":{"score":6,"reason":"t"},"beginner_friendly":{"score":8,"reason":"t"},"seasonality_risk":{"score":3,"reason":"t"},"final_verdict":"cautious","verdict_reason":"t"}\n```'
        result = _parse_ai_response(wrapped, "Wrapped Product")
        assert result["title"] == "Wrapped Product"
        assert result["final_verdict"] == "cautious"
        assert not result.get("parse_error")

    def test_parse_invalid_returns_raw(self):
        """无法解析的文本应回退为 raw_text。"""
        garbage = "这是一段完全不可解析的中文文本，不包含任何 JSON 结构"
        result = _parse_ai_response(garbage, "Bad Product")
        assert result["title"] == "Bad Product"
        assert result.get("parse_error") is True
        assert "raw_text" in result

    def test_validate_missing_dimension_fails(self):
        """缺少必填维度的数据应校验失败。"""
        bad_data = {"final_verdict": "recommended"}
        assert not _validate_result(bad_data)

    def test_validate_complete_data_passes(self):
        """完整数据应通过校验。"""
        good_data = {
            "market_capacity": {"score": 5, "reason": "ok"},
            "competition": {"score": 5, "reason": "ok"},
            "profit_potential": {"score": 5, "reason": "ok"},
            "beginner_friendly": {"score": 5, "reason": "ok"},
            "seasonality_risk": {"score": 5, "reason": "ok"},
            "final_verdict": "cautious",
            "verdict_reason": "test",
        }
        assert _validate_result(good_data)


class TestUtils:
    """工具函数测试 — format_number、parse_price、parse_rating、parse_review_count、is_blocked。"""

    # ---- format_number ----

    def test_format_number_thousands(self):
        """千位数格式化为 x.xk。"""
        assert format_number(12345) == "12.3k"
        assert format_number(1000) == "1.0k"

    def test_format_number_millions(self):
        """百万级格式化为 x.xM。"""
        assert format_number(1500000) == "1.5M"

    def test_format_number_small(self):
        """小于 1000 的数字保持原样。"""
        assert format_number(999) == "999"
        assert format_number(0) == "0"

    # ---- parse_price ----

    def test_parse_price_usd(self):
        """解析 USD 价格。"""
        assert parse_price("$29.99") == 29.99
        assert parse_price("USD 100") == 100.0

    def test_parse_price_jpy(self):
        """解析 JPY 价格并自动换算。"""
        # JPY 15000 → 100.0 USD（¥ 符号匹配 CNY，需用 JPY 前缀）
        result = parse_price("JPY15,000")
        assert result is not None
        assert abs(result - 100.0) < 1.0

    def test_parse_price_none(self):
        """空输入返回 None。"""
        assert parse_price("") is None
        assert parse_price(None) is None

    # ---- parse_rating ----

    def test_parse_rating_normal(self):
        """正常评分文本提取。"""
        assert parse_rating("4.5 out of 5 stars") == 4.5
        assert parse_rating("3.0") == 3.0

    def test_parse_rating_none(self):
        """空输入返回 None。"""
        assert parse_rating("") is None
        assert parse_rating(None) is None

    # ---- parse_review_count ----

    def test_parse_review_count_normal(self):
        """正常评论数提取。"""
        assert parse_review_count("12,345") == 12345
        assert parse_review_count("100") == 100

    def test_parse_review_count_empty(self):
        """空输入返回 0。"""
        assert parse_review_count("") == 0
        assert parse_review_count(None) == 0

    # ---- is_blocked ----

    def test_is_blocked_captcha(self):
        """包含 captcha 关键词应判定为被拦截。"""
        assert is_blocked("<html>please complete the captcha</html>") is True

    def test_is_blocked_robot_check(self):
        """包含 Robot Check 应判定为被拦截。"""
        assert is_blocked("<html><title>Robot Check</title></html>") is True

    def test_is_blocked_normal_page(self):
        """正常页面不应被判定为拦截。"""
        assert is_blocked("<html><title>Best Sellers</title></html>") is False

    # ---- USER_AGENTS ----

    def test_user_agents_not_empty(self):
        """User-Agent 池不应为空。"""
        assert len(USER_AGENTS) > 0
        for ua in USER_AGENTS:
            assert "Mozilla" in ua


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
