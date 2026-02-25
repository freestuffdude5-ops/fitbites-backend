"""
Recipe Cost Estimation Engine for FitBites.

Estimates ingredient costs to show users per-recipe and per-serving pricing.
This is a premium differentiator — competitors don't show cost breakdowns.

Features:
- Per-ingredient price estimates (crowd-sourced averages)
- Per-recipe total cost
- Per-serving cost (great for meal planning)
- Cost comparison across providers (Instacart vs Amazon vs Walmart)
- Budget-friendly badge for recipes under $3/serving
- Weekly meal plan cost estimation
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from src.services.affiliate import (
    parse_ingredient,
    classify_ingredient,
    IngredientCategory,
)


class PriceConfidence(str, Enum):
    HIGH = "high"       # exact match in price DB
    MEDIUM = "medium"   # category-based estimate
    LOW = "low"         # generic fallback


@dataclass
class IngredientCost:
    """Cost estimate for a single ingredient."""
    name: str
    amount: str
    estimated_cost: float          # USD
    confidence: PriceConfidence
    cost_per_unit: Optional[float] = None  # e.g., $5.99/lb
    unit: Optional[str] = None
    notes: Optional[str] = None    # e.g., "organic premium +30%"

    def to_dict(self) -> dict:
        d = {
            "name": self.name,
            "amount": self.amount,
            "estimated_cost": round(self.estimated_cost, 2),
            "confidence": self.confidence.value,
        }
        if self.notes:
            d["notes"] = self.notes
        return d


@dataclass
class RecipeCost:
    """Full cost breakdown for a recipe."""
    total_cost: float
    per_serving_cost: float
    servings: int
    ingredients: list[IngredientCost]
    is_budget_friendly: bool       # under $3/serving
    confidence: PriceConfidence    # overall (lowest of ingredients)
    currency: str = "USD"

    def to_dict(self) -> dict:
        return {
            "total_cost": round(self.total_cost, 2),
            "per_serving_cost": round(self.per_serving_cost, 2),
            "servings": self.servings,
            "is_budget_friendly": self.is_budget_friendly,
            "confidence": self.confidence.value,
            "currency": self.currency,
            "ingredients": [i.to_dict() for i in self.ingredients],
        }


# ── Price Database ───────────────────────────────────────────────────────────
# Average US grocery prices (2024-2025). Updated periodically.
# Format: ingredient → (price_per_standard_unit, standard_unit, standard_qty)

_PRICE_DB: dict[str, tuple[float, str, float]] = {
    # Proteins
    "chicken breast": (3.99, "lb", 1.0),
    "chicken thigh": (2.49, "lb", 1.0),
    "chicken": (3.49, "lb", 1.0),
    "ground turkey": (4.99, "lb", 1.0),
    "ground beef": (5.49, "lb", 1.0),
    "beef": (6.99, "lb", 1.0),
    "steak": (9.99, "lb", 1.0),
    "salmon": (8.99, "lb", 1.0),
    "tuna": (1.29, "can", 1.0),
    "shrimp": (7.99, "lb", 1.0),
    "tilapia": (5.99, "lb", 1.0),
    "cod": (7.49, "lb", 1.0),
    "pork": (3.99, "lb", 1.0),
    "bacon": (5.99, "pack", 1.0),
    "sausage": (3.99, "pack", 1.0),
    "eggs": (3.49, "dozen", 12.0),
    "egg": (0.30, "each", 1.0),
    "egg white": (4.99, "carton", 1.0),
    "tofu": (2.49, "block", 1.0),

    # Dairy
    "greek yogurt": (5.49, "32oz", 1.0),
    "yogurt": (4.99, "32oz", 1.0),
    "cottage cheese": (3.99, "16oz", 1.0),
    "milk": (3.99, "gallon", 1.0),
    "cream cheese": (2.99, "8oz", 1.0),
    "mozzarella": (3.99, "8oz", 1.0),
    "parmesan": (4.99, "5oz", 1.0),
    "cheddar": (3.49, "8oz", 1.0),
    "feta": (4.49, "6oz", 1.0),
    "butter": (4.49, "lb", 1.0),
    "sour cream": (2.49, "16oz", 1.0),
    "heavy cream": (3.99, "16oz", 1.0),
    "cream": (3.99, "16oz", 1.0),
    "cheese": (3.99, "8oz", 1.0),
    "ricotta": (3.99, "15oz", 1.0),

    # Produce
    "avocado": (1.50, "each", 1.0),
    "banana": (0.25, "each", 1.0),
    "apple": (1.29, "each", 1.0),
    "lemon": (0.69, "each", 1.0),
    "lime": (0.50, "each", 1.0),
    "orange": (0.99, "each", 1.0),
    "tomato": (1.99, "lb", 1.0),
    "onion": (1.29, "each", 1.0),
    "garlic": (0.50, "head", 1.0),
    "ginger": (3.99, "lb", 1.0),
    "ginger root": (3.99, "lb", 1.0),
    "spinach": (2.99, "bag", 1.0),
    "kale": (2.99, "bunch", 1.0),
    "lettuce": (2.49, "head", 1.0),
    "broccoli": (2.49, "lb", 1.0),
    "cauliflower": (3.49, "head", 1.0),
    "bell pepper": (1.29, "each", 1.0),
    "pepper": (1.29, "each", 1.0),
    "cucumber": (0.99, "each", 1.0),
    "zucchini": (1.49, "each", 1.0),
    "carrot": (1.99, "lb", 1.0),
    "celery": (1.99, "bunch", 1.0),
    "mushroom": (2.99, "8oz", 1.0),
    "sweet potato": (1.29, "each", 1.0),
    "potato": (0.99, "each", 1.0),
    "asparagus": (3.99, "bunch", 1.0),
    "green bean": (2.49, "lb", 1.0),
    "corn": (0.79, "each", 1.0),
    "mango": (1.49, "each", 1.0),
    "pineapple": (3.49, "each", 1.0),
    "strawberry": (3.99, "lb", 1.0),
    "blueberry": (3.99, "pint", 1.0),
    "raspberry": (4.99, "6oz", 1.0),
    "berry": (3.99, "pint", 1.0),
    "berries": (3.99, "pint", 1.0),
    "arugula": (3.49, "5oz", 1.0),
    "edamame": (2.99, "12oz", 1.0),

    # Pantry
    "rice": (2.99, "lb", 1.0),
    "quinoa": (4.99, "lb", 1.0),
    "oats": (3.99, "42oz", 1.0),
    "rolled oats": (3.99, "42oz", 1.0),
    "oatmeal": (3.99, "42oz", 1.0),
    "pasta": (1.49, "lb", 1.0),
    "noodles": (1.99, "pack", 1.0),
    "bread": (3.49, "loaf", 1.0),
    "tortilla": (3.49, "pack", 1.0),
    "flour": (3.49, "5lb", 1.0),
    "almond flour": (8.99, "lb", 1.0),
    "coconut flour": (6.99, "lb", 1.0),
    "sugar": (3.49, "4lb", 1.0),
    "brown sugar": (3.49, "2lb", 1.0),

    # Oils & Fats
    "olive oil": (7.99, "17oz", 1.0),
    "coconut oil": (6.99, "14oz", 1.0),
    "avocado oil": (8.99, "16oz", 1.0),
    "sesame oil": (3.99, "5oz", 1.0),

    # Nut butters
    "peanut butter": (4.99, "16oz", 1.0),
    "almond butter": (8.99, "16oz", 1.0),

    # Sweeteners
    "honey": (7.99, "12oz", 1.0),
    "maple syrup": (8.99, "12oz", 1.0),
    "stevia": (4.99, "pack", 1.0),

    # Seeds & Nuts
    "chia seeds": (5.99, "12oz", 1.0),
    "flax seeds": (4.99, "16oz", 1.0),
    "hemp seeds": (9.99, "10oz", 1.0),
    "almonds": (7.99, "lb", 1.0),
    "walnuts": (8.99, "lb", 1.0),
    "cashews": (9.99, "lb", 1.0),
    "peanuts": (4.99, "lb", 1.0),
    "sesame seeds": (3.99, "8oz", 1.0),
    "coconut flakes": (3.99, "7oz", 1.0),

    # Spices & Seasonings (per container — amortized per-recipe cost is low)
    "cinnamon": (3.99, "jar", 1.0),
    "cumin": (3.99, "jar", 1.0),
    "paprika": (3.99, "jar", 1.0),
    "turmeric": (4.99, "jar", 1.0),
    "chili powder": (3.49, "jar", 1.0),
    "oregano": (3.49, "jar", 1.0),
    "basil": (3.49, "jar", 1.0),
    "thyme": (3.49, "jar", 1.0),
    "rosemary": (3.49, "jar", 1.0),
    "taco seasoning": (1.29, "pack", 1.0),
    "salt": (1.99, "container", 1.0),
    "black pepper": (4.99, "jar", 1.0),
    "vanilla extract": (8.99, "4oz", 1.0),
    "garlic powder": (3.99, "jar", 1.0),
    "onion powder": (3.49, "jar", 1.0),
    "italian seasoning": (3.49, "jar", 1.0),
    "red pepper flakes": (3.49, "jar", 1.0),
    "cayenne": (3.49, "jar", 1.0),
    "nutmeg": (4.99, "jar", 1.0),
    "ginger powder": (3.99, "jar", 1.0),

    # Condiments & Sauces
    "soy sauce": (3.49, "15oz", 1.0),
    "sriracha": (3.99, "17oz", 1.0),
    "hot sauce": (2.99, "5oz", 1.0),
    "ketchup": (3.49, "20oz", 1.0),
    "mustard": (2.49, "8oz", 1.0),
    "mayo": (4.49, "30oz", 1.0),
    "mayonnaise": (4.49, "30oz", 1.0),
    "vinegar": (2.99, "16oz", 1.0),
    "apple cider vinegar": (3.99, "16oz", 1.0),
    "balsamic vinegar": (5.99, "8oz", 1.0),
    "teriyaki": (3.49, "10oz", 1.0),
    "salsa": (3.49, "16oz", 1.0),
    "bbq sauce": (3.49, "18oz", 1.0),
    "worcestershire": (3.49, "10oz", 1.0),
    "fish sauce": (3.99, "7oz", 1.0),
    "tahini": (5.99, "16oz", 1.0),
    "hummus": (3.99, "10oz", 1.0),

    # Supplements
    "protein powder": (29.99, "2lb", 1.0),
    "whey protein": (29.99, "2lb", 1.0),
    "creatine": (19.99, "300g", 1.0),
    "collagen": (24.99, "20oz", 1.0),

    # Baking
    "baking powder": (2.99, "8oz", 1.0),
    "baking soda": (1.49, "16oz", 1.0),
    "cocoa powder": (4.99, "8oz", 1.0),
    "dark chocolate": (3.49, "bar", 1.0),
    "chocolate chips": (3.49, "12oz", 1.0),

    # Milks
    "almond milk": (3.49, "64oz", 1.0),
    "oat milk": (4.49, "64oz", 1.0),
    "coconut milk": (2.49, "13.5oz", 1.0),

    # Other
    "broth": (2.99, "32oz", 1.0),
    "stock": (2.99, "32oz", 1.0),
    "chicken broth": (2.99, "32oz", 1.0),
    "vegetable broth": (2.99, "32oz", 1.0),
    "granola": (4.99, "12oz", 1.0),
    "frozen banana": (2.99, "bag", 1.0),
    "frozen berry": (3.99, "bag", 1.0),
    "frozen berries": (3.99, "bag", 1.0),
    "frozen spinach": (2.49, "bag", 1.0),
    "frozen mango": (3.99, "bag", 1.0),
    "frozen fruit": (3.99, "bag", 1.0),
}

# Per-recipe cost for spices/seasonings (you use a tiny fraction of the jar)
_SPICE_AMORTIZED_COST = 0.15  # ~$0.15 per recipe use
_SPICE_KEYWORDS = {
    "cinnamon", "cumin", "paprika", "turmeric", "chili powder", "oregano",
    "basil", "thyme", "rosemary", "salt", "black pepper", "garlic powder",
    "onion powder", "italian seasoning", "red pepper flakes", "cayenne",
    "nutmeg", "ginger powder", "taco seasoning",
}

# ── Quantity Parsing ─────────────────────────────────────────────────────────

_FRACTION_MAP = {
    "¼": 0.25, "½": 0.5, "¾": 0.75,
    "⅓": 0.333, "⅔": 0.667,
    "⅛": 0.125, "⅜": 0.375, "⅝": 0.625, "⅞": 0.875,
}

_UNIT_TO_CUPS = {
    "cup": 1.0, "cups": 1.0,
    "tbsp": 0.0625, "tablespoon": 0.0625, "tablespoons": 0.0625, "tbsps": 0.0625,
    "tsp": 0.0208, "teaspoon": 0.0208, "teaspoons": 0.0208, "tsps": 0.0208,
    "oz": 0.125, "ounce": 0.125, "ounces": 0.125,
    "lb": 1.0, "lbs": 1.0, "pound": 1.0, "pounds": 1.0,  # special: weight
    "g": 0.00423, "gram": 0.00423, "grams": 0.00423,
    "ml": 0.00423, "kg": 4.23,
    "scoop": 1.0, "scoops": 1.0,  # treat as ~1 serving
    "pinch": 0.005, "dash": 0.01,
    "clove": 1.0, "cloves": 1.0,  # garlic cloves
    "slice": 1.0, "slices": 1.0,
    "piece": 1.0, "pieces": 1.0,
    "can": 1.0, "cans": 1.0,
    "bunch": 1.0, "head": 1.0, "stalk": 1.0, "stalks": 1.0,
    "sprig": 1.0, "sprigs": 1.0,
    "package": 1.0, "serving": 1.0, "servings": 1.0,
}


def _parse_quantity(amount_str: str) -> float:
    """Parse a quantity string like '1 1/2', '¾', '2-3' into a float."""
    if not amount_str:
        return 1.0

    text = amount_str.strip().lower()

    # Replace unicode fractions
    for frac, val in _FRACTION_MAP.items():
        if frac in text:
            text = text.replace(frac, str(val))

    # Remove unit words to get just the number
    for unit in sorted(_UNIT_TO_CUPS.keys(), key=len, reverse=True):
        text = re.sub(rf'\b{re.escape(unit)}\b', '', text)

    text = text.strip()
    if not text:
        return 1.0

    # Handle ranges like "2-3" → take average
    if '-' in text and not text.startswith('-'):
        parts = text.split('-')
        try:
            return sum(float(p.strip()) for p in parts if p.strip()) / len(parts)
        except ValueError:
            pass

    # Handle "1 1/2" style
    parts = text.split()
    total = 0.0
    for part in parts:
        if '/' in part:
            try:
                num, den = part.split('/')
                total += float(num) / float(den)
            except (ValueError, ZeroDivisionError):
                pass
        else:
            try:
                total += float(part)
            except ValueError:
                pass

    return total if total > 0 else 1.0


def _extract_unit(amount_str: str) -> Optional[str]:
    """Extract the unit from an amount string."""
    if not amount_str:
        return None
    text = amount_str.lower()
    for unit in sorted(_UNIT_TO_CUPS.keys(), key=len, reverse=True):
        if unit in text:
            return unit
    return None


# ── Cost Estimation ──────────────────────────────────────────────────────────

def estimate_ingredient_cost(raw_ingredient: str) -> IngredientCost:
    """Estimate the cost of a single ingredient line.

    Uses the price database for known ingredients, with smart fallbacks
    for unknown items based on category averages.
    """
    amount_str, name = parse_ingredient(raw_ingredient)
    quantity = _parse_quantity(amount_str)
    unit = _extract_unit(amount_str)

    # Check if it's a spice (amortized cost)
    if name in _SPICE_KEYWORDS or any(s in name for s in _SPICE_KEYWORDS):
        return IngredientCost(
            name=name,
            amount=amount_str or "to taste",
            estimated_cost=_SPICE_AMORTIZED_COST,
            confidence=PriceConfidence.HIGH,
            notes="Pantry staple — amortized cost per recipe",
        )

    # Direct price DB lookup
    price_info = _PRICE_DB.get(name)
    if not price_info:
        # Try partial matches
        for db_name, info in _PRICE_DB.items():
            if db_name in name or name in db_name:
                price_info = info
                break

    if price_info:
        base_price, base_unit, base_qty = price_info

        # Estimate how much of the package this recipe uses
        # Simple heuristic: if unit matches, scale by quantity
        usage_fraction = _estimate_usage_fraction(quantity, unit, base_unit, base_qty)
        estimated = base_price * usage_fraction

        return IngredientCost(
            name=name,
            amount=amount_str or "1",
            estimated_cost=max(estimated, 0.10),  # minimum $0.10
            confidence=PriceConfidence.HIGH,
            cost_per_unit=base_price,
            unit=base_unit,
        )

    # Category-based fallback
    category = classify_ingredient(name)
    fallback_price = _CATEGORY_FALLBACK_PRICES.get(category, 3.00)

    return IngredientCost(
        name=name,
        amount=amount_str or "1",
        estimated_cost=fallback_price * min(quantity, 3.0),  # cap at 3x
        confidence=PriceConfidence.LOW,
        notes="Estimated from category average",
    )


# Category average prices for unknown ingredients
_CATEGORY_FALLBACK_PRICES: dict[IngredientCategory, float] = {
    IngredientCategory.SUPPLEMENT: 1.50,  # per serving
    IngredientCategory.PRODUCE: 1.50,
    IngredientCategory.DAIRY: 2.00,
    IngredientCategory.MEAT: 4.00,
    IngredientCategory.FROZEN: 2.50,
    IngredientCategory.CONDIMENT: 0.50,  # per recipe use
    IngredientCategory.ORGANIC: 3.00,
    IngredientCategory.PANTRY: 1.00,
    IngredientCategory.OTHER: 2.00,
}


def _estimate_usage_fraction(
    quantity: float,
    recipe_unit: Optional[str],
    package_unit: str,
    package_qty: float,
) -> float:
    """Estimate what fraction of a package this recipe uses.

    This is the tricky part — converting "2 cups chicken breast" into
    a fraction of a 1lb package.
    """
    # Weight-based items (meat, cheese, etc.)
    if package_unit in ("lb", "lbs"):
        if recipe_unit in ("lb", "lbs", "pound", "pounds"):
            return quantity / package_qty
        elif recipe_unit in ("oz", "ounce", "ounces"):
            return (quantity / 16.0) / package_qty
        elif recipe_unit in ("g", "gram", "grams"):
            return (quantity / 453.6) / package_qty
        elif recipe_unit in ("cup", "cups"):
            # ~0.5 lb per cup for most proteins
            return (quantity * 0.5) / package_qty
        else:
            # Default: assume 0.5-1lb used
            return min(quantity * 0.5, 2.0) / package_qty

    # Volume items (milk, broth, etc.)
    if package_unit in ("gallon",):
        if recipe_unit in ("cup", "cups"):
            return quantity / 16.0  # 16 cups per gallon
        elif recipe_unit in ("oz", "ounce", "ounces"):
            return quantity / 128.0
        return 0.25  # default quarter gallon

    # "each" items (avocado, banana, eggs)
    if package_unit == "each":
        return quantity / package_qty

    # Dozen (eggs)
    if package_unit == "dozen":
        return quantity / package_qty

    # Container items (spice jars, sauces)
    if package_unit in ("jar", "container", "pack"):
        # Spices: use a tiny fraction; sauces: use more
        if recipe_unit in ("tsp", "teaspoon", "teaspoons", "tsps"):
            return quantity * 0.02  # ~2% of jar per tsp
        elif recipe_unit in ("tbsp", "tablespoon", "tablespoons", "tbsps"):
            return quantity * 0.06  # ~6% of jar per tbsp
        elif recipe_unit in ("cup", "cups"):
            return quantity * 0.5
        return 0.15  # default ~15% of container

    # oz-based packages
    if "oz" in package_unit:
        pkg_oz = float(re.sub(r'[^0-9.]', '', package_unit) or 16)
        if recipe_unit in ("oz", "ounce", "ounces"):
            return quantity / pkg_oz
        elif recipe_unit in ("cup", "cups"):
            return (quantity * 8) / pkg_oz  # 8 oz per cup
        elif recipe_unit in ("tbsp", "tablespoon", "tablespoons"):
            return (quantity * 0.5) / pkg_oz
        elif recipe_unit in ("tsp", "teaspoon", "teaspoons"):
            return (quantity * 0.167) / pkg_oz
        return 0.25  # default quarter of package

    # Default: assume we use half the package
    return min(quantity * 0.3, 1.0)


# ── Recipe-Level Cost ────────────────────────────────────────────────────────

def estimate_recipe_cost(
    ingredients: list[str],
    servings: int = 4,
) -> RecipeCost:
    """Estimate total recipe cost from ingredient list.

    Args:
        ingredients: Raw ingredient strings (e.g., ["2 cups chicken breast", "1 tbsp olive oil"])
        servings: Number of servings the recipe makes

    Returns:
        RecipeCost with full breakdown
    """
    ingredient_costs = [estimate_ingredient_cost(ing) for ing in ingredients]
    total = sum(ic.estimated_cost for ic in ingredient_costs)
    per_serving = total / max(servings, 1)

    # Overall confidence = lowest ingredient confidence
    confidences = [ic.confidence for ic in ingredient_costs]
    if PriceConfidence.LOW in confidences:
        overall = PriceConfidence.LOW
    elif PriceConfidence.MEDIUM in confidences:
        overall = PriceConfidence.MEDIUM
    else:
        overall = PriceConfidence.HIGH

    return RecipeCost(
        total_cost=total,
        per_serving_cost=per_serving,
        servings=servings,
        ingredients=ingredient_costs,
        is_budget_friendly=per_serving <= 3.00,
        confidence=overall,
    )


def estimate_meal_plan_cost(
    recipes: list[dict],
) -> dict:
    """Estimate weekly meal plan cost.

    Args:
        recipes: List of recipe dicts with 'ingredients' and 'servings' keys

    Returns:
        Cost summary with total, daily average, and per-recipe breakdown
    """
    recipe_costs = []
    total = 0.0

    for recipe in recipes:
        ingredients = recipe.get("ingredients", [])
        servings = recipe.get("servings", 4)
        cost = estimate_recipe_cost(ingredients, servings)
        recipe_costs.append({
            "title": recipe.get("title", "Unknown"),
            "total_cost": round(cost.total_cost, 2),
            "per_serving": round(cost.per_serving_cost, 2),
            "is_budget_friendly": cost.is_budget_friendly,
        })
        total += cost.total_cost

    return {
        "total_weekly_cost": round(total, 2),
        "daily_average": round(total / 7, 2) if recipes else 0,
        "recipes": recipe_costs,
        "savings_tip": _get_savings_tip(total),
    }


def _get_savings_tip(weekly_total: float) -> str:
    """Generate a contextual savings tip based on total cost."""
    if weekly_total < 30:
        return "Great budget! You're eating healthy for under $5/day."
    elif weekly_total < 50:
        return "Solid balance of quality and cost. Try buying proteins in bulk to save more."
    elif weekly_total < 75:
        return "Consider batch cooking — make double portions and freeze half to reduce waste."
    else:
        return "Swap some proteins for budget options like eggs, canned tuna, or chicken thighs."
