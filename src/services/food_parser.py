"""Quick-log parser: converts natural language food entries to structured data.

Examples:
    "chicken breast 200g" → {food: "chicken breast", amount_g: 200}
    "2 eggs" → {food: "egg", amount_g: 100, quantity: 2}
    "grilled salmon 150g" → {food: "salmon", amount_g: 150}
    "1 cup rice" → {food: "white rice", amount_g: 185}
    "3 oz steak" → {food: "steak sirloin", amount_g: 85}
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from src.services.food_database import search_foods, scale_nutrition


# Common unit conversions to grams
UNIT_TO_GRAMS = {
    "g": 1.0,
    "gram": 1.0,
    "grams": 1.0,
    "kg": 1000.0,
    "oz": 28.35,
    "ounce": 28.35,
    "ounces": 28.35,
    "lb": 453.6,
    "lbs": 453.6,
    "pound": 453.6,
    "pounds": 453.6,
    "cup": 240.0,
    "cups": 240.0,
    "tbsp": 15.0,
    "tablespoon": 15.0,
    "tablespoons": 15.0,
    "tsp": 5.0,
    "teaspoon": 5.0,
    "teaspoons": 5.0,
    "ml": 1.0,
    "slice": 30.0,
    "slices": 30.0,
    "piece": 100.0,
    "pieces": 100.0,
    "scoop": 30.0,
    "scoops": 30.0,
    "serving": 100.0,
    "servings": 100.0,
}

# Default piece weights for specific foods (grams per piece)
PIECE_WEIGHTS = {
    "egg": 50,
    "banana": 118,
    "apple": 182,
    "orange": 131,
    "chicken breast": 174,
    "chicken thigh": 116,
    "chicken wing": 34,
    "chicken drumstick": 76,
    "tortilla flour": 45,
    "tortilla corn": 26,
    "bagel": 105,
    "slice": 30,
    "protein bar": 60,
}

# Cooking method words to strip
COOKING_METHODS = {
    "grilled", "baked", "fried", "roasted", "steamed", "boiled",
    "sauteed", "sautéed", "raw", "cooked", "smoked", "poached",
    "braised", "broiled", "pan-fried", "air-fried", "scrambled",
    "hard-boiled", "soft-boiled",
}


@dataclass
class ParsedFood:
    original_input: str
    food_name: str
    amount_g: float
    quantity: float
    unit: str | None
    matched: bool
    nutrition: dict | None = None

    def to_dict(self) -> dict:
        return {
            "original_input": self.original_input,
            "food_name": self.food_name,
            "amount_g": self.amount_g,
            "quantity": self.quantity,
            "unit": self.unit,
            "matched": self.matched,
            "nutrition": self.nutrition,
        }


def parse_food_entry(text: str) -> ParsedFood:
    """Parse a natural language food entry into structured data."""
    original = text.strip()
    text = original.lower().strip()

    # Extract quantity + unit patterns
    # Patterns: "200g", "2 cups", "3 oz", "150 grams", "2", etc.
    quantity = 1.0
    unit = None
    amount_g = 100.0  # default

    # Pattern: number + unit (e.g., "200g", "3 oz", "2 cups")
    unit_pattern = r'(\d+\.?\d*)\s*(' + '|'.join(re.escape(u) for u in sorted(UNIT_TO_GRAMS.keys(), key=len, reverse=True)) + r')\b'
    unit_match = re.search(unit_pattern, text)

    # Pattern: just a number at start (e.g., "2 eggs")
    qty_pattern = r'^(\d+\.?\d*)\s+'
    qty_match = re.match(qty_pattern, text)

    if unit_match:
        quantity = float(unit_match.group(1))
        unit = unit_match.group(2)
        amount_g = quantity * UNIT_TO_GRAMS.get(unit, 1.0)
        # Remove the matched pattern from text to get food name
        text = text[:unit_match.start()] + text[unit_match.end():]
    elif qty_match:
        quantity = float(qty_match.group(1))
        text = text[qty_match.end():]

    # Strip cooking methods
    words = text.split()
    words = [w for w in words if w not in COOKING_METHODS]
    food_query = " ".join(words).strip()
    food_query = re.sub(r'\s+', ' ', food_query).strip(" ,.-")

    if not food_query:
        food_query = original.lower()

    # Search for the food
    results = search_foods(food_query, limit=1)
    if results:
        food = results[0]
        food_name = food["name"]

        # If no explicit unit, check piece weights for quantity
        if not unit_match and quantity > 1:
            piece_weight = PIECE_WEIGHTS.get(food_name, 100)
            amount_g = quantity * piece_weight
        elif not unit_match and quantity == 1 and food_name in PIECE_WEIGHTS:
            amount_g = PIECE_WEIGHTS[food_name]

        nutrition = scale_nutrition(food, amount_g)
        return ParsedFood(
            original_input=original,
            food_name=food_name,
            amount_g=amount_g,
            quantity=quantity,
            unit=unit,
            matched=True,
            nutrition=nutrition,
        )

    return ParsedFood(
        original_input=original,
        food_name=food_query,
        amount_g=amount_g,
        quantity=quantity,
        unit=unit,
        matched=False,
        nutrition=None,
    )


def parse_multiple(text: str) -> list[ParsedFood]:
    """Parse multiple food entries separated by commas, newlines, or 'and'."""
    # Split on comma, newline, or " and "
    entries = re.split(r'[,\n]|\band\b', text)
    return [parse_food_entry(e) for e in entries if e.strip()]
