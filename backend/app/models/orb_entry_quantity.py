import uuid
from typing import Optional
from sqlalchemy import String, Float, ForeignKey
from sqlalchemy.orm import mapped_column, Mapped
from sqlalchemy.dialects.postgresql import UUID
from app.models.base import Base, TimestampMixin


class OrbEntryQuantity(Base, TimestampMixin):
    __tablename__ = "orb_entry_quantities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entry_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("orb_entries.id"), nullable=False, index=True)
    qty_type: Mapped[str] = mapped_column(String(20), nullable=False)
    qty_value: Mapped[float] = mapped_column(Float, nullable=False)
    qty_unit: Mapped[str] = mapped_column(String(10), nullable=False, default="m3")
    from_tank: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    to_tank: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
