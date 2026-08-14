"""Resolve many submitted assessments into one scoring band per dimension.

Decision 14: a `submitted` assessment SCORES. Sign-off marks it approved and controls what
may be exported as final; it is not a gate on ranking. A signed-off assessment still wins
over a newer submitted one, because it is the reviewed judgement.

The frame this returns is keyed the same way `financial_resale` is, so `scorecard.py`
consumes it through the interface it already has.
"""

from __future__ import annotations

import pandas as pd

PSYCHOLOGICAL = "Psychological"
MEDICAL = "Medical Risk"

KEY = ["player_id", "competition_id", "season_id"]
_SCORING_STATUSES = ("signed_off", "submitted")
OUTPUT_COLUMNS = KEY + ["psychological_band", "psychological_status",
                        "medical_band", "medical_status"]


def _winner(group: pd.DataFrame) -> pd.Series:
    """Signed-off wins; otherwise the most recently updated submitted assessment.

    A tie on both status and updated_at is broken by a stable sort, taking the
    last row -- deterministic, not a crash, since the UI shows all submissions
    anyway and which one wins in that exact tie is not meaningful.
    """
    signed = group[group["status"] == "signed_off"]
    pool = signed if not signed.empty else group[group["status"] == "submitted"]
    return pool.sort_values("updated_at", kind="stable").iloc[-1]


def resolve_bands(assessments: pd.DataFrame) -> pd.DataFrame:
    """One row per (player_id, competition_id, season_id) with the band that scores for
    each dimension.

    `draft` rows never score -- they are filtered out before grouping, so no code
    path downstream ever sees one. The two dimensions are grouped and resolved
    independently: a signed-off Medical Risk row plays no part in deciding the
    Psychological winner for the same player/competition/season, since each
    (dimension, *key) group is resolved on its own.

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
        row = _winner(group)
        prefix = "psychological" if dimension == PSYCHOLOGICAL else "medical"
        record = records.setdefault(tuple(key), dict(zip(KEY, key)))
        record[f"{prefix}_band"] = float(row["band"]) if pd.notna(row["band"]) else None
        record[f"{prefix}_status"] = row["status"]

    return pd.DataFrame(list(records.values())).reindex(columns=OUTPUT_COLUMNS)
