"""Idempotent loaders: put the processed table and reference data into Postgres.

Every loader upserts on a natural key, so running it twice updates rows instead of
duplicating them. Run with:  python -m lofc.store.load
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine

from lofc.config import settings
from lofc.store.models import (
    IdentityProfile,
    Player,
    PlayerSeasonMetric,
    WageFramework,
)

PROCESSED = Path(settings.raw_data_dir).parent / "processed" / "player_season_metrics.parquet"
REFERENCE = Path(settings.reference_data_dir)


def get_engine() -> Engine:
    return create_engine(settings.database_url)


def _records(df: pd.DataFrame) -> list[dict]:
    """DataFrame to row dicts with NaN turned into None (round-trip through JSON)."""
    return json.loads(df.to_json(orient="records"))


def _upsert(engine: Engine, table, rows: list[dict], conflict_cols: list[str]) -> int:
    """Insert rows, updating the non-key columns on conflict. Returns row count."""
    if not rows:
        return 0
    with engine.begin() as conn:
        stmt = pg_insert(table)
        update = {c.name: stmt.excluded[c.name] for c in table.columns
                  if c.name not in conflict_cols and not c.primary_key}
        stmt = stmt.on_conflict_do_update(index_elements=conflict_cols, set_=update)
        conn.execute(stmt, rows)
    return len(rows)


def load_players_and_metrics(engine: Engine) -> tuple[int, int]:
    """Load the Phase 2 table: one players row per player, plus every metrics row."""
    df = pd.read_parquet(PROCESSED)

    # players: one row per player_id, name taken from their highest-minutes season.
    primary = df.sort_values("minutes", ascending=False).drop_duplicates("player_id")
    players = [{"player_id": int(r.player_id), "player_name": r.player_name}
               for r in primary.itertuples()]
    n_players = _upsert(engine, Player.__table__, players, ["player_id"])

    metric_cols = [c.name for c in PlayerSeasonMetric.__table__.columns if c.name != "id"]
    n_metrics = _upsert(engine, PlayerSeasonMetric.__table__, _records(df[metric_cols]),
                        ["player_id", "competition_id", "season_id"])
    return n_players, n_metrics


def load_reference_csv(engine: Engine, filename: str, table, conflict_cols: list[str]) -> int:
    """Load one reference CSV (wage framework or identity profiles) if present."""
    path = REFERENCE / filename
    if not path.exists():
        print(f"  (skipped {filename}: not found in {REFERENCE}/)")
        return 0
    df = pd.read_csv(path)
    valid = {c.name for c in table.__table__.columns}
    df = df[[c for c in df.columns if c in valid]]
    return _upsert(engine, table.__table__, _records(df), conflict_cols)


def _count(engine: Engine, table) -> int:
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(table.__table__)).scalar_one()


def main() -> None:
    engine = get_engine()

    n_players, n_metrics = load_players_and_metrics(engine)
    print(f"players: upserted {n_players}")
    print(f"player_season_metrics: upserted {n_metrics}")

    n_wage = load_reference_csv(engine, "wage_framework.csv", WageFramework, ["position_group", "age_band"])
    n_identity = load_reference_csv(engine, "identity_profiles.csv", IdentityProfile, ["position_group", "metric"])
    print(f"wage_framework: upserted {n_wage}")
    print(f"identity_profiles: upserted {n_identity}")

    print("\nRow counts now in Postgres:")
    for table in (Player, PlayerSeasonMetric, WageFramework, IdentityProfile):
        print(f"  {table.__tablename__}: {_count(engine, table)}")


if __name__ == "__main__":
    main()
