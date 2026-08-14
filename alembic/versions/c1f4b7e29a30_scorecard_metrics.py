"""add four club-framework metrics to player_metrics_neutral

Impect stand-ins signed off with Joe: keeper catches, defensive touches outside the box,
crossing bypassed-opponents (high+low), and the actual dribble count. Additive, nullable.

Revision ID: c1f4b7e29a30
Revises: 71204e85d2fb
Create Date: 2026-07-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c1f4b7e29a30"
down_revision: Union[str, None] = "71204e85d2fb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = [
    "gk_catches_p90",
    "defensive_touches_outside_box_p90",
    "cross_bypassed_opponents_p90",
    "dribble_count_p90",
]


def upgrade() -> None:
    for col in _COLUMNS:
        op.add_column("player_metrics_neutral", sa.Column(col, sa.Float(), nullable=True))


def downgrade() -> None:
    for col in _COLUMNS:
        op.drop_column("player_metrics_neutral", col)
