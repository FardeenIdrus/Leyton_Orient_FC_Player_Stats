"""skillcorner_match_counts: matches SkillCorner tracked per player and league season

Revision ID: c5d8e1f2a7b9
Revises: b7c2e9a4d613
Create Date: 2026-11-09

Display only (the Physical page's "Tracked matches"). Filled by `python -m
lofc.model.build_neutral --write` from the SkillCorner files already landed under
data/raw/skillcorner/ -- no API call -- and by every weekly pipeline run after that.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c5d8e1f2a7b9'
down_revision: Union[str, None] = 'b7c2e9a4d613'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "skillcorner_match_counts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("player_id", sa.BigInteger(), nullable=False),
        sa.Column("competition_id", sa.Integer(), nullable=False),
        sa.Column("season_id", sa.Integer(), nullable=False),
        sa.Column("matches", sa.Integer(), nullable=False),
        sa.UniqueConstraint("player_id", "competition_id", "season_id",
                            name="uq_sc_matches_player_comp_season"),
    )
    op.create_index("ix_skillcorner_match_counts_player_id", "skillcorner_match_counts",
                    ["player_id"])


def downgrade() -> None:
    op.drop_index("ix_skillcorner_match_counts_player_id", table_name="skillcorner_match_counts")
    op.drop_table("skillcorner_match_counts")
