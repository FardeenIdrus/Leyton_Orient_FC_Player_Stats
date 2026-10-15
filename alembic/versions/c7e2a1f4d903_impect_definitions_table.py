"""impect_definitions: Impect's KPI glossary in Postgres (the prod dashboard reads only Postgres)

Revision ID: c7e2a1f4d903
Revises: b4d1e7a90c21
Create Date: 2026-10-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c7e2a1f4d903'
down_revision: Union[str, None] = 'b4d1e7a90c21'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "impect_definitions",
        sa.Column("column", sa.String(), primary_key=True),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("official_definition", sa.Text(), nullable=True),
        sa.Column("meaning", sa.Text(), nullable=True),
        sa.Column("parent_kpi", sa.String(), nullable=True),
        sa.Column("inverted", sa.Boolean(), nullable=True),
        sa.Column("context_name", sa.String(), nullable=True),
        sa.Column("context_label", sa.String(), nullable=True),
        sa.Column("context_definition", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("impect_definitions")
