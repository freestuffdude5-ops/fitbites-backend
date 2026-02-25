"""AI-powered recipe extraction from raw scraped content.

Uses Claude to parse titles, descriptions, and captions into
structured Recipe objects with ingredients, steps, and nutrition estimates.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

import anthropic

from src.models import Recipe, NutritionInfo, Ingredient, Creator, Platform

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """You are a recipe extraction AI for FitBites, a healthy recipe app.

Given the following raw post data from {platform}, extract a structured recipe.

Raw data:
```json
{raw_data}
```

Extract and return a JSON object with these fields:
- title: Recipe title (clean, appealing)
- description: 1-2 sentence description
- ingredients: Array of {{name, quantity}} objects
- steps: Array of step strings (numbered instructions)
- nutrition: {{calories, protein_g, carbs_g, fat_g, servings}} — estimate from ingredients if not stated
- tags: Array of relevant tags from: ["high-protein", "low-cal", "keto", "vegan", "gluten-free", "quick", "meal-prep", "dessert", "breakfast", "lunch", "dinner", "snack"]
- cook_time_minutes: estimated cook time
- difficulty: "easy", "medium", or "hard"

If the post doesn't contain a recipe, return {{"is_recipe": false}}.
Be accurate with nutrition estimates. When in doubt, overestimate calories.

Return ONLY valid JSON, no markdown."""


class RecipeExtractor:
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model

    async def extract(self, raw_data: dict) -> Optional[Recipe]:
        """Extract structured recipe from raw scraped data using AI."""
        platform = raw_data.get("platform", "unknown")

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=2000,
                messages=[
                    {
                        "role": "user",
                        "content": EXTRACTION_PROMPT.format(
                            platform=platform,
                            raw_data=json.dumps(raw_data, indent=2, default=str),
                        ),
                    }
                ],
            )

            text = response.content[0].text.strip()
            # Strip markdown code fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]

            parsed = json.loads(text)

            if parsed.get("is_recipe") is False:
                logger.info(f"Post is not a recipe: {raw_data.get('title', '')[:50]}")
                return None

            # Build Recipe model
            creator = Creator(
                username=raw_data.get("author") or raw_data.get("channel_title", "unknown"),
                platform=Platform(platform),
                profile_url=raw_data.get("channel_url", raw_data.get("source_url", "")),
            )

            ingredients = [
                Ingredient(name=i["name"], quantity=i["quantity"])
                for i in parsed.get("ingredients", [])
            ]

            nutrition = None
            if n := parsed.get("nutrition"):
                nutrition = NutritionInfo(
                    calories=n.get("calories", 0),
                    protein_g=n.get("protein_g", 0),
                    carbs_g=n.get("carbs_g", 0),
                    fat_g=n.get("fat_g", 0),
                    servings=n.get("servings", 1),
                )

            return Recipe(
                title=parsed.get("title", raw_data.get("title", "Untitled")),
                description=parsed.get("description"),
                creator=creator,
                platform=Platform(platform),
                source_url=raw_data.get("source_url", ""),
                thumbnail_url=raw_data.get("thumbnail_url"),
                ingredients=ingredients,
                steps=parsed.get("steps", []),
                nutrition=nutrition,
                tags=parsed.get("tags", []),
                cook_time_minutes=parsed.get("cook_time_minutes"),
                difficulty=parsed.get("difficulty"),
                views=raw_data.get("views"),
                likes=raw_data.get("likes"),
                comments=raw_data.get("comments"),
            )

        except Exception as e:
            logger.error(f"AI extraction failed: {e}")
            return None
