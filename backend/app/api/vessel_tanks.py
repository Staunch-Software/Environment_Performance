import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.vessel import Vessel
from app.models.vessel_tank import VesselTank
from app.models.user import User
from app.schemas.vessel_tank import TankCreate, TankUpdate, TankResponse
from app.schemas.common import success
from app.dependencies import get_current_user, require_admin

router = APIRouter(prefix="/vessels", tags=["vessel_tanks"])


@router.get("/{vessel_id}/tanks")
async def list_tanks(
    vessel_id: uuid.UUID,
    grouped: bool = False,   # ← pass ?grouped=true from frontend to get grouped view
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(
        select(VesselTank)
        .where(VesselTank.vessel_id == vessel_id)
        .order_by(VesselTank.tank_group, VesselTank.tank_name)   # ← order by group first
    )
    tanks = result.scalars().all()

    if grouped:
        groups = {}
        for t in tanks:
            key = t.tank_group or "Ungrouped"
            groups.setdefault(key, {"group": key, "tanks": [], "total_capacity_m3": 0.0})
            groups[key]["tanks"].append(TankResponse.model_validate(t).model_dump())
            groups[key]["total_capacity_m3"] += t.capacity_m3
        return success(data=list(groups.values()))

    return success(data=[TankResponse.model_validate(t).model_dump() for t in tanks])

@router.post("/{vessel_id}/tanks")
async def add_tank(
    vessel_id: uuid.UUID,
    body: TankCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(Vessel).where(Vessel.id == vessel_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Vessel not found")

    result = await db.execute(
        select(VesselTank).where(
            VesselTank.vessel_id == vessel_id,
            VesselTank.tank_code == body.tank_code,
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Tank code already exists for this vessel")

    tank = VesselTank(
        id=uuid.uuid4(),
        vessel_id=vessel_id,
        tank_name=body.tank_name,
        tank_code=body.tank_code,
        tank_group=body.tank_group, 
        capacity_m3=body.capacity_m3,
        is_iopp=body.is_iopp,
        is_evaporation_allowed=body.is_evaporation_allowed,
        is_active=True,
    )
    db.add(tank)
    await db.commit()
    await db.refresh(tank)
    return success(data=TankResponse.model_validate(tank).model_dump(), message="Tank added")


@router.put("/{vessel_id}/tanks/{tank_id}")
async def update_tank(
    vessel_id: uuid.UUID,
    tank_id: uuid.UUID,
    body: TankUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(
        select(VesselTank).where(VesselTank.id == tank_id, VesselTank.vessel_id == vessel_id)
    )
    tank = result.scalar_one_or_none()
    if not tank:
        raise HTTPException(status_code=404, detail="Tank not found")

    for field, val in body.model_dump(exclude_none=True).items():
        setattr(tank, field, val)

    await db.commit()
    await db.refresh(tank)
    return success(data=TankResponse.model_validate(tank).model_dump(), message="Tank updated")


@router.patch("/{vessel_id}/tanks/{tank_id}/deactivate")
async def deactivate_tank(
    vessel_id: uuid.UUID,
    tank_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(
        select(VesselTank).where(VesselTank.id == tank_id, VesselTank.vessel_id == vessel_id)
    )
    tank = result.scalar_one_or_none()
    if not tank:
        raise HTTPException(status_code=404, detail="Tank not found")
    tank.is_active = False
    await db.commit()
    return success(message="Tank deactivated")
