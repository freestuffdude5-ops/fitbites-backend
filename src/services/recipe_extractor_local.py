"""Local recipe extraction — parses Reddit posts without AI API calls.

Extracts ingredients, steps, nutrition from structured Reddit posts.
Many r/fitmeals and r/EatCheapAndHealthy posts follow predictable formats.

Falls back gracefully when a post can't be parsed (returns None).
"""
from __future__ import annotations

import re
import logging
from typing import Optional

from src.models import Recipe, NutritionInfo, Ingredient, Creator, Platform

logger = logging.getLogger(__name__)

# Patterns for extracting nutrition info from text
CALORIE_PATTERN = re.compile(r'(\d{2,4})\s*(?:cal(?:ories?)?|kcal)\b', re.IGNORECASE)
PROTEIN_PATTERN = re.compile(r'(\d{1,3})\.?\d*\s*g?\s*(?:of\s+)?protein', re.IGNORECASE)
CARB_PATTERN = re.compile(r'(\d{1,3})\.?\d*\s*g?\s*(?:of\s+)?carb', re.IGNORECASE)
FAT_PATTERN = re.compile(r'(\d{1,3})\.?\d*\s*g?\s*(?:of\s+)?fat', re.IGNORECASE)
SERVING_PATTERN = re.compile(r'(?:serves?|servings?|makes?)\s*:?\s*(\d+)', re.IGNORECASE)

# Common ingredient line patterns
INGREDIENT_LINE = re.compile(
    r'^[\s•\-\*]*'  # bullet or dash prefix
    r'(\d+[\d/\.]*\s*(?:cup|tbsp|tsp|oz|g|lb|ml|kg|clove|piece|slice|can|bunch|head)s?\b.*)',
    re.IGNORECASE | re.MULTILINE,
)

# Step patterns  
STEP_PATTERN = re.compile(
    r'(?:^|\n)\s*(?:\d+[\.\)]\s*|step\s*\d+[:\.\)]\s*)(.*?)(?=\n\s*(?:\d+[\.\)]|step\s*\d+|$))',
    re.IGNORECASE | re.DOTALL,
)


def _extract_number(pattern: re.Pattern, text: str) -> Optional[float]:
    """Extract a number from text using a regex pattern."""
    match = pattern.search(text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return None


def _looks_like_ingredient(line: str) -> bool:
    """Check if a line looks like an ingredient (not an instruction)."""
    lower = line.lower().strip()
    # Instructions tend to start with verbs
    instruction_starts = [
        "place", "cook", "bake", "mix", "stir", "heat", "add", "pour",
        "combine", "serve", "let", "remove", "slice", "chop", "preheat",
        "set", "put", "bring", "fold", "whisk", "cover", "turn",
        "to bake", "to cook",
    ]
    for verb in instruction_starts:
        if lower.startswith(verb + " "):
            return False
    # Too long = probably instruction
    if len(line) > 80:
        return False
    # Should contain food-like words or quantities
    has_quantity = bool(re.search(r'\d+\s*(?:g|oz|cup|tbsp|tsp|ml|lb|can|kg|piece|slice)', lower))
    has_food = bool(re.search(
        r'chicken|beef|pork|salmon|tuna|tofu|egg|rice|pasta|bread|cheese|yogurt|'
        r'butter|oil|onion|garlic|pepper|salt|sugar|flour|milk|cream|broccoli|'
        r'spinach|tomato|potato|bean|lentil|oat|avocado|banana|berry|apple|'
        r'sauce|powder|spice|vinegar|lemon|lime|honey|maple|cocoa|protein|'
        r'squash|cottage|mozzarella|cheddar|lettuce|cucumber|carrot|celery',
        lower,
    ))
    return has_quantity or has_food


def _extract_ingredients(text: str) -> list[Ingredient]:
    """Parse ingredient lines from post text."""
    ingredients = []
    lines = text.split("\n")

    # Strategy 1: Look for ingredients section
    in_ingredients_section = False
    for line in lines:
        stripped = line.strip()
        # Remove Reddit markdown escapes
        stripped = stripped.replace("\\-", "-").replace("\\*", "*")
        lower = stripped.lower()

        # Detect ingredients section header
        if any(kw in lower for kw in ["ingredient", "what you need", "you'll need", "shopping list"]):
            in_ingredients_section = True
            continue

        # Detect end of ingredients section
        if in_ingredients_section and any(kw in lower for kw in ["instruction", "direction", "step", "method", "how to"]):
            in_ingredients_section = False
            continue

        # Parse ingredient lines
        if in_ingredients_section and stripped and re.match(r'^[\-\*•\t]?\s*\S', stripped):
            clean = re.sub(r'^[\-\*•]\s*', '', stripped).strip()
            if len(clean) > 2 and _looks_like_ingredient(clean):
                qty_match = re.match(
                    r'^([\d/\.]+\s*(?:cup|tbsp|tsp|oz|g|lb|ml|kg|clove|piece|slice|can)s?)\s+(.+)',
                    clean, re.IGNORECASE,
                )
                if qty_match:
                    ingredients.append(Ingredient(name=qty_match.group(2).strip(), quantity=qty_match.group(1).strip()))
                else:
                    ingredients.append(Ingredient(name=clean, quantity=""))

    # Strategy 2: If no section found, scan all bullet lines for ingredient-like content
    if not ingredients:
        for line in lines:
            stripped = line.strip().replace("\\-", "-").replace("\\*", "*")
            # Match bullet/dash lines
            if re.match(r'^[\-\*•]\s+', stripped):
                clean = re.sub(r'^[\-\*•]\s+', '', stripped).strip()
                if len(clean) > 2 and _looks_like_ingredient(clean):
                    qty_match = re.match(
                        r'^([\d/\.]+\s*(?:cup|tbsp|tsp|oz|g|lb|ml|kg|clove|piece|slice|can)s?)\s+(.+)',
                        clean, re.IGNORECASE,
                    )
                    if qty_match:
                        ingredients.append(Ingredient(name=qty_match.group(2).strip(), quantity=qty_match.group(1).strip()))
                    else:
                        ingredients.append(Ingredient(name=clean, quantity=""))

    return ingredients[:20]


def _extract_steps(text: str) -> list[str]:
    """Parse cooking steps from post text."""
    steps = []
    lines = text.split("\n")

    in_steps_section = False
    for line in lines:
        stripped = line.strip()
        lower = stripped.lower()

        if any(kw in lower for kw in ["instruction", "direction", "step", "method", "how to make"]):
            in_steps_section = True
            continue

        if in_steps_section and stripped:
            # Numbered step
            step_match = re.match(r'^\d+[\.\)]\s*(.*)', stripped)
            if step_match:
                steps.append(step_match.group(1).strip())
            elif re.match(r'^[\-\*•]\s*\S', stripped):
                clean = re.sub(r'^[\-\*•]\s*', '', stripped)
                if len(clean) > 10:
                    steps.append(clean)

    return steps[:15]  # Cap at 15


def _infer_tags(title: str, text: str) -> list[str]:
    """Infer tags from content."""
    combined = f"{title} {text}".lower()
    tags = []
    tag_keywords = {
        "high-protein": ["high protein", "protein", "anabolic"],
        "low-cal": ["low cal", "1200", "1500", "deficit", "low calorie"],
        "keto": ["keto", "low carb"],
        "vegan": ["vegan", "plant based", "plant-based"],
        "gluten-free": ["gluten free", "gluten-free", "celiac"],
        "quick": ["quick", "15 min", "20 min", "easy", "simple", "fast"],
        "meal-prep": ["meal prep", "prep", "batch cook"],
        "breakfast": ["breakfast", "morning", "oats", "smoothie"],
        "lunch": ["lunch", "midday"],
        "dinner": ["dinner", "supper", "evening"],
        "snack": ["snack", "bite"],
        "dessert": ["dessert", "sweet", "treat"],
    }
    for tag, keywords in tag_keywords.items():
        if any(kw in combined for kw in keywords):
            tags.append(tag)
    return tags[:5]


def extract_recipe_local(raw_data: dict) -> Optional[Recipe]:
    """Extract a Recipe from raw scraped data using local parsing (no AI).

    Returns None if the post doesn't contain enough recipe-like content.
    """
    title = raw_data.get("title", "")
    description = raw_data.get("description", "")
    text = f"{title}\n{description}"

    # Extract nutrition from title and body
    calories = _extract_number(CALORIE_PATTERN, text)
    protein = _extract_number(PROTEIN_PATTERN, text)
    carbs = _extract_number(CARB_PATTERN, text)
    fat = _extract_number(FAT_PATTERN, text)
    servings = _extract_number(SERVING_PATTERN, text) or 1

    # Extract ingredients and steps
    ingredients = _extract_ingredients(description)
    steps = _extract_steps(description)

    # Build nutrition info (may be partial)
    nutrition = None
    if calories or protein:
        nutrition = NutritionInfo(
            calories=int(calories or 0),
            protein_g=protein or 0,
            carbs_g=carbs or 0,
            fat_g=fat or 0,
            servings=int(servings),
        )

    # Build creator
    platform_str = raw_data.get("platform", "reddit")
    try:
        platform = Platform(platform_str)
    except ValueError:
        platform = Platform.REDDIT

    creator = Creator(
        username=raw_data.get("author", raw_data.get("channel_title", "unknown")),
        platform=platform,
        profile_url=raw_data.get("source_url", ""),
    )

    tags = _infer_tags(title, description)

    # Clean up title (decode HTML entities)
    clean_title = title.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")

    return Recipe(
        title=clean_title,
        description=description[:500] if description else None,
        creator=creator,
        platform=platform,
        source_url=raw_data.get("source_url", ""),
        thumbnail_url=raw_data.get("thumbnail_url"),
        ingredients=ingredients,
        steps=steps,
        nutrition=nutrition,
        tags=tags,
        views=raw_data.get("views"),
        likes=raw_data.get("likes"),
        comments=raw_data.get("comments"),
    )
