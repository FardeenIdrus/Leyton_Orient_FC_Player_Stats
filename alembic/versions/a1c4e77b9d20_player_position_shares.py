"""how a player's minutes split across position groups, per league season

The platform assigns ONE position group per player-season -- the group he played most --
and scores him against that group's peers. For most players that is the whole story; for a
utility player it is not. Measured on the live Impect files, 668 of 6,575 rankable
player-seasons (10.2%) are assigned a group holding under half their minutes.

Impect already reports one row per player per position, so the split is a fact we held and
discarded at aggregation. This table keeps it so a report can show it. DISPLAY ONLY --
nothing here feeds scoring or the ranking.

Revision ID: a1c4e77b9d20
Revises: 174d3fc1a80c
Create Date: 2026-08-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1c4e77b9d20"
down_revision: Union[str, None] = "174d3fc1a80c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "player_position_shares",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("player_id", sa.BigInteger(), nullable=False),
        sa.Column("competition_id", sa.Integer(), nullable=False),
        sa.Column("season_id", sa.Integer(), nullable=False),
        sa.Column("position_group", sa.String(), nullable=False),
        sa.Column("minutes", sa.Float(), nullable=False),
        sa.Column("share", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["player_id"], ["players.player_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("player_id", "competition_id", "season_id", "position_group",
                            name="uq_position_share"),
    )
    op.create_index("ix_player_position_shares_player_id", "player_position_shares",
                    ["player_id"])
    op.create_index("ix_player_position_shares_competition_id", "player_position_shares",
                    ["competition_id"])
    op.create_index("ix_player_position_shares_season_id", "player_position_shares",
                    ["season_id"])


def downgrade() -> None:
    op.drop_table("player_position_shares")
