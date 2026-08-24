"""Resolve many submitted assessments into one scoring band per dimension.

Decision 17: a signed-off assessment is never in conflict, and beats any number of submitted
ones -- signing off is a deliberate act, so among several signed-off rows the most recently
APPROVED one is the considered revision. But two or more `submitted` assessments on the same
dimension, with none signed off, are a conflict: nobody has decided, so nothing scores. This
replaces the old "most recently updated submitted wins" tiebreak, which gave the final word to
whoever saved last -- a junior scout's Friday assessment silently overriding a senior's Monday
one, on no principle beyond recency. There is deliberately no threshold: a 3.0 and a 3.5 are
still two people who have not agreed, and judging which gaps "matter" would put the platform
back in the business of resolving disagreement on the user's behalf.

The frame this returns is keyed the same way `financial_resale` is, so `scorecard.py`
consumes it through the interface it already has.
"""

from __future__ import annotations

import pandas as pd

PSYCHOLOGICAL = "Psychological"
MEDICAL = "Medical Risk"
CONFLICT = "conflict"
REJECTED = "rejected"

KEY = ["player_id", "competition_id", "season_id"]
# `rejected` is deliberately absent: a rejection is a terminal review outcome (Problem 3),
# not a fourth thing that can win or contest a dimension. Leaving it out of the statuses this
# module groups on means a rejected row plays no part in `_winner` and cannot appear in a
# `group` here at all -- it neither scores nor keeps a conflict alive, with no extra branching
# needed below.
_SCORING_STATUSES = ("signed_off", "submitted")
OUTPUT_COLUMNS = KEY + ["psychological_band", "psychological_status",
                        "medical_band", "medical_status"]


def _winner(group: pd.DataFrame) -> pd.Series | None:
    """Decision 17. Signed-off rows present -> the most recently approved one wins (no row
    here has any other write path after sign-off, so `updated_at` IS the approval time).
    Otherwise, exactly one submitted row scores it. Two or more submitted rows with none
    signed off are a conflict -- returns None, and the caller records CONFLICT with no band.

    A tie on updated_at within the signed-off pool is broken by a stable sort, taking the
    last row -- deterministic, not a crash, and which one wins in that exact tie is not
    meaningful since the UI shows every submission regardless.
    """
    signed = group[group["status"] == "signed_off"]
    if not signed.empty:
        return signed.sort_values("updated_at", kind="stable").iloc[-1]

    submitted = group[group["status"] == "submitted"]
    if len(submitted) == 1:
        return submitted.iloc[0]
    # Zero submitted rows cannot happen here: `group` is drawn from _SCORING_STATUSES, so
    # every row is signed_off (handled above) or submitted -- reaching this branch with an
    # empty `submitted` would mean `signed` was also empty, which is impossible for a
    # non-empty group. Two or more submitted, none signed off: nobody has agreed.
    return None


def resolve_bands(assessments: pd.DataFrame) -> pd.DataFrame:
    """One row per (player_id, competition_id, season_id) with the band that scores for
    each dimension.

    Decision 17: a contested dimension -- two or more submitted rows, none signed off --
    yields `band = None` and `status = CONFLICT` rather than picking a side. Rule 3 downstream
    (`assessed_refresh`) means a conflict on either dimension blocks the assessed composite
    for that player-season, not just the contested dimension.

    `draft` rows never score -- they are filtered out before grouping, so no code
    path downstream ever sees one. The two dimensions are grouped and resolved
    independently: a signed-off Medical Risk row plays no part in deciding the
    Psychological winner for the same player/competition/season, since each
    (dimension, *key) group is resolved on its own.

    A `dimension` value that is neither PSYCHOLOGICAL nor MEDICAL is skipped (with a
    printed warning naming it), not folded into either bucket -- see the loop body.

    Always returns a frame with OUTPUT_COLUMNS, even when nothing scores -- an
    empty DataFrame(columns=...), never a bare DataFrame() -- so callers can
    .set_index on it unconditionally.
    """
    if assessments.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    scoring = assessments[assessments["status"].isin(_SCORING_STATUSES)]
    if scoring.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    records: dict[tuple, dict] = {}
    for (dimension, *key), group in scoring.groupby(["dimension"] + KEY):
        if dimension == PSYCHOLOGICAL:
            prefix = "psychological"
        elif dimension == MEDICAL:
            prefix = "medical"
        else:
            # An unrecognised dimension must not silently fall into either bucket --
            # `dimension` has no database CHECK constraint, so a typo on the write path
            # (e.g. lowercase "psychological") must surface, not get misfiled as
            # Medical by an if/else that treats "anything else" as the other case.
            # One bad row shouldn't take down a whole scorecard rebuild, so this
            # skips the group rather than raising -- but it must not vanish either.
            print(f"  [scout_scores] unrecognised dimension {dimension!r} -- skipped, "
                  "not scored to psychological or medical", flush=True)
            continue
        row = _winner(group)
        record = records.setdefault(tuple(key), dict(zip(KEY, key)))
        if row is None:
            # Decision 17: two or more submitted, none signed off -- a conflict, not a band.
            record[f"{prefix}_band"] = None
            record[f"{prefix}_status"] = CONFLICT
        else:
            record[f"{prefix}_band"] = float(row["band"]) if pd.notna(row["band"]) else None
            record[f"{prefix}_status"] = row["status"]

    return pd.DataFrame(list(records.values())).reindex(columns=OUTPUT_COLUMNS)
