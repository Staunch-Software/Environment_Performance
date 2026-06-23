import uuid
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete

from app.database import get_db
from app.models.orb_alert import OrbAlert
from app.models.orb_upload import OrbUpload
from app.models.user import User
from app.schemas.orb_alert import AlertResponse, ResolveRequest, AlertSummary
from app.schemas.common import success
from app.dependencies import get_current_user
from app.services.calculations import run_all_checks

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("/summary")
async def alert_summary(
    vessel_id: Optional[uuid.UUID] = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = select(OrbAlert).where(OrbAlert.is_resolved == False)
    if vessel_id:
        q = q.where(OrbAlert.vessel_id == vessel_id)
    result = await db.execute(q)
    alerts = result.scalars().all()

    by_type = {}
    counts = {"critical": 0, "major": 0, "minor": 0, "observation": 0}
    for a in alerts:
        counts[a.severity] = counts.get(a.severity, 0) + 1
        by_type[a.alert_type] = by_type.get(a.alert_type, 0) + 1

    return success(data={
        "total": len(alerts),
        **counts,
        "by_type": by_type,
    })


@router.get("")
async def list_alerts(
    vessel_id: Optional[uuid.UUID] = None,
    severity: Optional[str] = None,
    is_resolved: Optional[bool] = None,
    alert_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = select(OrbAlert).order_by(OrbAlert.created_at.desc())
    if vessel_id:
        q = q.where(OrbAlert.vessel_id == vessel_id)
    if severity:
        q = q.where(OrbAlert.severity == severity)
    if is_resolved is not None:
        q = q.where(OrbAlert.is_resolved == is_resolved)
    if alert_type:
        q = q.where(OrbAlert.alert_type == alert_type)

    result = await db.execute(q)
    alerts = result.scalars().all()
    return success(data=[AlertResponse.model_validate(a).model_dump() for a in alerts])


@router.get("/{alert_id}")
async def get_alert(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(OrbAlert).where(OrbAlert.id == alert_id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return success(data=AlertResponse.model_validate(alert).model_dump())


@router.post("/recalculate")
async def recalculate_alerts(
    vessel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete all unresolved alerts for a vessel and rerun all compliance checks."""
    # 1. Delete all unresolved alerts for the vessel
    deleted = await db.execute(
        delete(OrbAlert).where(
            OrbAlert.vessel_id == vessel_id,
            OrbAlert.is_resolved == False,
        )
    )
    await db.flush()

    # 2. Re-run checks for every completed upload belonging to this vessel
    uploads_result = await db.execute(
        select(OrbUpload).where(
            OrbUpload.vessel_id == vessel_id,
            OrbUpload.status == "completed",
        )
    )
    uploads = uploads_result.scalars().all()

    for upload in uploads:
        await run_all_checks(vessel_id, upload.id, db)

    return success(message=f"Recalculated alerts for vessel. Cleared {deleted.rowcount} stale alerts, processed {len(uploads)} upload(s).")


@router.patch("/{alert_id}/resolve")
async def resolve_alert(
    alert_id: uuid.UUID,
    body: ResolveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(OrbAlert).where(OrbAlert.id == alert_id))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    if alert.is_resolved:
        raise HTTPException(status_code=400, detail="Alert already resolved")

    alert.is_resolved = True
    alert.resolved_by = current_user.id
    alert.resolved_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(alert)
    return success(data=AlertResponse.model_validate(alert).model_dump(), message="Alert resolved")
