"""Tests for barcode scanner API — uses real OpenFoodFacts API."""
import asyncio
import sys
import json

sys.path.insert(0, ".")

from src.services.barcode import lookup_barcode, search_products


async def test_coca_cola():
    print("=== Testing Coca-Cola (5449000000996) ===")
    product = await lookup_barcode("5449000000996")
    assert product is not None, "Coca-Cola not found!"
    print(f"  Name: {product.product_name}")
    print(f"  Brand: {product.brand}")
    print(f"  Calories: {product.nutrition.calories} kcal/100g")
    print(f"  Carbs: {product.nutrition.carbs_g}g | Protein: {product.nutrition.protein_g}g | Fat: {product.nutrition.fat_g}g")
    print(f"  Sugar: {product.nutrition.sugar_g}g")
    print("  ✅ PASS\n")
    return product


async def test_snickers():
    print("=== Testing Snickers (5000159461122) ===")
    product = await lookup_barcode("5000159461122")
    assert product is not None, "Snickers not found!"
    print(f"  Name: {product.product_name}")
    print(f"  Brand: {product.brand}")
    print(f"  Calories: {product.nutrition.calories} kcal/100g")
    print(f"  Carbs: {product.nutrition.carbs_g}g | Protein: {product.nutrition.protein_g}g | Fat: {product.nutrition.fat_g}g")
    print("  ✅ PASS\n")
    return product


async def test_not_found():
    print("=== Testing invalid barcode (0000000000000) ===")
    product = await lookup_barcode("0000000000000")
    assert product is None, "Should return None for unknown barcode"
    print("  ✅ PASS — correctly returned None\n")


async def test_search():
    print("=== Testing search: 'nutella' ===")
    results = await search_products("nutella", page=1, page_size=5)
    print(f"  Found {results.count} total, showing {len(results.products)}")
    for p in results.products[:3]:
        print(f"  - {p.product_name} ({p.barcode}) — {p.nutrition.calories} kcal")
    assert len(results.products) > 0, "Search should return results"
    print("  ✅ PASS\n")


async def main():
    print("\n🔬 FitBites Barcode Scanner — Integration Tests\n")
    await test_coca_cola()
    await test_snickers()
    await test_not_found()
    await test_search()
    print("🎉 All tests passed!")


if __name__ == "__main__":
    asyncio.run(main())
