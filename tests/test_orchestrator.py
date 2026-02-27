"""Tests for recipe orchestrator, deduplicator, and quality scorer."""
import pytest
from datetime import datetime, timezone

from src.models import Recipe, Creator, NutritionInfo, Ingredient, Platform
from src.services.deduplicator import (
    RecipeDeduplicator, title_similarity, macros_similar, _normalize_title,
)
from src.services.quality_scorer import score_recipe, filter_quality


def _make_recipe(
    title="Test Recipe",
    platform=Platform.YOUTUBE,
    calories=500,
    protein=30.0,
    ingredients=None,
    steps=None,
    tags=None,
    description="A test recipe",
    id=None,
    **kwargs,
) -> Recipe:
    return Recipe(
        id=id or "test-id",
        title=title,
        description=description,
        creator=Creator(
            username="testuser",
            platform=platform,
            profile_url="https://example.com/testuser",
        ),
        platform=platform,
        source_url=f"https://example.com/{title.replace(' ', '-')}",
        ingredients=ingredients if ingredients is not None else [
            Ingredient(name="chicken", quantity="200g"),
            Ingredient(name="rice", quantity="1 cup"),
        ],
        steps=steps if steps is not None else ["Cook chicken", "Add rice", "Serve"],
        nutrition=NutritionInfo(
            calories=calories, protein_g=protein, carbs_g=50.0, fat_g=15.0,
        ),
        tags=tags or ["high-protein"],
        cook_time_minutes=20,
        views=10000,
        likes=500,
        thumbnail_url="https://img.example.com/thumb.jpg",
        **kwargs,
    )


# ── Title Similarity ──────────────────────────────────────────────

class TestTitleSimilarity:
    def test_exact_match(self):
        assert title_similarity("Chicken Rice Bowl", "Chicken Rice Bowl") == 1.0

    def test_case_insensitive(self):
        assert title_similarity("chicken rice bowl", "CHICKEN RICE BOWL") == 1.0

    def test_similar_titles(self):
        sim = title_similarity(
            "High Protein Chicken Rice Bowl",
            "Protein Chicken and Rice Bowl",
        )
        assert sim > 0.7

    def test_different_titles(self):
        sim = title_similarity("Chicken Rice Bowl", "Chocolate Cake Recipe")
        assert sim < 0.5

    def test_noise_removal(self):
        assert _normalize_title("Easy Homemade Chicken Recipe") == "chicken"
        assert _normalize_title("The Best Quick Pasta") == "pasta"


# ── Macro Similarity ──────────────────────────────────────────────

class TestMacroSimilarity:
    def test_similar_macros(self):
        a = _make_recipe(calories=500, protein=30.0)
        b = _make_recipe(calories=520, protein=32.0)
        assert macros_similar(a, b) is True

    def test_different_macros(self):
        a = _make_recipe(calories=500, protein=30.0)
        b = _make_recipe(calories=800, protein=60.0)
        assert macros_similar(a, b) is False

    def test_no_nutrition(self):
        a = _make_recipe()
        b = Recipe(
            title="No Macros",
            creator=Creator(username="x", platform=Platform.TIKTOK, profile_url="http://x"),
            platform=Platform.TIKTOK,
            source_url="http://x",
        )
        assert macros_similar(a, b) is False


# ── Deduplicator ──────────────────────────────────────────────────

class TestDeduplicator:
    def test_detect_duplicate_title(self):
        dedup = RecipeDeduplicator(title_threshold=0.80)
        existing = [_make_recipe(title="Chicken Rice Bowl", id="existing-1")]
        new = _make_recipe(title="Chicken Rice Bowl", id="new-1", platform=Platform.TIKTOK)
        result = dedup.check(new, existing)
        assert result.is_duplicate is True
        assert result.matched_recipe_id == "existing-1"

    def test_no_duplicate(self):
        dedup = RecipeDeduplicator()
        existing = [_make_recipe(title="Chicken Rice Bowl", id="existing-1")]
        new = _make_recipe(title="Chocolate Lava Cake", id="new-1")
        result = dedup.check(new, existing)
        assert result.is_duplicate is False

    def test_keep_better_version(self):
        dedup = RecipeDeduplicator(title_threshold=0.80)
        # Existing has no ingredients
        existing = [_make_recipe(title="Protein Bowl", id="old", ingredients=[], steps=[])]
        # New has full data
        new = _make_recipe(title="Protein Bowl", id="new")
        result = dedup.check(new, existing)
        assert result.is_duplicate is True
        assert result.kept_version == "new"

    def test_batch_dedup(self):
        dedup = RecipeDeduplicator(title_threshold=0.80)
        recipes = [
            _make_recipe(title="Chicken Bowl", id="1"),
            _make_recipe(title="Chicken Bowl", id="2"),
            _make_recipe(title="Pasta Salad", id="3"),
        ]
        result = dedup.deduplicate_batch(recipes)
        assert len(result) == 2
        titles = {r.title for r in result}
        assert "Pasta Salad" in titles


# ── Quality Scorer ────────────────────────────────────────────────

class TestQualityScorer:
    def test_complete_recipe(self):
        recipe = _make_recipe()
        report = score_recipe(recipe)
        assert report.score >= 0.8
        assert report.status == "complete"

    def test_minimal_recipe(self):
        recipe = Recipe(
            title="X",
            creator=Creator(username="x", platform=Platform.TIKTOK, profile_url="http://x"),
            platform=Platform.TIKTOK,
            source_url="http://x",
        )
        report = score_recipe(recipe)
        assert report.score < 0.3
        assert report.status == "incomplete"

    def test_invalid_nutrition_warning(self):
        recipe = _make_recipe(calories=5000, protein=500.0)
        report = score_recipe(recipe)
        assert len(report.warnings) > 0
        assert report.field_scores["nutrition_valid"] == 0.0

    def test_filter_quality(self):
        good = _make_recipe(title="Good Recipe")
        bad = Recipe(
            title="X",
            creator=Creator(username="x", platform=Platform.TIKTOK, profile_url="http://x"),
            platform=Platform.TIKTOK,
            source_url="http://x",
        )
        passed, failed = filter_quality([good, bad], min_score=0.4)
        assert len(passed) == 1
        assert len(failed) == 1


# ── Dedup Log ─────────────────────────────────────────────────────

class TestDedupLog:
    def test_log_summary(self):
        dedup = RecipeDeduplicator()
        existing = [_make_recipe(title="Chicken Bowl", id="e1")]
        dedup.check(_make_recipe(title="Chicken Bowl", id="n1"), existing)
        dedup.check(_make_recipe(title="Totally Different", id="n2"), existing)

        summary = dedup.log.summary()
        assert summary["total_checked"] == 2
        assert summary["duplicates_found"] == 1
