"""impect_squad_minutes: minutes per club, per player, per league-season (Impect)

Revision ID: d3e8a1c5f720
Revises: a1d4f6b8c902
Create Date: 2026-11-16

Filled by `python -m lofc.model.squad_minutes` (pipeline step "Squad minutes", after
"Current club") from the Impect averages files already landed. No API call. Display only:
the Squads & loans page reads it; nothing in scoring does.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd3e8a1c5f720'
down_revision: Union[str, None] = 'a1d4f6b8c902'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "impect_squad_minutes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("player_id", sa.BigInteger(), nullable=False),
        sa.Column("impect_squad_id", sa.Integer(), nullable=False),
        sa.Column("team_name", sa.String(), nullable=True),
        sa.Column("competition_id", sa.Integer(), nullable=False),
        sa.Column("season_id", sa.Integer(), nullable=False),
        sa.Column("minutes", sa.Float(), nullable=False),
        sa.Column("position_group", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("player_id", "impect_squad_id", "competition_id", "season_id",
                            name="uq_impect_squad_minutes"),
    )
    op.create_index("ix_impect_squad_minutes_player_id", "impect_squad_minutes", ["player_id"])
    op.create_index("ix_impect_squad_minutes_league", "impect_squad_minutes",
                    ["competition_id", "season_id"])


def downgrade() -> None:
    op.drop_index("ix_impect_squad_minutes_league", table_name="impect_squad_minutes")
    op.drop_index("ix_impect_squad_minutes_player_id", table_name="impect_squad_minutes")
    op.drop_table("impect_squad_minutes")
