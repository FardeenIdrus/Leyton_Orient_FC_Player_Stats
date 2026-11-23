"""match_scores: Impect fixtures and per-match player scores (monitoring only)

Revision ID: f3a9d2c6b814
Revises: e7b2c4d9f031
Create Date: 2026-11-23

Owner 2026-11-23 (phase 4): per-match IMPECT, Offensive and Defensive IMPECT scores for the
English leagues, as raw match totals (Impect's default view), with each game's percentile
within league + season + position (games of 45+ minutes) and its level (Top > 80, Average,
Low < 20). Filled by `python -m lofc.ingest.impect_matches` (pipeline step "Match scores").
MONITORING ONLY: nothing in scoring reads these tables (register P11).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f3a9d2c6b814'
down_revision: Union[str, None] = 'e7b2c4d9f031'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "impect_matches",
        sa.Column("match_id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("iteration_id", sa.Integer(), nullable=False),
        sa.Column("competition_id", sa.Integer(), nullable=False),
        sa.Column("season_id", sa.Integer(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(), nullable=True),
        sa.Column("home_squad_id", sa.Integer(), nullable=True),
        sa.Column("away_squad_id", sa.Integer(), nullable=True),
        sa.Column("home_name", sa.String(), nullable=True),
        sa.Column("away_name", sa.String(), nullable=True),
        sa.Column("home_goals", sa.Integer(), nullable=True),
        sa.Column("away_goals", sa.Integer(), nullable=True),
        sa.Column("available", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_calculated_at", sa.DateTime(), nullable=True),
        sa.Column("scores_pulled_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_impect_matches_league", "impect_matches", ["competition_id", "season_id"])
    op.create_index("ix_impect_matches_date", "impect_matches", ["scheduled_at"])
    op.create_table(
        "player_match_scores",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("match_id", sa.Integer(), nullable=False),
        sa.Column("impect_player_id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.BigInteger(), nullable=True),          # ours; NULL = not linked
        sa.Column("competition_id", sa.Integer(), nullable=False),
        sa.Column("season_id", sa.Integer(), nullable=False),
        sa.Column("squad_id", sa.Integer(), nullable=True),
        sa.Column("position_group", sa.String(), nullable=True),
        sa.Column("minutes", sa.Float(), nullable=True),
        sa.Column("impect", sa.Float(), nullable=True),
        sa.Column("offensive", sa.Float(), nullable=True),
        sa.Column("defensive", sa.Float(), nullable=True),
        sa.Column("impect_pct", sa.Float(), nullable=True),
        sa.Column("offensive_pct", sa.Float(), nullable=True),
        sa.Column("defensive_pct", sa.Float(), nullable=True),
        sa.UniqueConstraint("match_id", "impect_player_id", name="uq_player_match_scores"),
    )
    op.create_index("ix_player_match_scores_player", "player_match_scores", ["player_id"])
    op.create_index("ix_player_match_scores_league", "player_match_scores",
                    ["competition_id", "season_id", "position_group"])


def downgrade() -> None:
    op.drop_index("ix_player_match_scores_league", table_name="player_match_scores")
    op.drop_index("ix_player_match_scores_player", table_name="player_match_scores")
    op.drop_table("player_match_scores")
    op.drop_index("ix_impect_matches_date", table_name="impect_matches")
    op.drop_index("ix_impect_matches_league", table_name="impect_matches")
    op.drop_table("impect_matches")
