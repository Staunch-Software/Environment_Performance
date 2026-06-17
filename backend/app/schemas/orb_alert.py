import uuid
from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel, ConfigDict


class AlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vessel_id: uuid.UUID
    entry_id: Optional[uuid.UUID] = None
    alert_type: str
    severity: str
    message: str
    is_resolved: bool
    resolved_by: Optional[uuid.UUID] = None
    resolved_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class ResolveRequest(BaseModel):
    notes: Optional[str] = ""


class AlertSummary(BaseModel):
    total: int
    critical: int
    major: int
    minor: int
    observation: int
    by_type: dict
