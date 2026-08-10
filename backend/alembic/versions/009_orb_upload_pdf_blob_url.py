"""Add pdf_blob_url to orb_uploads.

Stores the Azure Blob Storage URL for the original uploaded PDF, so it can
be previewed in the UI without re-reading it from local disk.

Revision ID: 009
Revises: 008
Create Date: 2026-08-07
"""
from alembic import op
import sqlalchemy as sa

revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('orb_uploads', sa.Column('pdf_blob_url', sa.String(1000), nullable=True))


def downgrade():
    op.drop_column('orb_uploads', 'pdf_blob_url')
