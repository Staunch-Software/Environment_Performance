"""Add page_number, has_gap_before to orb_entries.

Needed to detect the IMO guidance rule "do not leave any full lines
empty between successive entries" — the extraction model now reports
per-entry page position and whether a blank gap precedes the entry.

Revision ID: 006
Revises: 005
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa

revision = '006'
down_revision = 'add_fuel_consumption_table'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('orb_entries', sa.Column('page_number', sa.Integer(), nullable=True))
    op.add_column('orb_entries', sa.Column('has_gap_before', sa.Boolean(), nullable=True))


def downgrade():
    op.drop_column('orb_entries', 'has_gap_before')
    op.drop_column('orb_entries', 'page_number')
