"""player_detail_metrics: display-only zones, Impect scores, possession-split physical

Revision ID: b4d1e7a90c21
Revises: 26e5e1b5fff3
Create Date: 2026-10-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b4d1e7a90c21'
down_revision: Union[str, None] = '26e5e1b5fff3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "player_detail_metrics",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("player_id", sa.BigInteger(), nullable=False),
        sa.Column("competition_id", sa.Integer(), nullable=False),
        sa.Column("season_id", sa.Integer(), nullable=False),
        sa.Column("metric", sa.String(), nullable=False),
        sa.Column("value_p90", sa.Float(), nullable=False),
        sa.Column("total", sa.Float(), nullable=True),
        sa.UniqueConstraint("player_id", "competition_id", "season_id", "metric",
                            name="uq_detail_player_comp_season_metric"),
    )
    op.create_index("ix_player_detail_metrics_player_id", "player_detail_metrics", ["player_id"])
    op.create_index("ix_detail_pool_metric", "player_detail_metrics",
                    ["competition_id", "season_id", "metric"])


def downgrade() -> None:
    op.drop_index("ix_detail_pool_metric", table_name="player_detail_metrics")
    op.drop_index("ix_player_detail_metrics_player_id", table_name="player_detail_metrics")
    op.drop_table("player_detail_metrics")
