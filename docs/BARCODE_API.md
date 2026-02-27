# Barcode Scanner API

**Base path:** `/api/v1/barcode`  
**Data source:** [OpenFoodFacts](https://world.openfoodfacts.org)  
**Nutrition values:** Per 100g unless adjusted by servings

---

## Endpoints

### POST `/api/v1/barcode/scan`

Lookup a product by barcode number.

**Request:**
```json
{ "barcode": "5449000000996" }
```

**Response:**
```json
{
  "success": true,
  "product": {
    "barcode": "5449000000996",
    "product_name": "Coke Original Taste",
    "brand": "Coca-Cola",
    "image_url": "https://...",
    "nutrition": {
      "calories": 42.0,
      "protein_g": 0.0,
      "carbs_g": 10.6,
      "fat_g": 0.0,
      "fiber_g": 0.0,
      "sugar_g": 10.6,
      "serving_size": "330 ml"
    },
    "categories": "...",
    "source": "openfoodfacts"
  }
}
```

### GET `/api/v1/barcode/search?q=nutella&page=1&page_size=10`

Search OpenFoodFacts by product name.

**Response:**
```json
{
  "products": [...],
  "count": 948,
  "page": 1,
  "page_size": 10
}
```

### POST `/api/v1/barcode/log-scanned`

Scan barcode + auto-log to daily nutrition tracker.

**Request:**
```json
{
  "barcode": "5000159461122",
  "servings": 1.0,
  "meal_type": "snack",
  "log_date": "2026-02-27"
}
```

**Response:** Product info + `meal_entry` with calculated nutrition (calories × servings).

---

## Tested Barcodes

| Product | Barcode | Calories/100g |
|---------|---------|---------------|
| Coca-Cola | 5449000000996 | 42 kcal |
| Snickers | 5000159461122 | 481 kcal |
| Nutella | 3017620422003 | 539 kcal |

## Integration

The `/log-scanned` endpoint produces a `meal_entry` compatible with ECHO's `/tracking/log-meal` endpoint. When the tracking service is fully wired, it will auto-log via internal service call.
