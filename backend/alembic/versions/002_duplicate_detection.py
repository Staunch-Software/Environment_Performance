"""Add duplicate detection columns to orb_uploads.

Revision ID: 002
Revises: 001
Create Date: 2026-06-16
"""
from alembic import op
import sqlalchemy as sa

revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('orb_uploads', sa.Column('file_hash', sa.String(64), nullable=True))
    op.add_column('orb_uploads', sa.Column('duplicate_entries_skipped', sa.Integer(), nullable=False, server_default='0'))
    op.create_index('ix_orb_uploads_file_hash', 'orb_uploads', ['file_hash'])


def downgrade():
    op.drop_index('ix_orb_uploads_file_hash', table_name='orb_uploads')
    op.drop_column('orb_uploads', 'duplicate_entries_skipped')
    op.drop_column('orb_uploads', 'file_hash')
