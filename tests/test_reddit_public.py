"""Tests for the public Reddit scraper (no API keys needed)."""
from __future__ import annotations

import pytest
from src.scrapers.reddit_public import RedditPublicScraper, RECIPE_KEYWORDS


def test_recipe_keyword_regex():
    """Verify the keyword regex catches recipe-related content."""
    assert RECIPE_KEYWORDS.search("High protein chicken recipe")
    assert RECIPE_KEYWORDS.search("450 calories per serving")
    assert RECIPE_KEYWORDS.search("35g of protein per meal")
    assert RECIPE_KEYWORDS.search("Easy meal prep for the week")
    assert RECIPE_KEYWORDS.search("Cook the salmon at 400F")
    assert not RECIPE_KEYWORDS.search("My cat is cute")
    assert not RECIPE_KEYWORDS.search("Stock market update today")


def test_is_recipe_post():
    scraper = RedditPublicScraper()

    # Good recipe post
    assert scraper._is_recipe_post({
        "title": "High protein chicken bowl recipe",
        "selftext": "Here are the ingredients: chicken breast 200g, rice 1 cup...",
        "is_self": True,
        "score": 50,
    })

    # Too low engagement
    assert not scraper._is_recipe_post({
        "title": "My recipe",
        "selftext": "Chicken and rice with ingredients",
        "is_self": True,
        "score": 2,
    })

    # No recipe keywords
    assert not scraper._is_recipe_post({
        "title": "Beautiful sunset",
        "selftext": "Look at this view from my window",
        "is_self": True,
        "score": 100,
    })


def test_extract_recipe_data():
    """Test synchronous data extraction logic."""
    import asyncio
    scraper = RedditPublicScraper()

    raw = {
        "id": "abc123",
        "title": "High Protein Chicken Bowl - 450cal, 45g protein",
        "selftext": "Ingredients: chicken, rice, broccoli...",
        "author": "fitchef",
        "subreddit": "fitmeals",
        "permalink": "/r/fitmeals/comments/abc123/high_protein/",
        "thumbnail": "https://i.redd.it/thumb.jpg",
        "ups": 500,
        "num_comments": 42,
        "score": 500,
        "upvote_ratio": 0.95,
        "created_utc": 1708800000,
        "url": "https://i.redd.it/image.jpg",
        "is_self": True,
        "link_flair_text": "Recipe",
    }

    result = asyncio.get_event_loop().run_until_complete(scraper.extract_recipe_data(raw))
    assert result["platform"] == "reddit"
    assert result["post_id"] == "abc123"
    assert result["author"] == "fitchef"
    assert result["likes"] == 500
    assert result["comments"] == 42
    assert "reddit.com" in result["source_url"]
