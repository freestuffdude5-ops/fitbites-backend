# YouTube Recipe Automation System

Automated pipeline to discover, extract, validate, and store 100+ fitness recipes/day from YouTube.

## Architecture

```
┌─────────────────┐     ┌──────────────────────┐     ┌──────────┐
│  YouTube Data   │────▸│  Recipe Automation    │────▸│ Database │
│  API v3 Search  │     │  Pipeline             │     │ (recipes)│
└─────────────────┘     └──────────────────────┘     └──────────┘
        ▲                        │
        │                  ┌─────┴─────┐
   Discovery           Validate    Deduplicate
   Service             Quality     by URL/title
```

## Modules

### 1. YouTube Discovery (`src/services/youtube_discovery.py`)
- Searches 15 fitness recipe queries via YouTube Data API v3
- Filters out multi-recipe compilations (regex on title)
- Filters by duration (1-30 min, skip shorts and long compilations)
- Enriches with view count and duration data
- Returns 50-100 `DiscoveredVideo` objects per run

### 2. Recipe Automation Pipeline (`src/services/recipe_automation.py`)
- Extracts recipe from each video using yt-dlp + transcript parsing
- **Quality validation:**
  - Success rate ≥ 75% (6+ of 8 fields)
  - Required: title, calories, protein, thumbnail, channel, ingredients, instructions
  - Calories: 100-2000 | Protein: 10-200g
- **Deduplication:** checks source_url + title+calories combo
- Saves to `recipes` table via `RecipeRepository.upsert()`

### 3. Recipe Harvester (`src/tasks/recipe_harvester.py`)
- Orchestrates discovery → extraction → save
- Logs each run to `logs/harvester/harvest-YYYY-MM-DD.json`
- Exposes API endpoints:
  - `POST /api/v1/admin/harvest?admin_key=...&target_videos=50`
  - `GET /api/v1/admin/harvest/logs?admin_key=...&date=2026-02-27`
- CLI: `python3 -m src.tasks.recipe_harvester [target_count]`

## Environment Variables

```
YOUTUBE_API_KEY=...        # Required - YouTube Data API v3 key
ADMIN_API_KEY=...          # Required for API harvest trigger
```

## Cron Setup

```bash
# Run daily at 3am UTC
0 3 * * * cd /path/to/fitbites-backend && python3 -m src.tasks.recipe_harvester 50
```

## Expected Output

Per daily run (~50 videos searched):
- ~30-40 pass quality validation
- ~5-10 duplicates filtered
- **~20-35 new recipes saved**

Run 3x daily = 60-100+ recipes/day.
