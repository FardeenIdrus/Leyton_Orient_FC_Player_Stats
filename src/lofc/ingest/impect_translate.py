"""Translate landed Impect data into our provider-neutral per-90 metrics.

This is the Impect half of the provider-neutral layer. It takes an iteration's
landed file (one row per player per position) and returns one row per player with
our internal metric names, so everything downstream (scoring, valuation, the
dashboard) reads the same names regardless of which provider supplied them.

Two corrections proven necessary (see impect_map + the per-90 investigation):
  - PER-90, not per-match. Impect KPIs are averages per full match played, and a
    full match runs ~100 min not 90. We rebuild each season total (value x
    matchShare, summed over a player's position rows) and divide by real minutes
    (playDuration seconds / 60) x 90, giving a true per-90 that matches StatsBomb.
  - MINUTES FLOOR. The same 450-minute rankable cut StatsBomb uses, because a tiny
    sample otherwise yields absurd rates (a one-minute cameo scorer reads as 14/90).

The "none" metrics (the StatsBomb-only set impect_map documents as having no
validated Impect equivalent) are NOT produced here; they come from StatsBomb until
the licence cutoff, when their honestly-named Impect successors take over.

Read-only: returns a DataFrame; writes nothing.
"""

from __future__ import annotations

import pandas as pd

from lofc.config import ImpectTarget
from lofc.ingest import impect as impect_landing
from lofc.ingest.impect_map import IMPECT_MAP, impect_columns_used

MINUTES_FLOOR = 450  # matches aggregate.player_season rankable cut


def translate_frame(frame: pd.DataFrame, competition_id: int | None = None,
                    season_id: int | None = None) -> pd.DataFrame:
    """One row per player with our internal metric names, per-90 corrected.

    `frame` is a landed Impect iteration (player x position rows). competition_id
    / season_id are stamped on every row so the result keys like the rest of the
    pipeline (player x league x season).
    """
    frame = frame.copy()
    used = [c for c in impect_columns_used() if c in frame.columns]

    # Season totals per column = sum(value x matchShare) across a player's rows;
    # season minutes = sum(playDuration seconds / 60).
    for col in used:
        frame[f"_t_{col}"] = frame[col] * frame["matchShare"]
    frame["_minutes"] = frame["playDuration"] / 60.0

    agg = {"_minutes": "sum", "matchShare": "sum"}
    agg.update({f"_t_{c}": "sum" for c in used})
    totals = frame.groupby("playerId", as_index=False).agg(agg)

    # Dominant identity = the position row with the most matchShare.
    dom_idx = frame.groupby("playerId")["matchShare"].idxmax()
    ident = frame.loc[dom_idx, ["playerId", "playerName", "birthdate",
                                "squadName", "position"]]
    out = totals.merge(ident, on="playerId", how="left")

    def tot(col: str) -> pd.Series:
        return out[f"_t_{col}"] if f"_t_{col}" in out.columns else pd.Series(0.0, index=out.index)

    minutes = out["_minutes"].replace(0, pd.NA)
    for m in IMPECT_MAP:
        if m.kind == "rate":
            season_total = sum(sign * tot(col) for col, sign in m.numer)
            out[m.name] = season_total / minutes * 90.0
        elif m.kind == "ratio":
            numer = sum(sign * tot(col) for col, sign in m.numer)
            denom = sum(sign * tot(col) for col, sign in m.denom).replace(0, pd.NA)
            out[m.name] = numer / denom
        # kind == "none": not produced from Impect

    result = out.rename(columns={"playerName": "player_name",
                                 "squadName": "team_name",
                                 "birthdate": "birth_date"})
    result["birth_date"] = pd.to_datetime(result["birth_date"], errors="coerce")
    result["minutes"] = out["_minutes"]
    result["rankable"] = result["minutes"] >= MINUTES_FLOOR
    result["competition_id"] = competition_id
    result["season_id"] = season_id

    metric_cols = [m.name for m in IMPECT_MAP if m.kind != "none"]
    keep = (["playerId", "player_name", "team_name", "birth_date", "position",
             "minutes", "rankable", "competition_id", "season_id"] + metric_cols)
    return result[keep]


def translate_target(target: ImpectTarget) -> pd.DataFrame:
    """Translate one configured iteration from its landed file."""
    frame = pd.read_parquet(impect_landing.averages_path(target.iteration_id))
    return translate_frame(frame, target.sb_competition_id, target.sb_season_id)
