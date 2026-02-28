"""Recipe data models — core schema for FitBites."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class Platform(str, Enum):
    TIKTOK = "tiktok"
    INSTAGRAM = "instagram"
    YOUTUBE = "youtube"
    REDDIT = "reddit"


class NutritionInfo(BaseModel):
    calories: int
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: Optional[float] = None
    sugar_g: Optional[float] = None
    servings: int = 1


class Ingredient(BaseModel):
    name: str
    quantity: Optional[str] = None  # e.g. "2 cups", "200g" - optional for compatibility
    affiliate_url: Optional[str] = None
    amazon_asin: Optional[str] = None
    category: Optional[str] = None  # "protein", "dairy", "produce", etc.


class Creator(BaseModel):
    username: str
    display_name: Optional[str] = None
    platform: Platform
    profile_url: str
    avatar_url: Optional[str] = None
    follower_count: Optional[int] = None


class Recipe(BaseModel):
    id: Optional[str] = None
    title: str
    description: Optional[str] = None
    creator: Creator
    platform: Platform
    source_url: str
    thumbnail_url: Optional[str] = None
    video_url: Optional[str] = None  # link to original video, not hosted

    ingredients: list[Ingredient] = []
    steps: list[str] = []
    nutrition: Optional[NutritionInfo] = None

    # Engagement metrics from source platform
    views: Optional[int] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    shares: Optional[int] = None

    # FitBites metadata
    tags: list[str] = []  # "high-protein", "low-cal", "keto", "vegan", etc.
    cook_time_minutes: Optional[int] = None
    difficulty: Optional[str] = None  # "easy", "medium", "hard"
    virality_score: Optional[float] = None  # computed engagement metric

    scraped_at: datetime = Field(default_factory=lambda: datetime.now(tz=__import__('datetime').timezone.utc))
    published_at: Optional[datetime] = None

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "title": "3-Ingredient Protein Ice Cream",
                    "creator": {
                        "username": "broccyourbody",
                        "platform": "tiktok",
                        "profile_url": "https://tiktok.com/@broccyourbody",
                    },
                    "platform": "tiktok",
                    "source_url": "https://tiktok.com/@broccyourbody/video/123",
                    "ingredients": [
                        {"name": "frozen banana", "quantity": "2 medium"},
                        {"name": "protein powder", "quantity": "1 scoop"},
                        {"name": "almond milk", "quantity": "1/4 cup"},
                    ],
                    "nutrition": {
                        "calories": 320,
                        "protein_g": 42,
                        "carbs_g": 38,
                        "fat_g": 4,
                        "servings": 1,
                    },
                    "views": 2300000,
                    "tags": ["high-protein", "dessert", "quick"],
                    "cook_time_minutes": 5,
                }
            ]
        }
    )
