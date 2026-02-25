"""Tests for multi-provider affiliate link engine."""
import pytest
from src.services.affiliate import (
    enrich_ingredient,
    enrich_ingredients,
    enrich_recipe,
    parse_ingredient,
    classify_ingredient,
    get_shop_all_url,
    generate_click_id,
    amazon_product_url,
    amazon_search_url,
    AffiliateProvider,
    IngredientCategory,
    AMAZON_TAG,
    DEFAULT_AMAZON_TAG,
)


# ── Ingredient Parsing ──────────────────────────────────────────────────────

class TestParseIngredient:
    def test_basic_amount(self):
        amount, name = parse_ingredient("2 cups greek yogurt")
        assert amount == "2 cups"
        assert name == "greek yogurt"

    def test_scoop(self):
        amount, name = parse_ingredient("1 scoop protein powder")
        assert amount == "1 scoop"
        assert name == "protein powder"

    def test_fraction(self):
        amount, name = parse_ingredient("1/2 cup oats")
        assert amount == "1/2 cup"
        assert name == "oats"

    def test_no_amount(self):
        amount, name = parse_ingredient("honey")
        assert amount == ""
        assert name == "honey"

    def test_parenthetical_stripped(self):
        amount, name = parse_ingredient("1 cup Greek Yogurt (0% fat)")
        assert "0% fat" not in name
        assert "greek yogurt" in name

    def test_tbsp(self):
        amount, name = parse_ingredient("2 tbsp peanut butter")
        assert amount == "2 tbsp"
        assert name == "peanut butter"

    def test_oz(self):
        amount, name = parse_ingredient("6 oz chicken breast")
        assert amount == "6 oz"
        assert name == "chicken breast"

    def test_preserves_original(self):
        result = enrich_ingredient("2 cups Greek Yogurt (0% fat)")
        assert result.original == "2 cups Greek Yogurt (0% fat)"


# ── Ingredient Classification ───────────────────────────────────────────────

class TestClassifyIngredient:
    def test_supplement(self):
        assert classify_ingredient("protein powder") == IngredientCategory.SUPPLEMENT
        assert classify_ingredient("creatine") == IngredientCategory.SUPPLEMENT
        assert classify_ingredient("collagen") == IngredientCategory.SUPPLEMENT

    def test_produce(self):
        assert classify_ingredient("broccoli") == IngredientCategory.PRODUCE
        assert classify_ingredient("banana") == IngredientCategory.PRODUCE
        assert classify_ingredient("avocado") == IngredientCategory.PRODUCE

    def test_dairy(self):
        assert classify_ingredient("greek yogurt") == IngredientCategory.DAIRY
        assert classify_ingredient("cottage cheese") == IngredientCategory.DAIRY

    def test_meat(self):
        assert classify_ingredient("chicken breast") == IngredientCategory.MEAT
        assert classify_ingredient("salmon") == IngredientCategory.MEAT
        assert classify_ingredient("ground turkey") == IngredientCategory.MEAT

    def test_pantry(self):
        assert classify_ingredient("oats") == IngredientCategory.PANTRY
        assert classify_ingredient("rice") == IngredientCategory.PANTRY
        assert classify_ingredient("olive oil") == IngredientCategory.PANTRY

    def test_condiment(self):
        assert classify_ingredient("sriracha") == IngredientCategory.CONDIMENT
        assert classify_ingredient("soy sauce") == IngredientCategory.CONDIMENT

    def test_frozen(self):
        assert classify_ingredient("frozen banana") == IngredientCategory.FROZEN
        assert classify_ingredient("frozen berries") == IngredientCategory.FROZEN

    def test_organic(self):
        assert classify_ingredient("organic chicken") == IngredientCategory.ORGANIC

    def test_unknown(self):
        assert classify_ingredient("dragon fruit extract") == IngredientCategory.OTHER


# ── Multi-Provider Link Generation ──────────────────────────────────────────

class TestEnrichIngredient:
    def test_supplement_gets_iherb(self):
        result = enrich_ingredient("1 scoop protein powder")
        providers = {l.provider for l in result.links}
        assert AffiliateProvider.IHERB in providers
        # iHerb should be primary (highest commission for supplements)
        assert result.primary_link.provider == AffiliateProvider.IHERB

    def test_produce_gets_instacart(self):
        result = enrich_ingredient("1 cup broccoli")
        providers = {l.provider for l in result.links}
        assert AffiliateProvider.INSTACART in providers
        # Instacart should be primary for produce (10% vs Amazon 4%)
        assert result.primary_link.provider == AffiliateProvider.INSTACART

    def test_pantry_gets_multiple(self):
        result = enrich_ingredient("1 cup oats")
        providers = {l.provider for l in result.links}
        # Oats should be available on Amazon, Instacart, and Thrive
        assert AffiliateProvider.AMAZON in providers
        assert AffiliateProvider.INSTACART in providers

    def test_known_asin_gets_direct_link(self):
        result = enrich_ingredient("2 tbsp peanut butter")
        amazon_links = [l for l in result.links if l.provider == AffiliateProvider.AMAZON]
        assert len(amazon_links) == 1
        assert amazon_links[0].is_direct is True
        assert "/dp/" in amazon_links[0].url

    def test_unknown_ingredient_gets_search(self):
        result = enrich_ingredient("3 dragon fruits")
        amazon_links = [l for l in result.links if l.provider == AffiliateProvider.AMAZON]
        assert len(amazon_links) == 1
        assert "/s?" in amazon_links[0].url

    def test_links_sorted_by_commission(self):
        result = enrich_ingredient("1 cup oats")
        commissions = [l.commission_pct for l in result.links]
        assert commissions == sorted(commissions, reverse=True)

    def test_amazon_tag_correct(self):
        result = enrich_ingredient("honey")
        amazon_links = [l for l in result.links if l.provider == AffiliateProvider.AMAZON]
        assert AMAZON_TAG in amazon_links[0].url

    def test_dairy_primary_is_instacart(self):
        result = enrich_ingredient("1 cup cottage cheese")
        assert result.primary_link.provider == AffiliateProvider.INSTACART

    def test_meat_primary_is_instacart(self):
        result = enrich_ingredient("6 oz chicken breast")
        assert result.primary_link.provider == AffiliateProvider.INSTACART


# ── Enrich Multiple Ingredients ─────────────────────────────────────────────

class TestEnrichIngredients:
    def test_returns_list_of_dicts(self):
        result = enrich_ingredients(["1 cup oats", "1 scoop protein powder"])
        assert isinstance(result, list)
        assert len(result) == 2
        assert "ingredient" in result[0]
        assert "primary_link" in result[0]
        assert "all_links" in result[0]

    def test_empty_list(self):
        assert enrich_ingredients([]) == []

    def test_backward_compat_shape(self):
        """Old API returned list of dicts with 'ingredient' and 'affiliate_url' shape.
        New API has 'ingredient' and 'primary_link' dict."""
        result = enrich_ingredients(["1 cup oats"])
        assert "ingredient" in result[0]
        assert result[0]["primary_link"]["url"]


# ── Enrich Recipe ───────────────────────────────────────────────────────────

class TestEnrichRecipe:
    def test_adds_affiliate_links(self):
        recipe = {
            "title": "Protein Oats",
            "ingredients": ["1 cup oats", "1 scoop protein powder"],
        }
        enriched = enrich_recipe(recipe)
        assert "affiliate_links" in enriched
        assert len(enriched["affiliate_links"]) == 2

    def test_adds_meta(self):
        recipe = {
            "title": "Protein Oats",
            "ingredients": ["1 cup oats", "1 scoop protein powder"],
        }
        enriched = enrich_recipe(recipe)
        assert "affiliate_meta" in enriched
        assert "providers_used" in enriched["affiliate_meta"]
        assert "avg_commission_pct" in enriched["affiliate_meta"]

    def test_no_ingredients(self):
        recipe = {"title": "Empty", "ingredients": []}
        enriched = enrich_recipe(recipe)
        assert "affiliate_links" not in enriched

    def test_missing_ingredients_key(self):
        recipe = {"title": "No key"}
        enriched = enrich_recipe(recipe)
        assert "affiliate_links" not in enriched


# ── Shop All Ingredients ────────────────────────────────────────────────────

class TestShopAll:
    def test_returns_instacart(self):
        result = get_shop_all_url(["1 cup oats", "2 tbsp peanut butter"])
        assert result["provider"] == "instacart"
        assert "instacart.com" in result["url"]
        assert result["label"] == "Shop All Ingredients"

    def test_limits_to_15(self):
        # Should not crash with many ingredients
        ings = [f"ingredient {i}" for i in range(30)]
        result = get_shop_all_url(ings)
        assert result["url"]  # should not be empty


# ── Click Tracking ──────────────────────────────────────────────────────────

class TestClickId:
    def test_deterministic(self):
        id1 = generate_click_id("user1", "recipe1", "oats", "amazon")
        id2 = generate_click_id("user1", "recipe1", "oats", "amazon")
        assert id1 == id2

    def test_unique_per_combo(self):
        id1 = generate_click_id("user1", "recipe1", "oats", "amazon")
        id2 = generate_click_id("user1", "recipe1", "oats", "instacart")
        assert id1 != id2

    def test_anon_user(self):
        cid = generate_click_id(None, "recipe1", "oats", "amazon")
        assert len(cid) == 16


# ── Legacy Compat ────────────────────────────────────────────────────────────

class TestLegacyCompat:
    def test_default_tag(self):
        assert DEFAULT_AMAZON_TAG == "83apps01-20"

    def test_amazon_product_url(self):
        url = amazon_product_url("B0015R36SK")
        assert "B0015R36SK" in url
        assert AMAZON_TAG in url

    def test_amazon_search_url(self):
        url = amazon_search_url("chicken breast")
        assert "chicken+breast" in url
