"""persist the club 1-5 recruitment composite (player_scorecards)

The scorecard was computed live in the dashboard only, so the offline shortlist pipeline
and the BI layer still read the retired Quality/Fit model. This table stores the live
ranking model so every consumer sees the same numbers.

One row per player-season PER ARCHETYPE ('All Metrics' for everyone, plus the club
archetypes for Full Back / Winger). Additive: no existing table is touched.

Revision ID: d8a3c5e17b40
Revises: c1f4b7e29a30
Create Date: 2026-08-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d8a3c5e17b40"
down_revision: Union[str, None] = "c1f4b7e29a30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "player_scorecards",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("player_id", sa.BigInteger(), nullable=False),
        sa.Column("competition_id", sa.Integer(), nullable=False),
        sa.Column("season_id", sa.Integer(), nullable=False),
        sa.Column("position_group", sa.String(), nullable=False),
        sa.Column("archetype", sa.String(), nullable=False),
        sa.Column("performance_band", sa.Float(), nullable=True),
        sa.Column("physical_band", sa.Float(), nullable=True),
        # Financial/Resale are MODELLED (wage grid + valuation regression): screening only.
        sa.Column("financial_band", sa.Float(), nullable=True),
        sa.Column("resale_band", sa.Float(), nullable=True),
        sa.Column("objective_composite", sa.Float(), nullable=True),
        sa.Column("objective_weight_covered", sa.Float(), nullable=True),
        sa.Column("full_composite", sa.Float(), nullable=True),
        sa.Column("full_weight_covered", sa.Float(), nullable=True),
        sa.Column("veto", sa.Boolean(), nullable=True),
        sa.Column("below_min_composite", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(["player_id"], ["players.player_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("player_id", "competition_id", "season_id", "archetype",
                            name="uq_scorecard_player_competition_season_archetype"),
    )
    op.create_index(op.f("ix_player_scorecards_player_id"), "player_scorecards", ["player_id"])
    op.create_index(op.f("ix_player_scorecards_competition_id"), "player_scorecards", ["competition_id"])
    op.create_index(op.f("ix_player_scorecards_season_id"), "player_scorecards", ["season_id"])
    op.create_index(op.f("ix_player_scorecards_position_group"), "player_scorecards", ["position_group"])
    op.create_index(op.f("ix_player_scorecards_archetype"), "player_scorecards", ["archetype"])


def downgrade() -> None:
    op.drop_table("player_scorecards")
