"""Recipe deduplication system for cross-platform recipe matching.

Detects duplicate recipes across YouTube, Instagram, and TikTok using
title similarity and macro-nutritional proximity.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Optional

from src.models import Recipe

logger = logging.getLogger(__name__)


@dataclass
class DedupResult:
    """Result of a deduplication check."""
    is_duplicate: bool
    matched_recipe_id: Optional[str] = None
    match_reason: Optional[str] = None
    title_similarity: float = 0.0
    kept_version: Optional[str] = None  # "existing" or "new"


@dataclass
class DedupLog:
    """Tracks all deduplication decisions for a harvest run."""
    entries: list[dict] = field(default_factory=list)
    total_checked: int = 0
    duplicates_found: int = 0
    duplicates_replaced: int = 0
    duplicates_skipped: int = 0

    def record(self, new_recipe: Recipe, result: DedupResult):
        self.total_checked += 1
        if result.is_duplicate:
            self.duplicates_found += 1
            if result.kept_version == "new":
                self.duplicates_replaced += 1
            else:
                self.duplicates_skipped += 1
            self.entries.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "new_title": new_recipe.title,
                "new_platform": new_recipe.platform.value if new_recipe.platform else "unknown",
                "matched_id": result.matched_recipe_id,
                "reason": result.match_reason,
                "title_similarity": round(result.title_similarity, 3),
                "action": result.kept_version or "skipped",
            })

    def summary(self) -> dict:
        return {
            "total_checked": self.total_checked,
            "duplicates_found": self.duplicates_found,
            "duplicates_replaced": self.duplicates_replaced,
            "duplicates_skipped": self.duplicates_skipped,
            "unique_new": self.total_checked - self.duplicates_skipped,
        }


def _normalize_title(title: str) -> str:
    """Normalize a recipe title for comparison."""
    import re
    t = title.lower().strip()
    # Remove common prefixes/suffixes
    for noise in ["recipe", "how to make", "easy", "quick", "the best", "my", "homemade"]:
        t = t.replace(noise, "")
    t = re.sub(r"[^\w\s]", "", t)  # remove punctuation
    t = re.sub(r"\s+", " ", t).strip()
    return t


def title_similarity(a: str, b: str) -> float:
    """Compute normalized title similarity (0.0 - 1.0)."""
    na, nb = _normalize_title(a), _normalize_title(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def macros_similar(a: Recipe, b: Recipe, cal_tol: int = 50, protein_tol: float = 5.0) -> bool:
    """Check if two recipes have similar macros within tolerance."""
    if not a.nutrition or not b.nutrition:
        return False
    cal_match = abs(a.nutrition.calories - b.nutrition.calories) <= cal_tol
    pro_match = abs(a.nutrition.protein_g - b.nutrition.protein_g) <= protein_tol
    return cal_match and pro_match


def _recipe_completeness(recipe: Recipe) -> int:
    """Count how many 'complete' fields a recipe has (for choosing best version)."""
    score = 0
    if recipe.ingredients:
        score += len(recipe.ingredients)
    if recipe.steps:
        score += len(recipe.steps)
    if recipe.nutrition:
        score += 3
    if recipe.description:
        score += 1
    if recipe.thumbnail_url:
        score += 1
    if recipe.tags:
        score += 1
    return score


class RecipeDeduplicator:
    """Cross-platform recipe deduplication engine."""

    def __init__(
        self,
        title_threshold: float = 0.80,
        calorie_tolerance: int = 50,
        protein_tolerance: float = 5.0,
    ):
        self.title_threshold = title_threshold
        self.calorie_tolerance = calorie_tolerance
        self.protein_tolerance = protein_tolerance
        self.log = DedupLog()

    def check(self, new_recipe: Recipe, existing_recipes: list[Recipe]) -> DedupResult:
        """Check if new_recipe is a duplicate of any existing recipe.

        Returns DedupResult with match info and which version to keep.
        """
        for existing in existing_recipes:
            sim = title_similarity(new_recipe.title, existing.title)

            if sim >= self.title_threshold:
                # Title match — decide which to keep
                kept = self._pick_best(new_recipe, existing)
                result = DedupResult(
                    is_duplicate=True,
                    matched_recipe_id=existing.id,
                    match_reason=f"title_similarity={sim:.2f}",
                    title_similarity=sim,
                    kept_version=kept,
                )
                self.log.record(new_recipe, result)
                return result

            # If titles are somewhat similar AND macros match, also flag
            if sim >= 0.60 and macros_similar(
                new_recipe, existing, self.calorie_tolerance, self.protein_tolerance
            ):
                kept = self._pick_best(new_recipe, existing)
                result = DedupResult(
                    is_duplicate=True,
                    matched_recipe_id=existing.id,
                    match_reason=f"title_similarity={sim:.2f}+macro_match",
                    title_similarity=sim,
                    kept_version=kept,
                )
                self.log.record(new_recipe, result)
                return result

        result = DedupResult(is_duplicate=False)
        self.log.record(new_recipe, result)
        return result

    def _pick_best(self, new: Recipe, existing: Recipe) -> str:
        """Decide whether to keep 'new' or 'existing' version."""
        new_score = _recipe_completeness(new)
        existing_score = _recipe_completeness(existing)
        return "new" if new_score > existing_score else "existing"

    def deduplicate_batch(self, recipes: list[Recipe]) -> list[Recipe]:
        """Deduplicate a batch of recipes, keeping the best version of each.

        Returns deduplicated list.
        """
        result: list[Recipe] = []
        for recipe in recipes:
            dedup = self.check(recipe, result)
            if not dedup.is_duplicate:
                result.append(recipe)
            elif dedup.kept_version == "new" and dedup.matched_recipe_id:
                # Replace existing with new (better version)
                result = [
                    r for r in result if r.id != dedup.matched_recipe_id
                ] + [recipe]
        return result
