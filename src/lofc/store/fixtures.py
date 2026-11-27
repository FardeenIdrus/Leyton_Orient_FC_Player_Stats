"""Fixtures page user data (owner 2026-11-27, phase 5): which scout goes to which game, games
added by hand, and scout reports a person linked to a player.

USER DATA, not pipeline output: nothing here is ever cleared by a pipeline run. Plain
SQLAlchemy Core so it runs the same on production Postgres and the sqlite used in tests.
"""
from __future__ import annotations

import datetime

import pandas as pd
from sqlalchemy import delete, insert, select, update

from lofc.store.models import FixtureAssignment, ManualFixture, ScoutReportLink

_A = FixtureAssignment.__table__
_M = ManualFixture.__table__
_L = ScoutReportLink.__table__


def assign(engine, key: str, user_id: int | None, by: int | None, name: str | None = None) -> None:
    """Set the scout for one game: a platform user, or any typed name (most scouts have no
    account, owner 2026-11-27). Neither clears it."""
    name = (name or "").strip() or None
    with engine.begin() as conn:
        conn.execute(delete(_A).where(_A.c.fixture_key == key))
        if user_id is not None or name:
            conn.execute(insert(_A).values(fixture_key=key, user_id=None if user_id is None else int(user_id),
                                           scout_name=None if user_id is not None else name, assigned_by=by,
                                           assigned_at=datetime.datetime.now()))


def assignments(engine) -> dict:
    """fixture key -> {"user_id", "name"} (name = a typed scout name)."""
    with engine.connect() as conn:
        rows = conn.execute(select(_A.c.fixture_key, _A.c.user_id, _A.c.scout_name)).all()
    return {k: {"user_id": None if u is None else int(u), "name": n} for k, u, n in rows}


def typed_names(engine) -> list[str]:
    """Names typed before, to suggest them again."""
    with engine.connect() as conn:
        rows = conn.execute(select(_A.c.scout_name).where(_A.c.scout_name.isnot(None)).distinct()).all()
    return sorted(r[0] for r in rows)


def add_manual(engine, when: datetime.datetime, competition, home: str, away: str,
               home_squad_id, away_squad_id, by: int | None) -> int:
    with engine.begin() as conn:
        res = conn.execute(insert(_M).values(
            scheduled_at=when, competition=(competition or None), home_name=home.strip(), away_name=away.strip(),
            home_squad_id=home_squad_id, away_squad_id=away_squad_id, added_by=by,
            added_at=datetime.datetime.now()))
        return int(res.inserted_primary_key[0])


def remove_manual(engine, fixture_id: int) -> None:
    with engine.begin() as conn:
        conn.execute(delete(_M).where(_M.c.id == int(fixture_id)))
        conn.execute(delete(_A).where(_A.c.fixture_key == f"x:{int(fixture_id)}"))


def manual_between(engine, start: datetime.datetime, end: datetime.datetime) -> pd.DataFrame:
    with engine.connect() as conn:
        rows = conn.execute(select(_M).where(_M.c.scheduled_at >= start, _M.c.scheduled_at < end)
                            .order_by(_M.c.scheduled_at)).mappings().all()
    return pd.DataFrame([dict(r) for r in rows], columns=[c.name for c in _M.columns])


def link_report(engine, submission_id: str, player_id: int, by: int | None) -> None:
    """A person says which player a report is about. Written to the report at once and kept
    over the automatic linking on every later sync."""
    from lofc.store.models import ScoutReport
    r = ScoutReport.__table__
    with engine.begin() as conn:
        conn.execute(delete(_L).where(_L.c.submission_id == submission_id))
        conn.execute(insert(_L).values(submission_id=submission_id, player_id=int(player_id), linked_by=by,
                                       linked_at=datetime.datetime.now()))
        conn.execute(update(r).where(r.c.submission_id == submission_id).values(player_id=int(player_id)))


def report_links(engine) -> dict:
    with engine.connect() as conn:
        return {s: int(p) for s, p in conn.execute(select(_L.c.submission_id, _L.c.player_id)).all()}
