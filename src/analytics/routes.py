"""Analytics API routes — event ingestion + admin dashboard metrics."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_session
from src.analytics.tables import AnalyticsEvent, RequestLog

logger = logging.getLogger(__name__)
router = APIRouter()


# --- Event Ingestion ---

class EventPayload(BaseModel):
    event: str = Field(..., max_length=100, description="Event name (e.g. recipe_view)")
    user_id: str | None = Field(None, max_length=36)
    session_id: str | None = Field(None, max_length=36)
    platform: str | None = Field(None, max_length=20)
    app_version: str | None = Field(None, max_length=20)
    properties: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime | None = None


class BatchPayload(BaseModel):
    events: list[EventPayload] = Field(..., max_length=100)


@router.post("/api/v1/events", status_code=202)
async def track_event(payload: EventPayload, session: AsyncSession = Depends(get_session)):
    """Track a single analytics event from the client."""
    session.add(AnalyticsEvent(
        event=payload.event,
        user_id=payload.user_id,
        session_id=payload.session_id,
        platform=payload.platform,
        app_version=payload.app_version,
        properties=payload.properties,
        timestamp=payload.timestamp or datetime.now(timezone.utc),
    ))
    await session.commit()
    return {"status": "accepted"}


@router.post("/api/v1/events/batch", status_code=202)
async def track_events_batch(payload: BatchPayload, session: AsyncSession = Depends(get_session)):
    """Track up to 100 events in a single request (for mobile clients batching offline events)."""
    for ev in payload.events:
        session.add(AnalyticsEvent(
            event=ev.event,
            user_id=ev.user_id,
            session_id=ev.session_id,
            platform=ev.platform,
            app_version=ev.app_version,
            properties=ev.properties,
            timestamp=ev.timestamp or datetime.now(timezone.utc),
        ))
    await session.commit()
    return {"status": "accepted", "count": len(payload.events)}


# --- Admin Dashboard Metrics ---

@router.get("/api/v1/admin/metrics")
async def get_metrics(
    hours: int = Query(24, ge=1, le=720, description="Lookback window in hours"),
    session: AsyncSession = Depends(get_session),
):
    """Real-time dashboard metrics. Shows event counts, top recipes, API performance."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    # Event counts by type
    event_counts_q = select(
        AnalyticsEvent.event,
        func.count().label("count"),
    ).where(AnalyticsEvent.timestamp >= since).group_by(AnalyticsEvent.event).order_by(func.count().desc())
    event_rows = (await session.execute(event_counts_q)).all()

    # Unique users
    unique_users_q = select(func.count(func.distinct(AnalyticsEvent.user_id))).where(
        AnalyticsEvent.timestamp >= since,
        AnalyticsEvent.user_id.is_not(None),
    )
    unique_users = (await session.execute(unique_users_q)).scalar() or 0

    # Platform breakdown
    platform_q = select(
        AnalyticsEvent.platform,
        func.count(func.distinct(AnalyticsEvent.user_id)).label("users"),
    ).where(
        AnalyticsEvent.timestamp >= since,
        AnalyticsEvent.platform.is_not(None),
    ).group_by(AnalyticsEvent.platform)
    platform_rows = (await session.execute(platform_q)).all()

    # API performance (avg response time by endpoint)
    perf_q = select(
        RequestLog.path,
        func.count().label("requests"),
        func.avg(RequestLog.duration_ms).label("avg_ms"),
        func.max(RequestLog.duration_ms).label("max_ms"),
    ).where(RequestLog.timestamp >= since).group_by(RequestLog.path).order_by(func.count().desc()).limit(15)
    perf_rows = (await session.execute(perf_q)).all()

    # Top recipe views (from recipe_view events)
    top_recipes_q = text("""
        SELECT json_extract(properties, '$.recipe_id') as recipe_id,
               json_extract(properties, '$.recipe_title') as title,
               COUNT(*) as views
        FROM analytics_events
        WHERE event = 'recipe_view' AND timestamp >= :since
        GROUP BY recipe_id
        ORDER BY views DESC
        LIMIT 10
    """)
    try:
        top_recipe_rows = (await session.execute(top_recipes_q, {"since": since})).all()
        top_recipes = [{"recipe_id": r[0], "title": r[1], "views": r[2]} for r in top_recipe_rows]
    except Exception:
        top_recipes = []

    # Affiliate click funnel
    affiliate_q = text("""
        SELECT json_extract(properties, '$.provider') as provider,
               COUNT(*) as clicks
        FROM analytics_events
        WHERE event = 'affiliate_click' AND timestamp >= :since
        GROUP BY provider
        ORDER BY clicks DESC
    """)
    try:
        aff_rows = (await session.execute(affiliate_q, {"since": since})).all()
        affiliate_clicks = [{"provider": r[0], "clicks": r[1]} for r in aff_rows]
    except Exception:
        affiliate_clicks = []

    return {
        "window_hours": hours,
        "since": since.isoformat(),
        "events": {name: count for name, count in event_rows},
        "unique_users": unique_users,
        "platforms": {name: users for name, users in platform_rows},
        "top_recipes": top_recipes,
        "affiliate_clicks": affiliate_clicks,
        "api_performance": [
            {
                "path": r.path,
                "requests": r.requests,
                "avg_ms": round(r.avg_ms, 1) if r.avg_ms else 0,
                "max_ms": round(r.max_ms, 1) if r.max_ms else 0,
            }
            for r in perf_rows
        ],
    }


@router.get("/api/v1/admin/metrics/funnel")
async def get_funnel(
    hours: int = Query(24, ge=1, le=720),
    session: AsyncSession = Depends(get_session),
):
    """Recipe-to-revenue funnel: recipe_view → affiliate_click → affiliate_conversion."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    funnel_events = ["app_open", "recipe_view", "recipe_save", "affiliate_click", "grocery_list_generated", "affiliate_conversion"]
    funnel = {}
    for event_name in funnel_events:
        q = select(func.count()).where(
            AnalyticsEvent.event == event_name,
            AnalyticsEvent.timestamp >= since,
        )
        funnel[event_name] = (await session.execute(q)).scalar() or 0

    # Calculate conversion rates
    conversions = {}
    for i in range(1, len(funnel_events)):
        prev = funnel_events[i - 1]
        curr = funnel_events[i]
        prev_count = funnel[prev]
        curr_count = funnel[curr]
        conversions[f"{prev}_to_{curr}"] = round(curr_count / prev_count * 100, 1) if prev_count > 0 else 0

    return {
        "window_hours": hours,
        "funnel": funnel,
        "conversion_rates": conversions,
    }
