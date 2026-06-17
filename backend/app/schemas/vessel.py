import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class VesselCreate(BaseModel):
    name: str
    imo_number: str
    call_sign: Optional[str] = None


class VesselUpdate(BaseModel):
    name: Optional[str] = None
    imo_number: Optional[str] = None
    call_sign: Optional[str] = None
    is_active: Optional[bool] = None


class VesselResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    imo_number: str
    call_sign: Optional[str] = None
    is_active: bool
    created_by: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime
