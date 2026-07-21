import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.vessel import Vessel
from app.models.vessel_tank import VesselTank
from app.models.user import User
from app.schemas.vessel_tank import TankResponse
from app.schemas.common import success
from app.dependencies import get_current_user, require_admin
from app.services.azure_storage import upload_iopp_document, download_iopp_document

router = APIRouter(prefix="/vessels", tags=["vessel_tanks"])


@router.get("/{vessel_id}/tanks")
async def list_tanks(
    vessel_id: uuid.UUID,
    grouped: bool = False,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(
        select(VesselTank)
        .where(VesselTank.vessel_id == vessel_id)
        .order_by(VesselTank.tank_group, VesselTank.tank_name)
    )
    tanks = result.scalars().all()

    if grouped:
        groups = {}
        for t in tanks:
            key = t.tank_group or "Ungrouped"
            # FIX: Ensure capacity is treated as 0.0 if None
            tank_capacity = t.capacity_m3 if t.capacity_m3 is not None else 0.0
            
            if key not in groups:
                groups[key] = {"group": key, "tanks": [], "total_capacity_m3": 0.0}
            
            groups[key]["tanks"].append(TankResponse.model_validate(t).model_dump())
            groups[key]["total_capacity_m3"] += tank_capacity
        return success(data=list(groups.values()))

    # For the non-grouped return, you might also have NaN in the list
    # Let's ensure the data sent is clean
    response_data = []
    for t in tanks:
        data = TankResponse.model_validate(t).model_dump()
        # Ensure numbers aren't None before sending to JSON
        data['capacity_m3'] = data.get('capacity_m3') or 0.0
        response_data.append(data)
        
    return success(data=response_data)

async def _store_iopp_docs(iopp_doc1: Optional[UploadFile], iopp_doc2: Optional[UploadFile]):
    """Upload whichever of the two IOPP files were actually provided — at
    least one is required for an IOPP tank, but both are optional individually."""
    doc1_url = None
    doc2_url = None
    if iopp_doc1:
        doc1_url = await upload_iopp_document(await iopp_doc1.read(), iopp_doc1.filename, iopp_doc1.content_type)
    if iopp_doc2:
        doc2_url = await upload_iopp_document(await iopp_doc2.read(), iopp_doc2.filename, iopp_doc2.content_type)
    return doc1_url, doc2_url


@router.post("/{vessel_id}/tanks")
async def add_tank(
    vessel_id: uuid.UUID,
    tank_name: str = Form(...),
    tank_code: str = Form(...),
    tank_group: Optional[str] = Form(None),
    capacity_m3: float = Form(...),
    is_iopp: bool = Form(True),
    is_evaporation_allowed: bool = Form(False),
    iopp_doc1: Optional[UploadFile] = File(None),
    iopp_doc2: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(Vessel).where(Vessel.id == vessel_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Vessel not found")

    result = await db.execute(
        select(VesselTank).where(
            VesselTank.vessel_id == vessel_id,
            VesselTank.tank_code == tank_code,
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Tank code already exists for this vessel")

    iopp_doc1_url = iopp_doc2_url = None
    if is_iopp:
        if not iopp_doc1 and not iopp_doc2:
            raise HTTPException(status_code=400, detail="At least one IOPP document is required for an IOPP tank")
        iopp_doc1_url, iopp_doc2_url = await _store_iopp_docs(iopp_doc1, iopp_doc2)

    tank = VesselTank(
        id=uuid.uuid4(),
        vessel_id=vessel_id,
        tank_name=tank_name,
        tank_code=tank_code,
        tank_group=tank_group,
        capacity_m3=capacity_m3,
        is_iopp=is_iopp,
        is_evaporation_allowed=is_evaporation_allowed,
        is_active=True,
        iopp_doc1_url=iopp_doc1_url,
        iopp_doc2_url=iopp_doc2_url,
    )
    db.add(tank)
    await db.commit()
    await db.refresh(tank)
    return success(data=TankResponse.model_validate(tank).model_dump(), message="Tank added")


@router.put("/{vessel_id}/tanks/{tank_id}")
async def update_tank(
    vessel_id: uuid.UUID,
    tank_id: uuid.UUID,
    tank_name: Optional[str] = Form(None),
    tank_code: Optional[str] = Form(None),
    tank_group: Optional[str] = Form(None),
    capacity_m3: Optional[float] = Form(None),
    is_iopp: Optional[bool] = Form(None),
    is_evaporation_allowed: Optional[bool] = Form(None),
    iopp_doc1: Optional[UploadFile] = File(None),
    iopp_doc2: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(
        select(VesselTank).where(VesselTank.id == tank_id, VesselTank.vessel_id == vessel_id)
    )
    tank = result.scalar_one_or_none()
    if not tank:
        raise HTTPException(status_code=404, detail="Tank not found")

    effective_is_iopp = is_iopp if is_iopp is not None else tank.is_iopp
    has_existing_doc = bool(tank.iopp_doc1_url or tank.iopp_doc2_url)
    if effective_is_iopp and not has_existing_doc and not iopp_doc1 and not iopp_doc2:
        raise HTTPException(status_code=400, detail="At least one IOPP document is required for an IOPP tank")

    if iopp_doc1 or iopp_doc2:
        new_doc1_url, new_doc2_url = await _store_iopp_docs(iopp_doc1, iopp_doc2)
        if new_doc1_url:
            tank.iopp_doc1_url = new_doc1_url
        if new_doc2_url:
            tank.iopp_doc2_url = new_doc2_url

    fields = {
        "tank_name": tank_name, "tank_code": tank_code, "tank_group": tank_group,
        "capacity_m3": capacity_m3, "is_iopp": is_iopp, "is_evaporation_allowed": is_evaporation_allowed,
    }
    for field, val in fields.items():
        if val is not None:
            setattr(tank, field, val)

    await db.commit()
    await db.refresh(tank)
    return success(data=TankResponse.model_validate(tank).model_dump(), message="Tank updated")


@router.get("/{vessel_id}/tanks/{tank_id}/iopp-doc/{doc_num}")
async def get_iopp_doc(
    vessel_id: uuid.UUID,
    tank_id: uuid.UUID,
    doc_num: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    if doc_num not in (1, 2):
        raise HTTPException(status_code=404, detail="Document not found")

    result = await db.execute(
        select(VesselTank).where(VesselTank.id == tank_id, VesselTank.vessel_id == vessel_id)
    )
    tank = result.scalar_one_or_none()
    if not tank:
        raise HTTPException(status_code=404, detail="Tank not found")

    blob_url = tank.iopp_doc1_url if doc_num == 1 else tank.iopp_doc2_url
    if not blob_url:
        raise HTTPException(status_code=404, detail="Document not found")

    content, content_type = await download_iopp_document(blob_url)
    return Response(content=content, media_type=content_type)


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
