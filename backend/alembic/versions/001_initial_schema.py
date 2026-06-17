"""initial_schema

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="viewer"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("last_login", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "vessels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("imo_number", sa.String(20), nullable=False, unique=True),
        sa.Column("call_sign", sa.String(20), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_vessels_imo_number", "vessels", ["imo_number"], unique=True)

    op.create_table(
        "vessel_tanks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("vessel_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("vessels.id"), nullable=False),
        sa.Column("tank_name", sa.String(200), nullable=False),
        sa.Column("tank_code", sa.String(50), nullable=False),
        sa.Column("capacity_m3", sa.Float, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("vessel_id", "tank_code", name="uq_vessel_tank_code"),
    )
    op.create_index("ix_vessel_tanks_vessel_id", "vessel_tanks", ["vessel_id"])

    op.create_table(
        "orb_uploads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("vessel_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("vessels.id"), nullable=False),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("storage_path", sa.String(500), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("total_pages", sa.Integer, nullable=True),
        sa.Column("extracted_entries_count", sa.Integer, nullable=True, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_orb_uploads_vessel_id", "orb_uploads", ["vessel_id"])

    op.create_table(
        "orb_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("upload_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orb_uploads.id"), nullable=False),
        sa.Column("vessel_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("vessels.id"), nullable=False),
        sa.Column("entry_date", sa.Date, nullable=False),
        sa.Column("orb_code", sa.String(5), nullable=False),
        sa.Column("item_number", sa.String(10), nullable=True),
        sa.Column("operation_description", sa.Text, nullable=False),
        sa.Column("tank_location", sa.String(300), nullable=True),
        sa.Column("time_start", sa.String(50), nullable=True),
        sa.Column("time_stop", sa.String(50), nullable=True),
        sa.Column("position_start", sa.String(100), nullable=True),
        sa.Column("position_stop", sa.String(100), nullable=True),
        sa.Column("officer_1_name", sa.String(100), nullable=True),
        sa.Column("officer_1_rank", sa.String(50), nullable=True),
        sa.Column("officer_2_name", sa.String(100), nullable=True),
        sa.Column("officer_2_rank", sa.String(50), nullable=True),
        sa.Column("raw_text", sa.Text, nullable=True),
        sa.Column("confidence_score", sa.Float, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_orb_entries_upload_id", "orb_entries", ["upload_id"])
    op.create_index("ix_orb_entries_vessel_id", "orb_entries", ["vessel_id"])
    op.create_index("ix_orb_entries_entry_date", "orb_entries", ["entry_date"])

    op.create_table(
        "orb_entry_quantities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("entry_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orb_entries.id"), nullable=False),
        sa.Column("qty_type", sa.String(20), nullable=False),
        sa.Column("qty_value", sa.Float, nullable=False),
        sa.Column("qty_unit", sa.String(10), nullable=False, server_default="m3"),
        sa.Column("from_tank", sa.String(200), nullable=True),
        sa.Column("to_tank", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_orb_entry_quantities_entry_id", "orb_entry_quantities", ["entry_id"])

    op.create_table(
        "orb_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("vessel_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("vessels.id"), nullable=False),
        sa.Column("entry_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orb_entries.id"), nullable=True),
        sa.Column("alert_type", sa.String(50), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("is_resolved", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("resolved_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_orb_alerts_vessel_id", "orb_alerts", ["vessel_id"])


def downgrade() -> None:
    op.drop_table("orb_alerts")
    op.drop_table("orb_entry_quantities")
    op.drop_table("orb_entries")
    op.drop_table("orb_uploads")
    op.drop_table("vessel_tanks")
    op.drop_table("vessels")
    op.drop_table("users")
