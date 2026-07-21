"""add fuel_consumption table (WNI fuel scraper, Check 7 support)

Revision ID: add_fuel_consumption_table
Revises: <set to your current head revision>
Create Date: 2026-07-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "add_fuel_consumption_table"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "fuel_consumption",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("vessel_name", sa.String(length=200), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("total_fuel_consumption", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("vessel_name", "report_date", name="uq_fuel_consumption_vessel_date"),
    )
    op.create_index("ix_fuel_consumption_vessel_name", "fuel_consumption", ["vessel_name"])
    op.create_index("ix_fuel_consumption_report_date", "fuel_consumption", ["report_date"])


def downgrade():
    op.drop_index("ix_fuel_consumption_report_date", table_name="fuel_consumption")
    op.drop_index("ix_fuel_consumption_vessel_name", table_name="fuel_consumption")
    op.drop_table("fuel_consumption")