"""Tests for the FitBites Premium Pricing Engine."""
import pytest
from collections import Counter
from src.services.pricing import PricingEngine, Tier, PricingExperiment, PricingVariant


@pytest.fixture
def engine():
    return PricingEngine()


class TestTierPricing:
    def test_free_tier_is_zero(self, engine):
        p = engine.get_pricing("user1", Tier.FREE, "web")
        assert p["price_monthly"] == 0
        assert p["price_annual"] == 0

    def test_pro_web_cheaper_than_app(self, engine):
        """Web checkout avoids Apple's 15% fee."""
        # Disable experiments to test base pricing
        engine.experiments = {}
        web = engine.get_pricing("user1", Tier.PRO, "web")
        ios = engine.get_pricing("user1", Tier.PRO, "ios")
        assert web["price_monthly"] < ios["price_monthly"]
        assert web["price_annual"] < ios["price_annual"]

    def test_annual_savings(self, engine):
        engine.experiments = {}
        p = engine.get_pricing("user1", Tier.PRO, "web")
        assert p["annual_savings_pct"] > 0
        assert p["price_annual_per_month"] < p["price_monthly"]

    def test_all_tiers_returns_three(self, engine):
        tiers = engine.get_all_tiers("user1", "web")
        assert len(tiers) == 3
        tier_names = [t["tier"] for t in tiers]
        assert "free" in tier_names
        assert "pro" in tier_names
        assert "pro_plus" in tier_names

    def test_apple_product_id_only_on_app(self, engine):
        engine.experiments = {}
        web = engine.get_pricing("user1", Tier.PRO, "web")
        ios = engine.get_pricing("user1", Tier.PRO, "ios")
        assert web["apple_product_id"] is None
        assert ios["apple_product_id"] == "com.83apps.fitbites.pro.monthly"


class TestABTesting:
    def test_deterministic_assignment(self, engine):
        """Same user always gets same variant."""
        p1 = engine.get_pricing("user_test", Tier.PRO, "web")
        p2 = engine.get_pricing("user_test", Tier.PRO, "web")
        assert p1["variant"] == p2["variant"]
        assert p1["price_monthly"] == p2["price_monthly"]

    def test_even_distribution(self, engine):
        """Variants distribute roughly evenly across 1000 users."""
        variants = Counter()
        for i in range(1000):
            p = engine.get_pricing(f"user_{i:06d}", Tier.PRO, "web")
            variants[p["variant"]] += 1
        # Each variant should be 25-42% (with 3 variants at ~33% each)
        for v, count in variants.items():
            assert 250 < count < 420, f"Variant {v} got {count}/1000 — too skewed"

    def test_no_experiment_returns_default(self, engine):
        """Tiers without experiments get default pricing."""
        p = engine.get_pricing("user1", Tier.PRO_PLUS, "web")
        assert p["variant"] == "default"
        assert p["experiment"] is None
        assert p["price_monthly"] == 9.99

    def test_disabled_experiment_returns_default(self, engine):
        for exp in engine.experiments.values():
            exp.is_active = False
        p = engine.get_pricing("user1", Tier.PRO, "web")
        assert p["variant"] == "default"


class TestLimits:
    def test_under_limit_allowed(self, engine):
        result = engine.check_limit(Tier.FREE, "saved_recipes", 5)
        assert result["allowed"] is True
        assert result["remaining"] == 5

    def test_at_limit_blocked(self, engine):
        result = engine.check_limit(Tier.FREE, "saved_recipes", 10)
        assert result["allowed"] is False
        assert result["remaining"] == 0

    def test_pro_unlimited(self, engine):
        result = engine.check_limit(Tier.PRO, "saved_recipes", 9999)
        assert result["allowed"] is True
        assert result["limit"] is None

    def test_near_limit_shows_message(self, engine):
        result = engine.check_limit(Tier.FREE, "saved_recipes", 9)
        assert result["message"] is not None
        assert "9/10" in result["message"]

    def test_far_from_limit_no_message(self, engine):
        result = engine.check_limit(Tier.FREE, "saved_recipes", 3)
        assert result["message"] is None
