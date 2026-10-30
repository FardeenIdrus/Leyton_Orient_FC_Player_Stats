"""player_current_club: each player's club now, from Impect's currentSquadId

Revision ID: b7c2e9a4d613
Revises: e4a9c7d21b58
Create Date: 2026-10-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b7c2e9a4d613'
down_revision: Union[str, None] = 'e4a9c7d21b58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "player_current_club",
        sa.Column("player_id", sa.BigInteger(), primary_key=True),
        sa.Column("impect_squad_id", sa.Integer(), nullable=False),
        sa.Column("club_name", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("player_current_club")
