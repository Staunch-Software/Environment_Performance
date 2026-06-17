import uuid
from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.vessel import Vessel
from app.models.user import User
from app.schemas.vessel import VesselCreate, VesselUpdate, VesselResponse
from app.schemas.common import success
from app.dependencies import get_current_user, require_admin

router = APIRouter(prefix="/vessels", tags=["vessels"])


@router.get("")
async def list_vessels(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(Vessel).where(Vessel.is_active == True).order_by(Vessel.name))
    vessels = result.scalars().all()
    return success(data=[VesselResponse.model_validate(v).model_dump() for v in vessels])


@router.post("")
async def create_vessel(
    body: VesselCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = await db.execute(select(Vessel).where(Vessel.imo_number == body.imo_number))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="IMO number already exists")

    vessel = Vessel(
        id=uuid.uuid4(),
        name=body.name,
        imo_number=body.imo_number,
        call_sign=body.call_sign,
        created_by=current_user.id,
        is_active=True,
    )
    db.add(vessel)
    await db.commit()
    await db.refresh(vessel)
    return success(data=VesselResponse.model_validate(vessel).model_dump(), message="Vessel created")


@router.get("/{vessel_id}")
async def get_vessel(
    vessel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(Vessel).where(Vessel.id == vessel_id))
    vessel = result.scalar_one_or_none()
    if not vessel:
        raise HTTPException(status_code=404, detail="Vessel not found")
    return success(data=VesselResponse.model_validate(vessel).model_dump())


@router.get("/{vessel_id}/daily-log")
async def get_vessel_daily_log(
    vessel_id: uuid.UUID,
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(Vessel).where(Vessel.id == vessel_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Vessel not found")

    from app.services.daily_log import build_daily_log_by_date
    log_data = await build_daily_log_by_date(vessel_id, date_from, date_to, db)
    return success(data=log_data)


@router.put("/{vessel_id}")
async def update_vessel(
    vessel_id: uuid.UUID,
    body: VesselUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(Vessel).where(Vessel.id == vessel_id))
    vessel = result.scalar_one_or_none()
    if not vessel:
        raise HTTPException(status_code=404, detail="Vessel not found")

    for field, val in body.model_dump(exclude_none=True).items():
        setattr(vessel, field, val)

    await db.commit()
    await db.refresh(vessel)
    return success(data=VesselResponse.model_validate(vessel).model_dump(), message="Vessel updated")
