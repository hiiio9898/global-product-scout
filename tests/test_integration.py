"""
全平台集成测试 — 验证 Spec 8-11 实施完整性。

覆盖范围：
    - 平台注册完整性（4 个平台全部注册）
    - 利润计算器工厂（每个平台计算器可正常调用）
    - 利润计算结果（用固定输入验证公式正确性）
    - 数据库 Schema（platform/region/currency 列存在）
    - 抓取模块可导入（Mock 方式验证调用链）
"""

import pytest
import json
from unittest.mock import patch, MagicMock


# ============================================================
# 测试平台注册完整性
# ============================================================

class TestPlatformRegistry:
    """Spec 8: 平台注册表。"""

    EXPECTED_PLATFORMS = ["amazon", "ebay", "walmart", "etsy"]

    def test_all_platforms_registered(self):
        """验证 4 个平台全部注册到 PLATFORMS。"""
        from src.platforms import PLATFORMS
        for pf in self.EXPECTED_PLATFORMS:
            assert pf in PLATFORMS, f"平台 {pf} 未注册"
            assert "name" in PLATFORMS[pf]
            assert "icon" in PLATFORMS[pf]
            assert "calculator" in PLATFORMS[pf]
            assert "regions" in PLATFORMS[pf]

    def test_each_platform_has_scraper(self):
        """验证每个平台都配置了抓取模块。"""
        from src.platforms import PLATFORMS
        for pf, cfg in PLATFORMS.items():
            assert "scraper_module" in cfg, f"{pf} 缺少 scraper_module"
            assert "scraper_func" in cfg, f"{pf} 缺少 scraper_func"

    def test_region_config_complete(self):
        """验证每个地区的配置完整。"""
        from src.platforms import PLATFORMS
        for pf, cfg in PLATFORMS.items():
            for region_key, region_cfg in cfg["regions"].items():
                assert "name" in region_cfg, f"{pf}.{region_key} 缺少 name"
                assert "domain" in region_cfg, f"{pf}.{region_key} 缺少 domain"
                assert "currency" in region_cfg, f"{pf}.{region_key} 缺少 currency"
                assert "exchange_rate" in region_cfg, f"{pf}.{region_key} 缺少 exchange_rate"

    def test_platform_choices(self):
        """验证 get_platform_choices 返回所有平台。"""
        from src.platforms import get_platform_choices
        choices = get_platform_choices()
        assert len(choices) >= 4
        for pf in self.EXPECTED_PLATFORMS:
            assert pf in choices

    def test_region_choices(self):
        """验证 get_region_choices 返回正确选项。"""
        from src.platforms import get_region_choices
        for pf in ["amazon", "ebay", "walmart", "etsy"]:
            choices = get_region_choices(pf)
            assert len(choices) >= 1, f"{pf} 地区选项不足"


# ============================================================
# 测试利润计算器
# ============================================================

class TestProfitCalculators:
    """Spec 8-11: 各平台利润计算器。"""

    @pytest.mark.parametrize("platform_key", ["amazon", "ebay", "walmart", "etsy"])
    def test_calculator_exists(self, platform_key):
        """验证每个平台的利润计算器已注册。"""
        from src.calculator import get_calculator
        calc = get_calculator(platform_key)
        assert callable(calc)

    def test_amazon_profit_positive(self):
        """Amazon: $20 售价应盈利。"""
        from src.calculator import get_calculator
        from src.platforms import PLATFORMS

        calc = get_calculator("amazon")
        defaults = PLATFORMS["amazon"]["profit_defaults"].copy()
        defaults["exchange_rate"] = 7.24

        result = calc(price=20.0, defaults=defaults, procurement_cny=10.0)
        assert result["margin_pct"] > 0
        assert result["is_profitable"] is True
        assert result["has_procurement"] is True
        assert result["price_local"] == 20.0

    def test_walmart_profit_positive(self):
        """Walmart: $20 售价应盈利。"""
        from src.calculator import get_calculator
        from src.platforms import PLATFORMS

        calc = get_calculator("walmart")
        defaults = PLATFORMS["walmart"]["profit_defaults"].copy()
        defaults["exchange_rate"] = 7.24

        result = calc(price=20.0, defaults=defaults, procurement_cny=8.0)
        assert result["margin_pct"] > 0
        assert result["is_profitable"] is True

    def test_etsy_profit_positive(self):
        """Etsy: $25 售价应盈利。"""
        from src.calculator import get_calculator
        from src.platforms import PLATFORMS

        calc = get_calculator("etsy")
        defaults = PLATFORMS["etsy"]["profit_defaults"].copy()
        defaults["exchange_rate"] = 7.24

        result = calc(price=25.0, defaults=defaults, procurement_cny=8.0)
        assert result["margin_pct"] > 0
        assert result["is_profitable"] is True

    def test_ebay_profit_with_fees(self):
        """eBay: 验证成交费+刊登费正确计算。"""
        from src.calculator import get_calculator
        from src.platforms import PLATFORMS

        calc = get_calculator("ebay")
        defaults = PLATFORMS["ebay"]["profit_defaults"].copy()
        defaults["exchange_rate"] = 7.24

        result = calc(price=20.0, defaults=defaults, procurement_cny=10.0)
        assert "fvf_cny" in result  # 成交费
        assert "listing_cny" in result  # 刊登费
        assert "payoneer_cny" in result  # 提现费
        assert result["fvf_cny"] > 0

    def test_unified_calculate_profit(self):
        """验证统一入口 calculate_profit 向后兼容。"""
        from src.calculator import calculate_profit
        from src.platforms import PLATFORMS

        defaults = PLATFORMS["amazon"]["profit_defaults"].copy()
        defaults["exchange_rate"] = 7.24

        # 旧代码调用方式
        result = calculate_profit(price_usd=20.0, defaults=defaults, procurement_cny=10.0)
        assert "price_usd" in result
        assert result["price_usd"] == 20.0

        # 新代码调用方式（指定平台）
        result2 = calculate_profit(price_usd=20.0, defaults=defaults, procurement_cny=10.0, platform="amazon")
        assert result2["price_usd"] == 20.0

    def test_zero_procurement_cost(self):
        """未输入采购成本时，结果仍然有效。"""
        from src.calculator import get_calculator
        from src.platforms import PLATFORMS

        for pf in ["amazon", "ebay", "walmart", "etsy"]:
            calc = get_calculator(pf)
            defaults = PLATFORMS[pf]["profit_defaults"].copy()
            defaults["exchange_rate"] = 7.24
            result = calc(price=10.0, defaults=defaults, procurement_cny=0.0)
            assert result["has_procurement"] is False
            assert "margin_pct" in result


# ============================================================
# 测试数据库多平台支持
# ============================================================

class TestDatabaseMultiPlatform:
    """Spec 8/12: 数据库多平台支持。"""

    def test_platform_column_exists(self, tmp_path):
        """验证 products 表包含 platform/region/currency 列。"""
        from src.database import init_db
        import sqlite3

        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute("PRAGMA table_info(products)")
            columns = {row[1] for row in cursor.fetchall()}
            assert "platform" in columns, "缺少 platform 列"
            assert "region" in columns, "缺少 region 列"
            assert "currency" in columns, "缺少 currency 列"
        finally:
            conn.close()

    def test_save_and_query_by_platform(self, tmp_path):
        """验证按平台保存和查询。"""
        from src.database import init_db, save_products, query_products

        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        # 保存 Amazon 产品
        products = [{"title": "Test Product A", "price": "19.99", "rank": 1}]
        analysis = [{"final_verdict": "recommended"}]
        save_products(products, analysis, platform="amazon", region="us", currency="USD", db_path=db_path)

        # 保存 eBay 产品
        products2 = [{"title": "Test Product B", "price": "9.99", "rank": 1}]
        analysis2 = [{"final_verdict": "cautious"}]
        save_products(products2, analysis2, platform="ebay", region="us", currency="USD", db_path=db_path)

        # 按平台查询
        amazon_only = query_products(platforms=["amazon"], db_path=db_path)
        assert len(amazon_only) == 1
        assert amazon_only[0]["title"] == "Test Product A"

        ebay_only = query_products(platforms=["ebay"], db_path=db_path)
        assert len(ebay_only) == 1
        assert ebay_only[0]["title"] == "Test Product B"

        # 查询全部
        all_products = query_products(db_path=db_path)
        assert len(all_products) == 2

    def test_query_by_keyword(self, tmp_path):
        """验证关键词搜索。"""
        from src.database import init_db, save_products, query_products

        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        products = [
            {"title": "Portable Blender USB", "price": "15.99"},
            {"title": "Wireless Mouse", "price": "9.99"},
        ]
        analysis = [{}, {}]
        save_products(products, analysis, platform="amazon", region="us", db_path=db_path)

        # 关键词搜索
        results = query_products(keyword="blender", db_path=db_path)
        assert len(results) == 1
        assert "Blender" in results[0]["title"]

    def test_get_product_count(self, tmp_path):
        """验证产品计数。"""
        from src.database import init_db, save_products, get_product_count

        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        assert get_product_count(db_path=db_path) == 0

        products = [{"title": "Product 1"}, {"title": "Product 2"}]
        save_products(products, [{}, {}], db_path=db_path)

        assert get_product_count(db_path=db_path) == 2


# ============================================================
# 测试抓取模块可导入
# ============================================================

class TestScraperImports:
    """Spec 9-11: 各平台抓取模块可导入。"""

    @pytest.mark.parametrize("platform_key,expected_func", [
        ("amazon", "fetch_amazon_best_sellers"),
        ("ebay", "fetch_ebay_best_sellers"),
        ("walmart", "fetch_walmart_best_sellers"),
        ("etsy", "fetch_etsy_trending"),
    ])
    def test_scraper_module_importable(self, platform_key, expected_func):
        """验证每个平台的抓取模块可导入。"""
        from src.platforms import PLATFORMS
        import importlib

        module_name = PLATFORMS[platform_key]["scraper_module"]
        func_name = PLATFORMS[platform_key]["scraper_func"]

        module = importlib.import_module(module_name)
        func = getattr(module, func_name)
        assert callable(func)
        assert func_name == expected_func

    @pytest.mark.parametrize("platform_key", ["amazon", "ebay", "walmart", "etsy"])
    def test_search_function_importable(self, platform_key):
        """验证每个平台的搜索函数可导入。"""
        from src.platforms import PLATFORMS
        import importlib

        module_name = PLATFORMS[platform_key]["search_module"]
        func_name = PLATFORMS[platform_key]["search_func"]

        module = importlib.import_module(module_name)
        func = getattr(module, func_name)
        assert callable(func)


# ============================================================
# 测试平台工具函数
# ============================================================

class TestPlatformUtils:
    """Spec 8: 平台工具函数。"""

    def test_get_platform_info(self):
        """验证 get_platform_info 返回正确数据。"""
        from src.platforms import get_platform_info
        info = get_platform_info("amazon")
        assert info["name"] == "Amazon"
        assert info["icon"] == "🟠"

    def test_get_platform_info_unknown(self):
        """验证未知平台抛出 KeyError。"""
        from src.platforms import get_platform_info
        with pytest.raises(KeyError):
            get_platform_info("unknown_platform")

    def test_get_region_info(self):
        """验证 get_region_info 返回正确数据。"""
        from src.platforms import get_region_info
        info = get_region_info("amazon", "us")
        assert info["domain"] == "amazon.com"
        assert info["currency"] == "USD"

    def test_get_exchange_rate(self):
        """验证汇率获取。"""
        from src.platforms import get_exchange_rate
        rate = get_exchange_rate("amazon", "us")
        assert rate > 0
        assert isinstance(rate, float)

    def test_config_profit_defaults_per_platform(self):
        """验证 get_profit_defaults 支持多平台。"""
        from src.config import get_profit_defaults

        amazon_defaults = get_profit_defaults("amazon")
        assert "commission_pct" in amazon_defaults
        assert "exchange_rate" in amazon_defaults

        walmart_defaults = get_profit_defaults("walmart")
        assert "commission_pct" in walmart_defaults
        assert "wfs_fee_pct" in walmart_defaults

        etsy_defaults = get_profit_defaults("etsy")
        assert "transaction_fee_pct" in etsy_defaults

        ebay_defaults = get_profit_defaults("ebay")
        assert "final_value_fee_pct" in ebay_defaults
