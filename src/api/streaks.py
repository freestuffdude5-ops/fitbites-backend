"""Streak tracking API — cooking streaks for retention."""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_session
from src.db.tables import UserStreakRow

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/streaks", tags=["streaks"])


# Request/Response models
class CookEventRequest(BaseModel):
    """Request to log a cook event."""
    user_id: str
    recipe_id: Optional[str] = None
    cooked_date: Optional[str] = None  # ISO date string, defaults to today


class StreakResponse(BaseModel):
    """Streak information response."""
    user_id: str
    current_streak: int
    longest_streak: int
    total_cooks: int
    status: str  # "new", "active", "at_risk", "broken", "cooked_today"
    last_cooked: Optional[str]
    days_until_streak_loss: Optional[int]
    streak_message: str
    new_record: Optional[bool] = False


class StreakStatusResponse(BaseModel):
    """Simple status for checking streak state."""
    current_streak: int
    longest_streak: int
    total_cooks: int
    status: str
    days_until_streak_loss: Optional[int]
    streak_message: str


def _calculate_streak_status(last_cooked_date: Optional[date]) -> tuple[str, Optional[int]]:
    """Calculate streak status based on last cooked date."""
    if last_cooked_date is None:
        return ("new", None)
    
    today = date.today()
    from datetime import timedelta
    yesterday = today - timedelta(days=1)
    
    if last_cooked_date == today:
        return ("cooked_today", 1)
    elif last_cooked_date == yesterday:
        return ("at_risk", 1)
    else:
        return ("broken", 0)


def _get_streak_message(current_streak: int) -> str:
    """Get motivational message based on streak."""
    if current_streak == 0:
        return "Start your streak today! 🔥"
    elif current_streak == 1:
        return "1 day down! Keep it going 💪"
    elif current_streak < 7:
        return f"{current_streak} day streak! You're on fire 🔥"
    elif current_streak < 14:
        return f"{current_streak} days! You're building a habit 🎯"
    elif current_streak < 30:
        return f"Incredible {current_streak} day streak! You're a pro 👑"
    else:
        return f"LEGENDARY {current_streak} day streak! 🏆"


@router.get("/{user_id}", response_model=StreakStatusResponse)
async def get_streak(user_id: str, session: AsyncSession = Depends(get_session)):
    """Get current streak status for a user."""
    result = await session.execute(
        select(UserStreakRow).where(UserStreakRow.user_id == user_id)
    )
    streak = result.scalar_one_or_none()
    
    if not streak:
        # Return default streak for new users
        return StreakStatusResponse(
            current_streak=0,
            longest_streak=0,
            total_cooks=0,
            status="new",
            days_until_streak_loss=None,
            streak_message="Start your streak today! 🔥"
        )
    
    status, days_until = _calculate_streak_status(streak.last_cooked_date)
    
    return StreakStatusResponse(
        current_streak=streak.current_streak,
        longest_streak=streak.longest_streak,
        total_cooks=streak.total_cooks,
        status=status,
        days_until_streak_loss=days_until,
        streak_message=_get_streak_message(streak.current_streak)
    )


@router.post("/cook", response_model=StreakResponse)
async def log_cook_event(request: CookEventRequest, session: AsyncSession = Depends(get_session)):
    """Log a cook event and update streak.
    
    Call this when user marks a recipe as "cooked" or "completed".
    Automatically handles streak logic (consecutive days, resets).
    """
    # Parse date or use today
    if request.cooked_date:
        try:
            cooked_date = date.fromisoformat(request.cooked_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    else:
        cooked_date = date.today()
    
    # Get or create streak
    result = await session.execute(
        select(UserStreakRow).where(UserStreakRow.user_id == request.user_id)
    )
    streak = result.scalar_one_or_none()
    
    is_new_record = False
    
    if not streak:
        # Create new streak record
        streak = UserStreakRow(
            user_id=request.user_id,
            current_streak=1,
            longest_streak=1,
            last_cooked_date=cooked_date,
            total_cooks=1,
            created_at=datetime.now(tz=timezone.utc),
            updated_at=datetime.now(tz=timezone.utc)
        )
        session.add(streak)
        is_new_record = True
    else:
        # Update existing streak logic
        from datetime import timedelta
        yesterday = date.today() - timedelta(days=1)
        
        if streak.last_cooked_date == cooked_date:
            # Already cooked today - no change
            pass
        elif streak.last_cooked_date == yesterday:
            # Consecutive day - increment streak
            streak.current_streak += 1
            streak.longest_streak = max(streak.current_streak, streak.longest_streak)
            is_new_record = streak.current_streak > streak.longest_streak
        elif streak.last_cooked_date is not None and streak.last_cooked_date < yesterday:
            # Missed a day - reset streak
            streak.current_streak = 1
            streak.longest_streak = max(streak.current_streak, streak.longest_streak)
        # else: cooking old date - no streak change
        
        streak.last_cooked_date = cooked_date
        streak.total_cooks += 1
        streak.updated_at = datetime.now(tz=timezone.utc)
    
    await session.commit()
    await session.refresh(streak)
    
    status, days_until = _calculate_streak_status(streak.last_cooked_date)
    
    return StreakResponse(
        user_id=streak.user_id,
        current_streak=streak.current_streak,
        longest_streak=streak.longest_streak,
        total_cooks=streak.total_cooks,
        status=status,
        last_cooked=streak.last_cooked_date.isoformat() if streak.last_cooked_date else None,
        days_until_streak_loss=days_until,
        streak_message=_get_streak_message(streak.current_streak),
        new_record=is_new_record
    )


@router.get("/{user_id}/milestones")
async def get_streak_milestones(user_id: str, session: AsyncSession = Depends(get_session)):
    """Get milestone achievements for a user's streak.
    
    Milestones: 3, 7, 14, 30, 60, 100, 365 days
    """
    result = await session.execute(
        select(UserStreakRow).where(UserStreakRow.user_id == user_id)
    )
    streak = result.scalar_one_or_none()
    
    if not streak:
        return {
            "user_id": user_id,
            "milestones": [],
            "next_milestone": {"days": 3, "reward": "🔥 3-Day Streak"}
        }
    
    milestone_targets = [3, 7, 14, 30, 60, 100, 365]
    current = streak.current_streak
    
    earned = []
    for m in milestone_targets:
        if current >= m:
            earned.append({
                "days": m,
                "earned": True,
                "reward": _get_milestone_reward(m)
            })
        else:
            earned.append({
                "days": m,
                "earned": False,
                "reward": _get_milestone_reward(m)
            })
            break  # First unearned is the next target
    
    next_milestone = next((m for m in milestone_targets if m > current), None)
    
    return {
        "user_id": user_id,
        "current_streak": current,
        "milestones": earned,
        "next_milestone": {
            "days": next_milestone,
            "reward": _get_milestone_reward(next_milestone) if next_milestone else None,
            "days_remaining": next_milestone - current if next_milestone else 0
        }
    }


def _get_milestone_reward(days: int) -> str:
    """Get reward description for milestone."""
    rewards = {
        3: "🔥 3-Day Streak - You're building a habit!",
        7: "🎯 7-Day Streak - Week warrior!",
        14: "💪 14-Day Streak - Consistency is key!",
        30: "⭐ 30-Day Streak - Monthly master chef!",
        60: "🏆 60-Day Streak - Dedication pays off!",
        100: "👑 100-Day Streak - You're unstoppable!",
        365: "🏅 365-Day Streak - LEGENDARY status!"
    }
    return rewards.get(days, f"🎉 {days}-Day Streak!")
