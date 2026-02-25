"""
Multi-provider affiliate link engine for FitBites.

Supports: Amazon Associates, Instacart, iHerb, Thrive Market
Implements priority waterfall: best commission rate → best user experience → broadest catalog.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)

# ── Affiliate Tags & Config ──────────────────────────────────────────────────

AMAZON_TAG = "83apps01-20"  # Confirmed by Hayden


class AffiliateProvider(str, Enum):
    IHERB = "iherb"
    INSTACART = "instacart"
    THRIVE = "thrive"
    AMAZON = "amazon"


@dataclass(frozen=True)
class AffiliateLink:
    """A single affiliate link for a product/ingredient."""
    provider: AffiliateProvider
    url: str
    commission_pct: float  # estimated commission rate
    product_name: str  # human-readable label
    is_direct: bool = False  # True = direct product link, False = search fallback


@dataclass
class EnrichedIngredient:
    """An ingredient enriched with affiliate links from multiple providers."""
    original: str  # raw ingredient string from recipe
    normalized: str  # cleaned name for matching
    amount: str  # extracted quantity
    links: list[AffiliateLink] = field(default_factory=list)
    primary_link: Optional[AffiliateLink] = None  # highest-value link

    def to_dict(self) -> dict:
        return {
            "ingredient": self.original,
            "normalized": self.normalized,
            "amount": self.amount,
            "primary_link": {
                "provider": self.primary_link.provider.value,
                "url": self.primary_link.url,
                "commission_pct": self.primary_link.commission_pct,
            } if self.primary_link else None,
            "all_links": [
                {
                    "provider": l.provider.value,
                    "url": l.url,
                    "commission_pct": l.commission_pct,
                    "is_direct": l.is_direct,
                }
                for l in self.links
            ],
        }


# ── Ingredient Classification ───────────────────────────────────────────────

class IngredientCategory(str, Enum):
    SUPPLEMENT = "supplement"  # protein powder, creatine, vitamins → iHerb (10%)
    PANTRY = "pantry"  # rice, oats, oils, spices → Amazon (4%) / Instacart (10%)
    PRODUCE = "produce"  # fresh fruits/veggies → Instacart (10%)
    DAIRY = "dairy"  # yogurt, cheese, milk → Instacart (10%)
    MEAT = "meat"  # chicken, beef, fish → Instacart (10%) / ButcherBox
    FROZEN = "frozen"  # frozen fruits, veggies → Instacart (10%)
    CONDIMENT = "condiment"  # sauces, dressings → Amazon (4%)
    ORGANIC = "organic"  # organic/specialty → Thrive Market
    OTHER = "other"


# Keyword-based classification (fast, no ML needed)
_CATEGORY_KEYWORDS: dict[IngredientCategory, list[str]] = {
    IngredientCategory.SUPPLEMENT: [
        "protein powder", "whey", "casein", "creatine", "bcaa", "pre-workout",
        "collagen", "fish oil", "omega", "multivitamin", "vitamin", "probiotic",
        "greens powder", "electrolyte", "amino acid", "glutamine",
    ],
    IngredientCategory.PRODUCE: [
        "lettuce", "spinach", "kale", "arugula", "tomato", "onion", "garlic",
        "pepper", "cucumber", "avocado", "banana", "apple", "berry", "berries",
        "strawberry", "blueberry", "raspberry", "lemon", "lime", "orange",
        "broccoli", "cauliflower", "zucchini", "carrot", "celery", "mushroom",
        "sweet potato", "potato", "corn", "asparagus", "green bean", "edamame",
        "mango", "pineapple", "ginger root", "fresh",
    ],
    IngredientCategory.DAIRY: [
        "yogurt", "greek yogurt", "cottage cheese", "cheese", "milk", "cream",
        "butter", "sour cream", "cream cheese", "mozzarella", "parmesan",
        "cheddar", "feta", "ricotta", "whipped cream", "half and half",
    ],
    IngredientCategory.MEAT: [
        "chicken", "turkey", "beef", "steak", "salmon", "tuna", "shrimp",
        "pork", "bacon", "sausage", "ground beef", "ground turkey", "fish",
        "tilapia", "cod", "egg", "eggs", "egg white",
    ],
    IngredientCategory.FROZEN: [
        "frozen banana", "frozen berry", "frozen berries", "frozen fruit",
        "frozen vegetable", "frozen spinach", "frozen mango",
    ],
    IngredientCategory.CONDIMENT: [
        "sriracha", "soy sauce", "hot sauce", "ketchup", "mustard", "mayo",
        "mayonnaise", "vinegar", "sesame oil", "teriyaki", "salsa", "bbq sauce",
        "worcestershire", "fish sauce", "oyster sauce", "tahini", "hummus",
    ],
    IngredientCategory.ORGANIC: [
        "organic", "grass-fed", "pasture-raised", "non-gmo", "raw honey",
        "sprouted", "cold-pressed",
    ],
    IngredientCategory.PANTRY: [
        "rice", "quinoa", "oats", "oatmeal", "flour", "sugar", "salt",
        "pepper", "olive oil", "coconut oil", "avocado oil", "peanut butter",
        "almond butter", "honey", "maple syrup", "cocoa powder", "stevia",
        "baking powder", "baking soda", "vanilla extract", "cinnamon",
        "cumin", "paprika", "turmeric", "chili powder", "oregano", "basil",
        "thyme", "rosemary", "chia seeds", "flax seeds", "hemp seeds",
        "sesame seeds", "almonds", "walnuts", "cashews", "peanuts",
        "coconut flakes", "dark chocolate", "granola", "bread", "tortilla",
        "pasta", "noodles", "taco seasoning", "broth", "stock",
        "almond milk", "oat milk", "coconut milk", "almond flour",
    ],
}

# ── Known Product ASINs (Amazon) ────────────────────────────────────────────

_AMAZON_ASINS: dict[str, str] = {
    "whey protein": "B0015R36SK",
    "protein powder": "B0015R36SK",
    "greek yogurt": "B07YZLQ2YZ",
    "chicken breast": "B08FCKM12C",
    "olive oil": "B004ULUVU4",
    "avocado oil": "B01CCOXRLY",
    "almond flour": "B00CLTGQIG",
    "oat flour": "B00DQZM86A",
    "coconut oil": "B00DS842HS",
    "peanut butter": "B0019GZ7BE",
    "almond butter": "B001HTIYDI",
    "rice": "B00JQYQQHG",
    "quinoa": "B008HQLLAG",
    "oats": "B07G5SJDN9",
    "rolled oats": "B07G5SJDN9",
    "honey": "B003WKAB4S",
    "maple syrup": "B072JBGVJT",
    "cocoa powder": "B001E5E0Y2",
    "stevia": "B001F0RAMG",
    "creatine": "B000GIQS02",
    "chia seeds": "B00K4VSN84",
    "flax seeds": "B007YYHHX0",
    "dark chocolate": "B003VXHGKC",
    "sriracha": "B07BNNKVNL",
    "soy sauce": "B0049YQAX2",
    "sesame oil": "B0001DMTPM",
    "coconut milk": "B074MFRVKJ",
    "almond milk": "B07TF1JTM9",
    "taco seasoning": "B000W9RAFY",
    "cinnamon": "B001PQHG5U",
    "turmeric": "B01LZJ0TBA",
    "vanilla extract": "B0011BQERW",
    "collagen": "B00NLR1PX0",
    "fish oil": "B002VLZHLS",
    "granola": "B01M0YWT0O",
}

# ── iHerb Product IDs ───────────────────────────────────────────────────────

_IHERB_PRODUCTS: dict[str, str] = {
    "whey protein": "27509",
    "protein powder": "27509",
    "creatine": "22067",
    "collagen": "64903",
    "fish oil": "16536",
    "multivitamin": "18915",
    "probiotic": "7574",
    "vitamin d": "36051",
    "vitamin c": "19380",
    "magnesium": "6235",
    "zinc": "694",
    "bcaa": "62716",
    "greens powder": "64556",
    "electrolyte": "85771",
    "ashwagandha": "72strp",
    "melatonin": "2064",
    "psyllium husk": "17617",
    "stevia": "34498",
    "coconut oil": "37627",
    "chia seeds": "62218",
    "flax seeds": "59987",
    "hemp seeds": "54914",
    "cocoa powder": "32727",
    "almond butter": "31191",
    "peanut butter": "68499",
}


# ── URL Generators ───────────────────────────────────────────────────────────

def _amazon_product_url(asin: str) -> str:
    return f"https://www.amazon.com/dp/{asin}?tag={AMAZON_TAG}"


def _amazon_search_url(query: str) -> str:
    return f"https://www.amazon.com/s?k={quote_plus(query)}&tag={AMAZON_TAG}"


def _iherb_product_url(product_id: str) -> str:
    return f"https://www.iherb.com/pr/p/{product_id}"


def _iherb_search_url(query: str) -> str:
    return f"https://www.iherb.com/search?kw={quote_plus(query)}"


def _instacart_search_url(query: str) -> str:
    return f"https://www.instacart.com/store/search/{quote_plus(query)}"


def _thrive_search_url(query: str) -> str:
    return f"https://thrivemarket.com/search?search={quote_plus(query)}"


# ── Ingredient Parsing ───────────────────────────────────────────────────────

_QUANTITY_RE = re.compile(
    r"^[\d¼½¾⅓⅔⅛/.\s-]+"
    r"(?:cups?|tbsps?|tsps?|tablespoons?|teaspoons?|oz|ounces?|lbs?|pounds?"
    r"|g|grams?|kg|ml|liters?|pieces?|cloves?|slices?|pinch(?:es)?|dash(?:es)?|bunch(?:es)?|cans?|packages?|scoops?|servings?|sprigs?|heads?|stalks?)"
    r"\s*",
    re.IGNORECASE,
)

_PARENTHETICAL_RE = re.compile(r"\(.*?\)")  # e.g. "(low sodium)", "(0% fat)"


def parse_ingredient(raw: str) -> tuple[str, str]:
    """Parse raw ingredient string into (amount, normalized_name).

    Examples:
        "2 cups greek yogurt (0% fat)" → ("2 cups", "greek yogurt")
        "1 scoop protein powder" → ("1 scoop", "protein powder")
        "honey" → ("", "honey")
    """
    text = raw.strip()

    # Extract amount
    match = _QUANTITY_RE.match(text)
    amount = match.group(0).strip() if match else ""
    name = text[match.end():] if match else text

    # Remove parentheticals and clean up
    name = _PARENTHETICAL_RE.sub("", name)
    name = re.sub(r"\s+", " ", name).strip(",. ").lower()

    return amount, name


def classify_ingredient(name: str) -> IngredientCategory:
    """Classify an ingredient into a category for provider routing."""
    name_lower = name.lower()

    # Frozen check first (before produce)
    for kw in _CATEGORY_KEYWORDS[IngredientCategory.FROZEN]:
        if kw in name_lower:
            return IngredientCategory.FROZEN

    # Organic check (modifier, check before other categories)
    for kw in _CATEGORY_KEYWORDS[IngredientCategory.ORGANIC]:
        if kw in name_lower:
            return IngredientCategory.ORGANIC

    # Check all other categories
    for cat in [
        IngredientCategory.SUPPLEMENT,
        IngredientCategory.DAIRY,
        IngredientCategory.MEAT,
        IngredientCategory.PRODUCE,
        IngredientCategory.CONDIMENT,
        IngredientCategory.PANTRY,
    ]:
        for kw in _CATEGORY_KEYWORDS[cat]:
            if kw in name_lower:
                return cat

    return IngredientCategory.OTHER


# ── Provider Priority Waterfall ──────────────────────────────────────────────

# Commission rates (approximate) used for priority sorting
_COMMISSION_RATES: dict[AffiliateProvider, dict[IngredientCategory, float]] = {
    AffiliateProvider.IHERB: {
        IngredientCategory.SUPPLEMENT: 0.10,  # 10% first 3 months, 5% after
        IngredientCategory.PANTRY: 0.05,
        IngredientCategory.OTHER: 0.05,
    },
    AffiliateProvider.INSTACART: {
        IngredientCategory.PRODUCE: 0.10,
        IngredientCategory.DAIRY: 0.10,
        IngredientCategory.MEAT: 0.10,
        IngredientCategory.FROZEN: 0.10,
        IngredientCategory.PANTRY: 0.10,
        IngredientCategory.CONDIMENT: 0.10,
        IngredientCategory.OTHER: 0.10,
    },
    AffiliateProvider.THRIVE: {
        IngredientCategory.ORGANIC: 0.08,
        IngredientCategory.PANTRY: 0.06,
        IngredientCategory.SUPPLEMENT: 0.06,
        IngredientCategory.OTHER: 0.06,
    },
    AffiliateProvider.AMAZON: {
        IngredientCategory.SUPPLEMENT: 0.01,
        IngredientCategory.PANTRY: 0.01,
        IngredientCategory.CONDIMENT: 0.04,
        IngredientCategory.OTHER: 0.04,
    },
}


def _get_commission(provider: AffiliateProvider, category: IngredientCategory) -> float:
    rates = _COMMISSION_RATES.get(provider, {})
    return rates.get(category, rates.get(IngredientCategory.OTHER, 0.01))


def _generate_links(name: str, category: IngredientCategory) -> list[AffiliateLink]:
    """Generate affiliate links from all applicable providers, sorted by commission."""
    links: list[AffiliateLink] = []

    # Amazon — check direct ASIN first, fall back to search
    asin = _AMAZON_ASINS.get(name)
    if asin:
        links.append(AffiliateLink(
            provider=AffiliateProvider.AMAZON,
            url=_amazon_product_url(asin),
            commission_pct=_get_commission(AffiliateProvider.AMAZON, category),
            product_name=name,
            is_direct=True,
        ))
    else:
        links.append(AffiliateLink(
            provider=AffiliateProvider.AMAZON,
            url=_amazon_search_url(name),
            commission_pct=_get_commission(AffiliateProvider.AMAZON, category),
            product_name=name,
            is_direct=False,
        ))

    # iHerb — supplements and health products
    if category in (IngredientCategory.SUPPLEMENT, IngredientCategory.ORGANIC):
        pid = _IHERB_PRODUCTS.get(name)
        if pid:
            links.append(AffiliateLink(
                provider=AffiliateProvider.IHERB,
                url=_iherb_product_url(pid),
                commission_pct=_get_commission(AffiliateProvider.IHERB, category),
                product_name=name,
                is_direct=True,
            ))
        else:
            links.append(AffiliateLink(
                provider=AffiliateProvider.IHERB,
                url=_iherb_search_url(name),
                commission_pct=_get_commission(AffiliateProvider.IHERB, category),
                product_name=name,
                is_direct=False,
            ))

    # Instacart — groceries (produce, dairy, meat, frozen, pantry)
    if category in (
        IngredientCategory.PRODUCE, IngredientCategory.DAIRY,
        IngredientCategory.MEAT, IngredientCategory.FROZEN,
        IngredientCategory.PANTRY, IngredientCategory.CONDIMENT,
    ):
        links.append(AffiliateLink(
            provider=AffiliateProvider.INSTACART,
            url=_instacart_search_url(name),
            commission_pct=_get_commission(AffiliateProvider.INSTACART, category),
            product_name=name,
            is_direct=False,
        ))

    # Thrive Market — organic/specialty
    if category in (IngredientCategory.ORGANIC, IngredientCategory.PANTRY,
                     IngredientCategory.SUPPLEMENT):
        links.append(AffiliateLink(
            provider=AffiliateProvider.THRIVE,
            url=_thrive_search_url(name),
            commission_pct=_get_commission(AffiliateProvider.THRIVE, category),
            product_name=name,
            is_direct=False,
        ))

    # Sort by commission rate descending — highest value first
    links.sort(key=lambda l: (-l.commission_pct, -l.is_direct))

    return links


# ── Public API ───────────────────────────────────────────────────────────────

def enrich_ingredient(raw: str) -> EnrichedIngredient:
    """Enrich a single ingredient string with multi-provider affiliate links."""
    amount, name = parse_ingredient(raw)
    category = classify_ingredient(name)
    links = _generate_links(name, category)

    return EnrichedIngredient(
        original=raw,
        normalized=name,
        amount=amount,
        links=links,
        primary_link=links[0] if links else None,
    )


def enrich_ingredients(
    ingredients: list[str],
    tag: str | None = None,  # kept for backward compat, ignored (uses AMAZON_TAG constant)
) -> list[dict]:
    """Enrich a list of ingredient strings. Returns list of dicts (API-compatible).

    Backward compatible with old API — returns same shape but with richer data.
    """
    return [enrich_ingredient(ing).to_dict() for ing in ingredients]


def enrich_recipe(recipe_dict: dict, **kwargs) -> dict:
    """Enrich a full recipe dict with multi-provider affiliate links."""
    ingredients = recipe_dict.get("ingredients", [])
    if not ingredients:
        return recipe_dict

    enriched = [enrich_ingredient(ing) for ing in ingredients]
    recipe_dict["affiliate_links"] = [e.to_dict() for e in enriched]

    # Compute recipe-level stats
    providers_used = set()
    total_commission_value = 0.0
    for e in enriched:
        if e.primary_link:
            providers_used.add(e.primary_link.provider.value)
            total_commission_value += e.primary_link.commission_pct

    recipe_dict["affiliate_meta"] = {
        "providers_used": sorted(providers_used),
        "avg_commission_pct": round(total_commission_value / len(enriched), 3) if enriched else 0,
        "total_links": sum(len(e.links) for e in enriched),
    }

    return recipe_dict


def get_shop_all_url(ingredients: list[str]) -> dict:
    """Generate a 'Shop All Ingredients' link via Instacart (highest-value action).

    This is the single highest monetization touchpoint — one click to buy
    all recipe ingredients via grocery delivery.
    """
    names = [parse_ingredient(ing)[1] for ing in ingredients]
    combined_query = ", ".join(names[:15])  # Instacart search limit
    return {
        "provider": AffiliateProvider.INSTACART.value,
        "url": _instacart_search_url(combined_query),
        "label": "Shop All Ingredients",
        "estimated_commission_pct": 0.10,
    }


def generate_click_id(
    user_id: str | None,
    recipe_id: str,
    ingredient: str,
    provider: str,
) -> str:
    """Generate a deterministic click tracking ID for deduplication."""
    raw = f"{user_id or 'anon'}:{recipe_id}:{ingredient}:{provider}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ── Legacy compatibility ─────────────────────────────────────────────────────
# These match the old API signatures so existing code doesn't break

DEFAULT_AMAZON_TAG = AMAZON_TAG  # backward compat export


def amazon_search_url(query: str, tag: str = AMAZON_TAG) -> str:
    return _amazon_search_url(query)


def amazon_product_url(asin: str, tag: str = AMAZON_TAG) -> str:
    return _amazon_product_url(asin)
