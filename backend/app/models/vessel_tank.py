import uuid
from sqlalchemy import String, Float, Boolean, ForeignKey, UniqueConstraint
from typing import Optional 
from sqlalchemy.orm import mapped_column, Mapped
from sqlalchemy.dialects.postgresql import UUID
from app.models.base import Base, TimestampMixin


class VesselTank(Base, TimestampMixin):
    __tablename__ = "vessel_tanks"
    __table_args__ = (UniqueConstraint("vessel_id", "tank_code", name="uq_vessel_tank_code"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vessel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("vessels.id"), nullable=False, index=True)
    tank_name: Mapped[str] = mapped_column(String(200), nullable=False)
    tank_code: Mapped[str] = mapped_column(String(50), nullable=False)
    tank_group: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    capacity_m3: Mapped[float] = mapped_column(Float, nullable=False)
    is_iopp: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_evaporation_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
