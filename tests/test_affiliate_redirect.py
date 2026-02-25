"""Tests for the affiliate link redirect & tracking service."""
import time
import pytest
from src.services.affiliate_redirect import (
    _generate_link_id,
    create_tracked_link,
    create_tracked_links_for_recipe,
    store_link,
    store_links,
    lookup_link,
    record_click,
    get_click_stats,
    cleanup_expired,
    _link_cache,
    _click_log,
    TrackedLink,
)


@pytest.fixture(autouse=True)
def clear_state():
    """Clear caches between tests."""
    _link_cache.clear()
    _click_log.clear()
    yield
    _link_cache.clear()
    _click_log.clear()


# ── Link ID Generation ──────────────────────────────────────────────────────

class TestLinkIdGeneration:
    def test_deterministic(self):
        id1 = _generate_link_id("recipe-1", "chicken breast", "amazon")
        id2 = _generate_link_id("recipe-1", "chicken breast", "amazon")
        assert id1 == id2

    def test_different_inputs_different_ids(self):
        id1 = _generate_link_id("recipe-1", "chicken breast", "amazon")
        id2 = _generate_link_id("recipe-1", "chicken breast", "instacart")
        id3 = _generate_link_id("recipe-2", "chicken breast", "amazon")
        assert id1 != id2
        assert id1 != id3

    def test_length_is_12(self):
        lid = _generate_link_id("r", "i", "p")
        assert len(lid) == 12

    def test_hex_characters_only(self):
        lid = _generate_link_id("recipe-1", "oats", "amazon")
        assert all(c in "0123456789abcdef" for c in lid)


# ── Tracked Link Creation ───────────────────────────────────────────────────

class TestCreateTrackedLink:
    def test_basic_creation(self):
        link = create_tracked_link(
            recipe_id="recipe-1",
            ingredient="chicken breast",
            provider="amazon",
            destination_url="https://amazon.com/dp/B123?tag=83apps01-20",
            commission_pct=0.04,
        )
        assert link.provider == "amazon"
        assert link.ingredient == "chicken breast"
        assert link.recipe_id == "recipe-1"
        assert link.commission_pct == 0.04
        assert link.redirect_url == f"/go/{link.link_id}"
        assert link.destination_url == "https://amazon.com/dp/B123?tag=83apps01-20"

    def test_with_base_url(self):
        link = create_tracked_link(
            recipe_id="r1",
            ingredient="oats",
            provider="instacart",
            destination_url="https://instacart.com/search/oats",
            commission_pct=0.10,
            base_url="https://api.fitbites.app",
        )
        assert link.redirect_url.startswith("https://api.fitbites.app/go/")

    def test_frozen_dataclass(self):
        link = create_tracked_link("r1", "oats", "amazon", "https://a.com", 0.04)
        with pytest.raises(AttributeError):
            link.provider = "instacart"


# ── Recipe-Level Link Creation ───────────────────────────────────────────────

class TestCreateTrackedLinksForRecipe:
    def test_creates_links_for_all_providers(self):
        enriched = [
            {
                "ingredient": "2 cups greek yogurt",
                "normalized": "greek yogurt",
                "all_links": [
                    {"provider": "instacart", "url": "https://instacart.com/s/yogurt", "commission_pct": 0.10},
                    {"provider": "amazon", "url": "https://amazon.com/s?k=yogurt", "commission_pct": 0.04},
                ],
            }
        ]
        links = create_tracked_links_for_recipe("recipe-1", enriched)
        assert len(links) == 2
        providers = {l.provider for l in links.values()}
        assert providers == {"instacart", "amazon"}

    def test_empty_ingredients(self):
        links = create_tracked_links_for_recipe("recipe-1", [])
        assert links == {}

    def test_link_ids_are_unique_per_provider(self):
        enriched = [
            {
                "normalized": "oats",
                "all_links": [
                    {"provider": "amazon", "url": "https://a.com", "commission_pct": 0.04},
                    {"provider": "instacart", "url": "https://i.com", "commission_pct": 0.10},
                ],
            }
        ]
        links = create_tracked_links_for_recipe("r1", enriched)
        ids = list(links.keys())
        assert len(ids) == 2
        assert ids[0] != ids[1]


# ── Link Store (Cache) ──────────────────────────────────────────────────────

class TestLinkStore:
    def test_store_and_lookup(self):
        link = create_tracked_link("r1", "oats", "amazon", "https://a.com", 0.04)
        store_link(link)
        found = lookup_link(link.link_id)
        assert found is not None
        assert found.destination_url == "https://a.com"

    def test_lookup_missing(self):
        assert lookup_link("nonexistent") is None

    def test_store_multiple(self):
        enriched = [
            {
                "normalized": "oats",
                "all_links": [
                    {"provider": "amazon", "url": "https://a.com", "commission_pct": 0.04},
                    {"provider": "instacart", "url": "https://i.com", "commission_pct": 0.10},
                ],
            }
        ]
        links = create_tracked_links_for_recipe("r1", enriched)
        store_links(links)
        for lid in links:
            assert lookup_link(lid) is not None

    def test_expired_link_returns_none(self):
        link = create_tracked_link("r1", "oats", "amazon", "https://a.com", 0.04)
        # Manually store with old timestamp
        _link_cache[link.link_id] = (link, time.time() - 90000)  # > 24h ago
        assert lookup_link(link.link_id) is None

    def test_cleanup_expired(self):
        link1 = create_tracked_link("r1", "a", "amazon", "https://a.com", 0.04)
        link2 = create_tracked_link("r1", "b", "amazon", "https://b.com", 0.04)
        _link_cache[link1.link_id] = (link1, time.time() - 90000)
        _link_cache[link2.link_id] = (link2, time.time())
        removed = cleanup_expired()
        assert removed == 1
        assert lookup_link(link1.link_id) is None
        assert lookup_link(link2.link_id) is not None


# ── Click Recording & Stats ─────────────────────────────────────────────────

class TestClickTracking:
    def test_record_click(self):
        link = create_tracked_link("r1", "oats", "amazon", "https://a.com", 0.04)
        record_click(link, user_id="user-1")
        assert len(_click_log) == 1
        assert _click_log[0]["provider"] == "amazon"
        assert _click_log[0]["user_id"] == "user-1"

    def test_record_click_anonymous(self):
        link = create_tracked_link("r1", "oats", "amazon", "https://a.com", 0.04)
        record_click(link)
        assert _click_log[0]["user_id"] is None

    def test_get_click_stats_empty(self):
        stats = get_click_stats()
        assert stats.total_clicks == 0
        assert stats.estimated_revenue == 0.0

    def test_get_click_stats_with_clicks(self):
        link_amazon = create_tracked_link("r1", "oats", "amazon", "https://a.com", 0.04)
        link_instacart = create_tracked_link("r1", "milk", "instacart", "https://i.com", 0.10)

        record_click(link_amazon)
        record_click(link_amazon)
        record_click(link_instacart)

        stats = get_click_stats()
        assert stats.total_clicks == 3
        assert stats.by_provider["amazon"] == 2
        assert stats.by_provider["instacart"] == 1
        assert stats.unique_recipes == 1
        assert stats.estimated_revenue > 0

    def test_stats_respects_time_window(self):
        link = create_tracked_link("r1", "oats", "amazon", "https://a.com", 0.04)
        record_click(link)
        # Manually age the click
        _click_log[0]["timestamp"] = time.time() - 90000  # 25h ago
        stats = get_click_stats(since_hours=24)
        assert stats.total_clicks == 0

    def test_stats_by_ingredient(self):
        for name in ["oats", "oats", "chicken", "oats"]:
            link = create_tracked_link("r1", name, "amazon", "https://a.com", 0.04)
            record_click(link)
        stats = get_click_stats()
        assert stats.by_ingredient["oats"] == 3
        assert stats.by_ingredient["chicken"] == 1

    def test_stats_to_dict(self):
        link = create_tracked_link("r1", "oats", "amazon", "https://a.com", 0.04)
        record_click(link)
        d = get_click_stats().to_dict()
        assert "total_clicks" in d
        assert "by_provider" in d
        assert "estimated_revenue" in d
        assert isinstance(d["estimated_revenue"], float)

    def test_revenue_estimation(self):
        # 10% commission, $45 avg order, 3% conversion = $0.135 per click
        link = create_tracked_link("r1", "milk", "instacart", "https://i.com", 0.10)
        for _ in range(100):
            record_click(link)
        stats = get_click_stats()
        # 100 clicks * 0.10 * 45 * 0.03 = $13.50
        assert abs(stats.estimated_revenue - 13.50) < 0.01

    def test_multiple_recipes(self):
        link1 = create_tracked_link("r1", "oats", "amazon", "https://a.com", 0.04)
        link2 = create_tracked_link("r2", "chicken", "amazon", "https://a.com", 0.04)
        record_click(link1)
        record_click(link2)
        stats = get_click_stats()
        assert stats.unique_recipes == 2
