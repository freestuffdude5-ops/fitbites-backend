#!/usr/bin/env python3
"""Seed the analytics_events table with realistic FitBites usage data.

Generates 30 days of synthetic but realistic user behavior:
- User acquisition curve (growing DAU)
- Realistic funnel: app_open → recipe_view → recipe_save → affiliate_click → conversion
- Platform mix (iOS 60%, Android 30%, Web 10%)
- Multiple affiliate providers with realistic conversion rates
- Diurnal patterns (more usage during meal prep hours)
"""
import asyncio
import random
import uuid
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

# Add parent to path
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.db.engine import engine, async_session
from src.db.tables import Base


# --- Config ---
DAYS = 30
BASE_DAU = 50          # Starting DAU
GROWTH_RATE = 0.08     # 8% daily growth
TOTAL_USERS = 2000     # User pool

PLATFORMS = ["ios", "android", "web"]
PLATFORM_WEIGHTS = [0.60, 0.30, 0.10]

PROVIDERS = ["amazon", "iherb", "instacart", "thrive", "hellofresh"]
PROVIDER_WEIGHTS = [0.45, 0.20, 0.15, 0.10, 0.10]

RECIPES = [
    ("r001", "High-Protein Greek Yogurt Bowl"),
    ("r002", "Chicken Breast Meal Prep (4 Ways)"),
    ("r003", "Protein Pancakes - 40g Per Serving"),
    ("r004", "Anabolic French Toast"),
    ("r005", "Low-Cal Cauliflower Mac & Cheese"),
    ("r006", "Greek Chicken Wraps (500cal)"),
    ("r007", "Cottage Cheese Ice Cream Hack"),
    ("r008", "Protein Overnight Oats"),
    ("r009", "Air Fryer Salmon + Asparagus"),
    ("r010", "Turkey Taco Lettuce Wraps"),
    ("r011", "Zero-Sugar Protein Brownie"),
    ("r012", "Egg White Veggie Omelette"),
    ("r013", "Shrimp Stir-Fry (Under 400cal)"),
    ("r014", "Baked Chicken Tenders - No Breading"),
    ("r015", "Protein Smoothie Bowl"),
    ("r016", "Zucchini Noodle Bolognese"),
    ("r017", "Tuna Stuffed Avocado"),
    ("r018", "Sweet Potato Protein Bites"),
    ("r019", "Mediterranean Chickpea Salad"),
    ("r020", "Lean Ground Turkey Burrito Bowl"),
]

INGREDIENTS = [
    "chicken breast", "greek yogurt", "protein powder", "eggs", "sweet potato",
    "avocado", "salmon", "cottage cheese", "ground turkey", "rice",
    "broccoli", "spinach", "oats", "almond milk", "peanut butter",
]

# Funnel conversion rates
FUNNEL = {
    "app_open_to_recipe_view": 0.75,    # 75% of opens lead to a view
    "recipe_view_to_save": 0.15,         # 15% save rate
    "recipe_view_to_affiliate_click": 0.08,  # 8% click affiliate
    "affiliate_click_to_conversion": 0.025,  # 2.5% convert
}

# Diurnal pattern (hour → relative activity, peaks at 7am, 12pm, 6pm)
HOUR_WEIGHTS = {
    0: 0.05, 1: 0.02, 2: 0.01, 3: 0.01, 4: 0.01, 5: 0.03,
    6: 0.08, 7: 0.12, 8: 0.10, 9: 0.06, 10: 0.05, 11: 0.08,
    12: 0.12, 13: 0.08, 14: 0.05, 15: 0.04, 16: 0.06, 17: 0.10,
    18: 0.14, 19: 0.10, 20: 0.08, 21: 0.06, 22: 0.04, 23: 0.03,
}


def weighted_hour() -> int:
    hours = list(HOUR_WEIGHTS.keys())
    weights = list(HOUR_WEIGHTS.values())
    return random.choices(hours, weights=weights, k=1)[0]


def make_ts(day_offset: int) -> datetime:
    """Generate a realistic timestamp for a given day offset from now."""
    base = datetime.now(timezone.utc) - timedelta(days=DAYS - day_offset)
    hour = weighted_hour()
    minute = random.randint(0, 59)
    second = random.randint(0, 59)
    return base.replace(hour=hour, minute=minute, second=second, microsecond=0)


async def seed():
    # Create tables
    import src.analytics.tables
    import src.db.user_tables
    import src.db.meal_plan_tables
    import src.db.review_tables
    import src.db.subscription_tables
    import src.db.social_tables
    import src.db.comment_tables
    import src.db.recently_viewed_tables
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Clear existing analytics
    async with async_session() as session:
        await session.execute(text("DELETE FROM analytics_events"))
        await session.commit()
        print("Cleared existing analytics events")

    # Generate user pool
    users = [str(uuid.uuid4()) for _ in range(TOTAL_USERS)]
    app_versions = ["1.0.0", "1.0.1", "1.1.0", "1.2.0"]

    events = []
    total_opens = 0
    total_views = 0
    total_saves = 0
    total_clicks = 0
    total_conversions = 0

    for day in range(DAYS):
        # Growing DAU
        dau = int(BASE_DAU * (1 + GROWTH_RATE) ** day)
        daily_users = random.sample(users[:min(dau * 3, TOTAL_USERS)], min(dau, TOTAL_USERS))

        for user_id in daily_users:
            platform = random.choices(PLATFORMS, weights=PLATFORM_WEIGHTS, k=1)[0]
            session_id = str(uuid.uuid4())
            version = random.choice(app_versions)
            ts = make_ts(day)

            # app_open
            events.append({
                "id": str(uuid.uuid4()),
                "event": "app_open",
                "user_id": user_id,
                "session_id": session_id,
                "platform": platform,
                "app_version": version,
                "properties": json.dumps({}),
                "timestamp": ts.isoformat(),
            })
            total_opens += 1

            # recipe_view (multiple per session)
            if random.random() < FUNNEL["app_open_to_recipe_view"]:
                num_views = random.choices([1, 2, 3, 4, 5, 7, 10], 
                                          weights=[0.15, 0.25, 0.25, 0.15, 0.10, 0.05, 0.05], k=1)[0]
                for v in range(num_views):
                    recipe = random.choice(RECIPES)
                    view_ts = ts + timedelta(minutes=random.randint(1, 30))
                    events.append({
                        "id": str(uuid.uuid4()),
                        "event": "recipe_view",
                        "user_id": user_id,
                        "session_id": session_id,
                        "platform": platform,
                        "app_version": version,
                        "properties": json.dumps({
                            "recipe_id": recipe[0],
                            "recipe_title": recipe[1],
                        }),
                        "timestamp": view_ts.isoformat(),
                    })
                    total_views += 1

                    # recipe_save
                    if random.random() < FUNNEL["recipe_view_to_save"]:
                        save_ts = view_ts + timedelta(seconds=random.randint(5, 60))
                        events.append({
                            "id": str(uuid.uuid4()),
                            "event": "recipe_save",
                            "user_id": user_id,
                            "session_id": session_id,
                            "platform": platform,
                            "app_version": version,
                            "properties": json.dumps({
                                "recipe_id": recipe[0],
                                "recipe_title": recipe[1],
                            }),
                            "timestamp": save_ts.isoformat(),
                        })
                        total_saves += 1

                    # affiliate_click
                    if random.random() < FUNNEL["recipe_view_to_affiliate_click"]:
                        provider = random.choices(PROVIDERS, weights=PROVIDER_WEIGHTS, k=1)[0]
                        ingredient = random.choice(INGREDIENTS)
                        click_ts = view_ts + timedelta(seconds=random.randint(10, 120))
                        events.append({
                            "id": str(uuid.uuid4()),
                            "event": "affiliate_click",
                            "user_id": user_id,
                            "session_id": session_id,
                            "platform": platform,
                            "app_version": version,
                            "properties": json.dumps({
                                "recipe_id": recipe[0],
                                "recipe_title": recipe[1],
                                "provider": provider,
                                "ingredient": ingredient,
                            }),
                            "timestamp": click_ts.isoformat(),
                        })
                        total_clicks += 1

                        # affiliate_conversion
                        if random.random() < FUNNEL["affiliate_click_to_conversion"]:
                            order_values = {"amazon": 35, "iherb": 42, "instacart": 65, "thrive": 0, "hellofresh": 0}
                            ov = order_values.get(provider, 35) * random.uniform(0.5, 2.0) if order_values.get(provider, 0) > 0 else 0
                            conv_ts = click_ts + timedelta(minutes=random.randint(5, 120))
                            events.append({
                                "id": str(uuid.uuid4()),
                                "event": "affiliate_conversion",
                                "user_id": user_id,
                                "session_id": session_id,
                                "platform": platform,
                                "app_version": version,
                                "properties": json.dumps({
                                    "recipe_id": recipe[0],
                                    "provider": provider,
                                    "ingredient": ingredient,
                                    "order_value": round(ov, 2),
                                    "category": random.choice(["grocery", "kitchen", "supplements"]),
                                }),
                                "timestamp": conv_ts.isoformat(),
                            })
                            total_conversions += 1

            # grocery_list_generated (occasional)
            if random.random() < 0.05:
                gl_ts = ts + timedelta(minutes=random.randint(5, 45))
                events.append({
                    "id": str(uuid.uuid4()),
                    "event": "grocery_list_generated",
                    "user_id": user_id,
                    "session_id": session_id,
                    "platform": platform,
                    "app_version": version,
                    "properties": json.dumps({
                        "item_count": random.randint(3, 15),
                    }),
                    "timestamp": gl_ts.isoformat(),
                })

    # Batch insert
    print(f"Generated {len(events)} events:")
    print(f"  app_open: {total_opens}")
    print(f"  recipe_view: {total_views}")
    print(f"  recipe_save: {total_saves}")
    print(f"  affiliate_click: {total_clicks}")
    print(f"  affiliate_conversion: {total_conversions}")

    BATCH = 500
    async with async_session() as session:
        for i in range(0, len(events), BATCH):
            batch = events[i:i+BATCH]
            await session.execute(
                text("""
                    INSERT INTO analytics_events (id, event, user_id, session_id, platform, app_version, properties, timestamp)
                    VALUES (:id, :event, :user_id, :session_id, :platform, :app_version, :properties, :timestamp)
                """),
                batch,
            )
            await session.commit()
            print(f"  Inserted batch {i//BATCH + 1}/{(len(events) + BATCH - 1) // BATCH}")

    print(f"\n✅ Seeded {len(events)} analytics events across {DAYS} days")


if __name__ == "__main__":
    asyncio.run(seed())
