"""store the club composite on the shortlist (the column it now ranks on)

The shortlist ranks on the club's objective 1-5 composite instead of the retired Style-fit,
so the number it ranked on must be stored alongside the row. full_composite (which adds the
MODELLED money dimensions) is carried for reference only and never orders the list.

Revision ID: e2f7b91c6a55
Revises: d8a3c5e17b40
Create Date: 2026-08-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e2f7b91c6a55"
down_revision: Union[str, None] = "d8a3c5e17b40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = ["objective_composite", "full_composite"]


def upgrade() -> None:
    for col in _COLUMNS:
        op.add_column("shortlists", sa.Column(col, sa.Float(), nullable=True))


def downgrade() -> None:
    for col in _COLUMNS:
        op.drop_column("shortlists", col)
