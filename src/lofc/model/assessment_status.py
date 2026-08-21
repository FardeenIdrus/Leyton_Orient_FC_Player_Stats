"""One assessment status per player-season, for the watchlist and the Players list.

DERIVED, never stored: the status comes from joining on the same (player, competition,
season) triple both tables already use, so a watchlist row and a player-profile row cannot
disagree about a player by reading two different sources.
"""

from __future__ import annotations

import pandas as pd

from lofc.model import scout_scores
from lofc.model.scout_scores import CONFLICT, MEDICAL, PSYCHOLOGICAL

KEY = ["player_id", "competition_id", "season_id"]

NOT_ASSESSED = "Not assessed"
AWAITING = "Awaiting sign-off"
CONFLICTED = "Assessments conflict"
SIGNED_OFF = "Signed off"
STATUSES: tuple[str, ...] = (NOT_ASSESSED, AWAITING, CONFLICTED, SIGNED_OFF)

_OUTPUT = KEY + ["assessment_status"]
_SCORING = ("submitted", "signed_off")


def per_player(assessments: pd.DataFrame) -> pd.DataFrame:
    """One row per assessed player-season with its overall status.

    CONFLICTED takes priority over the other two: if EITHER dimension is contested
    (Decision 17 -- `model.scout_scores.resolve_bands` would return `band=None,
    status=CONFLICT` for it), the aggregate reads as conflicted regardless of the other
    dimension's state, because a live disagreement is the thing that most needs a look --
    B1/task 10 requires this badge to read identically here, on the profile and on the
    sign-off queue, so this delegates to the same `resolve_bands` those surfaces use rather
    than re-deriving the conflict rule.

    Otherwise, SIGNED_OFF requires BOTH dimensions signed off. The weaker of the two
    governs: reporting 'Signed off' while half the assessment is still unreviewed would
    overstate what a director is being shown. Drafts are excluded entirely -- a draft never
    scores (Decision 14) and must not read as assessed either.

    both_signed is read off `resolve_bands`'s OWN psychological_status/medical_status, never
    re-derived from the raw group. Decision 17 means a signed-off row beats any number of
    submitted ones on the same dimension -- so a signed-off assessment sitting beside a
    newer, superseded `submitted` row (e.g. someone re-assessing after sign-off, or a second
    opinion nobody has signed off yet) still resolves to 'signed_off' for that dimension. A
    raw `(group["status"] == "signed_off").all()` check does not know that: any non-signed-off
    row in the group fails it, flipping the aggregate to Awaiting sign-off even though
    `resolve_bands` -- the same function that decides what actually scores -- says the
    dimension IS signed off. That mismatch was reproduced live (player 80945, competition 5,
    season 318) and is exactly what this docstring's "cannot happen" claim used to miss.
    """
    if assessments.empty:
        return pd.DataFrame(columns=_OUTPUT)

    scoring = assessments[assessments["status"].isin(_SCORING)]
    scoring = scoring[scoring["dimension"].isin([PSYCHOLOGICAL, MEDICAL])]
    if scoring.empty:
        return pd.DataFrame(columns=_OUTPUT)

    resolved = scout_scores.resolve_bands(assessments).set_index(KEY)

    records = []
    for key, group in scoring.groupby(KEY):
        resolved_row = resolved.loc[key] if key in resolved.index else None
        psych_status = resolved_row.get("psychological_status") if resolved_row is not None else None
        med_status = resolved_row.get("medical_status") if resolved_row is not None else None
        conflicted = psych_status == CONFLICT or med_status == CONFLICT
        if conflicted:
            status = CONFLICTED
        else:
            both_signed = psych_status == "signed_off" and med_status == "signed_off"
            status = SIGNED_OFF if both_signed else AWAITING
        records.append(dict(zip(KEY, key), assessment_status=status))
    return pd.DataFrame(records, columns=_OUTPUT)


def attach(frame: pd.DataFrame, statuses: pd.DataFrame) -> pd.DataFrame:
    """Add `assessment_status` to `frame`, defaulting to NOT_ASSESSED.

    A LEFT join, deliberately: showing the badge column must never drop a player. Filtering
    to assessed players is an explicit opt-in mode, never a side effect of rendering a badge.
    """
    if frame.empty:
        out = frame.copy()
        out["assessment_status"] = pd.Series(dtype=object)
        return out
    merged = frame.merge(statuses, on=KEY, how="left")
    merged["assessment_status"] = merged["assessment_status"].fillna(NOT_ASSESSED)
    return merged
