"""Shopping List API — aggregate ingredients across recipes with smart quantity merging."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_session
from src.db.tables import RecipeRow
from src.auth import require_user
from src.db.user_tables import UserRow

router = APIRouter(prefix="/api/v1/shopping-list", tags=["shopping-list"])

AMAZON_TAG = "83apps01-20"


# ── Models ──────────────────────────────────────────────────────────────

class ShoppingListRequest(BaseModel):
    recipe_ids: list[str] = Field(..., min_length=1, max_length=50)
    servings_multiplier: float = Field(1.0, ge=0.25, le=10)


class ShoppingItem(BaseModel):
    name: str
    total_quantity: str
    unit: str
    from_recipes: list[str]
    affiliate_url: Optional[str] = None
    checked: bool = False


class ShoppingListResponse(BaseModel):
    items: list[ShoppingItem]
    recipe_count: int
    total_items: int


# ── Unit normalization ──────────────────────────────────────────────────

UNIT_ALIASES: dict[str, str] = {
    "tbsp": "tbsp", "tablespoon": "tbsp", "tablespoons": "tbsp",
    "tsp": "tsp", "teaspoon": "tsp", "teaspoons": "tsp",
    "cup": "cup", "cups": "cup",
    "oz": "oz", "ounce": "oz", "ounces": "oz",
    "lb": "lb", "lbs": "lb", "pound": "lb", "pounds": "lb",
    "g": "g", "gram": "g", "grams": "g", "kg": "kg", "kilogram": "kg",
    "ml": "ml", "milliliter": "ml", "milliliters": "ml",
    "l": "L", "liter": "L", "liters": "L",
    "piece": "piece", "pieces": "piece",
    "clove": "clove", "cloves": "clove",
    "slice": "slice", "slices": "slice",
    "can": "can", "cans": "can",
    "bunch": "bunch", "bunches": "bunch",
    "head": "head", "heads": "head",
    "sprig": "sprig", "sprigs": "sprig",
    "pinch": "pinch", "pinches": "pinch",
    "dash": "dash", "dashes": "dash",
}

FRAC_MAP = {"½": 0.5, "¼": 0.25, "¾": 0.75, "⅓": 0.333, "⅔": 0.667, "⅛": 0.125, "⅜": 0.375, "⅝": 0.625, "⅞": 0.875}


def _normalize_unit(unit: str) -> str:
    return UNIT_ALIASES.get(unit.lower().strip(), unit.lower().strip())


def _parse_quantity(qty_str: str) -> float:
    if not qty_str:
        return 0
    qty_str = qty_str.strip()
    for sym, val in FRAC_MAP.items():
        if sym in qty_str:
            rest = qty_str.replace(sym, "").strip()
            return (float(rest) if rest else 0) + val
    if "/" in qty_str:
        parts = qty_str.split("/")
        try:
            return float(parts[0]) / float(parts[1])
        except (ValueError, ZeroDivisionError):
            return 0
    try:
        return float(qty_str)
    except ValueError:
        return 0


def _format_quantity(qty: float) -> str:
    if qty == 0:
        return ""
    if qty == int(qty):
        return str(int(qty))
    return f"{qty:.2f}".rstrip("0").rstrip(".")


def _affiliate_url(ingredient_name: str) -> str:
    q = ingredient_name.replace(" ", "+")
    return f"https://www.amazon.com/s?k={q}&tag={AMAZON_TAG}"


# ── Endpoint ────────────────────────────────────────────────────────────

@router.post("", response_model=ShoppingListResponse)
async def generate_shopping_list(
    req: ShoppingListRequest,
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Aggregate ingredients across multiple recipes into a unified shopping list.
    
    Merges matching ingredients, normalizes units, and includes affiliate links.
    """
    result = await session.execute(
        select(RecipeRow).where(RecipeRow.id.in_(req.recipe_ids))
    )
    recipes = result.scalars().all()

    if not recipes:
        raise HTTPException(404, "No recipes found for given IDs")

    # Aggregate: key = (normalized_name, normalized_unit)
    aggregated: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"qty": 0.0, "recipes": []}
    )

    for recipe in recipes:
        ingredients = recipe.ingredients or []
        for ing in ingredients:
            if isinstance(ing, dict):
                name = ing.get("name", "").strip().lower()
                if not name:
                    continue
                unit = _normalize_unit(ing.get("unit", ""))
                # Try quantity field, or parse from quantity string
                qty_raw = ing.get("quantity", ing.get("amount", ""))
                if isinstance(qty_raw, (int, float)):
                    qty = float(qty_raw) * req.servings_multiplier
                else:
                    # Parse string, possibly "2 cups" format
                    match = re.match(r'([\d/.½¼¾⅓⅔⅛⅜⅝⅞]+)\s*(.*)', str(qty_raw))
                    if match:
                        qty_str, parsed_unit = match.groups()
                        qty = _parse_quantity(qty_str) * req.servings_multiplier
                        if parsed_unit and not unit:
                            unit = _normalize_unit(parsed_unit)
                    else:
                        qty = _parse_quantity(str(qty_raw)) * req.servings_multiplier

                key = (name, unit)
                aggregated[key]["qty"] += qty
                if recipe.title not in aggregated[key]["recipes"]:
                    aggregated[key]["recipes"].append(recipe.title)

    items = []
    for (name, unit), data in sorted(aggregated.items(), key=lambda x: x[0][0]):
        formatted_qty = _format_quantity(data["qty"])
        items.append(ShoppingItem(
            name=name.title(),
            total_quantity=f"{formatted_qty} {unit}".strip() if formatted_qty and unit else formatted_qty,
            unit=unit,
            from_recipes=data["recipes"],
            affiliate_url=_affiliate_url(name),
        ))

    return ShoppingListResponse(
        items=items,
        recipe_count=len(recipes),
        total_items=len(items),
    )
