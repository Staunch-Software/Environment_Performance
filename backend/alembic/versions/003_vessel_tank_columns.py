"""Add tank_group, is_iopp, is_evaporation_allowed to vessel_tanks.

These columns exist on the VesselTank model but were never added by a
migration (model drifted ahead of the schema). server_default values are
set so the NOT NULL booleans apply cleanly to any existing rows.

Revision ID: 003
Revises: 002
Create Date: 2026-06-19
"""
from alembic import op
import sqlalchemy as sa

revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('vessel_tanks', sa.Column('tank_group', sa.String(100), nullable=True))
    op.add_column('vessel_tanks', sa.Column('is_iopp', sa.Boolean(), nullable=False, server_default='true'))
    op.add_column('vessel_tanks', sa.Column('is_evaporation_allowed', sa.Boolean(), nullable=False, server_default='false'))


def downgrade():
    op.drop_column('vessel_tanks', 'is_evaporation_allowed')
    op.drop_column('vessel_tanks', 'is_iopp')
    op.drop_column('vessel_tanks', 'tank_group')
