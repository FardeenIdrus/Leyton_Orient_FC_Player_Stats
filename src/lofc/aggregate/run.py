"""Aggregate the landed raw data into the player-season metrics table.

Reads the raw JSON under data/raw/, produces one row per player per league season,
and writes the result to data/processed/ as both parquet (for the next phases) and
CSV (so it opens in any spreadsheet).

Usage:
  python -m lofc.aggregate.run                  # all configured competitions
  python -m lofc.aggregate.run --competition 2  # one competition only
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from lofc.aggregate.player_season import RANKABLE_MINUTES, aggregate_competition
from lofc.config import settings

OUTPUT_NAME = "player_season_metrics"


def processed_dir() -> Path:
    return Path(settings.raw_data_dir).parent / "processed"


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate raw data into player-season metrics")
    parser.add_argument("--competition", type=int, help="only this competition_id")
    args = parser.parse_args()

    comps = settings.competitions
    if args.competition:
        comps = [c for c in comps if c.competition_id == args.competition]
        if not comps:
            raise SystemExit(f"competition_id {args.competition} is not in the configured list")

    tables = []
    for comp in comps:
        print(f"Aggregating {comp.label} ...")
        tables.append(aggregate_competition(comp))

    table = pd.concat(tables, ignore_index=True)

    out = processed_dir()
    out.mkdir(parents=True, exist_ok=True)
    table.to_parquet(out / f"{OUTPUT_NAME}.parquet", index=False)
    table.to_csv(out / f"{OUTPUT_NAME}.csv", index=False)

    rankable = int(table["rankable"].sum())
    print(f"\nWrote {len(table)} player-season rows ({rankable} rankable, >= {RANKABLE_MINUTES} min) to {out}/")
    print("\nRankable players per position group:")
    counts = table[table["rankable"]].groupby(["competition_name", "position_group"]).size()
    print(counts.to_string())


if __name__ == "__main__":
    main()
