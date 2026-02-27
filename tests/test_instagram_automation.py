"""
Tests for Instagram Recipe Automation System.
Covers: discovery, extraction parsing, dedup, quality filter, pipeline.
"""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.instagram_discovery import (
    InstagramDiscoveryService,
    DiscoveredPost,
    RECIPE_HASHTAGS,
    TOP_FITNESS_CREATORS,
)
from src.api.instagram_extract import (
    ExtractedRecipe,
    RecipeNutrition,
    RecipeInstruction,
    _parse_macros_from_text,
    _parse_ingredients_from_text,
    _parse_instructions_from_text,
    _extract_title,
    _compute_success_rate,
    _extract_shortcode,
)
from src.services.instagram_automation import (
    AutomationConfig,
    InstagramAutomationPipeline,
    RecipeDeduplicator,
    passes_quality_filter,
    PipelineResult,
)


# ── Shortcode Extraction ──────────────────────────────────────

class TestShortcodeExtraction:
    def test_standard_post(self):
        assert _extract_shortcode("https://www.instagram.com/p/C1234test/") == "C1234test"

    def test_reel(self):
        assert _extract_shortcode("https://www.instagram.com/reel/DABcDeF123/") == "DABcDeF123"

    def test_tv(self):
        assert _extract_shortcode("https://www.instagram.com/tv/XYZ_abc-1/") == "XYZ_abc-1"

    def test_instagr_am(self):
        assert _extract_shortcode("https://instagr.am/p/ABC123/") == "ABC123"

    def test_invalid(self):
        assert _extract_shortcode("https://example.com/foo") is None


# ── Macro Parsing ──────────────────────────────────────────────

class TestMacroParsing:
    def test_full_macros(self):
        text = "450 calories | 35g protein | 40g carbs | 15g fat"
        n = _parse_macros_from_text(text)
        assert n.calories == 450
        assert n.protein_grams == 35.0
        assert n.carbs_grams == 40.0
        assert n.fat_grams == 15.0

    def test_kcal_format(self):
        text = "This meal is only 320 kcal with 28g protein"
        n = _parse_macros_from_text(text)
        assert n.calories == 320
        assert n.protein_grams == 28.0

    def test_no_macros(self):
        text = "This is a delicious recipe! Try it out!"
        n = _parse_macros_from_text(text)
        assert n.calories is None
        assert n.protein_grams is None

    def test_partial_macros(self):
        text = "High protein meal - 42g protein per serving"
        n = _parse_macros_from_text(text)
        assert n.protein_grams == 42.0
        assert n.calories is None


# ── Ingredient Parsing ─────────────────────────────────────────

class TestIngredientParsing:
    def test_bullet_list(self):
        text = """My favorite recipe!

Ingredients:
- 2 cups chicken breast
- 1 cup rice
- 1 tbsp olive oil
- Salt and pepper

Instructions:
Cook it all together."""
        ingredients = _parse_ingredients_from_text(text)
        assert len(ingredients) >= 3
        assert any("chicken" in i.lower() for i in ingredients)

    def test_measurement_fallback(self):
        text = """Quick meal:
200g chicken breast diced
1 cup brown rice
2 tbsp soy sauce"""
        ingredients = _parse_ingredients_from_text(text)
        assert len(ingredients) >= 2

    def test_empty_text(self):
        assert _parse_ingredients_from_text("") == []


# ── Instruction Parsing ────────────────────────────────────────

class TestInstructionParsing:
    def test_numbered_steps(self):
        text = """Ingredients:
- chicken
- rice

Instructions:
1. Preheat oven to 400F and prepare baking sheet
2. Season chicken with spices and place on sheet
3. Bake for 25 minutes until golden

Nutrition: 450 cal"""
        steps = _parse_instructions_from_text(text)
        assert len(steps) == 3
        assert steps[0].step == 1
        assert "preheat" in steps[0].text.lower()

    def test_no_instructions(self):
        text = "Just a photo of food #yummy"
        assert _parse_instructions_from_text(text) == []


# ── Title Extraction ───────────────────────────────────────────

class TestTitleExtraction:
    def test_from_meta(self):
        title = _extract_title("some text", 'FitChef on Instagram: "High Protein Chicken Bowl"')
        assert "High Protein Chicken Bowl" in title

    def test_from_first_line(self):
        title = _extract_title("Creamy Garlic Pasta Recipe\n\nIngredients:\n- pasta")
        assert "Creamy Garlic Pasta" in title

    def test_fallback(self):
        title = _extract_title("")
        assert title == "Instagram Recipe"


# ── Success Rate ───────────────────────────────────────────────

class TestSuccessRate:
    def test_full_recipe(self):
        recipe = ExtractedRecipe(
            title="Chicken Bowl",
            source_url="https://instagram.com/p/test/",
            nutrition=RecipeNutrition(calories=450, protein_grams=35, carbs_grams=40, fat_grams=15),
            ingredients=["chicken", "rice", "broccoli"],
            instructions=[RecipeInstruction(step=1, text="Cook it")],
            description="A healthy chicken bowl for meal prep",
            success_rate=0.0,
        )
        rate = _compute_success_rate(recipe)
        assert rate == 1.0

    def test_minimal_recipe(self):
        recipe = ExtractedRecipe(
            title="Instagram Recipe",
            source_url="https://instagram.com/p/test/",
            nutrition=RecipeNutrition(),
            success_rate=0.0,
        )
        rate = _compute_success_rate(recipe)
        assert rate == 0.0


# ── Deduplication ──────────────────────────────────────────────

class TestDeduplication:
    def test_url_dedup(self):
        dedup = RecipeDeduplicator()
        r1 = ExtractedRecipe(
            title="Test", source_url="https://instagram.com/p/ABC/",
            nutrition=RecipeNutrition(), success_rate=0.5,
        )
        assert not dedup.is_duplicate(r1)
        assert dedup.is_duplicate(r1)  # Second time = duplicate

    def test_url_normalization(self):
        dedup = RecipeDeduplicator()
        r1 = ExtractedRecipe(
            title="Test", source_url="https://instagram.com/p/ABC/",
            nutrition=RecipeNutrition(), success_rate=0.5,
        )
        r2 = ExtractedRecipe(
            title="Test", source_url="https://instagram.com/p/ABC",
            nutrition=RecipeNutrition(), success_rate=0.5,
        )
        assert not dedup.is_duplicate(r1)
        assert dedup.is_duplicate(r2)

    def test_content_dedup(self):
        dedup = RecipeDeduplicator()
        r1 = ExtractedRecipe(
            title="Chicken Bowl", source_url="https://instagram.com/p/AAA/",
            nutrition=RecipeNutrition(), success_rate=0.5,
            ingredients=["chicken", "rice"],
        )
        r2 = ExtractedRecipe(
            title="Chicken Bowl", source_url="https://instagram.com/p/BBB/",
            nutrition=RecipeNutrition(), success_rate=0.5,
            ingredients=["chicken", "rice"],
        )
        assert not dedup.is_duplicate(r1)
        assert dedup.is_duplicate(r2)  # Same title + ingredients

    def test_preloaded_urls(self):
        dedup = RecipeDeduplicator()
        dedup.load_existing_urls(["https://instagram.com/p/existing/"])
        r = ExtractedRecipe(
            title="Test", source_url="https://instagram.com/p/existing/",
            nutrition=RecipeNutrition(), success_rate=0.5,
        )
        assert dedup.is_duplicate(r)


# ── Quality Filter ─────────────────────────────────────────────

class TestQualityFilter:
    def setup_method(self):
        self.config = AutomationConfig()

    def test_passes_good_recipe(self):
        recipe = ExtractedRecipe(
            title="Test", source_url="https://instagram.com/p/x/",
            nutrition=RecipeNutrition(calories=400, protein_grams=30, carbs_grams=40, fat_grams=10),
            ingredients=["a", "b", "c"],
            instructions=[RecipeInstruction(step=1, text="do it")],
            description="Great recipe for fitness goals",
            success_rate=0.875,
        )
        assert passes_quality_filter(recipe, self.config)

    def test_rejects_low_success_rate(self):
        recipe = ExtractedRecipe(
            title="Test", source_url="https://instagram.com/p/x/",
            nutrition=RecipeNutrition(), success_rate=0.25,
        )
        assert not passes_quality_filter(recipe, self.config)

    def test_rejects_no_ingredients(self):
        recipe = ExtractedRecipe(
            title="Test", source_url="https://instagram.com/p/x/",
            nutrition=RecipeNutrition(calories=400),
            instructions=[RecipeInstruction(step=1, text="cook")],
            success_rate=0.80,
        )
        assert not passes_quality_filter(recipe, self.config)


# ── Discovery Service ──────────────────────────────────────────

class TestDiscoveryService:
    def test_recipe_heuristic_positive(self):
        post = DiscoveredPost(
            url="https://instagram.com/p/test/",
            shortcode="test",
            source="hashtag:test",
            caption_preview="High protein chicken recipe! 450 calories, 35g protein. Ingredients: chicken breast, rice, broccoli",
        )
        assert InstagramDiscoveryService._looks_like_recipe(post)

    def test_recipe_heuristic_negative(self):
        post = DiscoveredPost(
            url="https://instagram.com/p/test/",
            shortcode="test",
            source="hashtag:test",
            caption_preview="Just got my new gym shoes! Love them so much!",
        )
        assert not InstagramDiscoveryService._looks_like_recipe(post)

    def test_empty_caption_passes(self):
        """Posts with no caption should pass (let extraction decide)."""
        post = DiscoveredPost(
            url="https://instagram.com/p/test/",
            shortcode="test",
            source="hashtag:test",
        )
        assert InstagramDiscoveryService._looks_like_recipe(post)

    def test_hashtag_list(self):
        assert len(RECIPE_HASHTAGS) >= 8
        assert "highproteinrecipes" in RECIPE_HASHTAGS

    def test_creator_list(self):
        assert len(TOP_FITNESS_CREATORS) >= 5
        assert "fitmencook" in TOP_FITNESS_CREATORS


# ── Pipeline Integration (mocked) ─────────────────────────────

class TestPipelineIntegration:
    @pytest.mark.asyncio
    async def test_dry_run_pipeline(self):
        """Test pipeline with mocked discovery and extraction."""
        config = AutomationConfig(
            rate_limit_per_hour=5,
            delay_between_extractions=0,  # No delay in tests
            min_success_rate=0.5,
            min_ingredients=1,
            min_instructions=0,
        )
        pipeline = InstagramAutomationPipeline(config)

        # Mock discovery
        mock_posts = [
            DiscoveredPost(
                url=f"https://instagram.com/p/test{i}/",
                shortcode=f"test{i}",
                source="test",
                caption_preview="High protein recipe",
                like_count=100 - i,
            )
            for i in range(3)
        ]

        mock_recipe = ExtractedRecipe(
            title="Test Chicken Bowl",
            source_url="https://instagram.com/p/test0/",
            nutrition=RecipeNutrition(calories=400, protein_grams=30),
            ingredients=["chicken", "rice"],
            instructions=[RecipeInstruction(step=1, text="Cook chicken")],
            description="A great test recipe for testing",
            success_rate=0.75,
            extraction_methods=["test"],
        )

        with patch.object(
            InstagramDiscoveryService, "discover", return_value=mock_posts
        ), patch(
            "src.services.instagram_automation.extract_recipe_from_instagram",
            return_value=mock_recipe,
        ):
            result = await pipeline.run(max_extract=3)

        assert result.discovered == 3
        assert result.extracted >= 1
        assert result.finished_at is not None
        await pipeline.close()

    @pytest.mark.asyncio
    async def test_dedup_in_pipeline(self):
        """Test that existing URLs are skipped."""
        config = AutomationConfig(delay_between_extractions=0)
        pipeline = InstagramAutomationPipeline(config)

        mock_posts = [
            DiscoveredPost(
                url="https://instagram.com/p/existing/",
                shortcode="existing",
                source="test",
            ),
        ]

        with patch.object(
            InstagramDiscoveryService, "discover", return_value=mock_posts
        ), patch(
            "src.services.instagram_automation.extract_recipe_from_instagram",
        ) as mock_extract:
            mock_extract.return_value = ExtractedRecipe(
                title="Dup Recipe",
                source_url="https://instagram.com/p/existing/",
                nutrition=RecipeNutrition(calories=400, protein_grams=30),
                ingredients=["a", "b"],
                instructions=[RecipeInstruction(step=1, text="do")],
                description="A duplicate recipe that should be skipped",
                success_rate=0.80,
            )
            result = await pipeline.run(
                existing_urls=["https://instagram.com/p/existing/"],
                max_extract=5,
            )

        assert result.duplicates_skipped >= 1
        assert result.saved == 0
        await pipeline.close()


# ── Pipeline Result ────────────────────────────────────────────

class TestPipelineResult:
    def test_summary(self):
        r = PipelineResult(discovered=10, extracted=8, passed_quality=6, saved=5)
        s = r.summary()
        assert s["discovered"] == 10
        assert s["saved"] == 5
        assert s["error_count"] == 0
