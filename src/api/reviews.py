"""Recipe reviews, ratings, cooking history, and search suggestions API."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, delete, update, case, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_session
from src.db.tables import RecipeRow
from src.db.user_tables import UserRow, SavedRecipeRow
from src.db.review_tables import RecipeReviewRow, CookingLogRow, ReviewHelpfulRow

router = APIRouter(prefix="/api/v1", tags=["reviews", "cooking", "search"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class ReviewCreateRequest(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    title: str | None = Field(None, max_length=200)
    body: str | None = Field(None, max_length=2000)
    made_it: bool = False
    photos: list[str] = Field(default_factory=list, max_length=5)


class ReviewUpdateRequest(BaseModel):
    rating: int | None = Field(None, ge=1, le=5)
    title: str | None = Field(None, max_length=200)
    body: str | None = Field(None, max_length=2000)
    made_it: bool | None = None


class CookingLogRequest(BaseModel):
    servings: float = Field(1.0, ge=0.25, le=20)
    notes: str | None = Field(None, max_length=500)
    rating: int | None = Field(None, ge=1, le=5)


# ── Recipe Reviews ───────────────────────────────────────────────────────────

@router.post("/recipes/{recipe_id}/reviews", status_code=201)
async def create_review(
    recipe_id: str,
    req: ReviewCreateRequest,
    user_id: str = Query(..., description="Authenticated user ID"),
    session: AsyncSession = Depends(get_session),
):
    """Submit a review for a recipe. One review per user per recipe."""
    # Verify recipe exists
    recipe = (await session.execute(
        select(RecipeRow).where(RecipeRow.id == recipe_id)
    )).scalar_one_or_none()
    if not recipe:
        raise HTTPException(404, "Recipe not found")

    # Verify user exists
    user = (await session.execute(
        select(UserRow).where(UserRow.id == user_id)
    )).scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")

    # Check for existing review
    existing = (await session.execute(
        select(RecipeReviewRow).where(
            RecipeReviewRow.user_id == user_id,
            RecipeReviewRow.recipe_id == recipe_id,
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(409, "You already reviewed this recipe. Use PATCH to update.")

    review = RecipeReviewRow(
        id=str(uuid.uuid4()),
        user_id=user_id,
        recipe_id=recipe_id,
        rating=req.rating,
        title=req.title,
        body=req.body,
        made_it=req.made_it,
        photos=req.photos,
    )
    session.add(review)
    await session.commit()

    return _review_response(review, user)


@router.get("/recipes/{recipe_id}/reviews")
async def list_reviews(
    recipe_id: str,
    sort: str = Query("newest", pattern="^(newest|highest|lowest|helpful)$"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """List reviews for a recipe with rating summary."""
    # Rating summary
    summary_stmt = select(
        func.count(RecipeReviewRow.id).label("total"),
        func.avg(RecipeReviewRow.rating).label("avg_rating"),
        func.sum(case((RecipeReviewRow.made_it == True, 1), else_=0)).label("made_it_count"),
    ).where(RecipeReviewRow.recipe_id == recipe_id)
    summary = (await session.execute(summary_stmt)).one()

    # Rating distribution
    dist_stmt = select(
        RecipeReviewRow.rating,
        func.count().label("count"),
    ).where(
        RecipeReviewRow.recipe_id == recipe_id
    ).group_by(RecipeReviewRow.rating)
    dist_rows = (await session.execute(dist_stmt)).all()
    distribution = {str(i): 0 for i in range(1, 6)}
    for rating_val, cnt in dist_rows:
        distribution[str(rating_val)] = cnt

    # Fetch reviews
    stmt = (
        select(RecipeReviewRow, UserRow)
        .join(UserRow, RecipeReviewRow.user_id == UserRow.id)
        .where(RecipeReviewRow.recipe_id == recipe_id)
    )
    if sort == "newest":
        stmt = stmt.order_by(RecipeReviewRow.created_at.desc())
    elif sort == "highest":
        stmt = stmt.order_by(RecipeReviewRow.rating.desc(), RecipeReviewRow.created_at.desc())
    elif sort == "lowest":
        stmt = stmt.order_by(RecipeReviewRow.rating.asc(), RecipeReviewRow.created_at.desc())
    elif sort == "helpful":
        stmt = stmt.order_by(RecipeReviewRow.helpful_count.desc(), RecipeReviewRow.created_at.desc())

    stmt = stmt.offset(offset).limit(limit)
    results = (await session.execute(stmt)).all()

    return {
        "summary": {
            "total_reviews": summary.total or 0,
            "average_rating": round(float(summary.avg_rating or 0), 1),
            "made_it_count": summary.made_it_count or 0,
            "distribution": distribution,
        },
        "data": [_review_response(review, user) for review, user in results],
        "pagination": {
            "total": summary.total or 0,
            "limit": limit,
            "offset": offset,
            "has_more": offset + limit < (summary.total or 0),
        },
    }


@router.patch("/recipes/{recipe_id}/reviews/{review_id}")
async def update_review(
    recipe_id: str,
    review_id: str,
    req: ReviewUpdateRequest,
    user_id: str = Query(...),
    session: AsyncSession = Depends(get_session),
):
    """Update your review."""
    review = (await session.execute(
        select(RecipeReviewRow).where(
            RecipeReviewRow.id == review_id,
            RecipeReviewRow.recipe_id == recipe_id,
            RecipeReviewRow.user_id == user_id,
        )
    )).scalar_one_or_none()
    if not review:
        raise HTTPException(404, "Review not found or not yours")

    updates = req.model_dump(exclude_none=True)
    for key, val in updates.items():
        setattr(review, key, val)
    review.updated_at = datetime.now(timezone.utc)
    await session.commit()

    user = (await session.execute(select(UserRow).where(UserRow.id == user_id))).scalar_one()
    return _review_response(review, user)


@router.delete("/recipes/{recipe_id}/reviews/{review_id}", status_code=204)
async def delete_review(
    recipe_id: str,
    review_id: str,
    user_id: str = Query(...),
    session: AsyncSession = Depends(get_session),
):
    """Delete your review."""
    result = await session.execute(
        delete(RecipeReviewRow).where(
            RecipeReviewRow.id == review_id,
            RecipeReviewRow.recipe_id == recipe_id,
            RecipeReviewRow.user_id == user_id,
        )
    )
    if result.rowcount == 0:
        raise HTTPException(404, "Review not found or not yours")
    await session.commit()


@router.post("/reviews/{review_id}/helpful")
async def mark_helpful(
    review_id: str,
    user_id: str = Query(...),
    session: AsyncSession = Depends(get_session),
):
    """Mark a review as helpful. Toggles on/off."""
    # Check existing vote
    existing = (await session.execute(
        select(ReviewHelpfulRow).where(
            ReviewHelpfulRow.user_id == user_id,
            ReviewHelpfulRow.review_id == review_id,
        )
    )).scalar_one_or_none()

    review = (await session.execute(
        select(RecipeReviewRow).where(RecipeReviewRow.id == review_id)
    )).scalar_one_or_none()
    if not review:
        raise HTTPException(404, "Review not found")

    if existing:
        # Toggle off
        await session.execute(
            delete(ReviewHelpfulRow).where(ReviewHelpfulRow.id == existing.id)
        )
        review.helpful_count = max(0, (review.helpful_count or 0) - 1)
        await session.commit()
        return {"status": "removed", "helpful_count": review.helpful_count}
    else:
        # Toggle on
        vote = ReviewHelpfulRow(
            id=str(uuid.uuid4()),
            user_id=user_id,
            review_id=review_id,
        )
        session.add(vote)
        review.helpful_count = (review.helpful_count or 0) + 1
        await session.commit()
        return {"status": "added", "helpful_count": review.helpful_count}


# ── Cooking History ──────────────────────────────────────────────────────────

@router.post("/users/{user_id}/cooking-log", status_code=201)
async def log_cooking(
    user_id: str,
    recipe_id: str = Query(...),
    req: CookingLogRequest = CookingLogRequest(),
    session: AsyncSession = Depends(get_session),
):
    """Log that you cooked a recipe. Used for stats, streaks, and personalization."""
    # Verify user
    user = (await session.execute(
        select(UserRow).where(UserRow.id == user_id)
    )).scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")

    # Verify recipe
    recipe = (await session.execute(
        select(RecipeRow).where(RecipeRow.id == recipe_id)
    )).scalar_one_or_none()
    if not recipe:
        raise HTTPException(404, "Recipe not found")

    log = CookingLogRow(
        id=str(uuid.uuid4()),
        user_id=user_id,
        recipe_id=recipe_id,
        servings=req.servings,
        notes=req.notes,
        rating=req.rating,
    )
    session.add(log)
    await session.commit()

    return {
        "id": log.id,
        "recipe": {"id": recipe.id, "title": recipe.title},
        "cooked_at": log.cooked_at.isoformat(),
        "servings": log.servings,
    }


@router.get("/users/{user_id}/cooking-log")
async def get_cooking_history(
    user_id: str,
    limit: int = Query(30, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """Get cooking history with stats."""
    # Fetch logs with recipe data
    stmt = (
        select(CookingLogRow, RecipeRow)
        .join(RecipeRow, CookingLogRow.recipe_id == RecipeRow.id)
        .where(CookingLogRow.user_id == user_id)
        .order_by(CookingLogRow.cooked_at.desc())
        .offset(offset)
        .limit(limit)
    )
    results = (await session.execute(stmt)).all()

    total = (await session.execute(
        select(func.count(CookingLogRow.id)).where(CookingLogRow.user_id == user_id)
    )).scalar() or 0

    # Cooking stats
    stats_stmt = select(
        func.count(CookingLogRow.id).label("total_cooked"),
        func.count(func.distinct(CookingLogRow.recipe_id)).label("unique_recipes"),
        func.sum(
            (RecipeRow.calories or 0) * CookingLogRow.servings
        ).label("total_calories"),
        func.sum(
            (RecipeRow.protein_g or 0) * CookingLogRow.servings
        ).label("total_protein"),
    ).join(RecipeRow, CookingLogRow.recipe_id == RecipeRow.id).where(
        CookingLogRow.user_id == user_id
    )
    stats = (await session.execute(stats_stmt)).one()

    return {
        "stats": {
            "total_cooked": stats.total_cooked or 0,
            "unique_recipes": stats.unique_recipes or 0,
            "total_calories": round(float(stats.total_calories or 0)),
            "total_protein_g": round(float(stats.total_protein or 0), 1),
        },
        "data": [
            {
                "id": log.id,
                "cooked_at": log.cooked_at.isoformat() if log.cooked_at else None,
                "servings": log.servings,
                "notes": log.notes,
                "rating": log.rating,
                "recipe": {
                    "id": recipe.id,
                    "title": recipe.title,
                    "thumbnail_url": recipe.thumbnail_url,
                    "calories": recipe.calories,
                    "protein_g": recipe.protein_g,
                },
            }
            for log, recipe in results
        ],
        "pagination": {"total": total, "limit": limit, "offset": offset, "has_more": offset + limit < total},
    }


@router.get("/users/{user_id}/cooking-stats")
async def get_cooking_stats(
    user_id: str,
    days: int = Query(7, ge=1, le=90, description="Stats window in days"),
    session: AsyncSession = Depends(get_session),
):
    """Get cooking stats for a time window — streak, favorites, macro totals.

    Powers the iOS stats widget and profile page.
    """
    cutoff = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0) - __import__('datetime').timedelta(days=days)

    # Logs in window
    logs = (await session.execute(
        select(CookingLogRow, RecipeRow)
        .join(RecipeRow, CookingLogRow.recipe_id == RecipeRow.id)
        .where(CookingLogRow.user_id == user_id, CookingLogRow.cooked_at >= cutoff)
        .order_by(CookingLogRow.cooked_at.desc())
    )).all()

    # Calculate daily cooking streak
    dates_cooked = sorted({
        log.cooked_at.date() for log, _ in logs if log.cooked_at
    }, reverse=True)

    streak = 0
    today = datetime.now(timezone.utc).date()
    for i, d in enumerate(dates_cooked):
        expected = today - __import__('datetime').timedelta(days=i)
        if d == expected:
            streak += 1
        else:
            break

    # Most cooked recipes
    recipe_counts = Counter()
    total_cals = 0.0
    total_protein = 0.0
    for log, recipe in logs:
        recipe_counts[recipe.id] += 1
        total_cals += (recipe.calories or 0) * (log.servings or 1)
        total_protein += (recipe.protein_g or 0) * (log.servings or 1)

    # Top 5 most cooked
    top_recipe_ids = [rid for rid, _ in recipe_counts.most_common(5)]
    top_recipes = []
    if top_recipe_ids:
        rows = (await session.execute(
            select(RecipeRow).where(RecipeRow.id.in_(top_recipe_ids))
        )).scalars().all()
        recipe_map = {r.id: r for r in rows}
        for rid in top_recipe_ids:
            r = recipe_map.get(rid)
            if r:
                top_recipes.append({
                    "id": r.id,
                    "title": r.title,
                    "thumbnail_url": r.thumbnail_url,
                    "times_cooked": recipe_counts[rid],
                })

    return {
        "window_days": days,
        "streak": streak,
        "meals_cooked": len(logs),
        "unique_recipes": len(recipe_counts),
        "avg_meals_per_day": round(len(logs) / max(days, 1), 1),
        "totals": {
            "calories": round(total_cals),
            "protein_g": round(total_protein, 1),
        },
        "top_recipes": top_recipes,
    }


# ── Search Suggestions & Trending ────────────────────────────────────────────

@router.get("/search/suggestions")
async def search_suggestions(
    q: str = Query("", min_length=0, max_length=100),
    limit: int = Query(8, ge=1, le=20),
    session: AsyncSession = Depends(get_session),
):
    """Autocomplete search suggestions — instant results as user types.

    Returns matching recipe titles + tag suggestions for premium UX.
    """
    if not q or len(q) < 2:
        # Return trending/popular tags instead
        return await _get_trending_suggestions(session, limit)

    q_lower = q.lower()

    # Title matches (prefix match for speed)
    title_stmt = (
        select(RecipeRow.id, RecipeRow.title, RecipeRow.thumbnail_url, RecipeRow.virality_score)
        .where(func.lower(RecipeRow.title).contains(q_lower))
        .order_by(RecipeRow.virality_score.desc())
        .limit(limit)
    )
    title_results = (await session.execute(title_stmt)).all()

    recipes = [
        {
            "type": "recipe",
            "id": r.id,
            "title": r.title,
            "thumbnail_url": r.thumbnail_url,
        }
        for r in title_results
    ]

    # Tag matches
    tag_stmt = (
        select(RecipeRow.tags)
        .where(RecipeRow.tags.isnot(None))
        .limit(500)
    )
    all_tags = (await session.execute(tag_stmt)).scalars().all()
    tag_counts: Counter = Counter()
    for tags in all_tags:
        if isinstance(tags, list):
            for tag in tags:
                if q_lower in tag.lower():
                    tag_counts[tag] += 1

    tag_suggestions = [
        {"type": "tag", "value": tag, "count": cnt}
        for tag, cnt in tag_counts.most_common(5)
    ]

    return {
        "query": q,
        "suggestions": tag_suggestions + recipes,
    }


@router.get("/trending/tags")
async def trending_tags(
    limit: int = Query(15, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
):
    """Get trending recipe tags — powers the explore/discover screen."""
    return await _get_trending_suggestions(session, limit)


async def _get_trending_suggestions(session: AsyncSession, limit: int) -> dict:
    """Get popular tags from high-virality recipes."""
    stmt = (
        select(RecipeRow.tags)
        .where(RecipeRow.tags.isnot(None))
        .order_by(RecipeRow.virality_score.desc())
        .limit(200)
    )
    results = (await session.execute(stmt)).scalars().all()

    tag_counts: Counter = Counter()
    for tags in results:
        if isinstance(tags, list):
            for tag in tags:
                tag_counts[tag] += 1

    trending = [
        {"tag": tag, "count": cnt}
        for tag, cnt in tag_counts.most_common(limit)
    ]

    return {"trending_tags": trending}


# ── Recipe Rating Summary (for recipe detail view) ──────────────────────────

@router.get("/recipes/{recipe_id}/rating")
async def get_recipe_rating(
    recipe_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Get rating summary for a recipe — used in recipe cards and detail views."""
    stmt = select(
        func.count(RecipeReviewRow.id).label("total"),
        func.avg(RecipeReviewRow.rating).label("avg"),
        func.sum(case((RecipeReviewRow.made_it == True, 1), else_=0)).label("made_it"),
    ).where(RecipeReviewRow.recipe_id == recipe_id)
    result = (await session.execute(stmt)).one()

    return {
        "recipe_id": recipe_id,
        "total_reviews": result.total or 0,
        "average_rating": round(float(result.avg or 0), 1),
        "made_it_count": result.made_it or 0,
    }


# ── Helpers ──────────────────────────────────────────────────────────────────

def _review_response(review: RecipeReviewRow, user: UserRow) -> dict:
    return {
        "id": review.id,
        "user": {
            "id": user.id,
            "display_name": user.display_name,
            "avatar_url": user.avatar_url,
        },
        "rating": review.rating,
        "title": review.title,
        "body": review.body,
        "made_it": review.made_it,
        "photos": review.photos or [],
        "helpful_count": review.helpful_count or 0,
        "created_at": review.created_at.isoformat() if review.created_at else None,
        "updated_at": review.updated_at.isoformat() if review.updated_at else None,
    }
