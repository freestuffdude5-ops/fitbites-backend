"""Scheduler API — trigger harvests, check status, view stats."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Header, BackgroundTasks
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_session
from src.db.tables import RecipeRow
from src.models import Platform
from src.services.recipe_orchestrator import RecipeOrchestrator, HarvestStats
from config.settings import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/recipes", tags=["recipe-scheduler"])

# Module-level orchestrator singleton
_orchestrator: RecipeOrchestrator | None = None
_harvest_lock = asyncio.Lock()


def _get_orchestrator() -> RecipeOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = RecipeOrchestrator.from_settings()
    return _orchestrator


def _verify_admin(x_admin_key: str = Header(None)) -> None:
    import hmac
    expected = getattr(settings, "ADMIN_API_KEY", None)
    if not expected:
        raise HTTPException(503, "Admin endpoints disabled")
    if not x_admin_key or not hmac.compare_digest(x_admin_key, expected):
        raise HTTPException(403, "Invalid admin key")


@router.post("/run-harvest")
async def run_harvest(
    background_tasks: BackgroundTasks,
    platforms: list[str] | None = None,
    limit_per_platform: int = 50,
    _auth: None = Depends(_verify_admin),
):
    """Trigger a manual recipe harvest.

    Runs asynchronously in background. Check /harvest-status for progress.
    """
    orch = _get_orchestrator()

    if orch.last_harvest and orch.last_harvest.status == "running":
        raise HTTPException(409, "Harvest already in progress")

    async def _run():
        async with _harvest_lock:
            await orch.run_harvest(
                limit_per_platform=limit_per_platform,
                platforms=platforms,
            )

    background_tasks.add_task(_run)

    return {
        "status": "started",
        "message": "Harvest started in background",
        "platforms": platforms or ["youtube", "instagram", "tiktok"],
        "limit_per_platform": limit_per_platform,
    }


@router.get("/harvest-status")
async def harvest_status(_auth: None = Depends(_verify_admin)):
    """Check the status of the last harvest run."""
    orch = _get_orchestrator()
    if not orch.last_harvest:
        return {"status": "no_runs", "message": "No harvest has been run yet"}
    return orch.last_harvest.to_dict()


@router.get("/stats")
async def recipe_stats(
    session: AsyncSession = Depends(get_session),
    _auth: None = Depends(_verify_admin),
):
    """Database stats: total recipes, by platform, by quality."""
    # Total
    total = (await session.execute(select(func.count(RecipeRow.id)))).scalar() or 0

    # By platform
    by_platform = {}
    for p in Platform:
        count = (await session.execute(
            select(func.count(RecipeRow.id)).where(RecipeRow.platform == p)
        )).scalar() or 0
        by_platform[p.value] = count

    # Quality breakdown (complete = has ingredients + nutrition + steps)
    complete = (await session.execute(
        select(func.count(RecipeRow.id)).where(
            RecipeRow.calories.isnot(None),
            RecipeRow.protein_g.isnot(None),
            func.json_array_length(RecipeRow.ingredients) > 0,
        )
    )).scalar() or 0

    # Average nutrition
    avg_cal = (await session.execute(
        select(func.avg(RecipeRow.calories)).where(RecipeRow.calories.isnot(None))
    )).scalar()
    avg_protein = (await session.execute(
        select(func.avg(RecipeRow.protein_g)).where(RecipeRow.protein_g.isnot(None))
    )).scalar()

    # Last harvest info
    orch = _get_orchestrator()
    last_harvest = orch.last_harvest.to_dict() if orch.last_harvest else None

    return {
        "total_recipes": total,
        "by_platform": by_platform,
        "complete_recipes": complete,
        "incomplete_recipes": total - complete,
        "avg_calories": round(avg_cal, 1) if avg_cal else None,
        "avg_protein_g": round(avg_protein, 1) if avg_protein else None,
        "last_harvest": last_harvest,
    }
