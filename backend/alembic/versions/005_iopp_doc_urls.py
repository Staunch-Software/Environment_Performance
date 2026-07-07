"""Add iopp_doc1_url, iopp_doc2_url to vessel_tanks.

Stores the Azure Blob Storage URLs for the IOPP certificate/survey
documents required when a tank is marked is_iopp.

Revision ID: 005
Revises: 004
Create Date: 2026-06-24
"""
from alembic import op
import sqlalchemy as sa

revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('vessel_tanks', sa.Column('iopp_doc1_url', sa.String(1000), nullable=True))
    op.add_column('vessel_tanks', sa.Column('iopp_doc2_url', sa.String(1000), nullable=True))


def downgrade():
    op.drop_column('vessel_tanks', 'iopp_doc2_url')
    op.drop_column('vessel_tanks', 'iopp_doc1_url')
