"""Tests for viral scoring algorithm."""
import pytest
from datetime import datetime, timezone, timedelta

from src.models.recipe import Recipe, Creator, Platform, NutritionInfo
from src.services.viral_score import (
    compute_viral_score,
    compute_health_score,
    score_and_rank,
    _normalize_engagement,
    _recency_boost,
)


def _make_recipe(**kwargs) -> Recipe:
    """Helper to create a recipe with sensible defaults."""
    defaults = {
        "title": "Test Recipe",
        "creator": Creator(
            username="testuser",
            platform=Platform.TIKTOK,
            profile_url="https://tiktok.com/@testuser",
            follower_count=100_000,
        ),
        "platform": Platform.TIKTOK,
        "source_url": "https://tiktok.com/@testuser/video/123",
        "likes": 5000,
        "comments": 2000,
        "shares": 1500,
        "views": 100_000,
        "published_at": datetime.now(timezone.utc) - timedelta(days=2),
        "nutrition": NutritionInfo(calories=400, protein_g=35, carbs_g=30, fat_g=10),
    }
    defaults.update(kwargs)
    return Recipe(**defaults)


class TestNormalizeEngagement:
    def test_with_followers(self):
        assert _normalize_engagement(5000, 100_000) == pytest.approx(0.05)

    def test_without_followers_uses_log(self):
        result = _normalize_engagement(1_000_000, None)
        assert 0.0 < result <= 1.0

    def test_none_metric(self):
        assert _normalize_engagement(None, 100_000) == 0.0

    def test_zero_metric(self):
        assert _normalize_engagement(0, 100_000) == 0.0

    def test_capped_at_one(self):
        assert _normalize_engagement(200_000, 100_000) == 1.0


class TestRecencyBoost:
    def test_today(self):
        assert _recency_boost(datetime.now(timezone.utc)) == pytest.approx(1.0, abs=0.05)

    def test_old_post(self):
        old = datetime.now(timezone.utc) - timedelta(days=60)
        assert _recency_boost(old) == 0.0

    def test_half_decay(self):
        half = datetime.now(timezone.utc) - timedelta(days=15)
        assert _recency_boost(half) == pytest.approx(0.5, abs=0.05)

    def test_none_date(self):
        assert _recency_boost(None) == 0.5


class TestHealthScore:
    def test_high_protein(self):
        n = NutritionInfo(calories=400, protein_g=40, carbs_g=30, fat_g=10)
        score = compute_health_score(n)
        assert score >= 0.8

    def test_low_protein(self):
        n = NutritionInfo(calories=800, protein_g=5, carbs_g=100, fat_g=30)
        score = compute_health_score(n)
        assert score < 0.6

    def test_none_nutrition(self):
        assert compute_health_score(None) == 0.5

    def test_high_sugar_penalty(self):
        high_sugar = NutritionInfo(calories=400, protein_g=30, carbs_g=50, fat_g=10, sugar_g=35)
        no_sugar = NutritionInfo(calories=400, protein_g=30, carbs_g=50, fat_g=10)
        assert compute_health_score(high_sugar) < compute_health_score(no_sugar)


class TestViralScore:
    def test_high_engagement_scores_high(self):
        recipe = _make_recipe(likes=10_000, comments=5000, shares=3000)
        score = compute_viral_score(recipe)
        assert score >= 50

    def test_zero_engagement_scores_low(self):
        recipe = _make_recipe(likes=0, comments=0, shares=0, published_at=datetime.now(timezone.utc) - timedelta(days=60))
        score = compute_viral_score(recipe)
        assert score < 20

    def test_tiktok_outscores_reddit(self):
        tiktok = _make_recipe(platform=Platform.TIKTOK)
        reddit = _make_recipe(
            platform=Platform.REDDIT,
            creator=Creator(
                username="testuser",
                platform=Platform.REDDIT,
                profile_url="https://reddit.com/u/testuser",
                follower_count=100_000,
            ),
        )
        assert compute_viral_score(tiktok) > compute_viral_score(reddit)

    def test_score_in_range(self):
        recipe = _make_recipe()
        score = compute_viral_score(recipe)
        assert 0 <= score <= 100

    def test_healthy_recipe_scores_higher(self):
        healthy = _make_recipe(
            nutrition=NutritionInfo(calories=350, protein_g=40, carbs_g=25, fat_g=8)
        )
        unhealthy = _make_recipe(
            nutrition=NutritionInfo(calories=900, protein_g=5, carbs_g=120, fat_g=40, sugar_g=50)
        )
        assert compute_viral_score(healthy) > compute_viral_score(unhealthy)


class TestScoreAndRank:
    def test_sorts_descending(self):
        recipes = [
            _make_recipe(title="Low", likes=100, comments=10, shares=5),
            _make_recipe(title="High", likes=50_000, comments=10_000, shares=8_000),
            _make_recipe(title="Mid", likes=5_000, comments=1_000, shares=500),
        ]
        ranked = score_and_rank(recipes)
        assert ranked[0].title == "High"
        assert ranked[-1].title == "Low"
        assert all(r.virality_score is not None for r in ranked)
