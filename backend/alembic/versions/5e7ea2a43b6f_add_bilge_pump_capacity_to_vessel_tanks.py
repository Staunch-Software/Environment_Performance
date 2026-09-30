"""add bilge pump capacity to vessel tanks

Revision ID: 5e7ea2a43b6f

Revises: 009

Create Date: 2026-09-30 11:10:38.028869

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '5e7ea2a43b6f'
down_revision: Union[str, None] = '009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'vessel_tanks',
        sa.Column(
            'bilge_pump_capacity_m3_per_hr',
            sa.Float(),
            nullable=True
        )
    )


def downgrade() -> None:
    op.drop_column(
        'vessel_tanks',
        'bilge_pump_capacity_m3_per_hr'
    )