"""Reading and writing scout assessments.

USER DATA: nothing here is ever written or cleared by the pipeline.

NOTHING IS EVER DELETED OR OVERWRITTEN. Every save is a new row, so two assessors who
disagree both stay on the record and the disagreement is visible on the profile rather than
silently resolved. `scout_assessments` deliberately carries no unique constraint on
(player, competition, season, dimension) -- see the model's docstring and the regression
test in tests/test_store.py.

Plain SQLAlchemy Core so this runs identically on production Postgres and the sqlite used
in tests, matching store/watchlist.py.
"""

from __future__ import annotations

import datetime
import logging

import pandas as pd
from sqlalchemy import select

from lofc.store.models import ScoutAssessment, ScoutCriterionScore, User

_LOG = logging.getLogger(__name__)

_A = ScoutAssessment.__table__
_C = ScoutCriterionScore.__table__
_U = User.__table__

_LOAD_COLUMNS = ["id", "player_id", "competition_id", "season_id", "dimension", "band",
                 "band_note", "screening_failed", "notes", "status", "author_id",
                 "approved_by", "approved_at", "created_at", "updated_at"]


def save(engine, *, player_id: int, competition_id: int, season_id: int, dimension: str,
         author_id: int, band: float | None, notes: str | None,
         criterion_scores: dict[str, int], criterion_passes: dict[str, bool],
         screening_failed: bool, status: str) -> int:
    """Insert one assessment and its criterion rows. Returns the new assessment id.

    Always an INSERT, never an update: a re-assessment is a new judgement, and the old one
    stays on the record attributed to whoever made it.
    """
    with engine.begin() as conn:
        result = conn.execute(_A.insert().values(
            player_id=player_id, competition_id=competition_id, season_id=season_id,
            dimension=dimension, author_id=author_id, band=band, notes=notes,
            screening_failed=screening_failed, status=status))
        assessment_id = int(result.inserted_primary_key[0])

        rows = [{"assessment_id": assessment_id, "criterion_key": key,
                 "score": score, "passed": None}
                for key, score in criterion_scores.items()]
        rows += [{"assessment_id": assessment_id, "criterion_key": key,
                  "score": None, "passed": passed}
                 for key, passed in criterion_passes.items()]
        if rows:
            conn.execute(_C.insert(), rows)

    # Local import: assessed_refresh needs store.assessments.load_all to read assessments
    # back, and this module needs assessed_refresh to close the loop after a save -- an
    # import cycle if either side were made module-level, so this one stays local.
    from lofc.model import assessed_refresh
    try:
        assessed_refresh.refresh_for_player(engine, player_id=player_id,
                                            competition_id=competition_id, season_id=season_id)
    except Exception:
        # The save is the user's work; the refresh is derived convenience. A refresh failure
        # must never lose an assessment that has already been committed.
        _LOG.exception("assessed_composite refresh failed for player_id=%s competition_id=%s "
                       "season_id=%s -- assessment %s is still saved", player_id,
                       competition_id, season_id, assessment_id)

    return assessment_id


def _frame(conn, query, columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(conn.execute(query).fetchall(), columns=columns)


def load_for_player(engine, player_id: int, competition_id: int,
                    season_id: int) -> pd.DataFrame:
    """Every assessment for one player-season, newest first, with the author's name and role.

    The author's ROLE is carried deliberately: Decision 16 lets any role enter any band, and
    the honest-record principle does the work a hard gate would otherwise do -- but only if
    the reader can see that a scout entered a medical judgement.
    """
    author = _U.alias("author")
    approver = _U.alias("approver")
    columns = _LOAD_COLUMNS + ["author_name", "author_role", "approver_name"]
    query = (select(*[_A.c[name] for name in _LOAD_COLUMNS],
                    author.c.full_name.label("author_name"),
                    author.c.role.label("author_role"),
                    approver.c.full_name.label("approver_name"))
             .select_from(_A.join(author, author.c.id == _A.c.author_id)
                            .outerjoin(approver, approver.c.id == _A.c.approved_by))
             .where(_A.c.player_id == player_id,
                    _A.c.competition_id == competition_id,
                    _A.c.season_id == season_id)
             .order_by(_A.c.updated_at.desc(), _A.c.id.desc()))
    with engine.connect() as conn:
        return _frame(conn, query, columns)


def criterion_scores_for(engine, assessment_id: int) -> pd.DataFrame:
    columns = ["criterion_key", "score", "passed"]
    query = (select(*[_C.c[name] for name in columns])
             .where(_C.c.assessment_id == assessment_id).order_by(_C.c.id))
    with engine.connect() as conn:
        return _frame(conn, query, columns)


def load_all(engine) -> pd.DataFrame:
    """Every assessment, in the shape `model/scout_scores.resolve_bands` consumes.

    The column names here are a CONTRACT with that function. If they drift, the scorecard
    rebuild stops seeing assessments and every assessed_composite silently goes NULL --
    tests/test_store_assessments.py pins the contract.
    """
    columns = ["player_id", "competition_id", "season_id", "dimension", "band", "status",
               "updated_at"]
    query = select(*[_A.c[name] for name in columns])
    with engine.connect() as conn:
        return _frame(conn, query, columns)


def pending_signoff(engine) -> pd.DataFrame:
    """Submitted assessments awaiting approval, oldest first -- a work queue, so the longest
    waiting is at the top."""
    author = _U.alias("author")
    columns = ["id", "player_id", "competition_id", "season_id", "dimension", "band",
               "screening_failed", "notes", "created_at", "author_name", "author_role"]
    query = (select(_A.c.id, _A.c.player_id, _A.c.competition_id, _A.c.season_id,
                    _A.c.dimension, _A.c.band, _A.c.screening_failed, _A.c.notes,
                    _A.c.created_at,
                    author.c.full_name.label("author_name"),
                    author.c.role.label("author_role"))
             .select_from(_A.join(author, author.c.id == _A.c.author_id))
             .where(_A.c.status == "submitted")
             .order_by(_A.c.created_at.asc(), _A.c.id.asc()))
    with engine.connect() as conn:
        return _frame(conn, query, columns)


def sign_off(engine, assessment_id: int, approver_id: int,
             now: datetime.datetime) -> None:
    """Approve one submitted assessment.

    Refuses a draft: a draft has not been offered for review, and approving one would put an
    incomplete assessment into the record as reviewed. Self-approval IS permitted (Decision
    16) -- with three people, requiring a different approver would jam the queue, and since
    a submitted assessment already scores, blocking it would gain nothing. The display layer
    labels it '(self-approved)' so one pair of eyes and two never look identical.

    Decision 17: sign-off decides WHICH assessment scores when several disagree, so it must
    recompute the stored composite -- the same refresh `save` already triggers. Without this
    the badge reads approved while the stored number is the one that was not approved. The
    approval itself commits first (`with engine.begin()` above closes before the refresh
    runs); a refresh failure below is logged, never allowed to undo the approval that already
    landed.
    """
    with engine.begin() as conn:
        current = conn.execute(
            select(_A.c.status, _A.c.player_id, _A.c.competition_id, _A.c.season_id)
            .where(_A.c.id == assessment_id)).one_or_none()
        if current is None:
            raise ValueError(f"no assessment {assessment_id}")
        status, player_id, competition_id, season_id = current
        if status != "submitted":
            raise ValueError(f"assessment {assessment_id} is {status!r}, not 'submitted'")
        conn.execute(_A.update().where(_A.c.id == assessment_id)
                     .values(status="signed_off", approved_by=approver_id,
                             approved_at=now))

    # Local import: assessed_refresh needs store.assessments.load_all to read assessments
    # back, and this module needs assessed_refresh to close the loop after a sign-off -- the
    # same cycle `save` already resolves the same way; see the comment there.
    from lofc.model import assessed_refresh
    try:
        assessed_refresh.refresh_for_player(engine, player_id=player_id,
                                            competition_id=competition_id, season_id=season_id)
    except Exception:
        # The approval is already committed; the refresh is derived convenience. A refresh
        # failure must never undo a sign-off that has already landed.
        _LOG.exception("assessed_composite refresh failed for player_id=%s competition_id=%s "
                       "season_id=%s after sign-off of assessment %s", player_id,
                       competition_id, season_id, assessment_id)


def conflicts(engine, now: datetime.datetime | None = None) -> pd.DataFrame:
    """One row per assessment inside a contested (player, competition, season, dimension)
    group -- both sides of every disagreement, not a single merged verdict, so the approver
    can see what they are choosing between rather than rubber-stamping one side.

    A dimension is contested exactly when `model.scout_scores` would resolve it to CONFLICT:
    two or more `submitted` rows and no `signed_off` row. Drafts never participate (Rule 5)
    and a signed-off assessment removes the whole dimension from this list (Rule 2) -- the
    most recently approved one would simply win, which is not a conflict.

    `waiting_days` is the same value repeated across every row of one conflict, measured from
    the OLDEST competing assessment's created_at, since that is when the disagreement began --
    not from the newest arrival, which would understate how long it has sat unresolved.

    Always returns a frame with the columns below, even when there are no conflicts -- callers
    `.groupby` on this unconditionally, and a bare empty DataFrame() has no columns to group.
    """
    now = now or datetime.datetime.now()
    out_columns = ["player_id", "competition_id", "season_id", "dimension", "id", "band",
                   "author_name", "author_role", "created_at", "waiting_days"]

    author = _U.alias("author")
    columns = ["player_id", "competition_id", "season_id", "dimension", "id", "band",
               "status", "author_name", "author_role", "created_at"]
    query = (select(_A.c.player_id, _A.c.competition_id, _A.c.season_id, _A.c.dimension,
                    _A.c.id, _A.c.band, _A.c.status,
                    author.c.full_name.label("author_name"),
                    author.c.role.label("author_role"),
                    _A.c.created_at)
             .select_from(_A.join(author, author.c.id == _A.c.author_id))
             .where(_A.c.status.in_(("submitted", "signed_off"))))
    with engine.connect() as conn:
        frame = _frame(conn, query, columns)

    if frame.empty:
        return pd.DataFrame(columns=out_columns)

    key = ["player_id", "competition_id", "season_id", "dimension"]
    rows: list[dict] = []
    for _, group in frame.groupby(key):
        if (group["status"] == "signed_off").any():
            continue  # Rule 2: a signed-off assessment is never in conflict.
        submitted = group[group["status"] == "submitted"]
        if len(submitted) < 2:
            continue  # exactly one submitted assessment -- nothing to decide.
        waiting_days = (now - submitted["created_at"].min()).days
        for row in submitted.itertuples():
            rows.append({
                "player_id": row.player_id, "competition_id": row.competition_id,
                "season_id": row.season_id, "dimension": row.dimension,
                "id": row.id, "band": row.band, "author_name": row.author_name,
                "author_role": row.author_role, "created_at": row.created_at,
                "waiting_days": waiting_days,
            })

    if not rows:
        return pd.DataFrame(columns=out_columns)
    return pd.DataFrame(rows, columns=out_columns)
