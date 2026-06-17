import uuid
import os
import hashlib
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import io

from app.config import get_settings
from app.database import get_db, AsyncSessionLocal
from app.models.orb_upload import OrbUpload
from app.models.orb_entry import OrbEntry
from app.models.vessel import Vessel
from app.models.user import User
from app.schemas.orb_upload import UploadResponse, UploadDetail
from app.schemas.orb_entry import EntryResponse
from app.schemas.common import success
from app.dependencies import get_current_user

router = APIRouter(prefix="/uploads", tags=["uploads"])
settings = get_settings()


@router.get("")
async def list_uploads(
    vessel_id: uuid.UUID = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = select(OrbUpload).order_by(OrbUpload.created_at.desc()).limit(50)
    if vessel_id:
        q = q.where(OrbUpload.vessel_id == vessel_id)
    result = await db.execute(q)
    uploads = result.scalars().all()
    return success(data=[UploadResponse.model_validate(u).model_dump() for u in uploads])


@router.post("")
async def create_upload(
    background_tasks: BackgroundTasks,
    vessel_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    content = await file.read()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(status_code=400, detail=f"File exceeds {settings.MAX_UPLOAD_SIZE_MB} MB limit")

    result = await db.execute(select(Vessel).where(Vessel.id == vessel_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Vessel not found")

    # ── Layer 1: file-hash duplicate check ───────────────────────────────────
    file_hash = hashlib.sha256(content).hexdigest()
    existing = await db.execute(
        select(OrbUpload).where(
            OrbUpload.vessel_id == vessel_id,
            OrbUpload.file_hash == file_hash,
            OrbUpload.status == "completed",
        )
    )
    duplicate_upload = existing.scalar_one_or_none()
    if duplicate_upload:
        raise HTTPException(
            status_code=409,
            detail=(
                f"This exact file has already been uploaded and processed for this vessel "
                f"(upload id: {duplicate_upload.id}, file: {duplicate_upload.original_filename}). "
                f"Uploading the same file twice would create duplicate ORB entries."
            ),
        )

    upload_id = uuid.uuid4()
    vessel_dir = os.path.join(settings.UPLOAD_DIR, str(vessel_id))
    os.makedirs(vessel_dir, exist_ok=True)
    storage_path = os.path.join(vessel_dir, f"{upload_id}_{file.filename}")

    with open(storage_path, "wb") as f:
        f.write(content)

    upload = OrbUpload(
        id=upload_id,
        vessel_id=vessel_id,
        uploaded_by=current_user.id,
        original_filename=file.filename,
        storage_path=storage_path,
        status="pending",
        extracted_entries_count=0,
        file_hash=file_hash,
        duplicate_entries_skipped=0,
    )
    db.add(upload)
    await db.commit()
    await db.refresh(upload)

    from app.services.extraction import run_extraction
    background_tasks.add_task(run_extraction, upload_id, storage_path, vessel_id, AsyncSessionLocal)

    return success(data=UploadResponse.model_validate(upload).model_dump(), message="Upload queued for processing")


@router.get("/{upload_id}")
async def get_upload(
    upload_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(OrbUpload).where(OrbUpload.id == upload_id))
    upload = result.scalar_one_or_none()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")

    vessel_result = await db.execute(select(Vessel).where(Vessel.id == upload.vessel_id))
    vessel = vessel_result.scalar_one_or_none()

    uploader_result = await db.execute(select(User).where(User.id == upload.uploaded_by))
    uploader = uploader_result.scalar_one_or_none()

    data = UploadDetail.model_validate(upload).model_dump()
    data["vessel_name"] = vessel.name if vessel else None
    data["uploader_name"] = uploader.name if uploader else None
    return success(data=data)


@router.get("/{upload_id}/entries")
async def get_upload_entries(
    upload_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    from app.models.orb_entry_quantity import OrbEntryQuantity
    result = await db.execute(
        select(OrbEntry).where(OrbEntry.upload_id == upload_id).order_by(OrbEntry.entry_date)
    )
    entries = result.scalars().all()

    data = []
    for entry in entries:
        qty_result = await db.execute(
            select(OrbEntryQuantity).where(OrbEntryQuantity.entry_id == entry.id)
        )
        quantities = qty_result.scalars().all()
        entry_data = EntryResponse.model_validate(entry).model_dump()
        from app.schemas.orb_entry import QuantityResponse
        entry_data["quantities"] = [QuantityResponse.model_validate(q).model_dump() for q in quantities]
        data.append(entry_data)

    return success(data=data)

@router.get("/{upload_id}/daily-log")
async def get_daily_log(
    upload_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(OrbUpload).where(OrbUpload.id == upload_id))
    upload = result.scalar_one_or_none()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")

    from app.services.daily_log import build_daily_log
    log_data = await build_daily_log(upload.vessel_id, upload_id, db)
    return success(data=log_data)

@router.get("/{upload_id}/export/excel")
async def export_excel(
    upload_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(OrbUpload).where(OrbUpload.id == upload_id))
    upload = result.scalar_one_or_none()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")

    from app.services.excel_report import generate_excel
    xlsx_bytes = await generate_excel(upload_id, db)
    filename = f"ORB_Report_{upload.original_filename.replace('.pdf', '')}.xlsx"

    return StreamingResponse(
        io.BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{upload_id}/export/pdf")
async def export_pdf(
    upload_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(OrbUpload).where(OrbUpload.id == upload_id))
    upload = result.scalar_one_or_none()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")

    from app.services.pdf_report import generate_pdf
    pdf_bytes = await generate_pdf(upload_id, db)
    filename = f"ORB_Report_{upload.original_filename.replace('.pdf', '')}.pdf"

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
