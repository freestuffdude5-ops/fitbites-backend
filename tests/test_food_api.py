"""Tests for Food Search API — search, common foods, quick-log parser."""
import pytest
from src.services.food_database import search_foods, get_common_foods, get_food_by_name, scale_nutrition
from src.services.food_parser import parse_food_entry, parse_multiple


class TestFoodDatabase:
    def test_search_exact(self):
        results = search_foods("chicken breast")
        assert len(results) > 0
        assert results[0]["name"] == "chicken breast"

    def test_search_partial(self):
        results = search_foods("chicken")
        assert len(results) >= 4  # breast, thigh, wing, drumstick

    def test_search_fuzzy(self):
        results = search_foods("brocoli")  # misspelled
        assert len(results) > 0
        assert "broccoli" in results[0]["name"]

    def test_search_empty(self):
        assert search_foods("") == []

    def test_common_foods(self):
        foods = get_common_foods(100)
        assert len(foods) == 100

    def test_get_by_name(self):
        food = get_food_by_name("salmon")
        assert food is not None
        assert food["name"] == "salmon"
        assert food["calories"] == 208

    def test_scale_nutrition(self):
        food = get_food_by_name("chicken breast")
        scaled = scale_nutrition(food, 200)
        assert scaled["calories"] == 330  # 165 * 2
        assert scaled["protein"] == 62.0
        assert scaled["amount_g"] == 200


class TestFoodParser:
    def test_simple_with_grams(self):
        p = parse_food_entry("chicken breast 200g")
        assert p.matched
        assert p.food_name == "chicken breast"
        assert p.amount_g == 200
        assert p.nutrition["calories"] == 330

    def test_with_cooking_method(self):
        p = parse_food_entry("grilled chicken breast 200g")
        assert p.matched
        assert p.food_name == "chicken breast"
        assert p.amount_g == 200

    def test_quantity_pieces(self):
        p = parse_food_entry("2 eggs")
        assert p.matched
        assert p.food_name == "egg"
        assert p.amount_g == 100  # 2 * 50g per egg

    def test_with_cups(self):
        p = parse_food_entry("1 cup rice")
        assert p.matched
        assert p.amount_g == 240  # 1 cup = 240g

    def test_with_oz(self):
        p = parse_food_entry("6 oz salmon")
        assert p.matched
        assert p.food_name == "salmon"
        assert abs(p.amount_g - 170.1) < 0.2

    def test_multiple_items(self):
        items = parse_multiple("chicken 200g, rice 150g and broccoli 100g")
        assert len(items) == 3
        assert all(i.matched for i in items)

    def test_unmatched_food(self):
        p = parse_food_entry("xyzfoobar 100g")
        assert not p.matched

    def test_single_banana(self):
        p = parse_food_entry("banana")
        assert p.matched
        assert p.food_name == "banana"
        assert p.amount_g == 118  # default piece weight

    def test_tbsp_olive_oil(self):
        p = parse_food_entry("2 tbsp olive oil")
        assert p.matched
        assert p.amount_g == 30  # 2 * 15g
        assert p.nutrition["calories"] == 265  # 884 * 0.3
