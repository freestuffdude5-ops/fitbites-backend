"""OpenFoodFacts barcode lookup service."""
from __future__ import annotations

import logging
from typing import Optional

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

OFF_BASE = "https://world.openfoodfacts.org"
OFF_PRODUCT_URL = f"{OFF_BASE}/api/v0/product/{{barcode}}.json"
OFF_SEARCH_URL = f"{OFF_BASE}/cgi/search.pl"

USER_AGENT = "FitBites/1.0 (fitbites-backend; contact@fitbites.app)"


class NutritionInfo(BaseModel):
    calories: float = 0.0
    protein_g: float = 0.0
    carbs_g: float = 0.0
    fat_g: float = 0.0
    fiber_g: float = 0.0
    sugar_g: float = 0.0
    serving_size: Optional[str] = None


class ProductInfo(BaseModel):
    barcode: str
    product_name: str
    brand: Optional[str] = None
    image_url: Optional[str] = None
    nutrition: NutritionInfo
    categories: Optional[str] = None
    source: str = "openfoodfacts"


class SearchResult(BaseModel):
    products: list[ProductInfo]
    count: int
    page: int
    page_size: int


def _parse_nutrition(nutriments: dict, product: dict) -> NutritionInfo:
    """Extract nutrition per 100g from OFF nutriments dict."""
    return NutritionInfo(
        calories=nutriments.get("energy-kcal_100g", nutriments.get("energy-kcal", 0)) or 0,
        protein_g=nutriments.get("proteins_100g", 0) or 0,
        carbs_g=nutriments.get("carbohydrates_100g", 0) or 0,
        fat_g=nutriments.get("fat_100g", 0) or 0,
        fiber_g=nutriments.get("fiber_100g", 0) or 0,
        sugar_g=nutriments.get("sugars_100g", 0) or 0,
        serving_size=product.get("serving_size"),
    )


def _parse_product(p: dict) -> ProductInfo:
    nutriments = p.get("nutriments", {})
    return ProductInfo(
        barcode=p.get("code", p.get("_id", "")),
        product_name=p.get("product_name", "Unknown"),
        brand=p.get("brands"),
        image_url=p.get("image_front_url") or p.get("image_url"),
        nutrition=_parse_nutrition(nutriments, p),
        categories=p.get("categories"),
    )


async def lookup_barcode(barcode: str) -> Optional[ProductInfo]:
    """Look up a barcode on OpenFoodFacts."""
    url = OFF_PRODUCT_URL.format(barcode=barcode)
    async with httpx.AsyncClient(timeout=10, headers={"User-Agent": USER_AGENT}) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()

    if data.get("status") != 1:
        return None

    return _parse_product(data["product"])


async def search_products(query: str, page: int = 1, page_size: int = 10) -> SearchResult:
    """Search OpenFoodFacts by product name."""
    params = {
        "search_terms": query,
        "search_simple": 1,
        "action": "process",
        "json": 1,
        "page": page,
        "page_size": page_size,
        "fields": "code,product_name,brands,image_front_url,nutriments,categories,serving_size",
    }
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": USER_AGENT}) as client:
        resp = await client.get(OFF_SEARCH_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    products = [_parse_product(p) for p in data.get("products", []) if p.get("product_name")]
    return SearchResult(
        products=products,
        count=data.get("count", 0),
        page=page,
        page_size=page_size,
    )
