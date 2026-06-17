import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class TankCreate(BaseModel):
    tank_name: str
    tank_code: str
    tank_group: Optional[str] = None
    capacity_m3: float
    is_iopp: bool = True
    is_evaporation_allowed: bool = False

class TankUpdate(BaseModel):
    tank_name: Optional[str] = None
    tank_code: Optional[str] = None
    tank_group: Optional[str] = None
    capacity_m3: Optional[float] = None
    is_iopp: Optional[bool] = None
    is_evaporation_allowed: Optional[bool] = None
    is_active: Optional[bool] = None


class TankResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vessel_id: uuid.UUID
    tank_name: str
    tank_code: str
    tank_group: Optional[str] = None
    capacity_m3: float
    is_iopp: bool
    is_evaporation_allowed: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime
