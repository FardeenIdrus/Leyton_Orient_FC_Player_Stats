"""goals and assists earned in each position, alongside the minutes split

A player's metrics remain WHOLE-SEASON across every position he played -- splitting them
was considered and rejected, because 23% of all goals and assists in the platform are
earned outside a player's assigned position and removing them would gut real profiles.

These two columns exist so a report can say where the output came from without changing a
single score: "Goals 4 - 2 as attacking mid, 2 as winger, 0 as full back".

Revision ID: b6e2a91f4c73
Revises: a1c4e77b9d20
Create Date: 2026-08-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b6e2a91f4c73"
down_revision: Union[str, None] = "a1c4e77b9d20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable: unknown is not the same claim as zero.
    op.add_column("player_position_shares", sa.Column("goals", sa.Float(), nullable=True))
    op.add_column("player_position_shares", sa.Column("assists", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("player_position_shares", "assists")
    op.drop_column("player_position_shares", "goals")
