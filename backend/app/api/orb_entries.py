import uuid
from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.orb_entry import OrbEntry
from app.models.orb_entry_quantity import OrbEntryQuantity
from app.models.user import User
from app.schemas.orb_entry import EntryResponse, QuantityResponse
from app.schemas.common import success
from app.dependencies import get_current_user

router = APIRouter(prefix="/entries", tags=["entries"])


@router.get("")
async def list_entries(
    vessel_id: Optional[uuid.UUID] = None,
    upload_id: Optional[uuid.UUID] = None,
    orb_code: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    confidence_below: Optional[float] = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = select(OrbEntry).order_by(OrbEntry.entry_date.desc())
    if vessel_id:
        q = q.where(OrbEntry.vessel_id == vessel_id)
    if upload_id:
        q = q.where(OrbEntry.upload_id == upload_id)
    if orb_code:
        q = q.where(OrbEntry.orb_code == orb_code)
    if date_from:
        q = q.where(OrbEntry.entry_date >= date_from)
    if date_to:
        q = q.where(OrbEntry.entry_date <= date_to)
    if confidence_below is not None:
        q = q.where(OrbEntry.confidence_score < confidence_below)

    result = await db.execute(q)
    entries = result.scalars().all()

    data = []
    for entry in entries:
        qty_result = await db.execute(select(OrbEntryQuantity).where(OrbEntryQuantity.entry_id == entry.id))
        quantities = qty_result.scalars().all()
        entry_data = EntryResponse.model_validate(entry).model_dump()
        entry_data["quantities"] = [QuantityResponse.model_validate(q).model_dump() for q in quantities]
        data.append(entry_data)

    return success(data=data)


@router.get("/{entry_id}")
async def get_entry(
    entry_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(OrbEntry).where(OrbEntry.id == entry_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    qty_result = await db.execute(select(OrbEntryQuantity).where(OrbEntryQuantity.entry_id == entry.id))
    quantities = qty_result.scalars().all()
    entry_data = EntryResponse.model_validate(entry).model_dump()
    entry_data["quantities"] = [QuantityResponse.model_validate(q).model_dump() for q in quantities]
    return success(data=entry_data)
