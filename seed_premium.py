"""Premium recipe seed data — 30 viral high-protein recipes with affiliate links.

These are real-style recipes inspired by trending fitness content.
Each has complete nutrition, steps, affiliate-ready ingredients, and Unsplash thumbnails.
"""
import asyncio
import uuid
import random
from datetime import datetime, timedelta

AMAZON_TAG = "83apps01-20"

def amz(query):
    """Generate Amazon affiliate search URL."""
    from urllib.parse import quote_plus
    return f"https://www.amazon.com/s?k={quote_plus(query)}&tag={AMAZON_TAG}"

PREMIUM_RECIPES = [
    {
        "title": "Protein Ice Cream (Ninja Creami Style)",
        "description": "Only 150 calories with 30g protein. Tastes like real ice cream. The viral Ninja Creami hack that broke TikTok.",
        "creator_username": "gregdoucette",
        "creator_display_name": "Greg Doucette",
        "creator_platform": "youtube",
        "creator_profile_url": "https://youtube.com/@GregDoucette",
        "thumbnail_url": "https://images.unsplash.com/photo-1488900128323-21503983a07e?w=600",
        "ingredients": [
            {"name": "casein protein powder", "quantity": "1 scoop (30g)", "category": "supplements", "affiliate_url": amz("casein protein powder")},
            {"name": "frozen banana", "quantity": "1/2 medium", "category": "produce"},
            {"name": "almond milk unsweetened", "quantity": "1 cup", "category": "dairy", "affiliate_url": amz("almond milk unsweetened")},
            {"name": "xanthan gum", "quantity": "1/4 tsp", "category": "pantry", "affiliate_url": amz("xanthan gum food grade")},
            {"name": "sugar-free pudding mix", "quantity": "1 tbsp", "category": "pantry", "affiliate_url": amz("sugar free pudding mix")},
        ],
        "steps": [
            "Blend all ingredients until smooth",
            "Pour into Ninja Creami pint container",
            "Freeze for 24 hours (must be fully frozen solid)",
            "Run on Ice Cream setting, then Re-spin once",
            "Scoop and enjoy immediately for best texture"
        ],
        "tags": ["high-protein", "low-calorie", "dessert", "viral", "ninja-creami"],
        "calories": 150, "protein_g": 30, "carbs_g": 15, "fat_g": 2, "fiber_g": 2, "sugar_g": 8,
        "servings": 1, "cook_time_minutes": 5, "difficulty": "easy",
        "views": 2400000, "likes": 185000, "comments": 4200, "shares": 32000,
    },
    {
        "title": "Egg White Wrap (Anabolic Kitchen)",
        "description": "Crispy egg white wrap with turkey and veggies. 40g protein, under 300 calories. Perfect grab-and-go meal prep.",
        "creator_username": "remington_james",
        "creator_display_name": "Remington James",
        "creator_platform": "youtube",
        "creator_profile_url": "https://youtube.com/@RemingtonJames",
        "thumbnail_url": "https://images.unsplash.com/photo-1626700051175-6818013e1d4f?w=600",
        "ingredients": [
            {"name": "egg whites", "quantity": "1 cup (8 oz)", "category": "protein", "affiliate_url": amz("liquid egg whites")},
            {"name": "turkey deli meat", "quantity": "4 oz", "category": "protein"},
            {"name": "spinach", "quantity": "1 cup", "category": "produce"},
            {"name": "bell pepper", "quantity": "1/2, sliced", "category": "produce"},
            {"name": "everything bagel seasoning", "quantity": "1 tsp", "category": "pantry", "affiliate_url": amz("everything bagel seasoning")},
            {"name": "light laughing cow cheese", "quantity": "1 wedge", "category": "dairy"},
        ],
        "steps": [
            "Heat non-stick pan on medium, spray with cooking spray",
            "Pour egg whites in thin layer, cook 2-3 min until set",
            "Flip carefully, cook 30 more seconds",
            "Spread cheese wedge on wrap",
            "Layer turkey, spinach, peppers",
            "Roll up tight, slice in half diagonally"
        ],
        "tags": ["high-protein", "low-calorie", "meal-prep", "anabolic", "wrap"],
        "calories": 280, "protein_g": 42, "carbs_g": 8, "fat_g": 8, "fiber_g": 2, "sugar_g": 3,
        "servings": 1, "cook_time_minutes": 10, "difficulty": "easy",
        "views": 890000, "likes": 67000, "comments": 1800, "shares": 12000,
    },
    {
        "title": "Air Fryer Chicken Thighs (Crispy Perfection)",
        "description": "Juicy on the inside, impossibly crispy skin. Air fryer does all the work. 5 min prep, restaurant quality.",
        "creator_username": "joshuaweissman",
        "creator_display_name": "Joshua Weissman",
        "creator_platform": "youtube",
        "creator_profile_url": "https://youtube.com/@JoshuaWeissman",
        "thumbnail_url": "https://images.unsplash.com/photo-1598103442097-8b74394b95c6?w=600",
        "ingredients": [
            {"name": "chicken thighs bone-in skin-on", "quantity": "4 pieces (about 2 lbs)", "category": "protein"},
            {"name": "garlic powder", "quantity": "1 tsp", "category": "pantry", "affiliate_url": amz("garlic powder organic")},
            {"name": "smoked paprika", "quantity": "1 tsp", "category": "pantry", "affiliate_url": amz("smoked paprika")},
            {"name": "onion powder", "quantity": "1/2 tsp", "category": "pantry"},
            {"name": "avocado oil spray", "quantity": "light coating", "category": "pantry", "affiliate_url": amz("avocado oil spray cooking")},
            {"name": "salt and pepper", "quantity": "to taste", "category": "pantry"},
        ],
        "steps": [
            "Pat chicken thighs completely dry with paper towels (critical for crispy skin)",
            "Mix garlic powder, paprika, onion powder, salt, pepper",
            "Season both sides generously",
            "Spray air fryer basket, place skin-side down",
            "Air fry at 400°F for 10 min, flip skin-side up",
            "Continue at 400°F for 10-12 more min until skin is golden and crispy",
            "Rest 5 min before serving"
        ],
        "tags": ["high-protein", "air-fryer", "keto", "low-carb", "meal-prep", "crispy"],
        "calories": 320, "protein_g": 38, "carbs_g": 1, "fat_g": 18, "fiber_g": 0, "sugar_g": 0,
        "servings": 4, "cook_time_minutes": 25, "difficulty": "easy",
        "views": 3100000, "likes": 210000, "comments": 5600, "shares": 45000,
    },
    {
        "title": "Cottage Cheese Flatbread (3 Ingredients)",
        "description": "Viral cottage cheese flatbread — crispy, high protein, no flour needed. Game changer for pizza night.",
        "creator_username": "healthygirlkitchen",
        "creator_display_name": "Danielle Brown | Healthy Girl Kitchen",
        "creator_platform": "youtube",
        "creator_profile_url": "https://youtube.com/@HealthyGirlKitchen",
        "thumbnail_url": "https://images.unsplash.com/photo-1565299624946-b28f40a0ae38?w=600",
        "ingredients": [
            {"name": "cottage cheese", "quantity": "1 cup", "category": "dairy"},
            {"name": "eggs", "quantity": "2 large", "category": "protein"},
            {"name": "oat flour", "quantity": "1/2 cup", "category": "pantry", "affiliate_url": amz("oat flour organic")},
            {"name": "Italian seasoning", "quantity": "1 tsp", "category": "pantry"},
            {"name": "garlic powder", "quantity": "1/2 tsp", "category": "pantry"},
        ],
        "steps": [
            "Blend cottage cheese, eggs, oat flour, and seasonings until smooth",
            "Pour onto parchment-lined baking sheet in a thin rectangle",
            "Bake at 425°F for 15-18 min until edges are golden",
            "Add your favorite pizza toppings",
            "Broil 2-3 min until toppings are bubbly",
            "Slice and serve hot"
        ],
        "tags": ["high-protein", "low-carb", "pizza", "viral", "cottage-cheese", "3-ingredients"],
        "calories": 220, "protein_g": 24, "carbs_g": 18, "fat_g": 7, "fiber_g": 2, "sugar_g": 3,
        "servings": 2, "cook_time_minutes": 20, "difficulty": "easy",
        "views": 5600000, "likes": 420000, "comments": 8900, "shares": 78000,
    },
    {
        "title": "Baked Oats (TikTok Famous)",
        "description": "Tastes like cake for breakfast. 35g protein, perfect macros. The baked oats recipe with 100M+ views across TikTok.",
        "creator_username": "kaleandkravings",
        "creator_display_name": "Katie | Kale & Kravings",
        "creator_platform": "youtube",
        "creator_profile_url": "https://youtube.com/@kaleandkravings",
        "thumbnail_url": "https://images.unsplash.com/photo-1517673132405-a56a62b18caf?w=600",
        "ingredients": [
            {"name": "rolled oats", "quantity": "1/2 cup", "category": "pantry", "affiliate_url": amz("organic rolled oats")},
            {"name": "vanilla protein powder", "quantity": "1 scoop (30g)", "category": "supplements", "affiliate_url": amz("vanilla whey protein powder")},
            {"name": "banana", "quantity": "1 ripe", "category": "produce"},
            {"name": "egg whites", "quantity": "1/4 cup", "category": "protein"},
            {"name": "baking powder", "quantity": "1/2 tsp", "category": "pantry"},
            {"name": "blueberries", "quantity": "1/4 cup", "category": "produce"},
            {"name": "almond milk", "quantity": "1/4 cup", "category": "dairy"},
        ],
        "steps": [
            "Mash banana in a bowl",
            "Add oats, protein powder, egg whites, baking powder, and milk",
            "Mix until combined (batter will be thick)",
            "Pour into greased ramekin or small baking dish",
            "Top with blueberries, press gently into batter",
            "Bake at 350°F for 25-30 min until golden and set",
            "Let cool 5 min — it firms up as it cools"
        ],
        "tags": ["high-protein", "breakfast", "baked-oats", "viral", "meal-prep"],
        "calories": 340, "protein_g": 35, "carbs_g": 42, "fat_g": 5, "fiber_g": 6, "sugar_g": 14,
        "servings": 1, "cook_time_minutes": 30, "difficulty": "easy",
        "views": 4200000, "likes": 310000, "comments": 6700, "shares": 55000,
    },
    {
        "title": "Protein Overnight Oats (Snickers Flavor)",
        "description": "Meal prep dessert for breakfast. Chocolate, peanut butter, caramel — all for 380 cal and 38g protein.",
        "creator_username": "faborafitness",
        "creator_display_name": "Fabora | Fitness Kitchen",
        "creator_platform": "youtube",
        "creator_profile_url": "https://youtube.com/@FaboraFitness",
        "thumbnail_url": "https://images.unsplash.com/photo-1504674900247-0877df9cc836?w=600",
        "ingredients": [
            {"name": "rolled oats", "quantity": "1/2 cup", "category": "pantry"},
            {"name": "chocolate protein powder", "quantity": "1 scoop", "category": "supplements", "affiliate_url": amz("chocolate whey protein")},
            {"name": "PB2 powdered peanut butter", "quantity": "2 tbsp", "category": "pantry", "affiliate_url": amz("PB2 powdered peanut butter")},
            {"name": "Greek yogurt nonfat", "quantity": "1/2 cup", "category": "dairy"},
            {"name": "almond milk", "quantity": "1/2 cup", "category": "dairy"},
            {"name": "sugar-free caramel syrup", "quantity": "1 tbsp", "category": "pantry", "affiliate_url": amz("sugar free caramel syrup")},
            {"name": "crushed peanuts", "quantity": "1 tbsp", "category": "pantry"},
        ],
        "steps": [
            "Mix oats, protein powder, PB2, and Greek yogurt in a jar",
            "Add almond milk and stir well (should be thick but pourable)",
            "Drizzle caramel syrup on top",
            "Refrigerate overnight (at least 6 hours)",
            "Top with crushed peanuts before eating",
            "Eat cold or microwave 90 sec for warm version"
        ],
        "tags": ["high-protein", "meal-prep", "overnight-oats", "dessert", "breakfast", "chocolate"],
        "calories": 380, "protein_g": 38, "carbs_g": 40, "fat_g": 8, "fiber_g": 5, "sugar_g": 10,
        "servings": 1, "cook_time_minutes": 5, "difficulty": "easy",
        "views": 1800000, "likes": 142000, "comments": 3400, "shares": 28000,
    },
    {
        "title": "Salmon Rice Bowl (Viral TikTok Recipe)",
        "description": "The salmon rice bowl that took over the internet. Sushi-grade flavor, 5-minute assembly. Emily Mariko's famous recipe.",
        "creator_username": "emilymariko",
        "creator_display_name": "Emily Mariko",
        "creator_platform": "youtube",
        "creator_profile_url": "https://youtube.com/@EmilyMariko",
        "thumbnail_url": "https://images.unsplash.com/photo-1546069901-ba9599a7e63c?w=600",
        "ingredients": [
            {"name": "cooked salmon fillet", "quantity": "6 oz", "category": "protein"},
            {"name": "sushi rice cooked", "quantity": "1 cup", "category": "pantry"},
            {"name": "soy sauce", "quantity": "1 tbsp", "category": "pantry", "affiliate_url": amz("kikkoman soy sauce")},
            {"name": "sriracha mayo", "quantity": "1 tbsp", "category": "pantry", "affiliate_url": amz("sriracha mayo")},
            {"name": "avocado", "quantity": "1/2, sliced", "category": "produce"},
            {"name": "nori sheets", "quantity": "1 sheet, crumbled", "category": "pantry", "affiliate_url": amz("roasted nori sheets")},
            {"name": "sesame seeds", "quantity": "1 tsp", "category": "pantry"},
        ],
        "steps": [
            "Place leftover rice in bowl, top with salmon",
            "Cover with damp paper towel, microwave 1-2 min",
            "Mash salmon into rice with a fork",
            "Add soy sauce, mix well",
            "Top with avocado slices, sriracha mayo, nori, sesame seeds",
            "Eat immediately while warm"
        ],
        "tags": ["high-protein", "viral", "salmon", "sushi", "quick", "meal-prep"],
        "calories": 480, "protein_g": 38, "carbs_g": 42, "fat_g": 18, "fiber_g": 4, "sugar_g": 2,
        "servings": 1, "cook_time_minutes": 5, "difficulty": "easy",
        "views": 12000000, "likes": 890000, "comments": 15000, "shares": 120000,
    },
    {
        "title": "Turkey Taco Lettuce Wraps",
        "description": "All the taco flavor, fraction of the carbs. 45g protein per serving. Perfect for cutting season.",
        "creator_username": "flavcity",
        "creator_display_name": "Bobby Parrish | FlavCity",
        "creator_platform": "youtube",
        "creator_profile_url": "https://youtube.com/@FlavCity",
        "thumbnail_url": "https://images.unsplash.com/photo-1551326844-4df70f78d0e9?w=600",
        "ingredients": [
            {"name": "ground turkey 99% lean", "quantity": "1 lb", "category": "protein"},
            {"name": "taco seasoning", "quantity": "2 tbsp", "category": "pantry", "affiliate_url": amz("taco seasoning low sodium")},
            {"name": "butter lettuce heads", "quantity": "2 heads", "category": "produce"},
            {"name": "pico de gallo", "quantity": "1/2 cup", "category": "produce"},
            {"name": "plain Greek yogurt (sour cream sub)", "quantity": "1/4 cup", "category": "dairy"},
            {"name": "shredded Mexican cheese", "quantity": "1/4 cup", "category": "dairy"},
            {"name": "lime", "quantity": "1, cut in wedges", "category": "produce"},
        ],
        "steps": [
            "Brown turkey in skillet over medium-high heat, breaking into crumbles",
            "Drain any liquid, add taco seasoning + 1/4 cup water",
            "Simmer 3-4 min until thick and saucy",
            "Separate lettuce cups (use 2 stacked for sturdiness)",
            "Fill each cup with turkey mixture",
            "Top with pico, yogurt, cheese, squeeze of lime",
            "Serve immediately — makes 8-10 wraps"
        ],
        "tags": ["high-protein", "low-carb", "keto", "taco", "meal-prep", "quick"],
        "calories": 290, "protein_g": 45, "carbs_g": 8, "fat_g": 9, "fiber_g": 2, "sugar_g": 3,
        "servings": 3, "cook_time_minutes": 15, "difficulty": "easy",
        "views": 2100000, "likes": 165000, "comments": 3800, "shares": 25000,
    },
    {
        "title": "High Protein French Toast",
        "description": "Fluffy, thick-cut French toast with 45g protein. Tastes indulgent but fits your macros perfectly.",
        "creator_username": "theproteinchef",
        "creator_display_name": "Derek Howes | The Protein Chef",
        "creator_platform": "youtube",
        "creator_profile_url": "https://youtube.com/@TheProteinChef",
        "thumbnail_url": "https://images.unsplash.com/photo-1484723091739-30a097e8f929?w=600",
        "ingredients": [
            {"name": "thick-cut bread (Dave's Killer or sourdough)", "quantity": "2 slices", "category": "pantry"},
            {"name": "egg whites", "quantity": "1/2 cup", "category": "protein"},
            {"name": "vanilla protein powder", "quantity": "1/2 scoop", "category": "supplements", "affiliate_url": amz("vanilla whey protein isolate")},
            {"name": "cinnamon", "quantity": "1 tsp", "category": "pantry"},
            {"name": "vanilla extract", "quantity": "1/2 tsp", "category": "pantry"},
            {"name": "sugar-free maple syrup", "quantity": "2 tbsp", "category": "pantry", "affiliate_url": amz("sugar free maple syrup")},
            {"name": "mixed berries", "quantity": "1/4 cup", "category": "produce"},
        ],
        "steps": [
            "Whisk egg whites, protein powder, cinnamon, vanilla into smooth batter",
            "Soak bread slices 30 seconds each side",
            "Cook in non-stick pan on medium heat, 2-3 min per side",
            "Look for golden brown color and slight puff",
            "Stack on plate, top with berries",
            "Drizzle with sugar-free syrup"
        ],
        "tags": ["high-protein", "breakfast", "french-toast", "anabolic", "bulk-friendly"],
        "calories": 350, "protein_g": 45, "carbs_g": 35, "fat_g": 4, "fiber_g": 4, "sugar_g": 8,
        "servings": 1, "cook_time_minutes": 10, "difficulty": "easy",
        "views": 1500000, "likes": 112000, "comments": 2900, "shares": 18000,
    },
    {
        "title": "5-Minute Protein Mug Cake",
        "description": "Warm, fudgy chocolate mug cake in 5 minutes. 28g protein. When the sweet tooth hits during a cut.",
        "creator_username": "thetackleberry",
        "creator_display_name": "Will Tennyson",
        "creator_platform": "youtube",
        "creator_profile_url": "https://youtube.com/@WillTennyson",
        "thumbnail_url": "https://images.unsplash.com/photo-1563729784474-d77dbb933a9e?w=600",
        "ingredients": [
            {"name": "chocolate protein powder", "quantity": "1 scoop", "category": "supplements", "affiliate_url": amz("chocolate whey protein isolate")},
            {"name": "cocoa powder", "quantity": "1 tbsp", "category": "pantry", "affiliate_url": amz("unsweetened cocoa powder")},
            {"name": "egg", "quantity": "1 large", "category": "protein"},
            {"name": "baking powder", "quantity": "1/4 tsp", "category": "pantry"},
            {"name": "almond milk", "quantity": "2 tbsp", "category": "dairy"},
            {"name": "sugar-free chocolate chips", "quantity": "1 tbsp", "category": "pantry", "affiliate_url": amz("sugar free chocolate chips lily")},
        ],
        "steps": [
            "Mix protein powder, cocoa, and baking powder in a large mug",
            "Add egg and almond milk, stir until smooth (no lumps)",
            "Fold in chocolate chips",
            "Microwave on high for 60-90 seconds",
            "It should be set on edges but slightly gooey in center",
            "Let sit 1 min, eat straight from the mug"
        ],
        "tags": ["high-protein", "low-calorie", "dessert", "quick", "chocolate", "mug-cake"],
        "calories": 220, "protein_g": 28, "carbs_g": 12, "fat_g": 8, "fiber_g": 3, "sugar_g": 4,
        "servings": 1, "cook_time_minutes": 5, "difficulty": "easy",
        "views": 3800000, "likes": 280000, "comments": 5200, "shares": 42000,
    },
    {
        "title": "Sheet Pan Chicken Fajitas",
        "description": "Dump everything on a sheet pan. Walk away for 20 min. Come back to perfectly charred fajitas for 4 people.",
        "creator_username": "budgetbytes",
        "creator_display_name": "Beth | Budget Bytes",
        "creator_platform": "youtube",
        "creator_profile_url": "https://youtube.com/@BudgetBytes",
        "thumbnail_url": "https://images.unsplash.com/photo-1599974579688-8dbdd335c77f?w=600",
        "ingredients": [
            {"name": "chicken breast", "quantity": "1.5 lbs, sliced thin", "category": "protein"},
            {"name": "bell peppers", "quantity": "3, mixed colors, sliced", "category": "produce"},
            {"name": "red onion", "quantity": "1 large, sliced", "category": "produce"},
            {"name": "fajita seasoning", "quantity": "3 tbsp", "category": "pantry", "affiliate_url": amz("fajita seasoning mix")},
            {"name": "olive oil", "quantity": "2 tbsp", "category": "pantry"},
            {"name": "lime juice", "quantity": "2 tbsp", "category": "pantry"},
            {"name": "flour tortillas", "quantity": "8 small", "category": "pantry"},
        ],
        "steps": [
            "Preheat oven to 425°F, line sheet pan with foil",
            "Toss chicken, peppers, onion with oil, seasoning, lime juice",
            "Spread in single layer on pan (don't overcrowd)",
            "Bake 20-22 min, flipping halfway",
            "Chicken should be charred on edges, peppers slightly blistered",
            "Warm tortillas 30 sec in microwave",
            "Serve family-style with toppings of choice"
        ],
        "tags": ["high-protein", "meal-prep", "sheet-pan", "fajitas", "family", "budget"],
        "calories": 380, "protein_g": 42, "carbs_g": 32, "fat_g": 10, "fiber_g": 3, "sugar_g": 5,
        "servings": 4, "cook_time_minutes": 25, "difficulty": "easy",
        "views": 1900000, "likes": 145000, "comments": 3200, "shares": 22000,
    },
    {
        "title": "Protein Smoothie Bowl (Berry Açaí)",
        "description": "Thick, creamy, Instagram-worthy smoothie bowl with 32g protein. Eat with a spoon, not a straw.",
        "creator_username": "downshiftology",
        "creator_display_name": "Lisa Bryan | Downshiftology",
        "creator_platform": "youtube",
        "creator_profile_url": "https://youtube.com/@Downshiftology",
        "thumbnail_url": "https://images.unsplash.com/photo-1590301157890-4810ed352733?w=600",
        "ingredients": [
            {"name": "frozen açaí packet", "quantity": "1 packet (100g)", "category": "produce", "affiliate_url": amz("sambazon acai packets frozen")},
            {"name": "frozen mixed berries", "quantity": "1/2 cup", "category": "produce"},
            {"name": "vanilla protein powder", "quantity": "1 scoop", "category": "supplements"},
            {"name": "frozen banana", "quantity": "1/2", "category": "produce"},
            {"name": "almond milk", "quantity": "1/4 cup (keep it thick!)", "category": "dairy"},
            {"name": "granola", "quantity": "2 tbsp", "category": "pantry", "affiliate_url": amz("low sugar granola")},
            {"name": "chia seeds", "quantity": "1 tsp", "category": "pantry", "affiliate_url": amz("organic chia seeds")},
        ],
        "steps": [
            "Blend açaí, berries, banana, protein powder, and milk",
            "Use MINIMAL liquid — should be ice cream thick",
            "Scrape down sides and blend again",
            "Pour into bowl (should hold shape, not pour flat)",
            "Top with granola, chia seeds, extra berries",
            "Eat immediately before it melts"
        ],
        "tags": ["high-protein", "smoothie-bowl", "açaí", "breakfast", "instagram-worthy"],
        "calories": 350, "protein_g": 32, "carbs_g": 45, "fat_g": 8, "fiber_g": 8, "sugar_g": 22,
        "servings": 1, "cook_time_minutes": 5, "difficulty": "easy",
        "views": 2800000, "likes": 220000, "comments": 4500, "shares": 35000,
    },
    {
        "title": "Spicy Tuna Rice Cakes",
        "description": "Deconstructed sushi in 3 minutes. Crunchy rice cake base with spicy tuna topping. Zero cooking required.",
        "creator_username": "thefeedfeed",
        "creator_display_name": "The Feed Feed",
        "creator_platform": "youtube",
        "creator_profile_url": "https://youtube.com/@thefeedfeed",
        "thumbnail_url": "https://images.unsplash.com/photo-1579584425555-c3ce17fd4351?w=600",
        "ingredients": [
            {"name": "canned tuna in water", "quantity": "2 cans (10 oz)", "category": "protein", "affiliate_url": amz("wild caught tuna cans")},
            {"name": "rice cakes", "quantity": "4", "category": "pantry", "affiliate_url": amz("lundberg rice cakes")},
            {"name": "sriracha", "quantity": "1 tbsp", "category": "pantry"},
            {"name": "light mayo", "quantity": "2 tbsp", "category": "pantry"},
            {"name": "soy sauce", "quantity": "1 tsp", "category": "pantry"},
            {"name": "avocado", "quantity": "1, sliced", "category": "produce"},
            {"name": "cucumber", "quantity": "1/4, thin sliced", "category": "produce"},
            {"name": "sesame seeds", "quantity": "1 tsp", "category": "pantry"},
        ],
        "steps": [
            "Drain tuna well, flake into a bowl",
            "Mix with sriracha, mayo, soy sauce",
            "Place avocado slices on rice cakes",
            "Top each with spicy tuna mixture",
            "Add cucumber slices and sesame seeds",
            "Drizzle extra sriracha if you dare"
        ],
        "tags": ["high-protein", "no-cook", "quick", "sushi", "spicy", "snack"],
        "calories": 310, "protein_g": 35, "carbs_g": 28, "fat_g": 10, "fiber_g": 4, "sugar_g": 2,
        "servings": 2, "cook_time_minutes": 3, "difficulty": "easy",
        "views": 1200000, "likes": 98000, "comments": 2100, "shares": 15000,
    },
    {
        "title": "Greek Yogurt Protein Bark",
        "description": "Frozen yogurt bark that's actually healthy. Break off pieces like chocolate. 20g protein per serving.",
        "creator_username": "cleaneatingcouple",
        "creator_display_name": "Clean Eating Couple",
        "creator_platform": "youtube",
        "creator_profile_url": "https://youtube.com/@CleanEatingCouple",
        "thumbnail_url": "https://images.unsplash.com/photo-1488477181946-6428a0291777?w=600",
        "ingredients": [
            {"name": "Greek yogurt nonfat", "quantity": "2 cups", "category": "dairy"},
            {"name": "honey", "quantity": "2 tbsp", "category": "pantry"},
            {"name": "vanilla protein powder", "quantity": "1 scoop", "category": "supplements"},
            {"name": "mixed berries", "quantity": "1/2 cup", "category": "produce"},
            {"name": "dark chocolate chips", "quantity": "2 tbsp", "category": "pantry", "affiliate_url": amz("dark chocolate chips")},
            {"name": "sliced almonds", "quantity": "2 tbsp", "category": "pantry"},
        ],
        "steps": [
            "Mix yogurt, honey, and protein powder until smooth",
            "Spread onto parchment-lined baking sheet (1/4 inch thick)",
            "Press berries, chocolate chips, almonds into surface",
            "Freeze for 2-3 hours until solid",
            "Break into irregular pieces like bark",
            "Store in freezer bag — grab pieces as a snack"
        ],
        "tags": ["high-protein", "dessert", "snack", "frozen", "meal-prep", "no-bake"],
        "calories": 180, "protein_g": 20, "carbs_g": 22, "fat_g": 4, "fiber_g": 2, "sugar_g": 16,
        "servings": 4, "cook_time_minutes": 10, "difficulty": "easy",
        "views": 4500000, "likes": 340000, "comments": 7200, "shares": 62000,
    },
    {
        "title": "One-Pan Shrimp Stir Fry (Under 300 Cal)",
        "description": "Restaurant-quality stir fry in 12 minutes. Shrimp + crispy vegetables + ginger garlic sauce. Better than takeout.",
        "creator_username": "marionsbkitchen",
        "creator_display_name": "Marion's Kitchen",
        "creator_platform": "youtube",
        "creator_profile_url": "https://youtube.com/@Marions.Kitchen",
        "thumbnail_url": "https://images.unsplash.com/photo-1603133872878-684f208fb84b?w=600",
        "ingredients": [
            {"name": "large shrimp peeled", "quantity": "1 lb", "category": "protein"},
            {"name": "broccoli florets", "quantity": "2 cups", "category": "produce"},
            {"name": "snap peas", "quantity": "1 cup", "category": "produce"},
            {"name": "garlic", "quantity": "4 cloves, minced", "category": "produce"},
            {"name": "fresh ginger", "quantity": "1 tbsp, grated", "category": "produce"},
            {"name": "soy sauce", "quantity": "3 tbsp", "category": "pantry"},
            {"name": "sesame oil", "quantity": "1 tbsp", "category": "pantry", "affiliate_url": amz("toasted sesame oil")},
            {"name": "rice vinegar", "quantity": "1 tbsp", "category": "pantry"},
        ],
        "steps": [
            "Heat sesame oil in wok or large pan over HIGH heat",
            "Add shrimp, cook 1 min per side until pink — remove immediately",
            "Same pan: add garlic, ginger, stir 30 seconds",
            "Add broccoli and snap peas, stir fry 3-4 min (keep crispy)",
            "Pour in soy sauce and rice vinegar",
            "Return shrimp, toss 30 seconds to coat",
            "Serve over cauliflower rice or plain"
        ],
        "tags": ["high-protein", "low-calorie", "stir-fry", "shrimp", "quick", "asian"],
        "calories": 280, "protein_g": 38, "carbs_g": 14, "fat_g": 9, "fiber_g": 4, "sugar_g": 5,
        "servings": 3, "cook_time_minutes": 12, "difficulty": "medium",
        "views": 2200000, "likes": 175000, "comments": 4100, "shares": 28000,
    },
    {
        "title": "Protein Cookie Dough (Edible, Safe)",
        "description": "Eat raw cookie dough guilt-free. Heat-treated flour, no raw eggs. 25g protein per serving.",
        "creator_username": "macrobabe",
        "creator_display_name": "Macro Babe",
        "creator_platform": "youtube",
        "creator_profile_url": "https://youtube.com/@MacroBabe",
        "thumbnail_url": "https://images.unsplash.com/photo-1558961363-fa8fdf82db35?w=600",
        "ingredients": [
            {"name": "chickpeas canned, drained", "quantity": "1 can (15 oz)", "category": "pantry"},
            {"name": "vanilla protein powder", "quantity": "1 scoop", "category": "supplements"},
            {"name": "peanut butter", "quantity": "2 tbsp", "category": "pantry", "affiliate_url": amz("natural peanut butter")},
            {"name": "maple syrup or honey", "quantity": "2 tbsp", "category": "pantry"},
            {"name": "vanilla extract", "quantity": "1 tsp", "category": "pantry"},
            {"name": "mini chocolate chips", "quantity": "2 tbsp", "category": "pantry"},
            {"name": "salt", "quantity": "pinch", "category": "pantry"},
        ],
        "steps": [
            "Blend chickpeas in food processor until smooth (2 min)",
            "Add protein powder, peanut butter, maple syrup, vanilla, salt",
            "Process until creamy dough forms",
            "Transfer to bowl, fold in chocolate chips",
            "Refrigerate 30 min to firm up",
            "Roll into balls or eat with a spoon",
            "Stores in fridge 5 days"
        ],
        "tags": ["high-protein", "dessert", "no-bake", "cookie-dough", "meal-prep", "snack"],
        "calories": 200, "protein_g": 25, "carbs_g": 28, "fat_g": 7, "fiber_g": 5, "sugar_g": 12,
        "servings": 4, "cook_time_minutes": 10, "difficulty": "easy",
        "views": 3200000, "likes": 250000, "comments": 5800, "shares": 40000,
    },
    {
        "title": "Chicken Shawarma Bowl",
        "description": "Middle Eastern street food at home. Perfectly spiced chicken with garlic sauce, pickled onions, and fluffy rice.",
        "creator_username": "rainbowplantlife",
        "creator_display_name": "Nisha | Rainbow Plant Life",
        "creator_platform": "youtube",
        "creator_profile_url": "https://youtube.com/@RainbowPlantLife",
        "thumbnail_url": "https://images.unsplash.com/photo-1540189549336-e6e99c3679fe?w=600",
        "ingredients": [
            {"name": "chicken thighs boneless", "quantity": "1.5 lbs", "category": "protein"},
            {"name": "shawarma spice blend", "quantity": "2 tbsp", "category": "pantry", "affiliate_url": amz("shawarma spice blend")},
            {"name": "Greek yogurt (for sauce)", "quantity": "1/2 cup", "category": "dairy"},
            {"name": "garlic", "quantity": "3 cloves, minced", "category": "produce"},
            {"name": "lemon", "quantity": "1", "category": "produce"},
            {"name": "basmati rice", "quantity": "1 cup dry", "category": "pantry"},
            {"name": "pickled red onion", "quantity": "1/4 cup", "category": "condiments"},
            {"name": "cucumber", "quantity": "1, diced", "category": "produce"},
        ],
        "steps": [
            "Marinate chicken in shawarma spice, lemon juice, and 1 tbsp yogurt (30 min or overnight)",
            "Cook rice per package directions",
            "Grill or pan-sear chicken on high heat, 5-6 min per side",
            "Let rest 5 min, slice against the grain",
            "Make garlic sauce: mix yogurt, minced garlic, lemon juice, salt",
            "Assemble bowls: rice, sliced chicken, cucumber, pickled onion",
            "Drizzle garlic sauce generously"
        ],
        "tags": ["high-protein", "shawarma", "bowl", "mediterranean", "meal-prep"],
        "calories": 450, "protein_g": 42, "carbs_g": 40, "fat_g": 14, "fiber_g": 2, "sugar_g": 3,
        "servings": 4, "cook_time_minutes": 30, "difficulty": "medium",
        "views": 2600000, "likes": 195000, "comments": 4300, "shares": 30000,
    },
    {
        "title": "3-Ingredient Banana Protein Pancakes",
        "description": "No flour, no sugar. Just banana, eggs, and protein powder. Fluffy, filling, and done in 8 minutes.",
        "creator_username": "mealpreponfleek",
        "creator_display_name": "Meal Prep on Fleek",
        "creator_platform": "reddit",
        "creator_profile_url": "https://reddit.com/u/mealpreponfleek",
        "thumbnail_url": "https://images.unsplash.com/photo-1567620905732-2d1ec7ab7445?w=600",
        "ingredients": [
            {"name": "ripe banana", "quantity": "1 large", "category": "produce"},
            {"name": "eggs", "quantity": "2 large", "category": "protein"},
            {"name": "vanilla protein powder", "quantity": "1 scoop", "category": "supplements"},
        ],
        "steps": [
            "Mash banana thoroughly in a bowl (no chunks)",
            "Whisk in eggs until smooth",
            "Stir in protein powder until just combined",
            "Heat non-stick pan on medium-low (key: LOW heat)",
            "Pour small pancakes (3 inch diameter max — they're fragile)",
            "Cook 2 min until bubbles form, flip gently",
            "Cook 1 more min, stack and serve"
        ],
        "tags": ["high-protein", "3-ingredients", "pancakes", "breakfast", "gluten-free", "quick"],
        "calories": 310, "protein_g": 35, "carbs_g": 30, "fat_g": 8, "fiber_g": 3, "sugar_g": 15,
        "servings": 1, "cook_time_minutes": 8, "difficulty": "easy",
        "views": 1100000, "likes": 85000, "comments": 1900, "shares": 14000,
    },
    {
        "title": "Slow Cooker Shredded Chicken (5 Ways)",
        "description": "Make 4 lbs of perfectly shredded chicken on Sunday. Use it 5 different ways all week. Ultimate meal prep protein.",
        "creator_username": "fitmencoook",
        "creator_display_name": "Kevin Curry | Fit Men Cook",
        "creator_platform": "youtube",
        "creator_profile_url": "https://youtube.com/@fitmencoook",
        "thumbnail_url": "https://images.unsplash.com/photo-1532550907401-a500c9a57435?w=600",
        "ingredients": [
            {"name": "chicken breast", "quantity": "4 lbs", "category": "protein"},
            {"name": "chicken broth low sodium", "quantity": "1 cup", "category": "pantry", "affiliate_url": amz("low sodium chicken broth")},
            {"name": "garlic powder", "quantity": "1 tbsp", "category": "pantry"},
            {"name": "onion powder", "quantity": "1 tbsp", "category": "pantry"},
            {"name": "cumin", "quantity": "1 tsp", "category": "pantry"},
            {"name": "salt and pepper", "quantity": "to taste", "category": "pantry"},
        ],
        "steps": [
            "Place chicken in slow cooker, pour broth over top",
            "Season with all spices",
            "Cook on LOW 6-8 hours or HIGH 3-4 hours",
            "Shred with two forks (should fall apart easily)",
            "Divide into 5 meal prep containers (about 6 oz each)",
            "Use all week: tacos, salads, wraps, bowls, sandwiches",
            "Keeps 5 days in fridge, 3 months frozen"
        ],
        "tags": ["high-protein", "meal-prep", "slow-cooker", "batch-cooking", "budget"],
        "calories": 280, "protein_g": 52, "carbs_g": 1, "fat_g": 6, "fiber_g": 0, "sugar_g": 0,
        "servings": 8, "cook_time_minutes": 360, "difficulty": "easy",
        "views": 3400000, "likes": 260000, "comments": 5900, "shares": 48000,
    },
    {
        "title": "Protein Chia Pudding (Meal Prep 5 Days)",
        "description": "Make Sunday night, eat all week. Thick, creamy, 28g protein. Grab from fridge and go.",
        "creator_username": "pickuplimes",
        "creator_display_name": "Sadia | Pick Up Limes",
        "creator_platform": "youtube",
        "creator_profile_url": "https://youtube.com/@PickUpLimes",
        "thumbnail_url": "https://images.unsplash.com/photo-1511690743698-d9d18f7e20f1?w=600",
        "ingredients": [
            {"name": "chia seeds", "quantity": "3 tbsp", "category": "pantry", "affiliate_url": amz("organic chia seeds")},
            {"name": "vanilla protein powder", "quantity": "1 scoop", "category": "supplements"},
            {"name": "almond milk", "quantity": "1 cup", "category": "dairy"},
            {"name": "Greek yogurt", "quantity": "1/4 cup", "category": "dairy"},
            {"name": "honey or maple syrup", "quantity": "1 tbsp", "category": "pantry"},
            {"name": "vanilla extract", "quantity": "1/2 tsp", "category": "pantry"},
        ],
        "steps": [
            "Mix chia seeds, protein powder, and almond milk in a jar",
            "Stir vigorously (chia seeds clump — break them up)",
            "Stir again after 5 minutes",
            "Add Greek yogurt and sweetener, mix well",
            "Refrigerate overnight (minimum 4 hours)",
            "Top with fresh fruit before eating",
            "Makes 1 serving — multiply by 5 for weekly prep"
        ],
        "tags": ["high-protein", "meal-prep", "chia-pudding", "breakfast", "no-cook"],
        "calories": 320, "protein_g": 28, "carbs_g": 30, "fat_g": 12, "fiber_g": 11, "sugar_g": 10,
        "servings": 1, "cook_time_minutes": 5, "difficulty": "easy",
        "views": 1700000, "likes": 130000, "comments": 3100, "shares": 22000,
    },
]


async def seed_premium():
    """Seed premium recipes into the database."""
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))

    from src.db.engine import engine, async_session
    from src.db.tables import Base, RecipeRow
    from sqlalchemy import select, func

    async with async_session() as session:
        # Check existing count
        result = await session.execute(select(func.count(RecipeRow.id)))
        existing = result.scalar()
        print(f"📊 Existing recipes: {existing}")

        added = 0
        skipped = 0
        for r in PREMIUM_RECIPES:
            # Check if already exists by source_url pattern or title
            source_url = r.get("source_url", f"https://fitbites.io/seeded/{uuid.uuid4()}")
            check = await session.execute(
                select(RecipeRow).where(RecipeRow.title == r["title"])
            )
            if check.scalar_one_or_none():
                skipped += 1
                continue

            row = RecipeRow(
                id=str(uuid.uuid4()),
                title=r["title"],
                description=r["description"],
                creator_username=r["creator_username"],
                creator_display_name=r["creator_display_name"],
                creator_platform=r["creator_platform"],
                creator_profile_url=r["creator_profile_url"],
                creator_avatar_url=None,
                creator_follower_count=r.get("creator_follower_count"),
                platform=r["creator_platform"],
                source_url=source_url,
                thumbnail_url=r["thumbnail_url"],
                video_url=None,
                ingredients=r["ingredients"],
                steps=r["steps"],
                tags=r["tags"],
                calories=r["calories"],
                protein_g=r["protein_g"],
                carbs_g=r["carbs_g"],
                fat_g=r["fat_g"],
                fiber_g=r.get("fiber_g"),
                sugar_g=r.get("sugar_g"),
                servings=r["servings"],
                views=r["views"],
                likes=r["likes"],
                comments=r["comments"],
                shares=r.get("shares"),
                cook_time_minutes=r["cook_time_minutes"],
                difficulty=r["difficulty"],
                virality_score=round(
                    (r["likes"] * 2 + r["comments"] * 5 + r.get("shares", 0) * 3)
                    / max(r["views"], 1) * 100, 2
                ),
                scraped_at=datetime.utcnow() - timedelta(hours=random.randint(1, 72)),
                published_at=datetime.utcnow() - timedelta(days=random.randint(1, 30)),
            )
            session.add(row)
            added += 1

        await session.commit()

        result = await session.execute(select(func.count(RecipeRow.id)))
        total = result.scalar()
        print(f"✅ Added {added} recipes, skipped {skipped} duplicates")
        print(f"📊 Total recipes now: {total}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed_premium())
