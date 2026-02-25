"""Tests for Recipe Cost Estimation Engine."""
import pytest
from src.services.recipe_cost import (
    estimate_ingredient_cost,
    estimate_recipe_cost,
    estimate_meal_plan_cost,
    PriceConfidence,
    _parse_quantity,
)


class TestQuantityParsing:
    def test_simple_integer(self):
        assert _parse_quantity("2") == 2.0

    def test_fraction(self):
        assert abs(_parse_quantity("1/2") - 0.5) < 0.01

    def test_unicode_fraction(self):
        assert abs(_parse_quantity("½") - 0.5) < 0.01

    def test_mixed_number(self):
        assert abs(_parse_quantity("1 1/2") - 1.5) < 0.01

    def test_range(self):
        assert abs(_parse_quantity("2-3") - 2.5) < 0.01

    def test_empty(self):
        assert _parse_quantity("") == 1.0

    def test_with_unit(self):
        assert abs(_parse_quantity("2 cups") - 2.0) < 0.01

    def test_quarter_fraction(self):
        assert abs(_parse_quantity("¼") - 0.25) < 0.01


class TestIngredientCost:
    def test_known_ingredient(self):
        cost = estimate_ingredient_cost("1 lb chicken breast")
        assert cost.estimated_cost > 0
        assert cost.confidence == PriceConfidence.HIGH
        assert cost.name == "chicken breast"

    def test_spice_amortized(self):
        cost = estimate_ingredient_cost("1 tsp cinnamon")
        assert cost.estimated_cost == 0.15
        assert "amortized" in (cost.notes or "").lower()

    def test_eggs(self):
        cost = estimate_ingredient_cost("3 eggs")
        assert cost.estimated_cost > 0
        assert cost.estimated_cost < 5.0  # 3 eggs shouldn't be $5+

    def test_unknown_ingredient(self):
        cost = estimate_ingredient_cost("1 cup dragon fruit puree")
        assert cost.estimated_cost > 0
        assert cost.confidence == PriceConfidence.LOW

    def test_protein_powder(self):
        cost = estimate_ingredient_cost("1 scoop protein powder")
        assert cost.estimated_cost > 0
        assert cost.confidence == PriceConfidence.HIGH

    def test_olive_oil(self):
        cost = estimate_ingredient_cost("2 tbsp olive oil")
        assert cost.estimated_cost > 0
        assert cost.estimated_cost < 5.0  # 2 tbsp shouldn't cost $5

    def test_chicken_breast_by_weight(self):
        cost = estimate_ingredient_cost("1 lb chicken breast")
        assert cost.estimated_cost >= 3.0
        assert cost.estimated_cost <= 6.0

    def test_minimum_cost(self):
        cost = estimate_ingredient_cost("1 pinch salt")
        assert cost.estimated_cost >= 0.10


class TestRecipeCost:
    def test_simple_recipe(self):
        ingredients = [
            "2 chicken breast",
            "1 cup rice",
            "2 tbsp olive oil",
            "1 tsp salt",
            "1 tsp black pepper",
        ]
        cost = estimate_recipe_cost(ingredients, servings=4)
        assert cost.total_cost > 0
        assert cost.per_serving_cost > 0
        assert cost.per_serving_cost == cost.total_cost / 4
        assert cost.servings == 4
        assert len(cost.ingredients) == 5

    def test_budget_friendly_flag(self):
        # Simple cheap recipe
        ingredients = ["2 eggs", "1 slice bread", "1 tsp butter"]
        cost = estimate_recipe_cost(ingredients, servings=1)
        # Should be well under $3/serving
        assert cost.per_serving_cost < 10  # reasonable upper bound

    def test_to_dict(self):
        ingredients = ["1 cup oats", "1 banana", "1 tbsp honey"]
        cost = estimate_recipe_cost(ingredients, servings=2)
        d = cost.to_dict()
        assert "total_cost" in d
        assert "per_serving_cost" in d
        assert "is_budget_friendly" in d
        assert "ingredients" in d
        assert len(d["ingredients"]) == 3

    def test_single_serving(self):
        ingredients = ["1 scoop protein powder", "1 cup almond milk", "1 banana"]
        cost = estimate_recipe_cost(ingredients, servings=1)
        assert cost.total_cost == cost.per_serving_cost

    def test_empty_recipe(self):
        cost = estimate_recipe_cost([], servings=4)
        assert cost.total_cost == 0
        assert cost.per_serving_cost == 0


class TestMealPlanCost:
    def test_weekly_plan(self):
        recipes = [
            {"title": "Chicken & Rice", "ingredients": ["1 lb chicken breast", "2 cups rice"], "servings": 4},
            {"title": "Protein Shake", "ingredients": ["1 scoop protein powder", "1 cup almond milk"], "servings": 1},
        ]
        result = estimate_meal_plan_cost(recipes)
        assert result["total_weekly_cost"] > 0
        assert result["daily_average"] > 0
        assert len(result["recipes"]) == 2
        assert "savings_tip" in result

    def test_empty_plan(self):
        result = estimate_meal_plan_cost([])
        assert result["total_weekly_cost"] == 0
        assert result["daily_average"] == 0

    def test_savings_tip_budget(self):
        recipes = [
            {"title": "Oatmeal", "ingredients": ["1 cup oats", "1 banana"], "servings": 1},
        ]
        result = estimate_meal_plan_cost(recipes)
        assert isinstance(result["savings_tip"], str)
        assert len(result["savings_tip"]) > 10


class TestEdgeCases:
    def test_unicode_fractions_in_ingredient(self):
        cost = estimate_ingredient_cost("½ cup greek yogurt")
        assert cost.estimated_cost > 0

    def test_parenthetical_stripped(self):
        cost = estimate_ingredient_cost("1 cup greek yogurt (0% fat)")
        assert cost.name == "greek yogurt"

    def test_ingredient_with_prep(self):
        cost = estimate_ingredient_cost("2 cups spinach, washed")
        assert cost.estimated_cost > 0

    def test_zero_servings_safe(self):
        cost = estimate_recipe_cost(["1 banana"], servings=0)
        assert cost.per_serving_cost > 0  # doesn't divide by zero
