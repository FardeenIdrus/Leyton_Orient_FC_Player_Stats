"""Pipeline step: store every player's playing-style signals (`player_style_signals`).

Reads the landed Impect files (one row per player per position), rebuilds season totals the
way `impect_translate` does -- per-match average x matchShare, summed over the player's
position rows; minutes = playDuration seconds / 60 -- and computes `styles.SIGNALS`. Players
are linked to ours through the same route as `position_shares` (`_linked_ids`), never by
minting an id. Values are stored raw; the dashboard takes percentiles at read time.

Labels only: nothing in scoring reads this table.

Run with:  python -m lofc.model.style_run
"""

from __future__ import annotations

import pandas as pd

from lofc.model import styles


def season_totals(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """(totals per playerId for every Impect KPI column, minutes per playerId)."""
    kpis = [c for c in raw.columns if c.isupper()]
    totals = raw[kpis].mul(raw["matchShare"], axis=0)
    totals["playerId"] = raw["playerId"]
    totals = totals.groupby("playerId").sum()
    minutes = raw.groupby("playerId")["playDuration"].sum() / 60.0
    return totals, minutes


def season_signals(totals: pd.DataFrame, minutes: pd.Series) -> pd.DataFrame:
    return styles.compute_signals(totals, minutes.reindex(totals.index))


def to_long(sig: pd.DataFrame, ids: pd.Series, competition_id: int, season_id: int,
            minutes: pd.Series | None = None) -> pd.DataFrame:
    """Long rows for linked players with a known value. Where two Impect records map to one
    of our players (a duplicate in their feed), the one with more minutes is kept."""
    frame = sig.copy()
    frame["player_id"] = frame.index.map(ids)
    frame["_minutes"] = frame.index.map(minutes) if minutes is not None else 0.0
    frame = (frame.dropna(subset=["player_id"])
                  .sort_values("_minutes", ascending=False)
                  .drop_duplicates("player_id"))
    long = frame.drop(columns="_minutes").melt(id_vars="player_id", var_name="signal",
                                               value_name="value").dropna(subset=["value"])
    long["player_id"] = long["player_id"].astype("int64")
    long["competition_id"] = competition_id
    long["season_id"] = season_id
    return long[["player_id", "competition_id", "season_id", "signal", "value"]] \
        .reset_index(drop=True)


def write_for(engine, frame: pd.DataFrame, competition_id: int, season_id: int) -> int:
    """Clear-then-insert one league season."""
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM player_style_signals WHERE "
                          "competition_id = :c AND season_id = :s"),
                     {"c": competition_id, "s": season_id})
        frame.to_sql("player_style_signals", conn, if_exists="append", index=False,
                     chunksize=20_000, method="multi")
    return len(frame)


def main() -> None:
    from lofc.config import settings
    from lofc.ingest import impect as landing
    from lofc.model.position_shares import _linked_ids
    from lofc.store.load import get_engine

    engine = get_engine()
    for target in settings.impect_targets:
        path = landing.averages_path(target.iteration_id)
        if not path.exists():
            print(f"{target.label}: no landed Impect file; skipped")
            continue
        totals, minutes = season_totals(pd.read_parquet(path))
        ids = _linked_ids(engine, target)
        if ids is None or ids.empty:
            print(f"{target.label}: no linked players; skipped")
            continue
        long = to_long(season_signals(totals, minutes), ids, target.competition_id,
                       target.season_id, minutes=minutes)
        n = write_for(engine, long, target.competition_id, target.season_id)
        print(f"{target.label}: {n:,} style signal rows "
              f"({long['player_id'].nunique():,} players)")


if __name__ == "__main__":
    main()
