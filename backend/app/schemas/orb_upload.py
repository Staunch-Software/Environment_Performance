import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class UploadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vessel_id: uuid.UUID
    uploaded_by: uuid.UUID
    original_filename: str
    storage_path: str
    status: str
    error_message: Optional[str] = None
    total_pages: Optional[int] = None
    extracted_entries_count: Optional[int] = 0
    duplicate_entries_skipped: int = 0
    created_at: datetime
    updated_at: datetime


class UploadDetail(UploadResponse):
    vessel_name: Optional[str] = None
    uploader_name: Optional[str] = None
