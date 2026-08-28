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
from lofc.ingest.impect_map import (IMPECT_MAP, IMPECT_POSITION_GROUPS,
                                    impect_columns_used)

MINUTES_FLOOR = 450  # matches aggregate.player_season rankable cut


def dominant_position(frame: pd.DataFrame) -> pd.Index:
    """Index of each player's representative position row, chosen by GROUP total.

    Impect reports one row per player per position, and splits two of our groups across
    sides: WINGER (LEFT_/RIGHT_) and WINGBACK_DEFENDER (LEFT_/RIGHT_). Taking the single
    longest single position ROW therefore systematically under-counts exactly those two -- a
    player with 3.0 at centre forward and 2.0 + 2.0 on the two wings reads as a centre
    forward, though he spent more time as a winger than as anything else.

    So: sum MINUTES per group, take the winning group, and within it take the side he
    actually played more (a left winger who also filled in on the right is a LEFT_WINGER).

    Minutes, not matchShare, deliberately. The two are near-identical (matchShare is
    minutes / ~100, Impect counting a full match as ~100 minutes of real elapsed time) and
    they disagree for only 7 of 6,575 player-seasons -- but the position SPLIT shown on the
    report is measured in minutes, so choosing on matchShare made those 7 reports
    self-contradictory: "Scored as Winger" above a split led by Attacking Mid.
    Measured on the live files this moves 29 of 1,999 Impect-spined rankable
    player-seasons, almost all of them INTO Winger or Full Back.

    Positions with no group mapping (a future Impect enum) are grouped under themselves,
    so they can still win on their own merit and can never raise a KeyError.

    Returns an index into `frame` with exactly one row per playerId.
    """
    grouped = frame[["playerId", "position", "playDuration"]].copy()
    grouped["_group"] = (grouped["position"].map(IMPECT_POSITION_GROUPS)
                         .fillna(grouped["position"]))
    # merge() returns a fresh RangeIndex, so carry frame's own labels through as a
    # COLUMN. Returning the merged frame's index would silently point at the wrong rows.
    grouped["_row"] = frame.index
    # Winning group per player: the group holding the most of his matchShare.
    per_group = grouped.groupby(["playerId", "_group"], as_index=False)["playDuration"].sum()
    winner = per_group.loc[per_group.groupby("playerId")["playDuration"].idxmax(),
                           ["playerId", "_group"]]
    # Representative row: the largest single row INSIDE the winning group.
    in_winner = grouped.merge(winner, on=["playerId", "_group"], how="inner")
    picked = in_winner.loc[in_winner.groupby("playerId")["playDuration"].idxmax(), "_row"]
    return pd.Index(picked.to_numpy())


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

    # Dominant identity (name/birthdate/position) = the row returned by
    # dominant_position, which sums matchShare per position GROUP before choosing.
    ident = frame.loc[dominant_position(frame),
                      ["playerId", "playerName", "birthdate", "position"]]

    # Club shown = the squad the player accumulated the most MINUTES for this season.
    # matchShare is a per-position share and doesn't respect a mid-season move: a
    # player's single highest-matchShare row can belong to the club he played FEWER
    # total minutes for (his minutes there were concentrated in one position, while at
    # his other club they were split across two or three). So club is picked
    # separately from identity, by summing playDuration per squad first.
    team_minutes = frame.groupby(["playerId", "squadName"])["_minutes"].sum().reset_index()
    team_idx = team_minutes.groupby("playerId")["_minutes"].idxmax()
    team = team_minutes.loc[team_idx, ["playerId", "squadName"]]

    out = totals.merge(ident, on="playerId", how="left").merge(team, on="playerId", how="left")

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
