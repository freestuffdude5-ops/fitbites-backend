"""Local food database with nutrition data for common foods.

Built as a local cache for fast food search. Covers top ~200 common foods
with USDA-sourced nutrition data (per 100g).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from difflib import SequenceMatcher

COMMON_FOODS: list[dict] = [
    # Proteins
    {"name": "chicken breast", "category": "protein", "calories": 165, "protein": 31.0, "carbs": 0.0, "fat": 3.6, "fiber": 0.0, "serving_g": 100},
    {"name": "chicken thigh", "category": "protein", "calories": 209, "protein": 26.0, "carbs": 0.0, "fat": 10.9, "fiber": 0.0, "serving_g": 100},
    {"name": "chicken wing", "category": "protein", "calories": 203, "protein": 30.5, "carbs": 0.0, "fat": 8.1, "fiber": 0.0, "serving_g": 100},
    {"name": "chicken drumstick", "category": "protein", "calories": 172, "protein": 28.3, "carbs": 0.0, "fat": 5.7, "fiber": 0.0, "serving_g": 100},
    {"name": "ground beef 80/20", "category": "protein", "calories": 254, "protein": 17.2, "carbs": 0.0, "fat": 20.0, "fiber": 0.0, "serving_g": 100},
    {"name": "ground beef 90/10", "category": "protein", "calories": 176, "protein": 20.0, "carbs": 0.0, "fat": 10.0, "fiber": 0.0, "serving_g": 100},
    {"name": "ground turkey", "category": "protein", "calories": 170, "protein": 21.0, "carbs": 0.0, "fat": 9.4, "fiber": 0.0, "serving_g": 100},
    {"name": "salmon", "category": "protein", "calories": 208, "protein": 20.4, "carbs": 0.0, "fat": 13.4, "fiber": 0.0, "serving_g": 100},
    {"name": "tuna", "category": "protein", "calories": 132, "protein": 28.2, "carbs": 0.0, "fat": 1.3, "fiber": 0.0, "serving_g": 100},
    {"name": "shrimp", "category": "protein", "calories": 85, "protein": 20.1, "carbs": 0.0, "fat": 0.5, "fiber": 0.0, "serving_g": 100},
    {"name": "tilapia", "category": "protein", "calories": 96, "protein": 20.1, "carbs": 0.0, "fat": 1.7, "fiber": 0.0, "serving_g": 100},
    {"name": "cod", "category": "protein", "calories": 82, "protein": 17.8, "carbs": 0.0, "fat": 0.7, "fiber": 0.0, "serving_g": 100},
    {"name": "pork chop", "category": "protein", "calories": 231, "protein": 25.7, "carbs": 0.0, "fat": 13.9, "fiber": 0.0, "serving_g": 100},
    {"name": "pork tenderloin", "category": "protein", "calories": 143, "protein": 26.2, "carbs": 0.0, "fat": 3.5, "fiber": 0.0, "serving_g": 100},
    {"name": "bacon", "category": "protein", "calories": 541, "protein": 37.0, "carbs": 1.4, "fat": 42.0, "fiber": 0.0, "serving_g": 100},
    {"name": "steak sirloin", "category": "protein", "calories": 183, "protein": 27.2, "carbs": 0.0, "fat": 7.6, "fiber": 0.0, "serving_g": 100},
    {"name": "steak ribeye", "category": "protein", "calories": 291, "protein": 24.8, "carbs": 0.0, "fat": 21.8, "fiber": 0.0, "serving_g": 100},
    {"name": "tofu", "category": "protein", "calories": 76, "protein": 8.0, "carbs": 1.9, "fat": 4.8, "fiber": 0.3, "serving_g": 100},
    {"name": "tempeh", "category": "protein", "calories": 192, "protein": 20.3, "carbs": 7.6, "fat": 10.8, "fiber": 0.0, "serving_g": 100},
    {"name": "egg", "category": "protein", "calories": 155, "protein": 13.0, "carbs": 1.1, "fat": 11.0, "fiber": 0.0, "serving_g": 100},
    {"name": "egg white", "category": "protein", "calories": 52, "protein": 10.9, "carbs": 0.7, "fat": 0.2, "fiber": 0.0, "serving_g": 100},
    {"name": "turkey breast", "category": "protein", "calories": 135, "protein": 30.0, "carbs": 0.0, "fat": 1.0, "fiber": 0.0, "serving_g": 100},
    {"name": "lamb", "category": "protein", "calories": 282, "protein": 25.5, "carbs": 0.0, "fat": 19.4, "fiber": 0.0, "serving_g": 100},
    {"name": "venison", "category": "protein", "calories": 158, "protein": 30.2, "carbs": 0.0, "fat": 3.2, "fiber": 0.0, "serving_g": 100},
    {"name": "bison", "category": "protein", "calories": 143, "protein": 28.4, "carbs": 0.0, "fat": 2.4, "fiber": 0.0, "serving_g": 100},

    # Dairy
    {"name": "whole milk", "category": "dairy", "calories": 61, "protein": 3.2, "carbs": 4.8, "fat": 3.3, "fiber": 0.0, "serving_g": 100},
    {"name": "skim milk", "category": "dairy", "calories": 34, "protein": 3.4, "carbs": 5.0, "fat": 0.1, "fiber": 0.0, "serving_g": 100},
    {"name": "greek yogurt", "category": "dairy", "calories": 97, "protein": 9.0, "carbs": 3.6, "fat": 5.0, "fiber": 0.0, "serving_g": 100},
    {"name": "yogurt plain", "category": "dairy", "calories": 63, "protein": 5.3, "carbs": 7.0, "fat": 1.6, "fiber": 0.0, "serving_g": 100},
    {"name": "cottage cheese", "category": "dairy", "calories": 98, "protein": 11.1, "carbs": 3.4, "fat": 4.3, "fiber": 0.0, "serving_g": 100},
    {"name": "cheddar cheese", "category": "dairy", "calories": 403, "protein": 24.9, "carbs": 1.3, "fat": 33.1, "fiber": 0.0, "serving_g": 100},
    {"name": "mozzarella", "category": "dairy", "calories": 280, "protein": 28.0, "carbs": 3.1, "fat": 17.1, "fiber": 0.0, "serving_g": 100},
    {"name": "parmesan", "category": "dairy", "calories": 431, "protein": 38.5, "carbs": 4.1, "fat": 28.6, "fiber": 0.0, "serving_g": 100},
    {"name": "cream cheese", "category": "dairy", "calories": 342, "protein": 5.9, "carbs": 4.1, "fat": 34.2, "fiber": 0.0, "serving_g": 100},
    {"name": "butter", "category": "dairy", "calories": 717, "protein": 0.9, "carbs": 0.1, "fat": 81.1, "fiber": 0.0, "serving_g": 100},
    {"name": "whey protein powder", "category": "dairy", "calories": 400, "protein": 80.0, "carbs": 10.0, "fat": 5.0, "fiber": 0.0, "serving_g": 100},

    # Grains & Carbs
    {"name": "white rice", "category": "grains", "calories": 130, "protein": 2.7, "carbs": 28.2, "fat": 0.3, "fiber": 0.4, "serving_g": 100},
    {"name": "brown rice", "category": "grains", "calories": 123, "protein": 2.7, "carbs": 25.6, "fat": 1.0, "fiber": 1.8, "serving_g": 100},
    {"name": "quinoa", "category": "grains", "calories": 120, "protein": 4.4, "carbs": 21.3, "fat": 1.9, "fiber": 2.8, "serving_g": 100},
    {"name": "oats", "category": "grains", "calories": 389, "protein": 16.9, "carbs": 66.3, "fat": 6.9, "fiber": 10.6, "serving_g": 100},
    {"name": "oatmeal cooked", "category": "grains", "calories": 71, "protein": 2.5, "carbs": 12.0, "fat": 1.5, "fiber": 1.7, "serving_g": 100},
    {"name": "pasta", "category": "grains", "calories": 131, "protein": 5.0, "carbs": 25.4, "fat": 1.1, "fiber": 1.8, "serving_g": 100},
    {"name": "whole wheat bread", "category": "grains", "calories": 247, "protein": 13.0, "carbs": 41.3, "fat": 3.4, "fiber": 6.8, "serving_g": 100},
    {"name": "white bread", "category": "grains", "calories": 265, "protein": 9.4, "carbs": 49.0, "fat": 3.2, "fiber": 2.7, "serving_g": 100},
    {"name": "tortilla flour", "category": "grains", "calories": 312, "protein": 8.3, "carbs": 52.0, "fat": 8.0, "fiber": 2.1, "serving_g": 100},
    {"name": "tortilla corn", "category": "grains", "calories": 218, "protein": 5.7, "carbs": 44.6, "fat": 2.9, "fiber": 5.2, "serving_g": 100},
    {"name": "bagel", "category": "grains", "calories": 257, "protein": 10.0, "carbs": 50.0, "fat": 1.6, "fiber": 2.2, "serving_g": 100},
    {"name": "couscous", "category": "grains", "calories": 112, "protein": 3.8, "carbs": 23.2, "fat": 0.2, "fiber": 1.4, "serving_g": 100},
    {"name": "sweet potato", "category": "grains", "calories": 86, "protein": 1.6, "carbs": 20.1, "fat": 0.1, "fiber": 3.0, "serving_g": 100},
    {"name": "potato", "category": "grains", "calories": 77, "protein": 2.0, "carbs": 17.5, "fat": 0.1, "fiber": 2.2, "serving_g": 100},

    # Vegetables
    {"name": "broccoli", "category": "vegetables", "calories": 34, "protein": 2.8, "carbs": 7.0, "fat": 0.4, "fiber": 2.6, "serving_g": 100},
    {"name": "spinach", "category": "vegetables", "calories": 23, "protein": 2.9, "carbs": 3.6, "fat": 0.4, "fiber": 2.2, "serving_g": 100},
    {"name": "kale", "category": "vegetables", "calories": 49, "protein": 4.3, "carbs": 8.8, "fat": 0.9, "fiber": 3.6, "serving_g": 100},
    {"name": "bell pepper", "category": "vegetables", "calories": 31, "protein": 1.0, "carbs": 6.0, "fat": 0.3, "fiber": 2.1, "serving_g": 100},
    {"name": "tomato", "category": "vegetables", "calories": 18, "protein": 0.9, "carbs": 3.9, "fat": 0.2, "fiber": 1.2, "serving_g": 100},
    {"name": "cucumber", "category": "vegetables", "calories": 15, "protein": 0.7, "carbs": 3.6, "fat": 0.1, "fiber": 0.5, "serving_g": 100},
    {"name": "carrot", "category": "vegetables", "calories": 41, "protein": 0.9, "carbs": 9.6, "fat": 0.2, "fiber": 2.8, "serving_g": 100},
    {"name": "onion", "category": "vegetables", "calories": 40, "protein": 1.1, "carbs": 9.3, "fat": 0.1, "fiber": 1.7, "serving_g": 100},
    {"name": "garlic", "category": "vegetables", "calories": 149, "protein": 6.4, "carbs": 33.1, "fat": 0.5, "fiber": 2.1, "serving_g": 100},
    {"name": "mushroom", "category": "vegetables", "calories": 22, "protein": 3.1, "carbs": 3.3, "fat": 0.3, "fiber": 1.0, "serving_g": 100},
    {"name": "zucchini", "category": "vegetables", "calories": 17, "protein": 1.2, "carbs": 3.1, "fat": 0.3, "fiber": 1.0, "serving_g": 100},
    {"name": "asparagus", "category": "vegetables", "calories": 20, "protein": 2.2, "carbs": 3.9, "fat": 0.1, "fiber": 2.1, "serving_g": 100},
    {"name": "green beans", "category": "vegetables", "calories": 31, "protein": 1.8, "carbs": 7.0, "fat": 0.2, "fiber": 2.7, "serving_g": 100},
    {"name": "cauliflower", "category": "vegetables", "calories": 25, "protein": 1.9, "carbs": 5.0, "fat": 0.3, "fiber": 2.0, "serving_g": 100},
    {"name": "celery", "category": "vegetables", "calories": 14, "protein": 0.7, "carbs": 3.0, "fat": 0.2, "fiber": 1.6, "serving_g": 100},
    {"name": "lettuce", "category": "vegetables", "calories": 15, "protein": 1.4, "carbs": 2.9, "fat": 0.2, "fiber": 1.3, "serving_g": 100},
    {"name": "cabbage", "category": "vegetables", "calories": 25, "protein": 1.3, "carbs": 5.8, "fat": 0.1, "fiber": 2.5, "serving_g": 100},
    {"name": "corn", "category": "vegetables", "calories": 86, "protein": 3.3, "carbs": 19.0, "fat": 1.4, "fiber": 2.7, "serving_g": 100},
    {"name": "peas", "category": "vegetables", "calories": 81, "protein": 5.4, "carbs": 14.5, "fat": 0.4, "fiber": 5.1, "serving_g": 100},
    {"name": "edamame", "category": "vegetables", "calories": 121, "protein": 11.9, "carbs": 8.9, "fat": 5.2, "fiber": 5.2, "serving_g": 100},

    # Fruits
    {"name": "banana", "category": "fruits", "calories": 89, "protein": 1.1, "carbs": 22.8, "fat": 0.3, "fiber": 2.6, "serving_g": 100},
    {"name": "apple", "category": "fruits", "calories": 52, "protein": 0.3, "carbs": 13.8, "fat": 0.2, "fiber": 2.4, "serving_g": 100},
    {"name": "orange", "category": "fruits", "calories": 47, "protein": 0.9, "carbs": 11.8, "fat": 0.1, "fiber": 2.4, "serving_g": 100},
    {"name": "strawberry", "category": "fruits", "calories": 32, "protein": 0.7, "carbs": 7.7, "fat": 0.3, "fiber": 2.0, "serving_g": 100},
    {"name": "blueberry", "category": "fruits", "calories": 57, "protein": 0.7, "carbs": 14.5, "fat": 0.3, "fiber": 2.4, "serving_g": 100},
    {"name": "avocado", "category": "fruits", "calories": 160, "protein": 2.0, "carbs": 8.5, "fat": 14.7, "fiber": 6.7, "serving_g": 100},
    {"name": "mango", "category": "fruits", "calories": 60, "protein": 0.8, "carbs": 15.0, "fat": 0.4, "fiber": 1.6, "serving_g": 100},
    {"name": "pineapple", "category": "fruits", "calories": 50, "protein": 0.5, "carbs": 13.1, "fat": 0.1, "fiber": 1.4, "serving_g": 100},
    {"name": "grapes", "category": "fruits", "calories": 69, "protein": 0.7, "carbs": 18.1, "fat": 0.2, "fiber": 0.9, "serving_g": 100},
    {"name": "watermelon", "category": "fruits", "calories": 30, "protein": 0.6, "carbs": 7.6, "fat": 0.2, "fiber": 0.4, "serving_g": 100},
    {"name": "peach", "category": "fruits", "calories": 39, "protein": 0.9, "carbs": 9.5, "fat": 0.3, "fiber": 1.5, "serving_g": 100},

    # Legumes
    {"name": "black beans", "category": "legumes", "calories": 132, "protein": 8.9, "carbs": 23.7, "fat": 0.5, "fiber": 8.7, "serving_g": 100},
    {"name": "chickpeas", "category": "legumes", "calories": 164, "protein": 8.9, "carbs": 27.4, "fat": 2.6, "fiber": 7.6, "serving_g": 100},
    {"name": "lentils", "category": "legumes", "calories": 116, "protein": 9.0, "carbs": 20.1, "fat": 0.4, "fiber": 7.9, "serving_g": 100},
    {"name": "kidney beans", "category": "legumes", "calories": 127, "protein": 8.7, "carbs": 22.8, "fat": 0.5, "fiber": 6.4, "serving_g": 100},
    {"name": "pinto beans", "category": "legumes", "calories": 143, "protein": 9.0, "carbs": 26.2, "fat": 0.7, "fiber": 9.0, "serving_g": 100},

    # Nuts & Seeds
    {"name": "almonds", "category": "nuts", "calories": 579, "protein": 21.2, "carbs": 21.6, "fat": 49.9, "fiber": 12.5, "serving_g": 100},
    {"name": "peanuts", "category": "nuts", "calories": 567, "protein": 25.8, "carbs": 16.1, "fat": 49.2, "fiber": 8.5, "serving_g": 100},
    {"name": "peanut butter", "category": "nuts", "calories": 588, "protein": 25.1, "carbs": 20.0, "fat": 50.4, "fiber": 6.0, "serving_g": 100},
    {"name": "walnuts", "category": "nuts", "calories": 654, "protein": 15.2, "carbs": 13.7, "fat": 65.2, "fiber": 6.7, "serving_g": 100},
    {"name": "cashews", "category": "nuts", "calories": 553, "protein": 18.2, "carbs": 30.2, "fat": 43.9, "fiber": 3.3, "serving_g": 100},
    {"name": "chia seeds", "category": "nuts", "calories": 486, "protein": 16.5, "carbs": 42.1, "fat": 30.7, "fiber": 34.4, "serving_g": 100},
    {"name": "flax seeds", "category": "nuts", "calories": 534, "protein": 18.3, "carbs": 28.9, "fat": 42.2, "fiber": 27.3, "serving_g": 100},
    {"name": "sunflower seeds", "category": "nuts", "calories": 584, "protein": 20.8, "carbs": 20.0, "fat": 51.5, "fiber": 8.6, "serving_g": 100},

    # Oils & Fats
    {"name": "olive oil", "category": "oils", "calories": 884, "protein": 0.0, "carbs": 0.0, "fat": 100.0, "fiber": 0.0, "serving_g": 100},
    {"name": "coconut oil", "category": "oils", "calories": 862, "protein": 0.0, "carbs": 0.0, "fat": 100.0, "fiber": 0.0, "serving_g": 100},

    # Beverages & Other
    {"name": "honey", "category": "other", "calories": 304, "protein": 0.3, "carbs": 82.4, "fat": 0.0, "fiber": 0.2, "serving_g": 100},
    {"name": "maple syrup", "category": "other", "calories": 260, "protein": 0.0, "carbs": 67.0, "fat": 0.1, "fiber": 0.0, "serving_g": 100},
    {"name": "dark chocolate", "category": "other", "calories": 546, "protein": 4.9, "carbs": 59.4, "fat": 31.3, "fiber": 7.0, "serving_g": 100},
    {"name": "protein bar", "category": "other", "calories": 350, "protein": 20.0, "carbs": 40.0, "fat": 12.0, "fiber": 5.0, "serving_g": 100},
    {"name": "hummus", "category": "other", "calories": 166, "protein": 7.9, "carbs": 14.3, "fat": 9.6, "fiber": 6.0, "serving_g": 100},
    {"name": "salsa", "category": "other", "calories": 36, "protein": 1.5, "carbs": 7.0, "fat": 0.2, "fiber": 1.5, "serving_g": 100},
    {"name": "guacamole", "category": "other", "calories": 160, "protein": 2.0, "carbs": 8.5, "fat": 14.7, "fiber": 6.7, "serving_g": 100},
    {"name": "sour cream", "category": "dairy", "calories": 198, "protein": 2.4, "carbs": 4.6, "fat": 19.4, "fiber": 0.0, "serving_g": 100},
    {"name": "almond milk", "category": "dairy", "calories": 17, "protein": 0.6, "carbs": 0.6, "fat": 1.1, "fiber": 0.2, "serving_g": 100},
    {"name": "oat milk", "category": "dairy", "calories": 47, "protein": 1.0, "carbs": 7.0, "fat": 1.5, "fiber": 0.8, "serving_g": 100},
]


def search_foods(query: str, limit: int = 20) -> list[dict]:
    """Search foods by name with fuzzy matching. Returns scored results."""
    query_lower = query.lower().strip()
    if not query_lower:
        return []

    results = []
    query_words = query_lower.split()

    for food in COMMON_FOODS:
        name = food["name"].lower()

        # Exact match
        if query_lower == name:
            results.append((1.0, food))
            continue

        # Starts with query
        if name.startswith(query_lower):
            results.append((0.95, food))
            continue

        # Contains query
        if query_lower in name:
            results.append((0.85, food))
            continue

        # All query words present
        if all(w in name for w in query_words):
            results.append((0.8, food))
            continue

        # Any query word present
        if any(w in name for w in query_words):
            results.append((0.6, food))
            continue

        # Fuzzy match
        ratio = SequenceMatcher(None, query_lower, name).ratio()
        if ratio > 0.5:
            results.append((ratio, food))

    results.sort(key=lambda x: x[0], reverse=True)
    return [r[1] for r in results[:limit]]


def get_common_foods(limit: int = 100) -> list[dict]:
    """Return top common foods, sorted by category."""
    return COMMON_FOODS[:limit]


def get_food_by_name(name: str) -> dict | None:
    """Exact or closest match lookup."""
    name_lower = name.lower().strip()
    for food in COMMON_FOODS:
        if food["name"].lower() == name_lower:
            return food
    # Try fuzzy
    results = search_foods(name, limit=1)
    return results[0] if results else None


def scale_nutrition(food: dict, grams: float) -> dict:
    """Scale nutrition values from per-100g to actual grams."""
    factor = grams / 100.0
    return {
        "name": food["name"],
        "category": food["category"],
        "amount_g": grams,
        "calories": round(food["calories"] * factor),
        "protein": round(food["protein"] * factor, 1),
        "carbs": round(food["carbs"] * factor, 1),
        "fat": round(food["fat"] * factor, 1),
        "fiber": round(food["fiber"] * factor, 1),
    }
