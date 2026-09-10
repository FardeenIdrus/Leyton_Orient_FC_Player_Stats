"""players on loan, per club, with parent club and loan end date

The only source is Transfermarkt's per-club loan page. Impect carries no registration
data at all -- 25 API endpoints, none about contracts or transfers -- so this cannot come
from the event feed. `loan_ends` is what makes the table useful for the January window: it
separates a player returning to his parent club in the summer from one available now.

Revision ID: c8f1d20a4e65
Revises: b6e2a91f4c73
Create Date: 2026-09-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8f1d20a4e65"
down_revision: Union[str, None] = "b6e2a91f4c73"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "player_loans",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        # Nullable: loans are scraped before identity matching and linked afterwards.
        sa.Column("player_id", sa.BigInteger(), nullable=True),
        sa.Column("tm_player_id", sa.BigInteger(), nullable=True),
        sa.Column("player_name", sa.String(), nullable=False),
        sa.Column("club_name", sa.String(), nullable=False),
        sa.Column("parent_club", sa.String(), nullable=True),
        sa.Column("competition_id", sa.Integer(), nullable=False),
        sa.Column("season_id", sa.Integer(), nullable=False),
        sa.Column("loan_ends", sa.Date(), nullable=True),
        sa.Column("scraped_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tm_player_id", "club_name", "season_id",
                            name="uq_player_loan"),
    )
    for col in ("player_id", "tm_player_id", "club_name", "competition_id", "season_id"):
        op.create_index(f"ix_player_loans_{col}", "player_loans", [col])


def downgrade() -> None:
    op.drop_table("player_loans")
