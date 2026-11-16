"""player_scorecards.peer_pool / peer_pool_size: the pool each player was rated in

Revision ID: a1d4f6b8c902
Revises: c5d8e1f2a7b9
Create Date: 2026-11-16

Midfield fallback (owner-approved 2026-11-16): a thin Defensive / Central / Attacking Mid
group is rated against all the league-season's midfielders. These two columns record which
pool ('position' or 'midfield') and its size, so the pages can tag the player. Filled by
`python -m lofc.model.scorecard_run`; NULL until that runs (readers then count as before).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a1d4f6b8c902'
down_revision: Union[str, None] = 'c5d8e1f2a7b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("player_scorecards", sa.Column("peer_pool", sa.String(), nullable=True))
    op.add_column("player_scorecards", sa.Column("peer_pool_size", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("player_scorecards", "peer_pool_size")
    op.drop_column("player_scorecards", "peer_pool")
