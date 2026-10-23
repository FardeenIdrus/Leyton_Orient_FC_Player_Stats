"""player_style_signals: raw playing-style signals per player-season (labels only, never scoring)

Revision ID: d8f3b2c5e104
Revises: c7e2a1f4d903
Create Date: 2026-10-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd8f3b2c5e104'
down_revision: Union[str, None] = 'c7e2a1f4d903'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "player_style_signals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("player_id", sa.BigInteger(), nullable=False),
        sa.Column("competition_id", sa.Integer(), nullable=False),
        sa.Column("season_id", sa.Integer(), nullable=False),
        sa.Column("signal", sa.String(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.UniqueConstraint("player_id", "competition_id", "season_id", "signal",
                            name="uq_style_player_comp_season_signal"),
    )
    op.create_index("ix_style_pool", "player_style_signals", ["competition_id", "season_id"])


def downgrade() -> None:
    op.drop_index("ix_style_pool", table_name="player_style_signals")
    op.drop_table("player_style_signals")
