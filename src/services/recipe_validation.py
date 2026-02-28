"""
Recipe Validation Service - Automated Quality Gate

Validates recipes before they are added to the production database.
Implements Hayden's automated validation requirements from 2026-02-28.

Validation Rules:
1. Required Data Check - Complete macros, ingredients, instructions, thumbnail, source
2. Multi-Recipe Detection - Reject compilations, "day in the life" videos
3. Quality Inference - Title length, ingredient quality, step coherence
"""

import re
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict


# Path to log rejected recipes
REJECTED_LOG_PATH = Path("/home/user/clawd/company/fitbites/rejected_recipes.jsonl")


@dataclass
class ValidationResult:
    is_valid: bool
    recipe_title: str
    source_url: str
    reject_reason: Optional[str] = None
    validation_details: Optional[dict] = None


# Multi-recipe detection patterns (from Hayden's requirements)
MULTI_RECIPE_PATTERNS = [
    (r'\bday\s+(?:in\s+(?:my|the)\s+)?life\b', "Multi-recipe: 'day in the life'"),
    (r'\bfull\s+day\s+(?:of\s+)?eating\b', "Multi-recipe: 'full day of eating'"),
    (r'\bwhat\s+I\s+eat\s+(?:in\s+)?(?:a\s+)?day\b', "Multi-recipe: 'what I eat in a day'"),
    (r'\b\d+\s*recipes?\b', "Multi-recipe: contains number of recipes"),
    (r'\b\d+\s*meals?\b.*\b(?:prep|for\s+the\s+week)\b', "Multi-recipe: meal prep for the week"),
    (r'\beverything\s+I\s+ate\b', "Multi-recipe: 'everything I ate'"),
    (r'\b24\s*hours?\s+(?:of\s+)?eating\b', "Multi-recipe: '24 hours of eating'"),
    (r'\b(?:multiple|various|several)\s+(?:recipes?|meals?|dishes?)\b', "Multi-recipe: multiple/various recipes"),
    (r'\b(?:first|second|third|fourth|fifth)\s+recipe\b', "Multi-recipe: numbered recipe list"),
    (r'\brecipe\s+(?:one|two|three|four|five)\b', "Multi-recipe: recipe one/two/three"),
    (r'\bX\s*recipes?\b', "Multi-recipe: X recipes pattern"),
    (r'\bmeal\s+prep\s+(?:for\s+)?(?:the\s+)?week\b', "Multi-recipe: meal prep for the week"),
    (r'\b(in my|a day|typical day)\s+(?:of\s+)?(?:eating|meals)\b', "Multi-recipe: day of eating pattern"),
]


def log_rejection(recipe_title: str, source_url: str, reason: str):
    """Log rejected recipe to jsonl file for review."""
    entry = {
        "title": recipe_title,
        "url": source_url,
        "reason": reason,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    with open(REJECTED_LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


def validate_recipe(
    title: str,
    source_url: str,
    thumbnail_url: Optional[str],
    ingredients: list,
    steps: list,
    calories: Optional[int],
    protein_grams: Optional[float],
    carbs_grams: Optional[float],
    fat_grams: Optional[float],
    description: str = "",
) -> ValidationResult:
    """
    Run all validation checks on a recipe.
    
    Returns ValidationResult with is_valid=True if all checks pass,
    or is_valid=False with reject_reason if any check fails.
    """
    
    # === 1. Required Data Check ===
    
    # Check macros (all must be non-null)
    missing_macros = []
    if calories is None:
        missing_macros.append("calories")
    if protein_grams is None:
        missing_macros.append("protein_grams")
    if carbs_grams is None:
        missing_macros.append("carbs_grams")
    if fat_grams is None:
        missing_macros.append("fat_grams")
    
    if missing_macros:
        reason = f"Missing required macros: {', '.join(missing_macros)}"
        log_rejection(title, source_url, reason)
        return ValidationResult(
            is_valid=False,
            recipe_title=title,
            source_url=source_url,
            reject_reason=reason,
            validation_details={"missing_macros": missing_macros}
        )
    
    # Check ingredients (at least 3)
    if not ingredients or len(ingredients) < 3:
        reason = f"Insufficient ingredients: {len(ingredients) if ingredients else 0} (need 3+)"
        log_rejection(title, source_url, reason)
        return ValidationResult(
            is_valid=False,
            recipe_title=title,
            source_url=source_url,
            reject_reason=reason,
            validation_details={"ingredient_count": len(ingredients) if ingredients else 0}
        )
    
    # Check steps (at least 3)
    if not steps or len(steps) < 3:
        reason = f"Insufficient steps: {len(steps) if steps else 0} (need 3+)"
        log_rejection(title, source_url, reason)
        return ValidationResult(
            is_valid=False,
            recipe_title=title,
            source_url=source_url,
            reject_reason=reason,
            validation_details={"step_count": len(steps) if steps else 0}
        )
    
    # Check thumbnail URL
    if not thumbnail_url:
        reason = "Missing thumbnail_url"
        log_rejection(title, source_url, reason)
        return ValidationResult(
            is_valid=False,
            recipe_title=title,
            source_url=source_url,
            reject_reason=reason
        )
    
    # Check source URL
    if not source_url:
        reason = "Missing source_url"
        log_rejection(title, source_url, reason)
        return ValidationResult(
            is_valid=False,
            recipe_title=title,
            source_url=source_url,
            reject_reason=reason
        )
    
    # === 2. Multi-Recipe Detection ===
    
    # Combine title and description for pattern matching
    search_text = f"{title} {description}".lower()
    
    for pattern, message in MULTI_RECIPE_PATTERNS:
        if re.search(pattern, search_text, re.IGNORECASE):
            log_rejection(title, source_url, message)
            return ValidationResult(
                is_valid=False,
                recipe_title=title,
                source_url=source_url,
                reject_reason=message,
                validation_details={"pattern_matched": pattern}
            )
    
    # === 3. Quality Inference ===
    
    # Check title is reasonable length (not truncated garbage)
    if len(title) < 10:
        reason = f"Title too short (likely truncated): {len(title)} chars"
        log_rejection(title, source_url, reason)
        return ValidationResult(
            is_valid=False,
            recipe_title=title,
            source_url=source_url,
            reject_reason=reason
        )
    
    if len(title) > 300:
        reason = f"Title too long (likely garbage): {len(title)} chars"
        log_rejection(title, source_url, reason)
        return ValidationResult(
            is_valid=False,
            recipe_title=title,
            source_url=source_url,
            reject_reason=reason
        )
    
    # Check ingredients aren't just noise (very short items like "ok", "yes", etc.)
    if ingredients:
        valid_ingredients = [i for i in ingredients if len(str(i).strip()) > 2]
        if len(valid_ingredients) < 3:
            reason = f"Ingredients appear to be noise/transcript garbage"
            log_rejection(title, source_url, reason)
            return ValidationResult(
                is_valid=False,
                recipe_title=title,
                source_url=source_url,
                reject_reason=reason,
                validation_details={"valid_ingredients": len(valid_ingredients)}
            )
    
    # Check steps make sense (not just timestamps or numbers)
    if steps:
        valid_steps = [s for s in steps if len(str(s).strip()) > 10]
        if len(valid_steps) < 2:
            reason = f"Steps appear to be auto-generated nonsense"
            log_rejection(title, source_url, reason)
            return ValidationResult(
                is_valid=False,
                recipe_title=title,
                source_url=source_url,
                reject_reason=reason,
                validation_details={"valid_steps": len(valid_steps)}
            )
    
    # === ALL CHECKS PASSED ===
    return ValidationResult(
        is_valid=True,
        recipe_title=title,
        source_url=source_url,
        validation_details={
            "ingredient_count": len(ingredients),
            "step_count": len(steps),
            "macros": {"calories": calories, "protein": protein_grams, "carbs": carbs_grams, "fat": fat_grams}
        }
    )


def validate_and_process_recipes(recipes: list[dict]) -> dict:
    """
    Validate a batch of recipes and return summary.
    
    Input: list of recipe dicts (as returned from extraction)
    Output: {
        "added": [...],   # recipes that passed validation
        "rejected": [...], # recipes that failed with reasons
        "summary": {
            "total": N,
            "passed": M,
            "rejected": K
        }
    }
    """
    added = []
    rejected = []
    
    for recipe in recipes:
        result = validate_recipe(
            title=recipe.get("title", ""),
            source_url=recipe.get("source_url", ""),
            thumbnail_url=recipe.get("thumbnail_url"),
            ingredients=recipe.get("ingredients", []),
            steps=recipe.get("steps", []),
            calories=recipe.get("calories") or recipe.get("nutrition", {}).get("calories"),
            protein_grams=recipe.get("protein_grams") or recipe.get("protein_g") or recipe.get("nutrition", {}).get("protein_grams") or recipe.get("nutrition", {}).get("protein_g"),
            carbs_grams=recipe.get("carbs_grams") or recipe.get("carbs_g") or recipe.get("nutrition", {}).get("carbs_grams") or recipe.get("nutrition", {}).get("carbs_g"),
            fat_grams=recipe.get("fat_grams") or recipe.get("fat_g") or recipe.get("nutrition", {}).get("fat_grams") or recipe.get("nutrition", {}).get("fat_g"),
            description=recipe.get("description", ""),
        )
        
        if result.is_valid:
            added.append(recipe)
        else:
            rejected.append({
                "title": recipe.get("title"),
                "source_url": recipe.get("source_url"),
                "reason": result.reject_reason
            })
    
    return {
        "added": added,
        "rejected": rejected,
        "summary": {
            "total": len(recipes),
            "passed": len(added),
            "rejected": len(rejected)
        }
    }


# Test function
if __name__ == "__main__":
    # Test cases
    test_recipes = [
        # Should pass
        {
            "title": "High Protein Grilled Cheese Breakfast Burrito",
            "source_url": "https://youtube.com/watch?v=abc123",
            "thumbnail_url": "https://img.youtube.com/vi/abc123/maxresdefault.jpg",
            "ingredients": ["2 eggs", "1 cup cheese", "1 tortilla", "50g chicken breast"],
            "steps": ["Cook chicken", "Scramble eggs", "Toast tortilla", "Assemble and serve"],
            "calories": 450,
            "protein_grams": 35.0,
            "carbs_grams": 28.0,
            "fat_grams": 22.0,
            "description": "A delicious high protein breakfast"
        },
        # Should fail - missing macros
        {
            "title": "Test Recipe",
            "source_url": "https://youtube.com/watch?v=def456",
            "thumbnail_url": "https://img.youtube.com/vi/def456/maxresdefault.jpg",
            "ingredients": ["egg", "cheese", "tortilla"],
            "steps": ["Cook", "Serve"],
            "calories": None,
            "protein_grams": 35.0,
            "carbs_grams": 28.0,
            "fat_grams": 22.0,
        },
        # Should fail - multi-recipe
        {
            "title": "5 Recipes For Meal Prep This Week",
            "source_url": "https://youtube.com/watch?v=ghi789",
            "thumbnail_url": "https://img.youtube.com/vi/ghi789/maxresdefault.jpg",
            "ingredients": ["rice", "chicken", "broccoli"],
            "steps": ["Cook chicken", "Cook rice", "Steam broccoli"],
            "calories": 450,
            "protein_grams": 35.0,
            "carbs_grams": 28.0,
            "fat_grams": 22.0,
            "description": "Here are 5 great recipes you can prep"
        },
    ]
    
    result = validate_and_process_recipes(test_recipes)
    print(json.dumps(result, indent=2))
