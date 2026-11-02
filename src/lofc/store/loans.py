"""Load the Transfermarkt loan file into `player_loans` -- the server side of the loan
refresh (TASKS 2.3, 2026-11-02).

Transfermarkt blocks the server, so loans are scraped on the Mac
(`python -m lofc.ingest.transfermarkt_loans`), which writes
`reference/transfermarkt/loans.csv`. That file is copied to the server with the squads
file, and this loads it -- on every weekly run, so a pushed refresh needs no extra step.
Reloading the same file is harmless: it replaces the season with the same rows.

A file much smaller than what is stored is REFUSED and the stored loans are kept (the
squads lesson of 11 Aug 2026: a truncated scrape must not empty the table). It does not fail
the weekly run; it says so in the log. Loans genuinely fall at the end of May, when most end
-- then load with --allow-shrink.

Run with:  python -m lofc.store.loans [--allow-shrink]
"""

from __future__ import annotations

import argparse
import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from lofc.ingest import transfermarkt_loans as tl

MIN_ROW_RATIO = 0.70


def frame_from_csv(path: Path | None = None) -> pd.DataFrame:
    """The loan file as a frame; `attrs["scraped_at"]` is when it was scraped."""
    path = Path(path) if path is not None else tl.csv_path()
    if not path.exists():
        return pd.DataFrame(columns=tl.COLUMNS)
    raw = pd.read_csv(path)
    out = raw[tl.COLUMNS].copy()
    out["loan_ends"] = [d.date() if pd.notna(d) else None
                        for d in pd.to_datetime(out["loan_ends"], errors="coerce")]
    out["tm_player_id"] = [int(x) if pd.notna(x) else None for x in out["tm_player_id"]]
    out = out.astype(object).where(out.notna(), None)
    stamp = pd.to_datetime(raw["scraped_at"].dropna().max()) if "scraped_at" in raw else None
    out.attrs["scraped_at"] = stamp.to_pydatetime() if stamp is not None else None
    return out


def stored_rows(engine, season_id: int) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text("SELECT COUNT(*) FROM player_loans WHERE season_id = :s"),
                                {"s": int(season_id)}).scalar() or 0)


def load_file(engine, path: Path | None = None, allow_shrink: bool = False) -> int:
    """Load the file, one season at a time. Returns rows written (0 if refused or absent)."""
    frame = frame_from_csv(path)
    if frame.empty:
        print(f"No loan file at {path or tl.csv_path()}; nothing to load.")
        return 0
    written = 0
    for season_id, part in frame.groupby("season_id"):
        existing = stored_rows(engine, int(season_id))
        if existing and len(part) < existing * MIN_ROW_RATIO and not allow_shrink:
            print(f"REFUSED: only {len(part)} loans in the file for season {season_id} "
                  f"against {existing} stored (under {MIN_ROW_RATIO:.0%}) -- that is what a "
                  f"truncated scrape looks like. Stored loans kept. Re-scrape, or load with "
                  f"--allow-shrink if the fall is real (e.g. loans ending in May).")
            continue
        written += tl.load(engine, part.reset_index(drop=True), int(season_id),
                           scraped_at=frame.attrs.get("scraped_at"))
    return written


def main(argv: list[str] | None = None) -> None:
    from lofc.store.load import get_engine
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-shrink", action="store_true",
                        help="load even though the file holds far fewer loans than stored")
    args = parser.parse_args(argv)
    load_file(get_engine(), allow_shrink=args.allow_shrink)


if __name__ == "__main__":
    main()
