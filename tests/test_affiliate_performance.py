"""Tests for the FitBites Affiliate Performance Tracker."""
import pytest

from src.services.affiliate_performance import (
    PARTNER_COMMISSIONS,
    estimate_commission,
    get_partner_info,
    generate_recommendations,
)


class TestPartnerCommissions:
    """Verify commission configuration for all partners."""

    def test_all_partners_defined(self):
        expected = {"amazon", "iherb", "thrive_market", "instacart", "hellofresh", "factor"}
        assert expected == set(PARTNER_COMMISSIONS.keys())

    def test_each_partner_has_type(self):
        for name, config in PARTNER_COMMISSIONS.items():
            assert config["type"] in ("cps", "cpa"), f"{name} has invalid type"

    def test_each_partner_has_rates(self):
        for name, config in PARTNER_COMMISSIONS.items():
            assert "default" in config["rates"], f"{name} missing default rate"

    def test_each_partner_has_cookie_days(self):
        for name, config in PARTNER_COMMISSIONS.items():
            assert config["cookie_days"] > 0, f"{name} has invalid cookie days"


class TestEstimateCommission:
    """Verify commission estimation logic."""

    def test_amazon_grocery_is_1_percent(self):
        commission = estimate_commission("amazon", "grocery", 100.0)
        assert commission == pytest.approx(1.0)

    def test_amazon_kitchen_is_3_percent(self):
        commission = estimate_commission("amazon", "kitchen", 100.0)
        assert commission == pytest.approx(3.0)

    def test_amazon_default_uses_avg_order(self):
        commission = estimate_commission("amazon")
        assert commission == pytest.approx(35.0 * 0.02)  # $35 * 2%

    def test_iherb_is_5_percent(self):
        commission = estimate_commission("iherb", "default", 40.0)
        assert commission == pytest.approx(2.0)

    def test_thrive_is_cpa_flat(self):
        commission = estimate_commission("thrive_market")
        assert commission == 10.0  # default CPA

    def test_factor_is_25_cpa(self):
        commission = estimate_commission("factor", "new_customer")
        assert commission == 25.0

    def test_hellofresh_is_10_cpa(self):
        commission = estimate_commission("hellofresh", "new_customer")
        assert commission == 10.0

    def test_unknown_partner_falls_back(self):
        commission = estimate_commission("unknown_partner")
        # Falls back to amazon
        assert commission > 0

    def test_cpa_partners_earn_more_per_conversion(self):
        """CPA partners should generally earn more per conversion than CPS."""
        amazon_earn = estimate_commission("amazon")
        factor_earn = estimate_commission("factor")
        assert factor_earn > amazon_earn * 5  # Factor should be way more


class TestGetPartnerInfo:
    """Verify partner info retrieval."""

    def test_known_partner(self):
        info = get_partner_info("amazon")
        assert info["partner"] == "amazon"
        assert info["type"] == "cps"
        assert "rates" in info

    def test_unknown_partner(self):
        info = get_partner_info("nonexistent")
        assert info["type"] == "unknown"


class TestOptimizationRecommendations:
    """Test the recommendation engine."""

    def test_empty_stats_suggests_add_partners(self):
        recs = generate_recommendations({}, [])
        # Should recommend adding high-value CPA partners
        assert any(r["type"] == "partner_gap" for r in recs)

    def test_amazon_heavy_suggests_diversification(self):
        stats = {"amazon": {"clicks": 900, "conversions": 30}}
        recs = generate_recommendations(stats, [])
        assert any(r["type"] == "diversification" for r in recs)

    def test_balanced_portfolio_no_diversification_warning(self):
        stats = {
            "amazon": {"clicks": 200, "conversions": 10},
            "iherb": {"clicks": 200, "conversions": 10},
            "thrive_market": {"clicks": 200, "conversions": 10},
            "instacart": {"clicks": 200, "conversions": 10},
            "factor": {"clicks": 100, "conversions": 5},
            "hellofresh": {"clicks": 100, "conversions": 5},
        }
        recs = generate_recommendations(stats, [])
        assert not any(r["type"] == "diversification" for r in recs)
        assert not any(r["type"] == "partner_gap" for r in recs)

    def test_low_ctr_recipe_flagged(self):
        recipe_stats = [
            {"title": "Protein Pancakes", "views": 500, "affiliate_clicks": 10},
        ]
        recs = generate_recommendations({}, recipe_stats)
        assert any(r["type"] == "ctr_optimization" for r in recs)

    def test_recommendations_capped(self):
        """Don't generate more than ~8 recommendations."""
        recipes = [
            {"title": f"Recipe {i}", "views": 500, "affiliate_clicks": 1}
            for i in range(20)
        ]
        recs = generate_recommendations({}, recipes)
        assert len(recs) <= 10  # Some headroom


class TestRouterEndpoints:
    def test_all_endpoints_exist(self):
        from src.services.affiliate_performance import router
        paths = [r.path for r in router.routes]
        assert any(p.endswith("/performance") for p in paths)
        assert any("/top-recipes" in p for p in paths)
        assert any("/partners" in p for p in paths)
        assert any("/optimize" in p for p in paths)
