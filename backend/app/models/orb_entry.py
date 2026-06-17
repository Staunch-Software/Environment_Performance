import uuid
from datetime import date
from typing import Optional
from sqlalchemy import String, Text, Float, Date, ForeignKey
from sqlalchemy.orm import mapped_column, Mapped
from sqlalchemy.dialects.postgresql import UUID
from app.models.base import Base, TimestampMixin


class OrbEntry(Base, TimestampMixin):
    __tablename__ = "orb_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    upload_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("orb_uploads.id"), nullable=False, index=True)
    vessel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("vessels.id"), nullable=False, index=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    orb_code: Mapped[str] = mapped_column(String(5), nullable=False)
    item_number: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    operation_description: Mapped[str] = mapped_column(Text, nullable=False)
    tank_location: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    time_start: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    time_stop: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    position_start: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    position_stop: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    officer_1_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    officer_1_rank: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    officer_2_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    officer_2_rank: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    raw_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
