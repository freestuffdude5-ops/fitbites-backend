"""
Tests for TikTok Recipe Automation System.

Covers:
- Discovery service
- Extraction API
- Automation pipeline
- Deduplication
- Quality filtering
"""
from __future__ import annotations

import json
import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path

# ── Unit tests (no network) ───────────────────────────────────────────────

class TestNutritionExtraction:
    """Test regex-based nutrition parsing."""

    def test_calories(self):
        from src.api.tiktok_extract import extract_nutrition
        n = extract_nutrition("This recipe is 450 calories per serving")
        assert n.calories == 450

    def test_protein(self):
        from src.api.tiktok_extract import extract_nutrition
        n = extract_nutrition("35g protein per serving")
        assert n.protein_grams == 35.0

    def test_full_macros(self):
        from src.api.tiktok_extract import extract_nutrition
        text = "350 calories, 40g protein, 25g carbs, 8g fat"
        n = extract_nutrition(text)
        assert n.calories == 350
        assert n.protein_grams == 40.0
        assert n.carbs_grams == 25.0
        assert n.fat_grams == 8.0

    def test_no_macros(self):
        from src.api.tiktok_extract import extract_nutrition
        n = extract_nutrition("Just a fun video about cooking")
        assert n.calories is None
        assert n.protein_grams is None

    def test_calorie_range_validation(self):
        from src.api.tiktok_extract import extract_nutrition
        # Too low
        n = extract_nutrition("only 5 cal")
        assert n.calories is None
        # Valid
        n = extract_nutrition("500 calories")
        assert n.calories == 500


class TestIngredientExtraction:
    """Test ingredient parsing."""

    def test_basic_ingredients(self):
        from src.api.tiktok_extract import extract_ingredients
        text = "2 cups rice, 1 tbsp olive oil, 200g chicken breast"
        items = extract_ingredients(text)
        assert len(items) >= 2

    def test_no_ingredients(self):
        from src.api.tiktok_extract import extract_ingredients
        items = extract_ingredients("Just vibes")
        assert items == []


class TestInstructionExtraction:
    """Test instruction parsing."""

    def test_numbered_steps(self):
        from src.api.tiktok_extract import extract_instructions
        text = "1. Preheat oven to 400F. 2. Mix ingredients together. 3. Bake for 25 minutes."
        steps = extract_instructions(text)
        assert len(steps) >= 2
        assert steps[0].step == 1

    def test_action_verb_fallback(self):
        from src.api.tiktok_extract import extract_instructions
        text = "First we need to chop the onions finely. Then heat olive oil in a pan. Combine with the rice and stir well."
        steps = extract_instructions(text)
        assert len(steps) >= 2


class TestSuccessRate:
    """Test quality scoring."""

    def test_full_extraction(self):
        from src.api.tiktok_extract import calculate_success_rate, RecipeNutrition
        rate = calculate_success_rate(
            RecipeNutrition(calories=400, protein_grams=30),
            has_title=True, has_creator=True, has_thumbnail=True,
            has_ingredients=True, has_instructions=True, has_caption=True,
        )
        assert rate > 0.8

    def test_empty_extraction(self):
        from src.api.tiktok_extract import calculate_success_rate, RecipeNutrition
        rate = calculate_success_rate(
            RecipeNutrition(),
            has_title=False, has_creator=False, has_thumbnail=False,
            has_ingredients=False, has_instructions=False, has_caption=False,
        )
        assert rate == 0.0


class TestDiscoveryService:
    """Test discovery service logic."""

    def test_filter_recipe_videos(self):
        from src.services.tiktok_discovery import TikTokDiscoveryService, DiscoveredVideo
        svc = TikTokDiscoveryService()
        videos = [
            DiscoveredVideo(
                url="https://tiktok.com/@test/video/1",
                video_id="1",
                title="High protein meal prep recipe",
                description="Easy protein recipe #mealprep",
                view_count=10000,
                duration=45,
            ),
            DiscoveredVideo(
                url="https://tiktok.com/@test/video/2",
                video_id="2",
                title="My cat doing tricks",
                description="cute cat #cat",
                view_count=50000,
                duration=15,
            ),
            DiscoveredVideo(
                url="https://tiktok.com/@test/video/3",
                video_id="3",
                title="600 calorie anabolic breakfast",
                description="macro friendly breakfast #anabolic",
                view_count=5000,
                duration=60,
            ),
        ]
        filtered = svc.filter_recipe_videos(videos)
        # Recipe videos should pass, cat video should not
        titles = [v.title for v in filtered]
        assert "My cat doing tricks" not in titles
        assert len(filtered) >= 2


class TestDeduplication:
    """Test pipeline deduplication."""

    def test_video_hash(self):
        from src.services.tiktok_automation import TikTokAutomationPipeline
        pipeline = TikTokAutomationPipeline()
        h1 = pipeline._video_hash("https://tiktok.com/@user/video/12345")
        h2 = pipeline._video_hash("https://tiktok.com/@user/video/12345")
        h3 = pipeline._video_hash("https://tiktok.com/@user/video/99999")
        assert h1 == h2
        assert h1 != h3

    def test_is_duplicate(self):
        from src.services.tiktok_automation import TikTokAutomationPipeline
        from src.services.tiktok_discovery import DiscoveredVideo
        pipeline = TikTokAutomationPipeline()
        video = DiscoveredVideo(url="https://tiktok.com/@test/video/111", video_id="111")
        assert not pipeline._is_duplicate(video)
        pipeline._mark_seen(video)
        assert pipeline._is_duplicate(video)


class TestSubtitleCleaning:
    """Test VTT/SRT subtitle cleaning."""

    def test_clean_vtt(self):
        from src.api.tiktok_extract import _clean_subtitle_text
        raw = """WEBVTT

1
00:00:01.000 --> 00:00:03.000
Hello everyone today we're making

2
00:00:03.000 --> 00:00:05.000
a high protein chicken recipe
"""
        cleaned = _clean_subtitle_text(raw)
        assert "Hello everyone" in cleaned
        assert "high protein chicken" in cleaned
        assert "WEBVTT" not in cleaned
        assert "-->" not in cleaned


# ── Integration tests (requires network + yt-dlp) ─────────────────────────

REAL_TIKTOK_URLS = [
    # Popular fitness recipe creators - these may change/expire
    "https://www.tiktok.com/@remington_james/video/7297000000000000000",
]


@pytest.mark.integration
class TestRealExtraction:
    """Integration tests with real TikTok videos. Run with: pytest -m integration"""

    def test_ytdlp_available(self):
        from src.api.tiktok_extract import YTDLP_PATH
        assert Path(YTDLP_PATH).exists(), "yt-dlp not installed"


# ── Run all tests ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
