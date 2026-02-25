"""Tests for viral scoring."""
import pytest
from src.services.viral_score import compute_viral_score
from src.models.recipe import Recipe, Creator, Platform


def _make_recipe(**kwargs) -> Recipe:
    """Create a minimal Recipe for testing."""
    defaults = {
        "title": "Test Recipe",
        "platform": "youtube",
        "source_url": "https://example.com",
        "creator": {
            "username": "testchef",
            "platform": "youtube",
            "profile_url": "https://youtube.com/@testchef",
            "follower_count": 100_000,
        },
        "ingredients": [],
        "views": 0,
        "likes": 0,
        "comments": 0,
        "shares": 0,
    }
    defaults.update(kwargs)
    return Recipe(**defaults)


def test_virality_zero_engagement():
    recipe = _make_recipe(views=0, likes=0, comments=0, shares=0)
    score = compute_viral_score(recipe)
    assert score >= 0.0


def test_virality_high_engagement():
    recipe = _make_recipe(
        views=10_000_000, likes=1_000_000, comments=100_000, shares=100_000
    )
    score = compute_viral_score(recipe)
    assert score > 50.0


def test_virality_moderate():
    recipe = _make_recipe(views=100_000, likes=10_000, comments=500, shares=100)
    score = compute_viral_score(recipe)
    assert score > 0


def test_virality_views_only():
    recipe = _make_recipe(views=1_000_000)
    score = compute_viral_score(recipe)
    assert score >= 0
