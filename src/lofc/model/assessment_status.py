"""One assessment status per player-season, for the watchlist and the Players list.

DERIVED, never stored: the status comes from joining on the same (player, competition,
season) triple both tables already use, so a watchlist row and a player-profile row cannot
disagree about a player by reading two different sources.
"""

from __future__ import annotations

import pandas as pd

from lofc.model.scout_scores import MEDICAL, PSYCHOLOGICAL

KEY = ["player_id", "competition_id", "season_id"]

NOT_ASSESSED = "Not assessed"
AWAITING = "Awaiting sign-off"
SIGNED_OFF = "Signed off"
STATUSES: tuple[str, ...] = (NOT_ASSESSED, AWAITING, SIGNED_OFF)

_OUTPUT = KEY + ["assessment_status"]
_SCORING = ("submitted", "signed_off")


def per_player(assessments: pd.DataFrame) -> pd.DataFrame:
    """One row per assessed player-season with its overall status.

    SIGNED_OFF requires BOTH dimensions signed off. The weaker of the two governs: reporting
    'Signed off' while half the assessment is still unreviewed would overstate what a
    director is being shown. Drafts are excluded entirely -- a draft never scores
    (Decision 14) and must not read as assessed either.
    """
    if assessments.empty:
        return pd.DataFrame(columns=_OUTPUT)

    scoring = assessments[assessments["status"].isin(_SCORING)]
    scoring = scoring[scoring["dimension"].isin([PSYCHOLOGICAL, MEDICAL])]
    if scoring.empty:
        return pd.DataFrame(columns=_OUTPUT)

    records = []
    for key, group in scoring.groupby(KEY):
        dimensions = set(group["dimension"])
        both_signed = (len(dimensions) == 2
                       and (group["status"] == "signed_off").all())
        records.append(dict(zip(KEY, key),
                            assessment_status=SIGNED_OFF if both_signed else AWAITING))
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
