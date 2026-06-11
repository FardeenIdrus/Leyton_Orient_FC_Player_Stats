"""The recruiter's watchlist: add, remove, annotate, and load tracked players.

USER DATA, not pipeline output: nothing here is ever cleared by a pipeline run.
Plain SQLAlchemy Core throughout (no Postgres-specific upserts) so the module
runs identically on the production Postgres and the sqlite used in tests.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError

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
    """
    query = """
        SELECT w.player_id, w.competition_id, w.season_id, w.note, w.status, w.created_at,
               p.player_name, p.contract_until, p.tm_player_id,
               m.team_name, m.position_group, m.competition_name,
               s.performance_score, s.fit_score,
               v.market_value_eur, v.age
        FROM watchlist w
        LEFT JOIN players p ON p.player_id = w.player_id
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
    return pd.read_sql(query, engine)
