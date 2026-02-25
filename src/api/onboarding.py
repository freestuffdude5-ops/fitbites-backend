"""Onboarding & Dietary Preferences API — premium personalization.

First-run experience that sets up the user's profile for personalized feeds:
- Dietary goals (lose weight, build muscle, maintain, eat healthier)
- Dietary restrictions (vegetarian, vegan, keto, gluten-free, dairy-free, etc.)
- Macro targets (auto-calculated or manual)
- Cooking skill level
- Time availability (how long they want to spend cooking)
- Allergens

This data drives the recommendation engine, search defaults, and meal planning.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_session
from src.db.user_tables import UserRow
from src.auth import require_user

router = APIRouter(prefix="/api/v1", tags=["onboarding"])


# ── Schemas ──────────────────────────────────────────────────────────────

class DietaryGoal(str, Enum):
    LOSE_WEIGHT = "lose_weight"
    BUILD_MUSCLE = "build_muscle"
    MAINTAIN = "maintain"
    EAT_HEALTHIER = "eat_healthier"

class SkillLevel(str, Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"

class OnboardingRequest(BaseModel):
    """Full onboarding profile — all fields optional for partial updates."""
    goal: DietaryGoal | None = None
    dietary_restrictions: list[str] | None = Field(
        None, max_length=20,
        description="e.g. ['vegetarian', 'gluten-free', 'dairy-free']"
    )
    allergens: list[str] | None = Field(
        None, max_length=20,
        description="e.g. ['peanuts', 'shellfish', 'soy']"
    )
    skill_level: SkillLevel | None = None
    max_cook_time_minutes: int | None = Field(None, ge=5, le=240)
    target_calories: int | None = Field(None, ge=800, le=5000)
    target_protein_g: int | None = Field(None, ge=20, le=500)
    target_carbs_g: int | None = Field(None, ge=0, le=800)
    target_fat_g: int | None = Field(None, ge=0, le=400)
    servings_per_meal: int | None = Field(None, ge=1, le=10)
    meals_per_day: int | None = Field(None, ge=1, le=8)

class QuickSetupRequest(BaseModel):
    """Simplified onboarding for users who want auto-calculated targets."""
    goal: DietaryGoal
    weight_kg: float = Field(..., ge=30, le=300)
    height_cm: float = Field(..., ge=100, le=250)
    age: int = Field(..., ge=13, le=120)
    sex: str = Field(..., pattern="^(male|female)$")
    activity_level: str = Field(
        ..., pattern="^(sedentary|light|moderate|active|very_active)$"
    )
    dietary_restrictions: list[str] = Field(default_factory=list)


# ── Macro Calculator ────────────────────────────────────────────────────

_ACTIVITY_MULTIPLIERS = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "very_active": 1.9,
}

def calculate_targets(
    weight_kg: float, height_cm: float, age: int,
    sex: str, activity_level: str, goal: DietaryGoal,
) -> dict:
    """Calculate TDEE and macro targets using Mifflin-St Jeor equation."""
    # BMR
    if sex == "male":
        bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age + 5
    else:
        bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age - 161

    tdee = bmr * _ACTIVITY_MULTIPLIERS[activity_level]

    # Adjust for goal
    if goal == DietaryGoal.LOSE_WEIGHT:
        calories = int(tdee * 0.8)  # 20% deficit
        protein_g = int(weight_kg * 2.0)  # High protein for muscle preservation
        fat_g = int(calories * 0.25 / 9)
        carbs_g = int((calories - protein_g * 4 - fat_g * 9) / 4)
    elif goal == DietaryGoal.BUILD_MUSCLE:
        calories = int(tdee * 1.1)  # 10% surplus
        protein_g = int(weight_kg * 2.2)
        fat_g = int(calories * 0.25 / 9)
        carbs_g = int((calories - protein_g * 4 - fat_g * 9) / 4)
    elif goal == DietaryGoal.EAT_HEALTHIER:
        calories = int(tdee)
        protein_g = int(weight_kg * 1.6)
        fat_g = int(calories * 0.30 / 9)
        carbs_g = int((calories - protein_g * 4 - fat_g * 9) / 4)
    else:  # maintain
        calories = int(tdee)
        protein_g = int(weight_kg * 1.6)
        fat_g = int(calories * 0.30 / 9)
        carbs_g = int((calories - protein_g * 4 - fat_g * 9) / 4)

    return {
        "target_calories": max(calories, 1200),
        "target_protein_g": protein_g,
        "target_carbs_g": max(carbs_g, 50),
        "target_fat_g": max(fat_g, 30),
        "tdee": int(tdee),
        "bmr": int(bmr),
    }


# ── Routes ───────────────────────────────────────────────────────────────

@router.post("/onboarding/profile")
async def set_onboarding_profile(
    body: OnboardingRequest,
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Set or update dietary preferences. Partial updates supported."""
    prefs = dict(user.preferences or {})

    for field in [
        "goal", "dietary_restrictions", "allergens", "skill_level",
        "max_cook_time_minutes", "target_calories", "target_protein_g",
        "target_carbs_g", "target_fat_g", "servings_per_meal", "meals_per_day",
    ]:
        value = getattr(body, field, None)
        if value is not None:
            prefs[field] = value.value if isinstance(value, Enum) else value

    prefs["onboarding_completed"] = True
    prefs["onboarding_updated_at"] = datetime.now(timezone.utc).isoformat()

    user.preferences = prefs
    await session.commit()
    await session.refresh(user)

    return {
        "message": "Profile updated",
        "preferences": user.preferences,
    }


@router.post("/onboarding/quick-setup")
async def quick_setup(
    body: QuickSetupRequest,
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Auto-calculate macro targets from body stats + goal."""
    targets = calculate_targets(
        body.weight_kg, body.height_cm, body.age,
        body.sex, body.activity_level, body.goal,
    )

    prefs = dict(user.preferences or {})
    prefs.update({
        "goal": body.goal.value,
        "dietary_restrictions": body.dietary_restrictions,
        **targets,
        "onboarding_completed": True,
        "onboarding_updated_at": datetime.now(timezone.utc).isoformat(),
        "body_stats": {
            "weight_kg": body.weight_kg,
            "height_cm": body.height_cm,
            "age": body.age,
            "sex": body.sex,
            "activity_level": body.activity_level,
        },
    })

    user.preferences = prefs
    await session.commit()
    await session.refresh(user)

    return {
        "message": "Profile set up! Your targets have been calculated.",
        "targets": targets,
        "preferences": user.preferences,
    }


@router.get("/onboarding/profile")
async def get_onboarding_profile(
    user: UserRow = Depends(require_user),
):
    """Get current dietary preferences and onboarding status."""
    prefs = user.preferences or {}
    return {
        "onboarding_completed": prefs.get("onboarding_completed", False),
        "preferences": prefs,
    }


@router.post("/onboarding/calculate-targets")
async def preview_targets(body: QuickSetupRequest):
    """Preview calculated targets without saving (no auth required).
    
    Useful for showing targets during onboarding before account creation.
    """
    targets = calculate_targets(
        body.weight_kg, body.height_cm, body.age,
        body.sex, body.activity_level, body.goal,
    )
    return {
        "targets": targets,
        "goal": body.goal.value,
    }


# ── Dietary Restriction Options ──────────────────────────────────────────

@router.get("/onboarding/options")
async def get_onboarding_options():
    """Return available dietary options for the onboarding UI.
    
    No auth required — used on the onboarding screens before/during signup.
    """
    return {
        "goals": [
            {"id": "lose_weight", "label": "Lose Weight", "emoji": "🔥", "description": "Calorie deficit with high protein"},
            {"id": "build_muscle", "label": "Build Muscle", "emoji": "💪", "description": "Calorie surplus with maximum protein"},
            {"id": "maintain", "label": "Maintain Weight", "emoji": "⚖️", "description": "Balanced macros at maintenance"},
            {"id": "eat_healthier", "label": "Eat Healthier", "emoji": "🥗", "description": "Better nutrition, balanced meals"},
        ],
        "dietary_restrictions": [
            {"id": "vegetarian", "label": "Vegetarian", "emoji": "🥬"},
            {"id": "vegan", "label": "Vegan", "emoji": "🌱"},
            {"id": "keto", "label": "Keto", "emoji": "🥑"},
            {"id": "paleo", "label": "Paleo", "emoji": "🥩"},
            {"id": "gluten_free", "label": "Gluten-Free", "emoji": "🌾"},
            {"id": "dairy_free", "label": "Dairy-Free", "emoji": "🥛"},
            {"id": "low_carb", "label": "Low Carb", "emoji": "📉"},
            {"id": "high_protein", "label": "High Protein", "emoji": "💪"},
            {"id": "whole30", "label": "Whole30", "emoji": "✅"},
            {"id": "mediterranean", "label": "Mediterranean", "emoji": "🫒"},
        ],
        "allergens": [
            {"id": "peanuts", "label": "Peanuts", "emoji": "🥜"},
            {"id": "tree_nuts", "label": "Tree Nuts", "emoji": "🌰"},
            {"id": "shellfish", "label": "Shellfish", "emoji": "🦐"},
            {"id": "fish", "label": "Fish", "emoji": "🐟"},
            {"id": "eggs", "label": "Eggs", "emoji": "🥚"},
            {"id": "soy", "label": "Soy", "emoji": "🫘"},
            {"id": "wheat", "label": "Wheat", "emoji": "🌾"},
            {"id": "milk", "label": "Milk/Dairy", "emoji": "🥛"},
            {"id": "sesame", "label": "Sesame", "emoji": "🫘"},
        ],
        "skill_levels": [
            {"id": "beginner", "label": "Beginner", "emoji": "👶", "description": "Simple recipes, basic techniques"},
            {"id": "intermediate", "label": "Intermediate", "emoji": "👨‍🍳", "description": "Comfortable in the kitchen"},
            {"id": "advanced", "label": "Advanced", "emoji": "⭐", "description": "Bring on the challenge!"},
        ],
        "activity_levels": [
            {"id": "sedentary", "label": "Sedentary", "description": "Little to no exercise"},
            {"id": "light", "label": "Light", "description": "1-3 days/week"},
            {"id": "moderate", "label": "Moderate", "description": "3-5 days/week"},
            {"id": "active", "label": "Active", "description": "6-7 days/week"},
            {"id": "very_active", "label": "Very Active", "description": "Athlete/physical job"},
        ],
    }
