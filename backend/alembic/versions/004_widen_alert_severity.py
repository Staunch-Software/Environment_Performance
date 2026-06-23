"""Widen orb_alerts.severity from VARCHAR(10) to VARCHAR(20)

'observation' is 11 chars and overflows the original 10-char column.

Revision ID: 004
Revises: 003
Create Date: 2026-06-23
"""
from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "orb_alerts",
        "severity",
        existing_type=sa.String(10),
        type_=sa.String(20),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "orb_alerts",
        "severity",
        existing_type=sa.String(20),
        type_=sa.String(10),
        existing_nullable=False,
    )
