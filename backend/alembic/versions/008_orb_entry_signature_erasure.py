"""Add master_signature_present, has_erasure to orb_entries.

These columns exist on the OrbEntry model and are read/written by the
extraction and calculations services, but no prior migration ever created
them -- environments built from migrations alone (rather than
`Base.metadata.create_all`) are missing both columns.

Revision ID: 008
Revises: 007
Create Date: 2026-08-06
"""
from alembic import op
import sqlalchemy as sa

revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('orb_entries', sa.Column('master_signature_present', sa.Boolean(), nullable=True))
    op.add_column('orb_entries', sa.Column('has_erasure', sa.Boolean(), nullable=True))


def downgrade():
    op.drop_column('orb_entries', 'has_erasure')
    op.drop_column('orb_entries', 'master_signature_present')
