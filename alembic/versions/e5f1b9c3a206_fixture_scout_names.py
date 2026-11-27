"""fixture_scout_names: assign a game to a scout with no platform account (a typed name)

Revision ID: e5f1b9c3a206
Revises: c3e8a1f5d702
Create Date: 2026-11-27

Owner 2026-11-27: most scouts have no login; the head of recruitment types their name.
fixture_assignments.user_id becomes optional and scout_name holds a typed name. USER DATA.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e5f1b9c3a206'
down_revision: Union[str, None] = 'c3e8a1f5d702'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("fixture_assignments", sa.Column("scout_name", sa.String(), nullable=True))
    op.alter_column("fixture_assignments", "user_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM fixture_assignments WHERE user_id IS NULL")
    op.alter_column("fixture_assignments", "user_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("fixture_assignments", "scout_name")
