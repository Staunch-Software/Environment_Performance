"""Add pages_processed to orb_uploads.

A hung extraction previously looked identical, in the DB, to a large file
that was still legitimately working through its pages -- both just show
status="processing" with no further signal until the whole job finishes.
This column is written after every page (success or failure) so a stuck
job can be told apart from a genuinely slow one at a glance.

Revision ID: 007
Revises: 006
Create Date: 2026-08-04
"""
from alembic import op
import sqlalchemy as sa

revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('orb_uploads', sa.Column('pages_processed', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('orb_uploads', 'pages_processed')
