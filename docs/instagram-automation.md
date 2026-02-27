# Instagram Recipe Automation System

## Overview

End-to-end system for discovering, extracting, and saving fitness recipe posts from Instagram at scale.

## Architecture

```
Discovery → Extraction → Validation → Deduplication → Save
```

### Components

| Component | Path | Purpose |
|-----------|------|---------|
| Discovery Service | `src/services/instagram_discovery.py` | Find recipe posts via hashtags + creators |
| Extraction API | `src/api/instagram_extract.py` | Extract structured recipe data from posts |
| Automation Pipeline | `src/services/instagram_automation.py` | Orchestrate full pipeline with rate limiting |
| Tests | `tests/test_instagram_automation.py` | 34 unit + integration tests |

## API Endpoints

### `POST /api/v1/instagram/extract`

Extract recipe from a single Instagram post.

```json
{
  "post_url": "https://www.instagram.com/p/ABC123/"
}
```

**Response:**
```json
{
  "success": true,
  "recipe": {
    "title": "High Protein Chicken Bowl",
    "source_url": "https://www.instagram.com/p/ABC123/",
    "creator_username": "fitmencook",
    "nutrition": {
      "calories": 450,
      "protein_grams": 35.0,
      "carbs_grams": 40.0,
      "fat_grams": 15.0
    },
    "ingredients": ["chicken breast", "brown rice", "broccoli"],
    "instructions": [{"step": 1, "text": "Season and grill chicken"}],
    "success_rate": 0.875,
    "extraction_methods": ["oembed", "browser"]
  }
}
```

### `GET /api/v1/instagram/health`

Health check endpoint.

## Extraction Strategies (ordered)

1. **oEmbed API** — No auth, works for public posts. Gets title + author.
2. **GraphQL endpoint** — Public endpoint with IG App ID. Gets full caption.
3. **Browser automation** — Playwright with mobile UA. Screenshots + DOM scraping.

## Discovery Strategies

1. **Hashtag search** — Queries fitness/recipe hashtags (#highproteinrecipes, #fitnessfood, etc.)
2. **Creator monitoring** — Fetches recent posts from known fitness accounts (fitmencook, etc.)

Both require `INSTAGRAM_API_KEY` for the RapidAPI Instagram scraper.

## Rate Limiting

Instagram is strict. Default config:
- **15 requests/hour** for extraction
- **4 min delay** between extractions
- Discovery requests also rate-limited

## Quality Filtering

Recipes must pass:
- ≥75% success rate (fields populated)
- ≥2 ingredients
- ≥1 instruction step

## Deduplication

Two-layer dedup:
1. **URL-based** — Normalized URL matching (case-insensitive, trailing slash)
2. **Content-based** — SHA256 hash of title + top ingredients

Pre-loads existing DB URLs to avoid re-processing.

## Usage

### Single extraction
```python
from src.api.instagram_extract import extract_recipe_from_instagram
recipe = await extract_recipe_from_instagram("https://instagram.com/p/ABC/")
```

### Full automation run
```python
from src.services.instagram_automation import run_instagram_automation, AutomationConfig

config = AutomationConfig(
    instagram_api_key="your-key",
    rate_limit_per_hour=15,
)
result = await run_instagram_automation(config=config)
print(result.summary())
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `INSTAGRAM_API_KEY` | For discovery | RapidAPI key for Instagram scraper |
| `INSTAGRAM_API_BASE` | No | API base URL (default: RapidAPI) |

## Tests

```bash
python3 -m pytest tests/test_instagram_automation.py -v
```

34 tests covering: shortcode parsing, macro extraction, ingredient parsing, instruction parsing, title extraction, success rate calculation, deduplication (URL + content + preloaded), quality filtering, discovery heuristics, pipeline integration.
