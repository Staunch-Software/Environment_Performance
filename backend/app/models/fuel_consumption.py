import uuid
from datetime import date as date_type
from sqlalchemy import String, Float, Date, UniqueConstraint
from sqlalchemy.orm import mapped_column, Mapped
from sqlalchemy.dialects.postgresql import UUID
from app.models.base import Base, TimestampMixin


class FuelConsumption(Base, TimestampMixin):
    """Latest-daily fuel consumption per vessel, sourced from the WNI
    Logbook+ fuel scraper (separate from the historical VoyageWNI pipeline).

    One row per (vessel_name, report_date) — upserted by the scraper, never
    holds historical backfill. Feeds ORB compliance Check 7
    (sludge_vs_fuel_consumption).
    """
    __tablename__ = "fuel_consumption"
    __table_args__ = (
        UniqueConstraint("vessel_name", "report_date", name="uq_fuel_consumption_vessel_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vessel_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    report_date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    total_fuel_consumption: Mapped[float] = mapped_column(Float, nullable=False)
    # created_at / updated_at come from TimestampMixin