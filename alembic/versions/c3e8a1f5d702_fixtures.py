"""fixtures: scout assignments, games added by hand, confirmed scout-report links

Revision ID: c3e8a1f5d702
Revises: a1c5e8f2b907
Create Date: 2026-11-27

Owner 2026-11-27 (phase 5, Fixtures). USER DATA, never written or cleared by the pipeline:
  * fixture_assignments -- which scout goes to which game (key "m:<impect match>" or "x:<added>");
  * manual_fixtures     -- a game a scout adds by hand (EFL Trophy, FA Cup, friendlies: games
                           Impect does not list for us);
  * scout_report_links  -- a person confirmed which player a report is about (G2). The
                           linking stage rewrites every automatic link on each sync; these win.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c3e8a1f5d702'
down_revision: Union[str, None] = 'a1c5e8f2b907'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fixture_assignments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("fixture_key", sa.String(), nullable=False, unique=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("assigned_by", sa.Integer(), nullable=True),
        sa.Column("assigned_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_table(
        "manual_fixtures",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("scheduled_at", sa.DateTime(), nullable=False),
        sa.Column("competition", sa.String(), nullable=True),
        sa.Column("home_name", sa.String(), nullable=False),
        sa.Column("away_name", sa.String(), nullable=False),
        sa.Column("home_squad_id", sa.Integer(), nullable=True),
        sa.Column("away_squad_id", sa.Integer(), nullable=True),
        sa.Column("added_by", sa.Integer(), nullable=True),
        sa.Column("added_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_manual_fixtures_scheduled_at", "manual_fixtures", ["scheduled_at"])
    op.create_table(
        "scout_report_links",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("submission_id", sa.String(), nullable=False, unique=True),
        sa.Column("player_id", sa.BigInteger(), nullable=False),
        sa.Column("linked_by", sa.Integer(), nullable=True),
        sa.Column("linked_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("scout_report_links")
    op.drop_index("ix_manual_fixtures_scheduled_at", table_name="manual_fixtures")
    op.drop_table("manual_fixtures")
    op.drop_table("fixture_assignments")
