"""Load the scraped Transfermarkt squad CSV into Postgres, so the dashboard reads a TABLE.

WHY THIS EXISTS. `data/reference/transfermarkt/efl_values.csv` is the scraper's output and
the platform's only source of registered-squad membership, contract expiry and height --
Impect carries none of it, and knows a player only once he has PLAYED (five matches into
2026/27 that meant 16 of Leyton Orient's 33). Four pipeline stages read that file directly
(`valuation`, `identity`, `player_bio`, the injury scraper) and will keep doing so: they run
alongside the scraper, on the same disk, so a file is the natural handoff.

The DASHBOARD also read it, and that was the problem. It made `Squads & loans` depend on the
app process sharing a filesystem with the scrape -- true on a laptop, false on any host where
the two are separate services. Where the file was absent the page silently fell back to
appearance data and showed 2,966 players instead of 3,783.

So this module does for squads exactly what `store/injuries.py` already does for injuries:
CSV -> loader -> table -> the dashboard reads the table. Postgres is the single data store;
this CSV was the exception.

A SNAPSHOT, NOT A HISTORY -- the one place this deliberately differs from `injuries.py`.
That module MERGES, because an injury spell the scraper did not revisit is still true. A
squad row for a player who has left is not true, so this REPLACES. The guard below is what
makes that safe.

Run:  python -m lofc.store.squads
"""

from __future__ import annotations

import argparse
import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

from lofc.config import settings
from lofc.store.models import TransfermarktSquad

_TABLE = TransfermarktSquad.__table__

COLUMNS = ["tm_player_id", "league_code", "competition_id", "club_name", "player_name",
           "date_of_birth", "position", "height_cm", "foot", "contract_until",
           "market_value_eur"]

# An incoming scrape must carry at least this share of what is already stored. Because the
# load REPLACES, a truncated file would otherwise empty the table. This is the 11 Aug 2026
# incident's lesson in guard form: that scrape ran against a stale season, silently produced
# blanks for every contract/foot/height, reported success, and destroyed 1,381 contract
# dates. Squad sizes move by a few percent across a window, never by half.
MIN_ROW_RATIO = 0.70


def csv_path() -> Path:
    return Path(settings.reference_data_dir) / "transfermarkt" / "efl_values.csv"


def _date(value):
    """A real `date`, or None. Never NaT/NaN -- those reach a DB driver as an error on some
    backends and as the literal string 'nan' on others."""
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else parsed.date()


def _value(value):
    """The value, or None where it is missing. Same reasoning as `_date`."""
    return None if pd.isna(value) else value


def squad_frame_from_csv(path: Path | None = None) -> pd.DataFrame:
    """The scrape as table-ready rows: dates parsed, missing values None, not NaN.

    An absent file yields an EMPTY frame rather than raising -- the caller (the pipeline
    stage) reports it and moves on, the same way `store/injuries.py` tolerates a machine
    that has never run the injury scraper.
    """
    path = Path(path) if path is not None else csv_path()
    if not path.exists():
        return pd.DataFrame(columns=COLUMNS)

    raw = pd.read_csv(path)
    out = pd.DataFrame({c: raw[c] if c in raw.columns else None for c in COLUMNS})

    # dtype=object on every rewritten column, deliberately. Assigning a list containing
    # None into a float64 column does NOT store None -- pandas re-infers a float dtype and
    # silently converts it straight back to NaN, which is what this guards against: a NaN
    # reaching the DB driver errors on some backends and lands as the literal string 'nan'
    # on others. Only an object-dtype column actually holds a None.
    def _column(values):
        return pd.Series(values, dtype=object, index=out.index)

    for column in ("date_of_birth", "contract_until"):
        out[column] = _column([_date(v) for v in out[column]])
    for column in ("league_code", "position", "foot", "height_cm", "market_value_eur"):
        out[column] = _column([_value(v) for v in out[column]])
    return out


def volume_problem(incoming: int, existing: int,
                   minimum_ratio: float = MIN_ROW_RATIO) -> str | None:
    """Why this scrape must not replace what is stored, or None when it is safe.

    `existing == 0` is always safe -- a first load has nothing to lose. Zero incoming rows
    against real stored data is the worst case, not an exemption, and the same ratio catches
    it.
    """
    if existing and incoming < existing * minimum_ratio:
        return (f"only {incoming} squad rows came back against {existing} already stored "
                f"(under {minimum_ratio:.0%}). That is what a truncated scrape or a "
                f"changed page layout looks like; refusing to replace the squad list. "
                f"Re-run the scrape, or pass --allow-shrink if this shrink is real.")
    return None


def stored_rows(engine) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text("SELECT COUNT(*) FROM transfermarkt_squads")).scalar() or 0)


def load_squads(engine, frame: pd.DataFrame, allow_shrink: bool = False) -> int:
    """Replace the stored squad snapshot with `frame`. Returns rows written.

    The guard runs BEFORE the DELETE -- a guard that fires afterwards protects nothing.
    """
    existing = stored_rows(engine)
    problem = volume_problem(len(frame), existing)
    if problem and not allow_shrink:
        raise RuntimeError(problem)
    if problem:
        print(f"WARNING: {problem}")

    now = datetime.datetime.now()
    records = [{**row, "scraped_at": now}
               for row in frame.to_dict(orient="records")]
    with engine.begin() as conn:
        conn.execute(_TABLE.delete())
        if records:
            conn.execute(_TABLE.insert(), records)
    return len(records)


def load_frame(engine) -> pd.DataFrame:
    """The stored snapshot, for the dashboard. The read side, mirroring
    `store/injuries.py::load_for_player`."""
    return pd.read_sql(f"SELECT {', '.join(COLUMNS)} FROM transfermarkt_squads", engine)


def scraped_at(engine) -> datetime.datetime | None:
    """When the stored snapshot was taken, or None if there is none.

    Replaces reading the CSV file's mtime, which was a proxy: any `touch`, `cp` or checkout
    moved it without the data changing.
    """
    with engine.connect() as conn:
        value = conn.execute(text("SELECT MAX(scraped_at) FROM transfermarkt_squads")).scalar()
    return pd.to_datetime(value).to_pydatetime() if value is not None else None


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-shrink", action="store_true",
                        help="replace the squad list even though the incoming scrape is "
                             "materially smaller (a deliberate human override)")
    args = parser.parse_args(argv)

    frame = squad_frame_from_csv()
    if frame.empty:
        print(f"No squad scrape at {csv_path()} - nothing to load. "
              "Run `python -m lofc.ingest.transfermarkt_efl` first.")
        return

    engine = create_engine(settings.database_url)
    written = load_squads(engine, frame, allow_shrink=args.allow_shrink)
    print(f"transfermarkt_squads: {written} rows for "
          f"{frame['club_name'].nunique()} clubs across "
          f"{frame['competition_id'].nunique()} leagues")


if __name__ == "__main__":
    main()
