"""Load the scraped injury CSV into Postgres.

Joins on players.tm_player_id, which the valuation stage populates. A Transfermarkt
player we hold no metrics for is dropped rather than guessed at.

The load is a REPLACE -- every stored `source = 'transfermarkt'` row is deleted before
the frame is appended -- so a shrunken CSV would silently destroy the injury history
(and with it the Medical dimension of the club composite). That has happened once, when
a 5-player smoke test left 16 rows in the table. A load carrying materially fewer rows
than the table already holds therefore ABORTS before the DELETE, and --allow-shrink is
the deliberate human override.

Run:  python -m lofc.store.injuries
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

from lofc.config import settings
from lofc.ingest.transfermarkt_injuries import output_path

COLUMNS = ["player_id", "tm_player_id", "season_label", "injury_type_raw",
           "injury_category", "date_from", "date_until", "days_out", "games_missed",
           "source"]
# An incoming load must keep at least this share of the rows already stored. Injury
# histories only grow, so the floor is loose purely to absorb squad churn (players
# leaving the four EFL divisions take their history out of the join with them).
MIN_ROW_RATIO = 0.70


def unambiguous_players(players: pd.DataFrame) -> pd.DataFrame:
    """Our players minus any whose Transfermarkt id another player also holds.

    The join below is one-to-many on tm_player_id, so a duplicate copies one player's
    ENTIRE injury history onto the other -- and the availability figure, a medical
    judgement, follows it. `model.identity` no longer writes a duplicate, but the ones
    already stored survive (the bio update is COALESCE-guarded, so a re-run cannot
    clear them). Nothing here says which player is the real one, so neither is given
    the history: a missing injury record is visibly missing, a wrong one is not.
    """
    counts = players.groupby("tm_player_id")["player_id"].nunique()
    ambiguous = sorted(counts[counts > 1].index)
    if not ambiguous:
        return players
    print(f"WARNING: {len(ambiguous)} Transfermarkt id(s) are held by more than one "
          f"player {[int(i) for i in ambiguous]} -- their injuries are loaded for "
          "NEITHER player rather than misattributed. Fix players.tm_player_id.")
    return players[~players["tm_player_id"].isin(ambiguous)]


def injury_frame(csv_path: Path, players: pd.DataFrame) -> pd.DataFrame:
    """Scraped rows joined to our player ids, shaped exactly like the table."""
    frame = pd.read_csv(csv_path)
    if frame.empty:
        return pd.DataFrame(columns=COLUMNS)
    merged = frame.merge(unambiguous_players(players)[["player_id", "tm_player_id"]],
                         on="tm_player_id", how="inner")
    merged["source"] = "transfermarkt"
    return merged.reindex(columns=COLUMNS)


def volume_problem(incoming: int, existing: int,
                   minimum_ratio: float = MIN_ROW_RATIO) -> str | None:
    """Why this load must not replace the stored rows, or None when it is safe.

    `existing == 0` is always safe: a first load, or a table that is already empty,
    has nothing to lose. Otherwise zero incoming rows is the worst case, not an
    exemption -- it is caught by the same ratio.
    """
    if existing and incoming < existing * minimum_ratio:
        return (f"only {incoming} injury rows to load against {existing} already stored "
                f"({incoming / existing:.0%}, minimum {minimum_ratio:.0%})")
    return None


def guard_volume(incoming: int, existing: int, allow_shrink: bool = False) -> None:
    """Abort the load unless it is safe to delete the stored transfermarkt rows."""
    problem = volume_problem(incoming, existing)
    if problem is None:
        return
    print(f"{'WARNING' if allow_shrink else 'ERROR'}: {problem}")
    if not allow_shrink:
        raise SystemExit(
            f"Refusing to replace {existing} stored injury rows: nothing has been "
            "deleted. This usually means injuries.csv is truncated (a --limit smoke "
            "test writes injuries.sample.csv, not this file) or the identity link has "
            "collapsed. Check the CSV and players.tm_player_id, then re-run. Pass "
            "--allow-shrink to load it anyway.")
    print("--allow-shrink was passed: replacing the stored rows anyway")


def stored_transfermarkt_rows(engine) -> int:
    """Injury rows currently in the table from the scrape -- the ones about to go."""
    with engine.connect() as conn:
        return int(conn.execute(text(
            "SELECT count(*) FROM player_injuries WHERE source = 'transfermarkt'"
        )).scalar_one())


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Load the scraped Transfermarkt injury history into Postgres")
    parser.add_argument("--allow-shrink", action="store_true",
                        help="load even when it carries far fewer rows than the table "
                             "already holds (only when a human has decided the smaller "
                             "history is correct)")
    args = parser.parse_args(argv)

    path = output_path()
    if not path.exists():
        print(f"{path} not found -- run lofc.ingest.transfermarkt_injuries first")
        return

    engine = create_engine(settings.database_url)
    players = pd.read_sql(
        "SELECT player_id, tm_player_id FROM players WHERE tm_player_id IS NOT NULL",
        engine)
    frame = injury_frame(path, players)

    # Checked BEFORE the transaction opens, so a refusal cannot even reach the DELETE.
    guard_volume(len(frame), stored_transfermarkt_rows(engine), args.allow_shrink)

    with engine.begin() as conn:
        # Replace only what we scraped. Manually entered rows are never touched.
        conn.execute(text("DELETE FROM player_injuries WHERE source = 'transfermarkt'"))
        if not frame.empty:
            frame.to_sql("player_injuries", conn, if_exists="append", index=False)
    print(f"Loaded {len(frame)} injury rows for "
          f"{frame['player_id'].nunique() if not frame.empty else 0} players")


if __name__ == "__main__":
    main()
