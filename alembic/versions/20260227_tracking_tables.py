"""Add meal_logs and user_goals tables for calorie tracking.

Revision ID: a1b2c3d4e5f6
Revises: 162747af30a6
Create Date: 2026-02-27
"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "162747af30a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "meal_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False, index=True),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("calories", sa.Float, nullable=False),
        sa.Column("protein", sa.Float, nullable=False, server_default="0"),
        sa.Column("carbs", sa.Float, nullable=False, server_default="0"),
        sa.Column("fat", sa.Float, nullable=False, server_default="0"),
        sa.Column("logged_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "user_goals",
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column("daily_calories", sa.Float, nullable=False, server_default="2000"),
        sa.Column("daily_protein", sa.Float, nullable=False, server_default="150"),
        sa.Column("daily_carbs", sa.Float, nullable=False, server_default="250"),
        sa.Column("daily_fat", sa.Float, nullable=False, server_default="65"),
    )


def downgrade() -> None:
    op.drop_table("user_goals")
    op.drop_table("meal_logs")
