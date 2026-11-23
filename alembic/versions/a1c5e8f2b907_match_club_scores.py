"""match_club_scores: the club's own per-game Performance / Physical / Overall (display only)

Revision ID: a1c5e8f2b907
Revises: f3a9d2c6b814
Create Date: 2026-11-23

Owner 2026-11-23 (N21): the club framework applied to one game, from Impect's per-match KPIs
and SkillCorner's per-match physical rows (`lofc.model.game_scoring`), so staff can see and
check each game on the club's terms. One row per player per game: each metric's game total
and per-90 value (JSON), its percentile in the pool of 45+ minute games at the position in that
league season, the 1-5 bands and "better than X%". `impect_matches.kpis_pulled_at` marks the
games whose KPIs are in. DISPLAY ONLY: nothing in scoring reads this table (register P11).
Size: ~5,000 rows per league season, ~10 KB each in JSON -> ~50 MB per league season at most.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a1c5e8f2b907'
down_revision: Union[str, None] = 'f3a9d2c6b814'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("impect_matches", sa.Column("kpis_pulled_at", sa.DateTime(), nullable=True))
    op.create_table(
        "player_match_club",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("match_id", sa.Integer(), nullable=False),
        sa.Column("impect_player_id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.BigInteger(), nullable=True),          # ours; NULL = not linked
        sa.Column("competition_id", sa.Integer(), nullable=False),
        sa.Column("season_id", sa.Integer(), nullable=False),
        sa.Column("position_group", sa.String(), nullable=True),
        sa.Column("minutes", sa.Float(), nullable=True),
        sa.Column("phys_minutes", sa.Float(), nullable=True),
        sa.Column("perf", sa.JSON(), nullable=True),
        sa.Column("phys", sa.JSON(), nullable=True),
        sa.Column("metric_pcts", sa.JSON(), nullable=True),
        sa.Column("performance", sa.Float(), nullable=True),
        sa.Column("physical", sa.Float(), nullable=True),
        sa.Column("overall", sa.Float(), nullable=True),
        sa.Column("performance_pct", sa.Float(), nullable=True),
        sa.Column("physical_pct", sa.Float(), nullable=True),
        sa.Column("overall_pct", sa.Float(), nullable=True),
        sa.UniqueConstraint("match_id", "impect_player_id", name="uq_player_match_club"),
    )
    op.create_index("ix_player_match_club_player", "player_match_club", ["player_id"])
    op.create_index("ix_player_match_club_league", "player_match_club", ["competition_id", "season_id"])


def downgrade() -> None:
    op.drop_index("ix_player_match_club_league", table_name="player_match_club")
    op.drop_index("ix_player_match_club_player", table_name="player_match_club")
    op.drop_table("player_match_club")
    op.drop_column("impect_matches", "kpis_pulled_at")
