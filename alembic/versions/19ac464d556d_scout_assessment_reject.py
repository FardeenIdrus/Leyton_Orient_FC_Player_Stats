"""scout assessment reject

Adds a `rejected` status value alongside the existing draft / submitted / signed_off (no
CHECK constraint on `status`, so this needs no schema change) and one new nullable column,
`rejection_reason`, to carry the mandatory explanation. Additive only: the new column defaults
to NULL, so every existing `scout_assessments` row is untouched and remains readable exactly
as it was. `approved_by` / `approved_at` are reused to record who rejected and when -- those
columns already mean "the reviewer who acted on this and when", not "who approved this",
so a rejection populates them the same way a sign-off does.

Revision ID: 19ac464d556d
Revises: f9b87065fa41
Create Date: 2026-08-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '19ac464d556d'
down_revision: Union[str, None] = 'f9b87065fa41'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('scout_assessments',
                  sa.Column('rejection_reason', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('scout_assessments', 'rejection_reason')
