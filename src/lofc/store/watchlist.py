"""The recruiter's watchlist: add, remove, annotate, and load tracked players.

USER DATA, not pipeline output: nothing here is ever cleared by a pipeline run.
Plain SQLAlchemy Core throughout (no Postgres-specific upserts) so the module
runs identically on the production Postgres and the sqlite used in tests.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError

from lofc.config import SEASON_REF_DATE
from lofc.store.models import WatchlistEntry

WATCHLIST_STATUSES = ["Watching", "Scout sent", "Contact agent", "Dropped"]

_TABLE = WatchlistEntry.__table__


def _key_clause(player_id: int, competition_id: int, season_id: int):
    return and_(_TABLE.c.player_id == player_id,
                _TABLE.c.competition_id == competition_id,
                _TABLE.c.season_id == season_id)


def is_watched(engine, player_id: int, competition_id: int, season_id: int) -> bool:
    with engine.connect() as conn:
        found = conn.execute(select(_TABLE.c.id)
                             .where(_key_clause(player_id, competition_id, season_id))).first()
    return found is not None


def add(engine, player_id: int, competition_id: int, season_id: int) -> bool:
    """Add one player season-row. True = added, False = was already on the list."""
    try:
        with engine.begin() as conn:
            exists = conn.execute(select(_TABLE.c.id)
                                  .where(_key_clause(player_id, competition_id, season_id))).first()
            if exists:
                return False
            conn.execute(_TABLE.insert().values(
                player_id=player_id, competition_id=competition_id, season_id=season_id))
        return True
    except IntegrityError:  # raced with another add; the unique constraint held
        return False


def remove(engine, player_id: int, competition_id: int, season_id: int) -> bool:
    """Remove one entry. True = a row was deleted."""
    with engine.begin() as conn:
        result = conn.execute(_TABLE.delete()
                              .where(_key_clause(player_id, competition_id, season_id)))
    return result.rowcount > 0


def set_note(engine, player_id: int, competition_id: int, season_id: int,
             note: str | None) -> None:
    with engine.begin() as conn:
        conn.execute(_TABLE.update()
                     .where(_key_clause(player_id, competition_id, season_id))
                     .values(note=note))


def set_status(engine, player_id: int, competition_id: int, season_id: int,
               status: str) -> None:
    if status not in WATCHLIST_STATUSES:
        raise ValueError(f"unknown watchlist status {status!r}; expected one of {WATCHLIST_STATUSES}")
    with engine.begin() as conn:
        conn.execute(_TABLE.update()
                     .where(_key_clause(player_id, competition_id, season_id))
                     .values(status=status))


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
        SELECT w.player_id, w.competition_id, w.season_id, w.note, w.status, w.created_at,
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
    return frame.drop(columns=["birth_date", "valuation_age"])
