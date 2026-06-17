import uuid
from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict


class QuantityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    entry_id: uuid.UUID
    qty_type: str
    qty_value: float
    qty_unit: str
    from_tank: Optional[str] = None
    to_tank: Optional[str] = None


class EntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    upload_id: uuid.UUID
    vessel_id: uuid.UUID
    entry_date: date
    orb_code: str
    item_number: Optional[str] = None
    operation_description: str
    tank_location: Optional[str] = None
    time_start: Optional[str] = None
    time_stop: Optional[str] = None
    position_start: Optional[str] = None
    position_stop: Optional[str] = None
    officer_1_name: Optional[str] = None
    officer_1_rank: Optional[str] = None
    officer_2_name: Optional[str] = None
    officer_2_rank: Optional[str] = None
    raw_text: Optional[str] = None
    confidence_score: Optional[float] = None
    created_at: datetime
    updated_at: datetime
    quantities: List[QuantityResponse] = []
