"""The recruiter's watchlist: add, remove, annotate, and load tracked players.

USER DATA, not pipeline output: nothing here is ever cleared by a pipeline run.
Plain SQLAlchemy Core throughout (no Postgres-specific upserts) so the module
runs identically on the production Postgres and the sqlite used in tests.
"""

from __future__ import annotations

import pandas as pd
import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from lofc.config import SEASON_REF_DATE
from lofc.store.models import WatchlistDismissed, WatchlistEntry

# owner 2026-11-23 (Watchlist redesign): stages, one entry per player
STAGES = ["Watching", "Scout to watch", "Shortlisted", "Agent contacted", "Signed", "Dropped"]
ACTIVE_STAGES = STAGES[:4]
OLD_TO_NEW = {"Watching": "Watching", "Scout sent": "Scout to watch",
              "Contact agent": "Agent contacted", "Dropped": "Dropped"}
WATCHLIST_STATUSES = STAGES          # the name the older callers use
# fields a user can edit on the page (`update`)
EDITABLE = ("status", "owner_user_id", "next_step", "due_date", "note", "drop_reason")

_TABLE = WatchlistEntry.__table__
_DISMISSED = WatchlistDismissed.__table__


def _now() -> datetime.datetime:
    return datetime.datetime.now()


def _latest_id(conn, player_id: int):
    """The id of the player's latest row (the one the page shows and edits), or None."""
    row = conn.execute(select(_TABLE.c.id).where(_TABLE.c.player_id == player_id)
                       .order_by(_TABLE.c.created_at.desc(), _TABLE.c.id.desc())).first()
    return None if row is None else row[0]


def is_watched(engine, player_id: int, competition_id: int | None = None,
               season_id: int | None = None) -> bool:
    """Is the PLAYER on the list (any league or season)? `competition_id`/`season_id` are
    accepted for older callers and ignored (owner 2026-11-23: one entry per player)."""
    with engine.connect() as conn:
        return _latest_id(conn, player_id) is not None


def add(engine, player_id: int, competition_id: int, season_id: int,
        user_id: int | None = None, snapshot: dict | None = None) -> bool:
    """Put a player on the list from one of his rows. True = added, False = he was already on it
    (from any row). `snapshot` = {"rating", "club", "competition_id"} when added, for "What
    changed since added"."""
    snap = snapshot or {}
    try:
        with engine.begin() as conn:
            if _latest_id(conn, player_id) is not None:
                return False
            conn.execute(_TABLE.insert().values(
                player_id=player_id, competition_id=competition_id, season_id=season_id,
                status="Watching", added_by_user_id=user_id, stage_changed_at=_now(),
                added_rating=snap.get("rating"), added_club=snap.get("club"),
                added_competition_id=snap.get("competition_id")))
        return True
    except IntegrityError:  # raced with another add; the unique constraint held
        return False


def remove(engine, player_id: int, competition_id: int | None = None,
           season_id: int | None = None) -> bool:
    """Take the player off the list (every row of his). True = something was removed. A user's
    own action from the card; the page's "Dropped" stage keeps him on record instead."""
    with engine.begin() as conn:
        result = conn.execute(_TABLE.delete().where(_TABLE.c.player_id == player_id))
    return result.rowcount > 0


def update(engine, player_id: int, user_id: int | None = None, **fields) -> bool:
    """Edit the player's latest row: any of EDITABLE. Blank text, None or "" clears a field.
    A stage change stamps `stage_changed_at`; a note change stamps who and when. A drop reason
    is optional (owner 2026-11-23). False when the player is not on the list."""
    bad = set(fields) - set(EDITABLE)
    if bad:
        raise ValueError(f"cannot edit {sorted(bad)}; expected some of {EDITABLE}")
    if "status" in fields and fields["status"] not in STAGES:
        raise ValueError(f"unknown stage {fields['status']!r}; expected one of {STAGES}")
    values = {}
    for k, v in fields.items():
        if isinstance(v, str):
            v = v.strip() or None
        values[k] = v
    with engine.begin() as conn:
        rid = _latest_id(conn, player_id)
        if rid is None:
            return False
        cur = conn.execute(select(_TABLE.c.status, _TABLE.c.note).where(_TABLE.c.id == rid)).first()
        if "status" in values and values["status"] != cur.status:
            values["stage_changed_at"] = _now()
        if "note" in values and values["note"] != cur.note:
            values.update(note_updated_by=user_id, note_updated_at=_now())
        if values:
            conn.execute(_TABLE.update().where(_TABLE.c.id == rid).values(**values))
    return True


def set_note(engine, player_id: int, competition_id: int, season_id: int,
             note: str | None) -> None:
    update(engine, player_id, note=note)


def set_status(engine, player_id: int, competition_id: int, season_id: int,
               status: str) -> None:
    update(engine, player_id, status=status)


def row_count(engine) -> int:
    """Every stored row, duplicates included (the page shows one per player)."""
    with engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(_TABLE)).scalar())


def dismiss(engine, report_id: int, player_id: int | None, user_id: int | None) -> None:
    """Hide one "Suggested from scout reports" entry (its report). Twice is harmless."""
    try:
        with engine.begin() as conn:
            if conn.execute(select(_DISMISSED.c.id).where(_DISMISSED.c.report_id == report_id)).first():
                return
            conn.execute(_DISMISSED.insert().values(report_id=report_id, player_id=player_id,
                                                    user_id=user_id))
    except IntegrityError:
        return


def dismissed_report_ids(engine) -> set[int]:
    with engine.connect() as conn:
        return {int(r[0]) for r in conn.execute(select(_DISMISSED.c.report_id))}


def load(engine) -> pd.DataFrame:
    """Every watched row with its display facts, newest first.

    LEFT joins on purpose: a pipeline rebuild clears the derived tables before
    refilling them, and a watched player must survive that with blanks rather
    than vanish from the list.

    `player_season_metrics` only ever holds the four English leagues (Championship down
    to National League); a watched Scottish Premiership/Championship or PL2 player has no
    row there, so team_name/position_group joined from it alone come back blank even though
    the same player's profile shows both fine. `player_metrics_neutral` is the combined
    7-league table the profile itself reads from, so it is joined first and preferred via
    COALESCE, with `player_season_metrics` kept as the fallback (it is still the only source
    of `competition_name`, used by the dashboard only when a competition_id lookup misses).

    Age likewise cannot rely on `valuations` alone -- that table is Transfermarkt-derived
    and only covers a subset of (mostly EFL) players. As on the profile
    (`dashboard/loaders.py::load_candidates`), age is derived primarily from
    `players.birth_date` at the season's reference midpoint, falling back to the valuation's
    age only when no birth date is on file.
    """
    query = """
        SELECT w.id AS row_id, w.player_id, w.competition_id, w.season_id, w.note, w.status,
               w.created_at, w.drop_reason, w.owner_user_id, w.next_step, w.due_date,
               w.added_by_user_id, w.stage_changed_at, w.note_updated_by, w.note_updated_at,
               w.added_rating, w.added_club, w.added_competition_id,
               p.player_name, p.contract_until, p.tm_player_id, p.birth_date,
               COALESCE(n.team_name, m.team_name) AS team_name,
               COALESCE(n.position_group, m.position_group) AS position_group,
               m.competition_name,
               s.performance_score, s.fit_score,
               v.market_value_eur, v.age AS valuation_age
        FROM watchlist w
        LEFT JOIN players p ON p.player_id = w.player_id
        LEFT JOIN player_metrics_neutral n
               ON n.player_id = w.player_id AND n.competition_id = w.competition_id
              AND n.season_id = w.season_id
        LEFT JOIN player_season_metrics m
               ON m.player_id = w.player_id AND m.competition_id = w.competition_id
              AND m.season_id = w.season_id
        LEFT JOIN player_scores s
               ON s.player_id = w.player_id AND s.competition_id = w.competition_id
              AND s.season_id = w.season_id
        LEFT JOIN valuations v
               ON v.player_id = w.player_id AND v.competition_id = w.competition_id
              AND v.season_id = w.season_id
        ORDER BY w.created_at DESC, w.id DESC
    """
    frame = pd.read_sql(query, engine)
    frame["birth_date"] = pd.to_datetime(frame["birth_date"], errors="coerce")
    ref_date = frame["season_id"].map(SEASON_REF_DATE)
    dob_age = ((ref_date - frame["birth_date"]).dt.days / 365.25).round(1)
    dob_age = dob_age.where(dob_age.between(14, 50))          # drop nonsense before using
    # pd.to_numeric, not a bare fallback: `valuation_age` can hold a Python None (object
    # dtype) rather than a real NaN for a player with no valuation row -- `.where()`
    # against an object-dtype column upcasts the whole result to object, mixing float NaN
    # with Python None, and a table column built from that later renders the None as the
    # literal text "None" instead of leaving the cell blank. See
    # `dashboard/loaders.py::load_candidates` for the identical fix, same reasoning.
    fallback_age = pd.to_numeric(frame["valuation_age"], errors="coerce")
    frame["age"] = dob_age.where(dob_age.notna(), fallback_age)
    # owner 2026-11-23 (decision A): one entry per player -- his latest row (newest first)
    frame = frame.drop_duplicates("player_id", keep="first").reset_index(drop=True)
    return frame.drop(columns=["birth_date", "valuation_age"])
