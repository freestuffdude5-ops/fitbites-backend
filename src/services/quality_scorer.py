"""Quality scoring system for recipes.

Scores each recipe 0.0-1.0 based on data completeness and validity.
Used to filter incomplete/garbage recipes from the database.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from src.models import Recipe

logger = logging.getLogger(__name__)

# Validation ranges
VALID_CALORIES = (100, 2000)
VALID_PROTEIN = (10, 200)
VALID_CARBS = (0, 500)
VALID_FAT = (0, 200)
MIN_COMPLETE_FIELDS = 6


@dataclass
class QualityReport:
    """Detailed quality assessment for a recipe."""
    score: float  # 0.0 - 1.0
    status: str  # "complete" or "incomplete"
    field_scores: dict  # breakdown by field
    warnings: list[str]  # validation issues


def _in_range(val: Optional[float], low: float, high: float) -> bool:
    return val is not None and low <= val <= high


def score_recipe(recipe: Recipe) -> QualityReport:
    """Score a recipe's quality from 0.0 to 1.0.

    Scoring weights:
      - Title present: 0.10
      - Description present: 0.05
      - Ingredients (1+): 0.20
      - Steps (1+): 0.15
      - Nutrition present: 0.15
      - Nutrition valid: 0.10
      - Tags present: 0.05
      - Creator info: 0.05
      - Media (thumbnail/video): 0.05
      - Engagement data: 0.05
      - Cook time: 0.05
    """
    scores: dict[str, float] = {}
    warnings: list[str] = []

    # Title
    scores["title"] = 0.10 if recipe.title and len(recipe.title) >= 5 else 0.0

    # Description
    scores["description"] = 0.05 if recipe.description and len(recipe.description) >= 10 else 0.0

    # Ingredients
    if recipe.ingredients and len(recipe.ingredients) >= 2:
        scores["ingredients"] = 0.20
    elif recipe.ingredients:
        scores["ingredients"] = 0.10
    else:
        scores["ingredients"] = 0.0

    # Steps
    if recipe.steps and len(recipe.steps) >= 2:
        scores["steps"] = 0.15
    elif recipe.steps:
        scores["steps"] = 0.08
    else:
        scores["steps"] = 0.0

    # Nutrition present
    if recipe.nutrition:
        scores["nutrition_present"] = 0.15
        # Nutrition valid
        valid = True
        if not _in_range(recipe.nutrition.calories, *VALID_CALORIES):
            warnings.append(f"Calories {recipe.nutrition.calories} outside range {VALID_CALORIES}")
            valid = False
        if not _in_range(recipe.nutrition.protein_g, *VALID_PROTEIN):
            warnings.append(f"Protein {recipe.nutrition.protein_g}g outside range {VALID_PROTEIN}")
            valid = False
        scores["nutrition_valid"] = 0.10 if valid else 0.0
    else:
        scores["nutrition_present"] = 0.0
        scores["nutrition_valid"] = 0.0
        warnings.append("No nutrition data")

    # Tags
    scores["tags"] = 0.05 if recipe.tags and len(recipe.tags) >= 1 else 0.0

    # Creator
    scores["creator"] = 0.05 if recipe.creator and recipe.creator.username else 0.0

    # Media
    has_media = bool(recipe.thumbnail_url or recipe.video_url)
    scores["media"] = 0.05 if has_media else 0.0

    # Engagement
    has_engagement = any([recipe.views, recipe.likes, recipe.comments])
    scores["engagement"] = 0.05 if has_engagement else 0.0

    # Cook time
    scores["cook_time"] = 0.05 if recipe.cook_time_minutes and recipe.cook_time_minutes > 0 else 0.0

    total = sum(scores.values())
    total = round(min(total, 1.0), 3)

    # Count filled fields for completeness check
    filled = sum(1 for v in scores.values() if v > 0)
    status = "complete" if filled >= MIN_COMPLETE_FIELDS else "incomplete"

    return QualityReport(
        score=total,
        status=status,
        field_scores=scores,
        warnings=warnings,
    )


def filter_quality(recipes: list[Recipe], min_score: float = 0.4) -> tuple[list[Recipe], list[Recipe]]:
    """Split recipes into passing and failing quality threshold.

    Returns (passed, failed).
    """
    passed, failed = [], []
    for r in recipes:
        report = score_recipe(r)
        if report.score >= min_score:
            passed.append(r)
        else:
            failed.append(r)
            logger.debug(f"Quality filter rejected: {r.title[:50]} (score={report.score})")
    return passed, failed
