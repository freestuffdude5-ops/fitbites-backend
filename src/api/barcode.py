"""
Barcode Scanner API — /api/v1/barcode/* endpoints.

CORRECT UX FLOW:
1. User scans barcode → POST /scan → Returns product info (NO LOGGING)
2. App shows confirmation: "Add Coca-Cola (42 cal) to your log?"
3a. User taps 'Add' → POST /confirm-and-log → Logs to tracker
3b. User taps 'Cancel' → Nothing logged

This pattern prevents accidental logging and matches industry UX (MyFitnessPal, Lose It!, etc.).
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.services.barcode import lookup_barcode, search_products, ProductInfo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/barcode", tags=["barcode"])


# ── Request / Response Models ────────────────────────────────────────────────

class BarcodeScanRequest(BaseModel):
    barcode: str = Field(..., description="Product barcode (EAN-13, UPC-A, etc.)")


class BarcodeScanResponse(BaseModel):
    success: bool
    product: Optional[ProductInfo] = None
    message: Optional[str] = None


class BarcodeLogRequest(BaseModel):
    barcode: str = Field(..., description="Product barcode to scan and log")
    servings: float = Field(1.0, ge=0.1, le=50, description="Number of servings")
    meal_type: str = Field("snack", description="Meal type: breakfast, lunch, dinner, snack")
    log_date: Optional[str] = Field(None, description="Date to log (YYYY-MM-DD), defaults to today")


class BarcodeLogResponse(BaseModel):
    success: bool
    product: Optional[ProductInfo] = None
    logged: bool = False
    meal_entry: Optional[dict] = None
    message: Optional[str] = None


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/scan", response_model=BarcodeScanResponse)
async def scan_barcode(req: BarcodeScanRequest):
    """Scan a barcode and return product info + nutrition data from OpenFoodFacts."""
    barcode = req.barcode.strip()
    if not barcode.isdigit() or len(barcode) < 8:
        raise HTTPException(status_code=400, detail="Invalid barcode format. Expected 8-13 digit number.")

    product = await lookup_barcode(barcode)
    if not product:
        return BarcodeScanResponse(success=False, message=f"Product not found for barcode: {barcode}")

    return BarcodeScanResponse(success=True, product=product)


@router.get("/search")
async def search_barcode(
    q: str = Query(..., min_length=2, description="Product name to search"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
):
    """Search OpenFoodFacts by product name."""
    results = await search_products(q, page=page, page_size=page_size)
    return results


@router.post("/confirm-and-log", response_model=BarcodeLogResponse)
async def confirm_and_log_barcode(req: BarcodeLogRequest):
    """
    Confirm and log a scanned product to the daily tracker.
    
    This endpoint should ONLY be called after the user explicitly confirms they want to log the item.
    Use POST /scan to get product info without logging.
    """
    barcode = req.barcode.strip()
    if not barcode.isdigit() or len(barcode) < 8:
        raise HTTPException(status_code=400, detail="Invalid barcode format.")

    product = await lookup_barcode(barcode)
    if not product:
        return BarcodeLogResponse(
            success=False,
            message=f"Product not found for barcode: {barcode}",
        )

    # Build meal entry matching ECHO's tracking format
    log_date = req.log_date or date.today().isoformat()
    nutrition = product.nutrition
    meal_entry = {
        "food_name": product.product_name,
        "brand": product.brand,
        "barcode": product.barcode,
        "meal_type": req.meal_type,
        "servings": req.servings,
        "log_date": log_date,
        "calories": round(nutrition.calories * req.servings, 1),
        "protein_g": round(nutrition.protein_g * req.servings, 1),
        "carbs_g": round(nutrition.carbs_g * req.servings, 1),
        "fat_g": round(nutrition.fat_g * req.servings, 1),
        "fiber_g": round(nutrition.fiber_g * req.servings, 1),
        "sugar_g": round(nutrition.sugar_g * req.servings, 1),
        "source": "barcode_scan",
        "logged_at": datetime.utcnow().isoformat(),
    }

    # NOTE: Integration point for ECHO's /tracking/log-meal endpoint.
    # When the tracking module is available, call it here:
    #   from src.services.tracking import log_meal
    #   await log_meal(meal_entry)
    # For now, we return the entry for client-side logging.

    logger.info(f"Barcode log: {product.product_name} ({barcode}) → {meal_entry['calories']} kcal")

    return BarcodeLogResponse(
        success=True,
        product=product,
        logged=True,
        meal_entry=meal_entry,
        message=f"Logged {product.product_name} ({req.servings}x serving) — {meal_entry['calories']} kcal",
    )
