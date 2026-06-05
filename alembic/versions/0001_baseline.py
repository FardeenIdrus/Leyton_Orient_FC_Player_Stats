"""baseline: empty schema

Phase 0 baseline so ``alembic upgrade head`` runs clean on an empty database and
stamps a starting revision. The real schema (players, player_season_metrics,
wage_framework, identity_profiles, valuations, archetypes, shortlists) arrives in
Phase 3.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-06-02

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
