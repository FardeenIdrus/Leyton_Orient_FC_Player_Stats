"""Load the scraped injury CSV into Postgres, and read it back for the evidence panel.

Joins on players.tm_player_id, which the valuation stage populates. A Transfermarkt
player we hold no metrics for is dropped rather than guessed at.

The load is a MERGE, not a replace: only `source = 'transfermarkt'` rows for players
PRESENT IN THE INCOMING FILE are deleted before being reinserted; every other player's
rows -- and every `source = 'manual'` row regardless of player -- are left exactly as
they are. This is the same principle as the COALESCE-guarded bio update in
`model/identity.py`: absent data must never overwrite known data. The scraper only
visits players in CURRENT squads, so a summer transfer window routinely drops hundreds
of players who have left the four English leagues out of the file -- the scraper not
visiting a player is not evidence he was never injured. A delete-then-insert keyed on
`source` alone would erase that player's entire injury history (and with it the
Medical dimension of the club composite) every August.

Because the delete is scoped to the players actually in the file, the volume guard is
scoped the same way: it compares, for the players the scraper DID visit, how many rows
came back against how many were already stored for those SAME players. A player who
has left the leagues contributes to neither side of that comparison, so an ordinary
transfer-window shrink is invisible to it. A load carrying materially fewer rows than
that for the players it DID cover ABORTS before the DELETE -- that is what a truncated
file or a broken tm_player_id join looks like, and is what this guard is actually for.
--allow-shrink is the deliberate human override. (The row-count check used to compare
against the whole table -- correct for the single incident that motivated it, a
5-player smoke test that left 16 rows and would have replaced the lot, but wrong every
August once squad turnover became the normal case rather than the exception.)

Run:  python -m lofc.store.injuries

`load_for_player` and `COVERAGE` below are the read side, used by the evidence panel
(`dashboard/evidence.py`). They are plain SQLAlchemy Core, matching `store/watchlist.py`,
so they run identically on production Postgres and the sqlite used in tests.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from sqlalchemy import bindparam, create_engine, select, text

from lofc.config import settings
from lofc.ingest.transfermarkt_injuries import output_path
from lofc.store.models import PlayerInjury

COLUMNS = ["player_id", "tm_player_id", "season_label", "injury_type_raw",
           "injury_category", "date_from", "date_until", "days_out", "games_missed",
           "source"]
# An incoming load must keep at least this share of the rows already stored FOR THE
# PLAYERS IT VISITED (see module docstring -- the comparison is scoped, not global).
# Injury histories only grow, so the floor is loose purely to absorb ordinary re-scrape
# noise (a spell dropping off Transfermarkt's own page, a date correction) -- not squad
# churn, which a scoped comparison never sees in the first place.
MIN_ROW_RATIO = 0.70

_TABLE = PlayerInjury.__table__

_PLAYER_COLUMNS = ["id", "player_id", "season_label", "injury_type_raw", "injury_category",
                   "date_from", "date_until", "days_out", "games_missed", "source",
                   "entered_by"]

# Decision 12 / spec section 10, point 3. Measured on live data 2026-08-14.
#   linked       -- share of the league's players matched to a Transfermarkt profile at all
#   with_record  -- share that have at least one injury row
#   knowable     -- share whose availability can be established either way, once minutes
#                   played is used as the independent cross-check. None where it was not
#                   measured for that league.
# These are DISPLAY figures. Nothing in scoring reads them -- Decision 12 removed the
# automatic Medical band precisely because these numbers make it unsound.
COVERAGE: dict[int, dict[str, float | None]] = {
    3:  {"linked": 0.98, "with_record": 0.74, "knowable": 0.84},   # Championship
    4:  {"linked": 0.95, "with_record": 0.39, "knowable": 0.64},   # League One
    5:  {"linked": 0.96, "with_record": 0.32, "knowable": 0.58},   # League Two
    65: {"linked": 0.92, "with_record": 0.18, "knowable": 0.49},   # National League
}


def load_for_player(engine, player_id: int) -> pd.DataFrame:
    """Every recorded spell for one player, newest first.

    Returns an empty frame WITH the full column set when there are none: the caller indexes
    into these columns to decide between "no injuries" and "not known", and a bare empty
    frame would raise KeyError instead of rendering that distinction.
    """
    query = (select(*[_TABLE.c[name] for name in _PLAYER_COLUMNS])
             .where(_TABLE.c.player_id == player_id)
             .order_by(_TABLE.c.date_from.desc(), _TABLE.c.id.desc()))
    with engine.connect() as conn:
        frame = pd.DataFrame(conn.execute(query).fetchall(), columns=_PLAYER_COLUMNS)
    return frame


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


def visited_player_ids(frame: pd.DataFrame) -> list[int]:
    """Distinct player_id values this load actually covers -- the only players whose
    stored transfermarkt rows are eligible to be touched."""
    if frame.empty:
        return []
    return sorted(int(pid) for pid in frame["player_id"].unique())


def volume_problem(incoming: int, existing: int,
                   minimum_ratio: float = MIN_ROW_RATIO) -> str | None:
    """Why this load must not replace the stored rows for the players it covers, or
    None when it is safe.

    `incoming` and `existing` must already be scoped to the SAME set of players -- the
    ones present in the incoming file -- not the whole table. A player absent from the
    file is outside this comparison entirely, on both sides of it.

    `existing == 0` is always safe: none of the visited players had any rows stored
    (a first load, or every one of them is new), so there is nothing to lose. Otherwise
    zero incoming rows is the worst case, not an exemption -- it is caught by the same
    ratio.
    """
    if existing and incoming < existing * minimum_ratio:
        return (f"only {incoming} injury rows came back for the players this scrape "
                f"visited, against {existing} already stored for those same players "
                f"({incoming / existing:.0%}, minimum {minimum_ratio:.0%})")
    return None


def guard_volume(incoming: int, existing: int, allow_shrink: bool = False) -> None:
    """Abort the load unless it is safe to delete the stored rows of the visited players."""
    problem = volume_problem(incoming, existing)
    if problem is None:
        return
    print(f"{'WARNING' if allow_shrink else 'ERROR'}: {problem}")
    if not allow_shrink:
        raise SystemExit(
            f"Refusing to replace those {existing} stored injury rows: nothing has "
            "been deleted. Players who have left the leagues are excluded from this "
            "comparison entirely, so this is not an ordinary transfer-window shrink -- "
            "it means either injuries.csv is truncated (a --limit smoke test writes "
            "injuries.sample.csv, not this file) or the tm_player_id join is matching "
            "fewer of the visited players than it should. Check the CSV and "
            "players.tm_player_id, then re-run. Pass --allow-shrink to load it anyway.")
    print("--allow-shrink was passed: replacing the stored rows anyway")


def stored_transfermarkt_rows(engine, player_ids: list[int] | None = None) -> int:
    """Transfermarkt-sourced injury rows currently in the table.

    With `player_ids` given, counts only rows belonging to those players -- the scope
    the merge and its guard actually operate on. Without it, counts every transfermarkt
    row in the table, which is a global figure useful for before/after reporting but is
    NOT what the guard compares against (see module docstring).
    """
    query = "SELECT count(*) FROM player_injuries WHERE source = 'transfermarkt'"
    stmt: text
    params: dict = {}
    if player_ids is not None:
        stmt = text(query + " AND player_id IN :player_ids").bindparams(
            bindparam("player_ids", expanding=True))
        params["player_ids"] = list(player_ids)
    else:
        stmt = text(query)
    with engine.connect() as conn:
        return int(conn.execute(stmt, params).scalar_one())


def merge_transfermarkt_rows(engine, frame: pd.DataFrame, allow_shrink: bool = False) -> int:
    """Delete-then-reinsert the transfermarkt rows of only the players in `frame`.

    Every player NOT present in `frame` -- including every player who has left the
    leagues since the last scrape, and every `source = 'manual'` row regardless of
    player -- is left untouched. Raises SystemExit via `guard_volume` if the players
    `frame` covers came back with materially fewer rows than they already had stored.

    Returns the number of players touched (0 for an empty frame: nothing is deleted
    and nothing is inserted, since there is nothing to merge).
    """
    ids = visited_player_ids(frame)
    existing = stored_transfermarkt_rows(engine, ids)
    guard_volume(len(frame), existing, allow_shrink)
    with engine.begin() as conn:
        if ids:
            delete_stmt = text(
                "DELETE FROM player_injuries WHERE source = 'transfermarkt' "
                "AND player_id IN :player_ids"
            ).bindparams(bindparam("player_ids", expanding=True))
            conn.execute(delete_stmt, {"player_ids": ids})
            frame.to_sql("player_injuries", conn, if_exists="append", index=False)
    return len(ids)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Load the scraped Transfermarkt injury history into Postgres")
    parser.add_argument("--allow-shrink", action="store_true",
                        help="load even when the players this scrape visited carry far "
                             "fewer rows than they already had stored (only when a human "
                             "has decided the smaller history is correct)")
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

    # Checked (and the delete/insert scoped) BEFORE the transaction opens, so a
    # refusal cannot even reach the DELETE.
    touched = merge_transfermarkt_rows(engine, frame, args.allow_shrink)
    print(f"Loaded {len(frame)} injury rows for {touched} players")


if __name__ == "__main__":
    main()
