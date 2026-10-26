"""Run record + per-league failure isolation for the pipeline (owner, 2026-10-26).

Before this, `pipeline.main` stopped at the first failed step: one broken league froze every
league's data, and the only trace was a file on the server. Now:

  * every step, and every league inside a league-by-league step, is recorded in
    `pipeline_runs` (status, start/finish, rows, error);
  * `for_each_league` runs each league inside a guard -- a failure is recorded and the other
    leagues carry on;
  * `finish_step` then exits PARTIAL_EXIT, which the orchestrator treats as "carry on, but
    finish the whole run as partial". Any other non-zero exit still stops the run.

The run id travels to each step subprocess in the LOFC_RUN_ID environment variable, so all
rows of one weekly run share it. Recording is best-effort: if the database cannot be written,
the pipeline still runs (a log that breaks the thing it logs is worse than no log).
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import traceback
from typing import Callable, Iterable

RUN_ID_ENV = "LOFC_RUN_ID"
PARTIAL_EXIT = 3           # a step finished, but at least one league inside it failed
MAX_ERROR_CHARS = 1000


def new_run_id() -> str:
    return dt.datetime.utcnow().strftime("run-%Y%m%dT%H%M%SZ")


def current_run_id() -> str:
    """The run this process belongs to; a manual run of one step gets its own id."""
    return os.environ.get(RUN_ID_ENV) or ("manual-" + new_run_id()[4:])


def error_text(exc: BaseException) -> str:
    """Exception class and message, capped. Never the traceback's local variables, so a
    credential held in a local can never reach the table. Never raises, even for an
    exception whose message cannot be printed."""
    try:
        message = str(exc)
    except Exception:                                        # noqa: BLE001
        message = "(message could not be read)"
    return f"{type(exc).__name__}: {message}"[:MAX_ERROR_CHARS]


def _rows(n) -> int | None:
    """A row count to record, or None -- never raises on NaN, bool or other types."""
    try:
        if isinstance(n, bool) or n is None:
            return None
        value = float(n)
        return int(value) if value == value else None        # NaN != NaN
    except (TypeError, ValueError, OverflowError):
        return None


def _engine():
    from lofc.store.load import get_engine
    return get_engine()


def record(engine=None, *, step: str, status: str, league: str | None = None,
           competition_id: int | None = None, season_id: int | None = None,
           started_at: dt.datetime | None = None, finished_at: dt.datetime | None = None,
           rows: int | None = None, error: str | None = None,
           run_id: str | None = None) -> None:
    """Insert one pipeline_runs row. Never raises."""
    try:
        from sqlalchemy import insert
        from lofc.store.models import PipelineRun
        engine = engine or _engine()
        with engine.begin() as conn:
            conn.execute(insert(PipelineRun.__table__).values(
                run_id=run_id or current_run_id(), step=step, status=status, league=league,
                competition_id=competition_id, season_id=season_id, started_at=started_at,
                finished_at=finished_at or dt.datetime.utcnow(), rows=rows, error=error))
    except Exception as exc:                                 # noqa: BLE001 -- see docstring
        print(f"  (could not record pipeline run for {step}: {type(exc).__name__})")


def for_each_league(step: str, items: Iterable, *, label: Callable, keys: Callable,
                    fn: Callable, engine=None) -> list[str]:
    """Run `fn(item)` for every league, isolating failures. Returns the failed labels.

    `keys(item)` -> (competition_id, season_id); `fn` may return a row count to record."""
    failures = []
    for i, item in enumerate(items):
        started = dt.datetime.utcnow()
        name, comp, season = f"league #{i + 1}", None, None
        try:
            # Naming the league is inside the guard too: nothing about ONE league may stop
            # the others. SystemExit is caught for the same reason; Ctrl-C is not.
            name = label(item)
            comp, season = keys(item)
            n = fn(item)
        except KeyboardInterrupt:
            raise
        except BaseException as exc:                         # noqa: BLE001 -- isolation
            traceback.print_exc()
            print(f"  [{name}] FAILED in {step}: {error_text(exc)} -- other leagues continue")
            record(engine, step=step, status="failed", league=str(name), competition_id=comp,
                   season_id=season, started_at=started, error=error_text(exc))
            failures.append(str(name))
            continue
        record(engine, step=step, status="success", league=str(name), competition_id=comp,
               season_id=season, started_at=started, rows=_rows(n))
    return failures


def finish_step(step: str, failures: list[str]) -> None:
    """End a league-by-league step: exit PARTIAL_EXIT if any league failed."""
    if failures:
        print(f"{step}: {len(failures)} league(s) failed: {', '.join(failures)}")
        sys.exit(PARTIAL_EXIT)


def failed_leagues(run_id: str, engine=None) -> list[str]:
    """'step: league' for every league that failed in this run. Never raises."""
    try:
        from sqlalchemy import text
        engine = engine or _engine()
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT step, league FROM pipeline_runs WHERE run_id = :r AND status = 'failed' "
                "AND league IS NOT NULL ORDER BY id"), {"r": run_id}).fetchall()
        return [f"{s}: {lg}" for s, lg in rows]
    except Exception:                                        # noqa: BLE001
        return []
