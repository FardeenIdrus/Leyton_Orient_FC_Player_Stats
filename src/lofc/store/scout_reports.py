"""Scout reports and the form's player lookup into Postgres, and the sync record.

TWO WRITE MODES, DELIBERATELY DIFFERENT, for the same reason the injury and squad loaders
differ from each other:

  `scout_reports`       UPSERT, never delete. A report that was filed is a fact about work
                        a scout did. A row that disappears from the sheet is STAMPED
                        (`missing_since`), not removed -- someone sorting or filtering a
                        spreadsheet must not erase the record that a match was watched.

  `scout_player_lookup` REPLACE wholesale. It is the form's dropdown list, a snapshot: a
                        name no longer offered is simply no longer offered.

THE KEY IS JOTFORM'S `submission_id` -- unique across all 437 live rows and stable across
edits, which is exactly why the upsert works. 127 of those rows have been edited since
submission; keyed on anything less stable (name, fixture, timestamp) every edit would
insert a duplicate instead of updating.

`player_id` IS NEVER WRITTEN HERE. Identity is resolved by a separate stage
(`model/scout_report_link.py`) after the load, and this loader must not touch the column
-- a sync that reset it to NULL would undo the linking work once a minute, every minute.

Plain SQLAlchemy Core, matching `store/watchlist.py` and `store/injuries.py`, so it runs
identically on production Postgres and the in-memory sqlite the tests use.

Run:  python -m lofc.store.scout_reports
"""

from __future__ import annotations

import argparse
import datetime as dt

import pandas as pd
from sqlalchemy import delete, func, insert, select, text, update

from lofc.store.models import ScoutPlayerLookup, ScoutReport, ScoutSync

# A read carrying less than this share of what is already stored is treated as truncated.
# Reports only ever accumulate, so a real shrink does not happen; a small one is still
# refused because the alternative -- flagging live reports as missing -- is worse.
MIN_VOLUME_RATIO = 0.80

# scout_sync gets a row every minute (the cron records unchanged runs too, so the dashboard
# can say when the sheet was last CHECKED). Unpruned it reached 32,686 rows. Seven days is
# ample for the freshness read, which only needs the newest row; the newest changed row is
# kept regardless of age, so "last changed" never disappears.
SYNC_HISTORY_DAYS = 7

REPORT_COLUMNS = [
    "submission_id", "scout", "observation", "report_type", "player_name", "club_name",
    "foot", "home_team", "away_team", "fixture_date", "comments", "positions_played",
    "recommended_positions", "grade", "squad_role", "verdict", "edit_url",
    "submitted_at", "updated_at", "linkable", "name_from_report",
]
LOOKUP_COLUMNS = ["player_name", "date_of_birth", "source_ref", "profile_url", "flagged"]


def volume_problem(incoming: int, existing: int) -> str | None:
    """A message when a read looks truncated, or None when it looks whole.

    The sheet is one accidental Ctrl-A from empty and the platform reads it every 60
    seconds. Here a bad read cannot destroy data -- nothing is ever deleted -- but it
    would stamp several hundred live reports as missing, which reads on screen exactly
    like the club losing its scouting record.

    The first load has nothing to compare against and is always allowed.
    """
    if existing == 0:
        return None
    if incoming >= existing * MIN_VOLUME_RATIO:
        return None
    return (f"Refusing the scouting-sheet read: {incoming} reports against {existing} "
            f"already stored (under {MIN_VOLUME_RATIO:.0%}). That is what a truncated "
            f"fetch, a filtered view or a cleared sheet looks like. Nothing was changed.")


def _json_safe(value):
    """Lists reach the JSON column as lists; NaN reaches it as NULL.

    A NaN handed to a JSON column serialises to the string "NaN", which is not valid
    JSON and reads back as neither a list nor a null.
    """
    if isinstance(value, list):
        return value
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return value


def upsert_reports(engine, frame: pd.DataFrame) -> int:
    """Insert new reports, update existing ones, and clear any stale missing stamp.

    Returns the number of rows written. `player_id` is deliberately absent from both the
    INSERT and the UPDATE -- see the module docstring.
    """
    if frame is None or frame.empty:
        return 0

    rows = []
    for record in frame.to_dict("records"):
        row = {c: record.get(c) for c in REPORT_COLUMNS}
        row["submission_id"] = str(row["submission_id"])
        for column in ("positions_played", "recommended_positions"):
            row[column] = _json_safe(row[column])
        for column in ("fixture_date", "submitted_at", "updated_at"):
            value = row[column]
            row[column] = None if value is None or pd.isna(value) else value
        row["linkable"] = bool(row["linkable"]) if row["linkable"] is not None else True
        row["name_from_report"] = bool(row.get("name_from_report"))
        rows.append(row)

    # Core constructs against the Table, NOT text() SQL: `positions_played` is a JSON
    # column, and a raw statement hands the driver a Python list it cannot bind
    # ("type 'list' is not supported"). Going through the Table lets SQLAlchemy's own
    # type machinery serialise it, identically on sqlite and Postgres.
    table = ScoutReport.__table__
    now = dt.datetime.now()
    with engine.begin() as conn:
        for row in rows:
            changes = {k: v for k, v in row.items() if k != "submission_id"}
            updated = conn.execute(
                update(table)
                .where(table.c.submission_id == row["submission_id"])
                # Seen again, so any earlier disappearance is over.
                .values(**changes, last_synced_at=now, missing_since=None)).rowcount
            if not updated:
                conn.execute(insert(table).values(**row, last_synced_at=now))
    return len(rows)


def stamp_missing(engine, seen_ids: set[str]) -> int:
    """Mark stored reports absent from this read, WITHOUT deleting them.

    Returns how many were newly stamped. Already-stamped rows are left alone, so the
    timestamp records when a report first went missing rather than when it was last
    noticed.
    """
    table = ScoutReport.__table__
    now = dt.datetime.now()
    with engine.begin() as conn:
        live = select(table.c.submission_id).where(table.c.missing_since.is_(None))
        gone = [r[0] for r in conn.execute(live) if r[0] not in seen_ids]
        if not gone:
            return 0
        conn.execute(update(table)
                     .where(table.c.submission_id.in_(gone))
                     .values(missing_since=now))
        return len(gone)


def load_player_lookup(engine, frame: pd.DataFrame, allow_shrink: bool = False) -> int:
    """Replace the form's player dropdown list. Aborts BEFORE the delete if truncated."""
    table = ScoutPlayerLookup.__table__
    with engine.begin() as conn:
        existing = int(conn.execute(select(func.count()).select_from(table)).scalar() or 0)
        incoming = 0 if frame is None or frame.empty else len(frame)
        if not allow_shrink:
            problem = volume_problem(incoming, existing)
            if problem:
                raise RuntimeError(
                    problem.replace("reports", "player lookup rows")
                           .replace("scouting-sheet read", "player lookup load"))
        conn.execute(delete(table))
        if incoming:
            rows = []
            for record in frame.to_dict("records"):
                row = {c: record.get(c) for c in LOOKUP_COLUMNS}
                rows.append({c: (None if v is None or (not isinstance(v, (list, dict))
                                                       and pd.isna(v)) else v)
                             for c, v in row.items()})
            conn.execute(insert(table), rows)
        return incoming


def _prune_sync_history(conn) -> int:
    """Delete sync rows older than SYNC_HISTORY_DAYS, keeping the two the platform reads.

    The newest row (the change detector's digest and the dashboard's "last checked" time)
    and the newest CHANGED row (the dashboard's "last actually changed" time) survive
    whatever their age. Returns how many rows were deleted.
    """
    table = ScoutSync.__table__
    keep = [i for i in (
        conn.execute(select(func.max(table.c.id))).scalar(),
        conn.execute(select(func.max(table.c.id)).where(table.c.changed.is_(True))).scalar(),
    ) if i is not None]
    cutoff = dt.datetime.now() - dt.timedelta(days=SYNC_HISTORY_DAYS)
    result = conn.execute(delete(table).where(
        table.c.synced_at < cutoff, table.c.id.not_in(keep)))
    return result.rowcount


def prune_sync_history(engine) -> int:
    """Public wrapper for the retention rule, so it can be run on its own."""
    with engine.begin() as conn:
        return _prune_sync_history(conn)


def record_sync(engine, digest: str, reports_seen: int, reports_written: int,
                changed: bool = True) -> None:
    """Record that a sync completed, whether or not anything moved.

    Recording an UNCHANGED run matters as much as a changed one: on screen, "nothing has
    changed for three hours" and "the sync died three hours ago" are indistinguishable
    without it. That is register P14 in miniature, and the reason this is the first table
    in the platform that can state its own freshness.

    The cron runs this every minute, so the table would grow by ~1,440 rows a day. Each
    write therefore also prunes history older than SYNC_HISTORY_DAYS, in the same
    transaction. Nothing reads further back than the newest row and newest change.
    """
    with engine.begin() as conn:
        conn.execute(insert(ScoutSync.__table__).values(
            digest=digest, synced_at=dt.datetime.now(), reports_seen=reports_seen,
            reports_written=reports_written, changed=changed))
        _prune_sync_history(conn)


def last_digest(engine) -> str | None:
    """The digest of the most recent sync, or None on a fresh database."""
    table = ScoutSync.__table__
    with engine.connect() as conn:
        return conn.execute(
            select(table.c.digest).order_by(table.c.id.desc()).limit(1)).scalar()


def sync(engine, force: bool = False) -> dict:
    """Fetch the sheet, load it, and resolve player links. Returns a summary.

    The single entry point for BOTH the cron and the dashboard's Refresh button, so the two
    cannot drift: a button that only cleared a cache would leave the page showing whatever
    the last cron run stored, while claiming to have refreshed.

    Reads Google; writes only to Postgres. Raises RuntimeError on a problem the caller
    should show, rather than exiting — the dashboard cannot handle a SystemExit.
    """
    from lofc.config import settings
    from lofc.ingest.scout_lookup import lookup_frame
    from lofc.ingest.scout_reports import reports_frame
    from lofc.ingest.scout_sheets import fetch, frame_from_values, payload_hash
    from lofc.model.scout_report_link import relink

    if not settings.scout_sheet_configured:
        raise RuntimeError(
            "Scouting sheet not configured: set SCOUT_SHEET_ID and place the "
            f"service-account key at {settings.scout_sheet_credentials}.")

    payload = fetch(settings.scout_sheet_id, settings.scout_sheet_credentials)
    digest = payload_hash(payload)
    reports = reports_frame(frame_from_values(payload["Form responses"]))

    if digest == last_digest(engine) and not force:
        record_sync(engine, digest, len(reports), 0, changed=False)
        return {"changed": False, "reports": len(reports), "written": 0,
                "missing": 0, "lookup": 0, "linked": 0}

    with engine.connect() as conn:
        existing = int(conn.execute(
            text("SELECT COUNT(*) FROM scout_reports")).scalar() or 0)
    problem = volume_problem(len(reports), existing)
    if problem:
        raise RuntimeError(problem)

    written = upsert_reports(engine, reports)
    gone = stamp_missing(engine, set(reports["submission_id"]))
    lookup = lookup_frame(frame_from_values(payload["Player Names"]))
    load_player_lookup(engine, lookup)
    # Linked in the same run: the link needs BOTH the reports and the lookup current, and
    # doing it separately would leave a window where new reports exist with no player
    # attached — on screen indistinguishable from a player we cannot match.
    linked = relink(engine)
    record_sync(engine, digest, len(reports), written, changed=True)
    return {"changed": True, "reports": len(reports), "written": written,
            "missing": gone, "lookup": len(lookup), "linked": linked}


def main() -> None:
    """Fetch the sheet and load it. Reads the sheet; writes only to Postgres."""
    from lofc.store.load import get_engine

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true",
                        help="load even when the sheet is unchanged")
    args = parser.parse_args()
    try:
        r = sync(get_engine(), force=args.force)
    except RuntimeError as exc:
        raise SystemExit(str(exc))
    if not r["changed"]:
        print(f"scouting sheet unchanged ({r['reports']} reports); nothing written")
        return
    print(f"scout_reports: {r['written']} reports upserted, {r['missing']} newly missing")
    print(f"scout_player_lookup: {r['lookup']} rows")
    print(f"scout reports linked: {r['linked']}")


if __name__ == "__main__":
    main()
