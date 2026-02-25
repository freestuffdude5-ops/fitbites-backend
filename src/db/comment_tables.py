"""Comment database tables — casual social conversation on recipes."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, Index, UniqueConstraint
from sqlalchemy.orm import relationship

from src.db.tables import Base


class CommentRow(Base):
    """User comment on a recipe."""
    __tablename__ = "comments"
    
    id = Column(Integer, primary_key=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_id = Column(Integer, ForeignKey("comments.id", ondelete="CASCADE"), nullable=True, index=True)
    text = Column(Text, nullable=False)
    like_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=True)
    
    # Relationships
    author = relationship("UserRow", foreign_keys=[user_id], back_populates="comments")
    recipe = relationship("RecipeRow", foreign_keys=[recipe_id])
    parent = relationship("CommentRow", remote_side=[id], foreign_keys=[parent_id])
    
    # Index for sorting by likes (top comments)
    __table_args__ = (
        Index("ix_comments_recipe_likes", "recipe_id", "like_count"),
    )


class CommentLikeRow(Base):
    """User like on a comment."""
    __tablename__ = "comment_likes"
    
    id = Column(Integer, primary_key=True)
    comment_id = Column(Integer, ForeignKey("comments.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (
        UniqueConstraint("comment_id", "user_id", name="uq_comment_user_like"),
    )
