# Recipe Orchestrator — Unified Harvest System

## Overview

The Recipe Orchestrator is the master coordinator that runs all 3 platform scrapers (YouTube, Instagram, TikTok) in parallel, extracts recipes via AI, deduplicates cross-platform, quality-scores, and stores to the database.

## Architecture

```
┌─────────────────────────────────────────────┐
│           RecipeOrchestrator                │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│  │ YouTube  │ │Instagram │ │  TikTok  │   │
│  │ Scraper  │ │ Scraper  │ │ Scraper  │   │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘   │
│       └──────┬──────┴──────┬─────┘         │
│              ▼                              │
│       RecipeExtractor (AI)                  │
│              ▼                              │
│       RecipeDeduplicator                    │
│              ▼                              │
│       QualityScorer                         │
│              ▼                              │
│       Database (upsert)                     │
└─────────────────────────────────────────────┘
```

## API Endpoints

### `POST /api/v1/recipes/run-harvest`
Trigger a manual harvest. Requires `X-Admin-Key` header.

```bash
curl -X POST https://api.fitbites.app/api/v1/recipes/run-harvest \
  -H "X-Admin-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"limit_per_platform": 50, "platforms": ["youtube", "tiktok"]}'
```

### `GET /api/v1/recipes/harvest-status`
Check last harvest run status.

### `GET /api/v1/recipes/stats`
Database stats: total recipes, by platform, quality breakdown.

## Deduplication

- **Title similarity**: >80% match (normalized, noise words removed) → duplicate
- **Title + macro match**: >60% title similarity AND calories ±50, protein ±5g → duplicate
- **Best version kept**: Prefers recipes with more ingredients, steps, and nutrition data
- **Dedup log**: Tracks all decisions for audit

## Quality Scoring (0.0 - 1.0)

| Field | Weight |
|-------|--------|
| Title (5+ chars) | 0.10 |
| Description (10+ chars) | 0.05 |
| Ingredients (2+) | 0.20 |
| Steps (2+) | 0.15 |
| Nutrition present | 0.15 |
| Nutrition valid | 0.10 |
| Tags | 0.05 |
| Creator info | 0.05 |
| Media | 0.05 |
| Engagement | 0.05 |
| Cook time | 0.05 |

Recipes with 6+ fields scoring > 0 = "complete". Default minimum score: 0.4.

## Cron Job Setup (Production)

### Using systemd timer (recommended)

```bash
# /etc/systemd/system/fitbites-harvest.service
[Unit]
Description=FitBites Daily Recipe Harvest
After=network.target

[Service]
Type=oneshot
WorkingDirectory=/opt/fitbites-backend
ExecStart=/opt/fitbites-backend/venv/bin/python -c "
import asyncio
from src.services.recipe_orchestrator import RecipeOrchestrator
async def main():
    orch = RecipeOrchestrator.from_settings()
    stats = await orch.run_harvest(limit_per_platform=50)
    print(stats.to_dict())
asyncio.run(main())
"
Environment=PYTHONPATH=/opt/fitbites-backend
EnvironmentFile=/opt/fitbites-backend/.env

[Install]
WantedBy=multi-user.target
```

```bash
# /etc/systemd/system/fitbites-harvest.timer
[Unit]
Description=Run FitBites harvest daily at 3 AM

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl enable --now fitbites-harvest.timer
```

### Using crontab (alternative)

```bash
0 3 * * * cd /opt/fitbites-backend && /opt/fitbites-backend/venv/bin/python -c "import asyncio; from src.services.recipe_orchestrator import RecipeOrchestrator; asyncio.run(RecipeOrchestrator.from_settings().run_harvest(limit_per_platform=50))" >> /var/log/fitbites-harvest.log 2>&1
```

## Environment Variables Required

```
YOUTUBE_API_KEY=...
TIKTOK_API_KEY=...
TIKTOK_API_BASE=https://ensembledata.com/apis
INSTAGRAM_API_KEY=...
INSTAGRAM_API_BASE=https://instagram-scraper-api.p.rapidapi.com
ANTHROPIC_API_KEY=...
ADMIN_API_KEY=...
DATABASE_URL=...
```

## Monitoring

- Check `/api/v1/recipes/harvest-status` after each run
- Target: 100+ new complete recipes per day (50/platform × 3 platforms, ~60% extraction rate)
- Logs tagged with `[harvest:<run_id>]` for easy filtering
