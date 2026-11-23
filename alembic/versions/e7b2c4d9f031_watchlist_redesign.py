"""watchlist_redesign: stages, owner, next step, due date, snapshot; dismissed suggestions

Revision ID: e7b2c4d9f031
Revises: d3e8a1c5f720
Create Date: 2026-11-23

Owner 2026-11-23 (Watchlist redesign, decision A): one shared list, one entry per player -- the
page shows a player's latest row. NOTHING is merged or deleted here: older rows stay as they are.
Statuses are renamed to the new stages (Scout sent -> Scout to watch, Contact agent -> Agent
contacted; Watching and Dropped unchanged). All new columns are nullable: user data only.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e7b2c4d9f031'
down_revision: Union[str, None] = 'd3e8a1c5f720'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_COLUMNS = [
    sa.Column("drop_reason", sa.String(), nullable=True),
    sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
    sa.Column("next_step", sa.String(), nullable=True),
    sa.Column("due_date", sa.Date(), nullable=True),
    sa.Column("added_by_user_id", sa.Integer(), nullable=True),
    sa.Column("stage_changed_at", sa.DateTime(), nullable=True),
    sa.Column("note_updated_by", sa.Integer(), nullable=True),
    sa.Column("note_updated_at", sa.DateTime(), nullable=True),
    sa.Column("added_rating", sa.Float(), nullable=True),
    sa.Column("added_club", sa.String(), nullable=True),
    sa.Column("added_competition_id", sa.Integer(), nullable=True),
]


def upgrade() -> None:
    for col in _NEW_COLUMNS:
        op.add_column("watchlist", col)
    op.execute("UPDATE watchlist SET status = 'Scout to watch' WHERE status = 'Scout sent'")
    op.execute("UPDATE watchlist SET status = 'Agent contacted' WHERE status = 'Contact agent'")
    op.create_table(
        "watchlist_dismissed",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.BigInteger(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.UniqueConstraint("report_id", name="uq_watchlist_dismissed_report"),
    )
    op.create_index("ix_watchlist_dismissed_report_id", "watchlist_dismissed", ["report_id"])


def downgrade() -> None:
    op.drop_index("ix_watchlist_dismissed_report_id", table_name="watchlist_dismissed")
    op.drop_table("watchlist_dismissed")
    op.execute("UPDATE watchlist SET status = 'Scout sent' WHERE status = 'Scout to watch'")
    op.execute("UPDATE watchlist SET status = 'Contact agent' WHERE status = 'Agent contacted'")
    op.execute("UPDATE watchlist SET status = 'Watching' WHERE status IN ('Shortlisted', 'Signed')")
    for col in reversed(_NEW_COLUMNS):
        op.drop_column("watchlist", col.name)
