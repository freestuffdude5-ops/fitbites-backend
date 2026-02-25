#!/usr/bin/env python3
"""Seed recipes table with realistic FitBites recipe data."""
import asyncio
import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from src.db.engine import engine, async_session
from src.db.tables import Base

RECIPES = [
    {
        "id": "r001", "title": "High-Protein Greek Yogurt Bowl",
        "description": "Creamy Greek yogurt topped with berries, granola, and a drizzle of honey. 35g protein per serving.",
        "creator_username": "fitmeals_mike", "creator_display_name": "Mike's Fit Meals",
        "creator_platform": "youtube", "creator_profile_url": "https://youtube.com/@fitmeals_mike",
        "platform": "youtube", "source_url": "https://youtube.com/watch?v=abc123",
        "ingredients": [
            {"name": "greek yogurt", "amount": "1 cup", "calories": 130},
            {"name": "mixed berries", "amount": "1/2 cup", "calories": 40},
            {"name": "granola", "amount": "1/4 cup", "calories": 120},
            {"name": "honey", "amount": "1 tbsp", "calories": 60},
            {"name": "protein powder", "amount": "1 scoop", "calories": 120},
        ],
        "steps": ["Add yogurt to bowl", "Top with berries and granola", "Mix in protein powder", "Drizzle honey"],
        "tags": ["high-protein", "breakfast", "quick", "vegetarian"],
        "calories": 470, "protein_g": 35, "carbs_g": 52, "fat_g": 12, "fiber_g": 4,
        "views": 245000, "likes": 12400, "comments": 890, "cook_time_minutes": 5,
        "difficulty": "easy", "virality_score": 92.5,
    },
    {
        "id": "r002", "title": "Chicken Breast Meal Prep (4 Ways)",
        "description": "Four different flavors of perfectly cooked chicken breast for the whole week. Under 250 calories each.",
        "creator_username": "prepking", "creator_display_name": "The Prep King",
        "creator_platform": "youtube", "creator_profile_url": "https://youtube.com/@prepking",
        "platform": "youtube", "source_url": "https://youtube.com/watch?v=def456",
        "ingredients": [
            {"name": "chicken breast", "amount": "4 lbs", "calories": 440},
            {"name": "olive oil", "amount": "2 tbsp", "calories": 240},
            {"name": "garlic powder", "amount": "2 tsp", "calories": 10},
            {"name": "paprika", "amount": "2 tsp", "calories": 10},
            {"name": "italian seasoning", "amount": "2 tsp", "calories": 5},
        ],
        "steps": ["Season chicken 4 ways", "Bake at 400°F for 22 min", "Slice and portion", "Store in containers"],
        "tags": ["high-protein", "meal-prep", "low-carb", "budget"],
        "calories": 220, "protein_g": 42, "carbs_g": 2, "fat_g": 5, "fiber_g": 0,
        "views": 890000, "likes": 45000, "comments": 3200, "cook_time_minutes": 30,
        "difficulty": "easy", "virality_score": 97.8,
    },
    {
        "id": "r003", "title": "Protein Pancakes - 40g Per Serving",
        "description": "Fluffy pancakes with 40g protein. Better than IHOP, fraction of the calories.",
        "creator_username": "gains_kitchen", "creator_display_name": "Gains Kitchen",
        "creator_platform": "reddit", "creator_profile_url": "https://reddit.com/u/gains_kitchen",
        "platform": "reddit", "source_url": "https://reddit.com/r/fitmeals/comments/xyz",
        "ingredients": [
            {"name": "protein powder", "amount": "2 scoops", "calories": 240},
            {"name": "egg whites", "amount": "1/2 cup", "calories": 60},
            {"name": "oats", "amount": "1/3 cup", "calories": 100},
            {"name": "banana", "amount": "1/2", "calories": 50},
            {"name": "baking powder", "amount": "1 tsp", "calories": 0},
        ],
        "steps": ["Blend all ingredients", "Cook on medium heat", "Flip when bubbles form", "Top with berries"],
        "tags": ["high-protein", "breakfast", "vegetarian"],
        "calories": 450, "protein_g": 40, "carbs_g": 45, "fat_g": 8, "fiber_g": 5,
        "views": 156000, "likes": 8900, "comments": 567, "cook_time_minutes": 15,
        "difficulty": "easy", "virality_score": 88.2,
    },
    {
        "id": "r004", "title": "Anabolic French Toast",
        "description": "The viral anabolic French toast recipe. 45g protein, tastes like dessert.",
        "creator_username": "remington_james", "creator_display_name": "Remington James",
        "creator_platform": "youtube", "creator_profile_url": "https://youtube.com/@remington_james",
        "platform": "youtube", "source_url": "https://youtube.com/watch?v=ghi789",
        "ingredients": [
            {"name": "egg whites", "amount": "1 cup", "calories": 120},
            {"name": "protein powder", "amount": "1.5 scoops", "calories": 180},
            {"name": "ezekiel bread", "amount": "4 slices", "calories": 320},
            {"name": "cinnamon", "amount": "1 tsp", "calories": 5},
            {"name": "sugar-free syrup", "amount": "2 tbsp", "calories": 10},
        ],
        "steps": ["Mix egg whites, protein, cinnamon", "Dip bread slices", "Cook on griddle 3 min/side", "Top with syrup"],
        "tags": ["high-protein", "breakfast", "anabolic"],
        "calories": 635, "protein_g": 45, "carbs_g": 65, "fat_g": 8, "fiber_g": 8,
        "views": 2100000, "likes": 98000, "comments": 7800, "cook_time_minutes": 15,
        "difficulty": "easy", "virality_score": 99.1,
    },
    {
        "id": "r005", "title": "Low-Cal Cauliflower Mac & Cheese",
        "description": "All the comfort, 1/3 the calories. You won't believe it's cauliflower.",
        "creator_username": "lowcal_lucy", "creator_display_name": "Low Cal Lucy",
        "creator_platform": "reddit", "creator_profile_url": "https://reddit.com/u/lowcal_lucy",
        "platform": "reddit", "source_url": "https://reddit.com/r/1200isplenty/comments/abc",
        "ingredients": [
            {"name": "cauliflower", "amount": "1 head", "calories": 150},
            {"name": "reduced fat cheddar", "amount": "1 cup", "calories": 280},
            {"name": "cream cheese", "amount": "2 oz", "calories": 100},
            {"name": "garlic", "amount": "3 cloves", "calories": 12},
            {"name": "mustard powder", "amount": "1 tsp", "calories": 5},
        ],
        "steps": ["Steam cauliflower until tender", "Make cheese sauce", "Combine", "Bake 15 min at 375°F"],
        "tags": ["low-calorie", "comfort-food", "vegetarian", "keto"],
        "calories": 280, "protein_g": 18, "carbs_g": 15, "fat_g": 16, "fiber_g": 6,
        "views": 320000, "likes": 15600, "comments": 1200, "cook_time_minutes": 25,
        "difficulty": "medium", "virality_score": 91.3,
    },
]

# Add more to get to 20
for i in range(6, 21):
    rid = f"r{i:03d}"
    RECIPES.append({
        "id": rid,
        "title": f"Recipe {i} - Healthy Meal",
        "description": f"A delicious healthy recipe #{i}",
        "creator_username": f"chef_{i}", "creator_display_name": f"Chef {i}",
        "creator_platform": "youtube", "creator_profile_url": f"https://youtube.com/@chef{i}",
        "platform": "youtube", "source_url": f"https://youtube.com/watch?v=recipe{i}",
        "ingredients": [{"name": "ingredient", "amount": "1 cup", "calories": 100}] * 4,
        "steps": ["Step 1", "Step 2", "Step 3"],
        "tags": ["high-protein", "healthy"],
        "calories": 350 + i * 10, "protein_g": 25 + i, "carbs_g": 30, "fat_g": 10, "fiber_g": 4,
        "views": 50000 + i * 10000, "likes": 2000 + i * 500, "comments": 100 + i * 50,
        "cook_time_minutes": 15 + i, "difficulty": "easy", "virality_score": 70 + i,
    })


async def seed():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        # Clear
        await session.execute(text("DELETE FROM recipes"))
        await session.commit()

        for r in RECIPES:
            await session.execute(
                text("""
                    INSERT INTO recipes (id, title, description, creator_username, creator_display_name,
                        creator_platform, creator_profile_url, platform, source_url,
                        ingredients, steps, tags, calories, protein_g, carbs_g, fat_g, fiber_g,
                        views, likes, comments, cook_time_minutes, difficulty, virality_score)
                    VALUES (:id, :title, :description, :creator_username, :creator_display_name,
                        :creator_platform, :creator_profile_url, :platform, :source_url,
                        :ingredients, :steps, :tags, :calories, :protein_g, :carbs_g, :fat_g, :fiber_g,
                        :views, :likes, :comments, :cook_time_minutes, :difficulty, :virality_score)
                """),
                {
                    **{k: v for k, v in r.items() if k not in ("ingredients", "steps", "tags")},
                    "ingredients": json.dumps(r["ingredients"]),
                    "steps": json.dumps(r["steps"]),
                    "tags": json.dumps(r["tags"]),
                },
            )
        await session.commit()
        print(f"✅ Seeded {len(RECIPES)} recipes")


if __name__ == "__main__":
    asyncio.run(seed())
