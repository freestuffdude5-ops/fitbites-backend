"""Streak tracking model — tracks user cooking streaks for retention."""
from __future__ import annotations

from datetime import datetime, timezone, date
from typing import Optional

from sqlmodel import Field, SQLModel


class UserStreak(SQLModel, table=True):
    """Tracks daily cooking activity streaks for users."""
    
    __tablename__ = "user_streaks"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(index=True, unique=True)
    
    # Streak state
    current_streak: int = Field(default=0, ge=0)
    longest_streak: int = Field(default=0, ge=0)
    
    # Activity tracking
    last_cooked_date: Optional[date] = Field(default=None)
    total_cooks: int = Field(default=0, ge=0)
    
    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    
    def update_streak(self, cooked_date: date) -> dict:
        """Update streak based on new cook activity.
        
        Returns:
            dict with streak_info: {streak_type, streak_count, is_new_record}
        """
        today = date.today()
        yesterday = date.today()
        
        # Import timedelta for date calculation
        from datetime import timedelta
        yesterday = today - timedelta(days=1)
        
        is_new_record = False
        
        if self.last_cooked_date is None:
            # First cook ever
            self.current_streak = 1
            self.longest_streak = max(1, self.longest_streak)
            is_new_record = self.current_streak > 1
        elif cooked_date == self.last_cooked_date:
            # Already cooked today - no change
            pass
        elif cooked_date == yesterday:
            # Consecutive day - increment streak
            self.current_streak += 1
            self.longest_streak = max(self.current_streak, self.longest_streak)
            is_new_record = self.current_streak > self.longest_streak
        elif cooked_date < self.last_cooked_date:
            # Cooking old meal - no streak change
            pass
        else:
            # Missed a day - reset streak
            self.current_streak = 1
            self.longest_streak = max(self.current_streak, self.longest_streak)
        
        self.last_cooked_date = cooked_date
        self.total_cooks += 1
        self.updated_at = datetime.now(tz=timezone.utc)
        
        return {
            "streak_type": "current",
            "streak_count": self.current_streak,
            "longest_streak": self.longest_streak,
            "is_new_record": is_new_record,
            "total_cooks": self.total_cooks,
            "last_cooked": self.last_cooked_date.isoformat() if self.last_cooked_date else None
        }
    
    def get_status(self) -> dict:
        """Get current streak status for display."""
        today = date.today()
        from datetime import timedelta
        yesterday = today - timedelta(days=1)
        
        status = "active"
        days_until_streak_loss = None
        
        if self.last_cooked_date is None:
            status = "new"
            days_until_streak_loss = None
        elif self.last_cooked_date == today:
            status = "cooked_today"
            days_until_streak_loss = 1
        elif self.last_cooked_date == yesterday:
            status = "at_risk"
            days_until_streak_loss = 1
        else:
            status = "broken"
            days_until_streak_loss = 0
        
        return {
            "user_id": self.user_id,
            "current_streak": self.current_streak,
            "longest_streak": self.longest_streak,
            "total_cooks": self.total_cooks,
            "status": status,
            "last_cooked": self.last_cooked_date.isoformat() if self.last_cooked_date else None,
            "days_until_streak_loss": days_until_streak_loss,
            "streak_message": self._get_streak_message()
        }
    
    def _get_streak_message(self) -> str:
        """Get motivational message based on streak."""
        if self.current_streak == 0:
            return "Start your streak today! 🔥"
        elif self.current_streak == 1:
            return "1 day down! Keep it going 💪"
        elif self.current_streak < 7:
            return f"{self.current_streak} day streak! You're on fire 🔥"
        elif self.current_streak < 14:
            return f"{self.current_streak} days! You're building a habit 🎯"
        elif self.current_streak < 30:
            return f"Incredible {self.current_streak} day streak! You're a pro 👑"
        else:
            return f"LEGENDARY {self.current_streak} day streak! 🏆"
