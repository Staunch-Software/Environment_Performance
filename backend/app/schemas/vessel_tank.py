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
    # NEW — only meaningful when tank_group == 'BILGE'. Rated pump output in
    # m³/hr, taken from the vessel's pump/IOPP certificate. Optional — checks
    # that depend on it (Check 9) simply skip tanks where this is unset.
    bilge_pump_capacity_m3_per_hr: Optional[float] = None


class TankUpdate(BaseModel):
    tank_name: Optional[str] = None
    tank_code: Optional[str] = None
    tank_group: Optional[str] = None
    capacity_m3: Optional[float] = None
    is_iopp: Optional[bool] = None
    is_evaporation_allowed: Optional[bool] = None
    is_active: Optional[bool] = None
    # NEW
    bilge_pump_capacity_m3_per_hr: Optional[float] = None


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
    iopp_doc1_url: Optional[str] = None
    iopp_doc2_url: Optional[str] = None
    # NEW
    bilge_pump_capacity_m3_per_hr: Optional[float] = None
    created_at: datetime
    updated_at: datetime