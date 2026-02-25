"""Viral recipe scoring algorithm — ranks discovered recipes by engagement + health quality.

Designed by IRIS research team. Weights based on social media engagement analysis:
- Saves (30%): Strongest "I want to make this" intent signal
- Shares (25%): Organic reach expansion
- Comments (20%): Depth of engagement, "I made this!" validation
- Likes (15%): Passive engagement (weakest signal)
- Recency (10%): Fresh content preferred, 30-day decay

Recipe content has 2-3x higher save rates than avg TikTok content.
Save rate >3% = exceptional, Share rate >1% = viral territory.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

from src.models.recipe import NutritionInfo, Platform, Recipe

# --- Weights ---
W_SAVES = 0.30
W_SHARES = 0.25
W_COMMENTS = 0.20
W_LIKES = 0.15
W_RECENCY = 0.10

# Platform credibility multipliers (TikTok recipe content indexes highest for virality)
PLATFORM_WEIGHT: dict[str, float] = {
    Platform.TIKTOK: 1.0,
    Platform.YOUTUBE: 0.9,
    Platform.INSTAGRAM: 0.85,
    Platform.REDDIT: 0.75,
}

# Recency decay window (days)
RECENCY_WINDOW_DAYS = 30

# Health score thresholds
MIN_PROTEIN_G = 20
MAX_CALORIES = 500
IDEAL_PROTEIN_RATIO = 0.30  # 30% of calories from protein is ideal


def _normalize_engagement(metric: Optional[int], follower_count: Optional[int]) -> float:
    """Normalize an engagement metric by follower count to get engagement rate.

    If follower count is unknown, use absolute metric with log scaling
    to prevent mega-accounts from dominating.
    """
    if metric is None or metric <= 0:
        return 0.0

    if follower_count and follower_count > 0:
        # Engagement rate (capped at 1.0 for sanity)
        return min(metric / follower_count, 1.0)

    # Fallback: log-scale absolute numbers (handles unknown follower counts)
    # log10(1000) = 3, log10(1M) = 6, log10(1B) = 9
    # Normalize to 0-1 range assuming max ~100M engagements
    return min(math.log10(max(metric, 1)) / 8.0, 1.0)


def _recency_boost(published_at: Optional[datetime]) -> float:
    """Calculate recency boost: 1.0 for today, decays linearly to 0.0 over RECENCY_WINDOW_DAYS."""
    if published_at is None:
        return 0.5  # Unknown date gets neutral score

    now = datetime.now(timezone.utc)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)

    days_old = (now - published_at).total_seconds() / 86400
    if days_old < 0:
        return 1.0  # Future date (clock skew) — treat as brand new

    return max(0.0, 1.0 - (days_old / RECENCY_WINDOW_DAYS))


def compute_health_score(nutrition: Optional[NutritionInfo]) -> float:
    """Score 0.0-1.0 based on nutritional quality.

    Factors:
    - Protein-to-calorie ratio (higher = better)
    - Absolute protein content (>20g bonus)
    - Calorie reasonableness (<500 per serving bonus)
    - Macro balance penalty for extreme ratios
    """
    if nutrition is None:
        return 0.5  # Unknown nutrition gets neutral score

    score = 0.5  # Base score

    cal = max(nutrition.calories, 1)  # avoid division by zero
    protein = nutrition.protein_g

    # Protein-to-calorie ratio (protein has 4 cal/g)
    protein_cal_ratio = (protein * 4) / cal
    # Reward high protein ratio (0.25-0.40 is ideal range)
    if protein_cal_ratio >= 0.25:
        score += 0.25
    elif protein_cal_ratio >= 0.15:
        score += 0.15
    else:
        score += protein_cal_ratio * 0.6  # Proportional for low protein

    # Absolute protein bonus
    if protein >= 30:
        score += 0.15
    elif protein >= 20:
        score += 0.10

    # Calorie reasonableness (per serving)
    per_serving_cal = cal / max(nutrition.servings, 1)
    if per_serving_cal <= 400:
        score += 0.10
    elif per_serving_cal <= 600:
        score += 0.05
    # >600 cal/serving: no bonus

    # Sugar penalty (if available)
    if nutrition.sugar_g is not None and nutrition.sugar_g > 20:
        score -= 0.10

    return max(0.0, min(1.0, score))


def compute_viral_score(recipe: Recipe) -> float:
    """Compute the FitBites viral score (0-100) for a recipe.

    Combines engagement metrics, recency, platform weight, and health score.
    Returns a float 0-100 suitable for ranking and display.
    """
    follower_count = recipe.creator.follower_count

    # For platforms like Reddit, use upvotes as "likes" and saves aren't available
    # Map available metrics (saves/shares may be None for some platforms)
    saves = _normalize_engagement(
        getattr(recipe, 'saves', None) or (recipe.shares if recipe.platform == Platform.REDDIT else None),
        follower_count,
    )
    shares = _normalize_engagement(recipe.shares, follower_count)
    comments = _normalize_engagement(recipe.comments, follower_count)
    likes = _normalize_engagement(recipe.likes, follower_count)
    recency = _recency_boost(recipe.published_at)

    # Weighted engagement score (0-1)
    engagement = (
        W_SAVES * saves
        + W_SHARES * shares
        + W_COMMENTS * comments
        + W_LIKES * likes
        + W_RECENCY * recency
    )

    # Platform weight
    platform_mult = PLATFORM_WEIGHT.get(recipe.platform, 0.7)

    # Health score
    health = compute_health_score(recipe.nutrition)

    # Final score: engagement × platform × health, scaled to 0-100
    # Use geometric-ish combination so health can't be zero'd out entirely
    raw = engagement * platform_mult * (0.5 + 0.5 * health)

    # Scale to 0-100 (engagement rates are typically tiny, so amplify)
    # A save rate of 3% with good health should score ~80+
    scaled = min(100.0, raw * 500)

    return round(scaled, 1)


def score_and_rank(recipes: list[Recipe]) -> list[Recipe]:
    """Score all recipes and return sorted by viral_score descending."""
    for recipe in recipes:
        recipe.virality_score = compute_viral_score(recipe)
    return sorted(recipes, key=lambda r: r.virality_score or 0, reverse=True)
