"""Content Reporting API — App Store compliance + community safety.

Users can report:
- Recipes (misleading nutrition, spam, copyright)
- Comments (spam, harassment, inappropriate)
- Reviews (fake reviews, spam)
- Users (impersonation, spam accounts)

Admin endpoints for moderation queue.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_session
from src.db.report_tables import ReportRow
from src.auth import require_user
from src.db.user_tables import UserRow

router = APIRouter(prefix="/api/v1", tags=["reports"])

VALID_CONTENT_TYPES = {"recipe", "comment", "review", "user"}
VALID_REASONS = {"spam", "inappropriate", "misleading", "harmful", "copyright", "harassment", "other"}


class ReportRequest(BaseModel):
    content_type: str = Field(..., description="recipe, comment, review, or user")
    content_id: str
    reason: str = Field(..., description="spam, inappropriate, misleading, harmful, copyright, harassment, other")
    details: str | None = Field(None, max_length=2000)


class ReportUpdateRequest(BaseModel):
    status: str = Field(..., pattern="^(reviewed|resolved|dismissed)$")
    admin_notes: str | None = Field(None, max_length=2000)


@router.post("/reports", status_code=201)
async def submit_report(
    body: ReportRequest,
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Submit a content report."""
    if body.content_type not in VALID_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid content type. Must be: {', '.join(VALID_CONTENT_TYPES)}")
    if body.reason not in VALID_REASONS:
        raise HTTPException(status_code=400, detail=f"Invalid reason. Must be: {', '.join(VALID_REASONS)}")

    # Check for duplicate report
    existing = await session.execute(
        select(ReportRow).where(
            ReportRow.reporter_id == user.id,
            ReportRow.content_type == body.content_type,
            ReportRow.content_id == body.content_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="You have already reported this content")

    report = ReportRow(
        reporter_id=user.id,
        content_type=body.content_type,
        content_id=body.content_id,
        reason=body.reason,
        details=body.details,
    )
    session.add(report)
    await session.commit()
    await session.refresh(report)

    return {
        "id": report.id,
        "content_type": report.content_type,
        "content_id": report.content_id,
        "reason": report.reason,
        "status": report.status,
        "message": "Report submitted. Our team will review it shortly.",
    }


@router.get("/reports/my")
async def my_reports(
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
):
    """List reports submitted by the current user."""
    result = await session.execute(
        select(ReportRow)
        .where(ReportRow.reporter_id == user.id)
        .order_by(ReportRow.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    reports = result.scalars().all()
    return {
        "reports": [
            {
                "id": r.id,
                "content_type": r.content_type,
                "content_id": r.content_id,
                "reason": r.reason,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in reports
        ]
    }


# ── Admin Endpoints ──────────────────────────────────────────────────────

@router.get("/admin/reports")
async def list_reports(
    status: str = Query("pending", pattern="^(pending|reviewed|resolved|dismissed|all)$"),
    content_type: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """List reports for admin moderation queue."""
    # TODO: Add proper admin role check
    query = select(ReportRow)
    if status != "all":
        query = query.where(ReportRow.status == status)
    if content_type:
        query = query.where(ReportRow.content_type == content_type)

    query = query.order_by(ReportRow.created_at.desc()).offset(offset).limit(limit)
    result = await session.execute(query)
    reports = result.scalars().all()

    # Get count
    count_query = select(func.count(ReportRow.id))
    if status != "all":
        count_query = count_query.where(ReportRow.status == status)
    total = (await session.execute(count_query)).scalar() or 0

    return {
        "reports": [
            {
                "id": r.id,
                "reporter_id": r.reporter_id,
                "content_type": r.content_type,
                "content_id": r.content_id,
                "reason": r.reason,
                "details": r.details,
                "status": r.status,
                "admin_notes": r.admin_notes,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
            }
            for r in reports
        ],
        "total": total,
    }


@router.patch("/admin/reports/{report_id}")
async def update_report(
    report_id: str,
    body: ReportUpdateRequest,
    user: UserRow = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Update report status (admin)."""
    result = await session.execute(
        select(ReportRow).where(ReportRow.id == report_id)
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    report.status = body.status
    if body.admin_notes:
        report.admin_notes = body.admin_notes
    if body.status in ("resolved", "dismissed"):
        report.resolved_at = datetime.now(timezone.utc)

    await session.commit()
    return {"id": report.id, "status": report.status, "message": "Report updated"}
