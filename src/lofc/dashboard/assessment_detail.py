"""The shared "what did the scout actually score" component (Problem 2).

Both the sign-off queue and the player profile used to show only the MEAN of an assessment --
a psychological band of 4.0, which reads identically whether it came from `5, 5, 2` (a
volatile, divisive player) or `4, 4, 4` (a genuinely consistent one). The per-criterion scores
were already stored (`scout_criterion_scores`) and already readable
(`store.assessments.criterion_scores_for`); nothing rendered them. This module is the ONE
place that turns those rows into something a reader can scan, so the queue and the profile can
never disagree about what a criterion-by-criterion breakdown looks like.

Split deliberately into a pure half (`criterion_rows`, `comparison_table`, `entries_table`) --
plain functions over DataFrames, no Streamlit, no database -- and a thin Streamlit half that
fetches from the store and calls the pure half. The pure half is what tests/test_assessment_detail.py
exercises directly.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from lofc.dashboard import badges
from lofc.model import assessment_rules as rules
from lofc.model import club_criteria as cc
from lofc.model import scout_scores
from lofc.model.scout_scores import MEDICAL, PSYCHOLOGICAL, REJECTED
from lofc.store import assessments as store_assess


def dimension_status(frame: pd.DataFrame, dimension: str) -> str | None:
    """The Decision 17 verdict for one dimension of one player-season: `'signed_off'`,
    `'submitted'` or `scout_scores.CONFLICT` -- `None` if nothing scoring exists yet.

    Delegates to `model.scout_scores.resolve_bands`, the SAME function that decides
    `assessed_composite`, rather than re-deriving the conflict rule here -- so the profile
    and the sign-off queue can never show a different verdict than the one that actually
    scored (or didn't). In particular this is NOT `len(submitted rows) > 1`: a dimension with
    a signed-off row and several newer submitted re-assessments is not a conflict (a
    signed-off row is never in conflict, Decision 17), even though more than one `submitted`
    row exists alongside it.
    """
    resolved = scout_scores.resolve_bands(frame)
    if resolved.empty:
        return None
    prefix = "psychological" if dimension == PSYCHOLOGICAL else "medical"
    value = resolved.iloc[0].get(f"{prefix}_status")
    return None if pd.isna(value) else value


def criterion_rows(position: str, dimension: str) -> list[tuple[str, str]]:
    """(criterion_key, criterion text) pairs, in the club's own order, for one position and
    dimension.

    Medical lists only the `screening` criteria (Decision 7): `availability` is a computed
    figure shown elsewhere as evidence and `protocol` is a club process step, and neither is
    ever scored by the assessor, so neither has an answer to compare.
    """
    if dimension == PSYCHOLOGICAL:
        return [(rules.criterion_key(t), t) for t in cc.PSYCHOLOGICAL_CRITERIA[position]]
    if dimension == MEDICAL:
        return [(rules.criterion_key(c.text), c.text) for c in cc.MEDICAL_CRITERIA[position]
                if c.kind == "screening"]
    return []


def _cell(dimension: str, score: int | None, passed: bool | None) -> str:
    if dimension == PSYCHOLOGICAL:
        return "—" if score is None else str(int(score))
    return "—" if passed is None else ("Meets" if passed else "Does not meet")


def comparison_table(position: str, dimension: str, columns: list[str],
                     per_entry_scores: list[dict[str, tuple[int | None, bool | None]]]
                     ) -> pd.DataFrame:
    """One row per club criterion, one column per assessment -- so two scouts' answers to the
    SAME criterion sit on the same line and diverge visibly, rather than requiring the reader
    to hold one scout's whole card in their head while scrolling to compare it with the next.

    `columns` and `per_entry_scores` are parallel: `columns[i]` labels the assessment whose
    scores are `per_entry_scores[i]`, a `{criterion_key: (score, passed)}` map (exactly one of
    the pair is meaningful per Decision -- psychological carries `score`, medical `passed`).
    A criterion missing from an entry's map (an incomplete draft, or a position mismatch)
    reads as "—", never a crash or a silently dropped row.

    Returns an empty DataFrame if this position has no criteria for `dimension` at all (e.g.
    a position with only `availability`/`protocol` medical criteria) -- callers check
    `.empty` rather than assuming a non-empty table.
    """
    rows = criterion_rows(position, dimension)
    if not rows:
        return pd.DataFrame()
    data = {label: [_cell(dimension, *score_map.get(key, (None, None))) for key, _ in rows]
           for label, score_map in zip(columns, per_entry_scores)}
    return pd.DataFrame(data, index=[text for _, text in rows])


def entries_table(rows: pd.DataFrame) -> pd.DataFrame:
    """A scannable one-row-per-assessment summary: who, band, status in words, when -- the
    replacement for the stacked cards `tabs/players.py` used to render one per scout.

    `rows` needs `author_name`, `author_role`, `band`, `status`, `created_at` and, where
    present, `approver_name`/`approved_at` -- exactly what `store.assessments.load_for_player`
    and `pending_signoff` already return. The Status column reuses `badges.for_status` rather
    than inventing separate wording, so a reader can never see the queue and the profile
    describe the same assessment two different ways.
    """
    columns = ["Entered by", "Role", "Band", "Status", "Date"]
    if rows.empty:
        return pd.DataFrame(columns=columns)

    def _status_text(row) -> str:
        approver = row["approver_name"] if "approver_name" in row and pd.notna(row["approver_name"]) else None
        approved_at = row["approved_at"] if "approved_at" in row and pd.notna(row["approved_at"]) else None
        return badges.for_status(row["status"], row["author_name"], approver, approved_at).text

    return pd.DataFrame({
        "Entered by": rows["author_name"].tolist(),
        "Role": rows["author_role"].tolist(),
        "Band": [("—" if pd.isna(b) else f"{b:.2f}") for b in rows["band"]],
        "Status": [_status_text(row) for _, row in rows.iterrows()],
        "Date": rows["created_at"].dt.strftime("%d %b %Y").tolist(),
    })


# --- Streamlit rendering (not unit-tested; see the module docstring) -------------------


def render_flags(entries) -> None:
    """Anything a band/status/date does not already say -- a screening disagreement, a
    rejection and its reason, free-text notes -- attributed per assessment so several scouts'
    flags are never run together into one anonymous caption.

    `entries` is an iterable of rows shaped like `entries_table`'s input (namedtuples from
    `.itertuples()` work, since only attribute access is used).
    """
    for e in entries:
        pieces: list[str] = []
        if getattr(e, "screening_failed", False):
            pieces.append("a screening criterion was not met — the band is unchanged; this "
                          "records the disagreement, it does not cap the figure")
        if e.status == REJECTED:
            reason = getattr(e, "rejection_reason", None)
            pieces.append(f"rejected — {reason}" if (reason and str(reason).strip())
                          else "rejected (no reason recorded)")
        notes = getattr(e, "notes", None)
        if pd.notna(notes) and str(notes).strip():
            pieces.append(f"notes: {notes}")
        if pieces:
            st.caption(f"**{e.author_name}**, {e.created_at:%d %b %Y} — " + "; ".join(pieces))


def _entry_scores(engine, assessment_id: int) -> dict[str, tuple[int | None, bool | None]]:
    crit = store_assess.criterion_scores_for(engine, assessment_id)
    out: dict[str, tuple[int | None, bool | None]] = {}
    for r in crit.itertuples():
        score = int(r.score) if pd.notna(r.score) else None
        passed = bool(r.passed) if pd.notna(r.passed) else None
        out[r.criterion_key] = (score, passed)
    return out


def render_criterion_detail(engine, position: str | None, dimension: str, entries) -> None:
    """One expander holding the criterion-by-criterion table for every entry passed in -- a
    single assessment renders as one column (still worth expanding: '5, 5, 2' vs '4' is the
    whole point of Problem 2), several as a side-by-side comparison so a reader can see WHERE
    two scouts diverged rather than only THAT they did.
    """
    entries = list(entries)
    if not entries:
        return
    if not position or position not in cc.POSITION_GROUPS:
        st.caption("No club criteria are configured for this position — per-criterion "
                   "detail is unavailable.")
        return

    columns, scores = [], []
    for e in entries:
        band = "—" if e.band is None or pd.isna(e.band) else f"{e.band:.2f}"
        columns.append(f"{e.author_name} — band {band}")
        scores.append(_entry_scores(engine, int(e.id)))
    table = comparison_table(position, dimension, columns, scores)

    label = f"Per-criterion detail ({len(entries)} assessment{'s' if len(entries) != 1 else ''})"
    with st.expander(label):
        if table.empty:
            st.caption("No per-criterion detail recorded.")
        else:
            st.dataframe(table, width="stretch")
