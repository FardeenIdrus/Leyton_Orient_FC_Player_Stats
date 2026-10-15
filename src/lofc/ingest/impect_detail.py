"""Impect detail data for DISPLAY: zones, lanes, receptions by availability, Impect's scores.

Nothing here reaches the composite. The averages file already landed by `ingest.impect`
carries ~1,480 KPI columns per player; scoring uses 36. This module names the ones the
player card shows and translates them to per-90 values and season totals.

Zone codes are Impect's packing zones; lanes are its five vertical channels. "Receptions"
are Impect's packing receptions (BYPASSED_OPPONENTS_RECEIVING_NUMBER) -- passes received
that bypassed at least one opponent -- not every touch of the ball. Availability codes are
Impect's (context.label): BTL = receiving in the DM/CM/AM zones, OUT_WIDE = in the wide or
full-back zones, FDR = from deep runs, behind the defensive chain.

Stored long (player x metric) in player_detail_metrics, so a new family needs no migration.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

ZONES = ("CB", "FBL", "FBR", "DM", "CM", "WL", "WR", "AM", "IBWL", "IB", "IBWR")
LANES = ("LEFT_WING", "LEFT_HALF_SPACE", "CENTER", "RIGHT_HALF_SPACE", "RIGHT_WING")

# Impect's own zone names: the `context.label` of every *_PACKING_ZONE_* KPI in its catalogue
# (kpi_definitions.json). Zones are defined RELATIVE TO THE OPPONENT'S PLAYERS, not as fixed
# pitch areas -- e.g. "In-Behind Central: at most one opposing centre-back and the keeper between
# the ball and the goal". Impect's GK zone exists but carries no per-zone values in the API.
ZONE_LABELS = {
    "CB": "Centre-Back Zone", "FBL": "Full-Back Left Zone", "FBR": "Full-Back Right Zone",
    "DM": "Defensive-Mid Zone", "CM": "Centre-Mid Zone", "WL": "Wide Left Zone",
    "WR": "Wide Right Zone", "AM": "Attacking-Mid Zone", "IBWL": "In-Behind Wide Left Zone",
    "IB": "In-Behind Central Zone", "IBWR": "In-Behind Wide Right Zone",
}

# family -> (zone template, lane template or None, label). Labels are Impect's catalogue
# names (`parentKpi.label`); "from zone" / "to zone" is the API's own split -- where the action
# started, and where it ended.
ZONE_FAMILIES: dict[str, tuple[str, str | None, str]] = {
    "touches": ("OFFENSIVE_TOUCHES_IN_PACKING_ZONE_{}", "OFFENSIVE_TOUCHES_IN_LANE_{}",
                "Offensive Touches"),
    "defensive_touches": ("DEFENSIVE_TOUCHES_IN_PACKING_ZONE_{}", "DEFENSIVE_TOUCHES_IN_LANE_{}",
                          "Defensive Touches"),
    "bypassed_opponents_from": ("BYPASSED_OPPONENTS_FROM_PACKING_ZONE_{}", None,
                                "Bypassed Opponents — from zone"),
    "bypassed_opponents_to": ("BYPASSED_OPPONENTS_TO_PACKING_ZONE_{}", None,
                              "Bypassed Opponents — to zone"),
    "bypassed_opponents_receiving_from": ("BYPASSED_OPPONENTS_RECEIVING_FROM_PACKING_ZONE_{}", None,
                                          "Bypassed Opponents Receiving — from zone"),
    "bypassed_opponents_receiving_to": ("BYPASSED_OPPONENTS_RECEIVING_TO_PACKING_ZONE_{}", None,
                                        "Progressive Receiving"),   # Impect platform name, verified
    "bypassed_defenders_from": ("BYPASSED_DEFENDERS_FROM_PACKING_ZONE_{}", None,
                                "Bypassed Defenders — from zone"),
    "bypassed_defenders_to": ("BYPASSED_DEFENDERS_TO_PACKING_ZONE_{}", None,
                              "Bypassed Defenders — to zone"),
    "bypassed_defenders_receiving_from": ("BYPASSED_DEFENDERS_RECEIVING_FROM_PACKING_ZONE_{}", None,
                                          "Bypassed Defenders Receiving — from zone"),
    "bypassed_defenders_receiving_to": ("BYPASSED_DEFENDERS_RECEIVING_TO_PACKING_ZONE_{}", None,
                                        "Bypassed Defenders Receiving — to zone"),
    "ball_wins": ("BALL_WIN_NUMBER_IN_PACKING_ZONE_{}", "BALL_WIN_NUMBER_IN_LANE_{}",
                  "Ball Win Number"),
    # Stored for profiles; not on Impect's Packing Zones tab.
    "receptions": ("BYPASSED_OPPONENTS_RECEIVING_NUMBER_TO_PACKING_ZONE_{}",
                   "BYPASSED_OPPONENTS_RECEIVING_NUMBER_TO_LANE_{}",
                   "Bypassed Opponents Receiving Number — to zone"),
    "ground_duels_won": ("WON_GROUND_DUELS_IN_PACKING_ZONE_{}", "WON_GROUND_DUELS_IN_LANE_{}",
                         "Won Ground Duels"),
    "aerial_duels_won": ("WON_AERIAL_DUELS_IN_PACKING_ZONE_{}", "WON_AERIAL_DUELS_IN_LANE_{}",
                         "Won Aerial Duels"),
    "shots": ("SHOT_AT_GOAL_NUMBER_IN_PACKING_ZONE_{}", "SHOT_AT_GOAL_NUMBER_IN_LANE_{}",
              "Total Shots"),
    "xg": ("SHOT_XG_IN_PACKING_ZONE_{}", "SHOT_XG_IN_LANE_{}", "Shot-based xG"),
    "goals": ("GOALS_IN_PACKING_ZONE_{}", "GOALS_IN_LANE_{}", "Goals"),
}

# Total touches = offensive + defensive, verified equal to Impect's TOTAL_TOUCHES (scores
# endpoint) in every zone checked -- so it is computed here rather than pulled twice.
TOTAL_TOUCHES_LABEL = "Total Touches"

# The map's dropdown, in the order of Impect's Packing Zones tab.
MAP_FAMILIES = ["total_touches", "touches", "defensive_touches",
                "bypassed_opponents_from", "bypassed_opponents_to",
                "bypassed_opponents_receiving_to", "bypassed_opponents_receiving_from",
                "bypassed_defenders_from", "bypassed_defenders_to",
                "bypassed_defenders_receiving_to", "bypassed_defenders_receiving_from",
                "ball_wins"]

AVAILABILITY: dict[str, tuple[str, str]] = {
    "BTL": ("BYPASSED_OPPONENTS_RECEIVING_NUMBER_BY_ACTION_AVAILABILITY_BTL",
            "Receptions between the lines"),
    "OUT_WIDE": ("BYPASSED_OPPONENTS_RECEIVING_NUMBER_BY_ACTION_AVAILABILITY_OUT_WIDE",
                 "Receptions out wide"),
    "IN_THE_BOX": ("BYPASSED_OPPONENTS_RECEIVING_NUMBER_BY_ACTION_AVAILABILITY_IN_THE_BOX",
                   "Receptions in the box"),
    # Impect: "Availability From Deep Runs" -- receiving behind the defensive chain.
    "FDR": ("BYPASSED_OPPONENTS_RECEIVING_NUMBER_BY_ACTION_AVAILABILITY_FDR",
            "Receptions from deep runs (in behind)"),
    "HOLD_UP_PLAY": ("BYPASSED_OPPONENTS_RECEIVING_NUMBER_BY_ACTION_HOLD_UP_PLAY",
                     "Hold-up play receptions"),
}

# our key -> (Impect score column, label). Impect's own ratings, from getPlayerIterationScores.
SCORES: dict[str, tuple[str, str]] = {
    "impect": ("IMPECT_SCORE_PACKING", "IMPECT"),
    "offensive": ("OFFENSIVE_IMPECT_SCORE_PACKING", "Offensive IMPECT"),
    "defensive": ("DEFENSIVE_IMPECT_SCORE_PACKING", "Defensive IMPECT"),
    "progression": ("PROGRESSION_SCORE_PACKING", "Progression"),
    "receiving": ("RECEIVING_SCORE_PACKING", "Receiving"),
    "interventions": ("INTERVENTIONS_SCORE_PACKING", "Interventions"),
    "defensive_positioning": ("DEFENSIVE_POSITIONAL_PLAY_SCORE_PACKING", "Defensive positioning"),
    "scorer": ("SCORER_SCORE", "Scorer"),
    "availability_btl": ("AVAILABILITY_BTL_SCORE", "Available between the lines"),
    "availability_wide": ("AVAILABILITY_OUT_WIDE_SCORE", "Available out wide"),
    "availability_box": ("AVAILABILITY_IN_THE_BOX_SCORE", "Available in the box"),
    "hold_up": ("HOLD_UP_PLAY_SCORE", "Hold-up play"),
    "dribble": ("DRIBBLE_SCORE", "Dribbling"),
}


@dataclass(frozen=True)
class DetailMetric:
    name: str      # e.g. zone.touches.IB, lane.receptions.LEFT_WING, avail.receptions.BTL
    source: str    # the Impect column
    label: str


def _build() -> list[DetailMetric]:
    out: list[DetailMetric] = []
    for family, (ztpl, ltpl, label) in ZONE_FAMILIES.items():
        out += [DetailMetric(f"zone.{family}.{z}", ztpl.format(z), label) for z in ZONES]
        if ltpl:
            out += [DetailMetric(f"lane.{family}.{l}", ltpl.format(l), label) for l in LANES]
    out += [DetailMetric(f"avail.receptions.{k}", col, label)
            for k, (col, label) in AVAILABILITY.items()]
    out += [DetailMetric(f"score.{k}", col, label) for k, (col, label) in SCORES.items()]
    return out


DETAIL_METRICS: list[DetailMetric] = _build()
LABELS: dict[str, str] = {m.name: m.label for m in DETAIL_METRICS}
FAMILY_LABELS: dict[str, str] = {f: v[2] for f, v in ZONE_FAMILIES.items()} | {
    "total_touches": TOTAL_TOUCHES_LABEL}

COLUMNS = ["playerId", "metric", "value_p90", "total"]


def translate_detail(frame: pd.DataFrame) -> pd.DataFrame:
    """Long frame (playerId, metric, value_p90, total) from a landed averages file.
    A column absent from the file yields no rows -- never zeros."""
    counts = [m for m in DETAIL_METRICS if not m.name.startswith("score.")
              and m.source in frame.columns]
    if not counts:
        return pd.DataFrame(columns=COLUMNS)
    work = pd.concat(
        [frame[["playerId"]], (frame["playDuration"] / 60.0).rename("_minutes")]
        + [(frame[m.source] * frame["matchShare"]).rename(m.name) for m in counts], axis=1)
    # Total touches per zone = offensive + defensive (see TOTAL_TOUCHES_LABEL).
    extra = {}
    for z in ZONES:
        o, dcol = f"zone.touches.{z}", f"zone.defensive_touches.{z}"
        if o in work.columns and dcol in work.columns:
            extra[f"zone.total_touches.{z}"] = work[o] + work[dcol]
    # Matches, Impect's unit: its "Absolute" figures are season total / sum(matchShare).
    extra["meta.matches"] = frame["matchShare"]
    work = pd.concat([work, pd.DataFrame(extra)], axis=1)
    season = work.groupby("playerId", as_index=False).sum()
    minutes = season["_minutes"].where(season["_minutes"] > 0)
    long = season.melt(id_vars=["playerId", "_minutes"], var_name="metric", value_name="total")
    long["value_p90"] = long["total"] / long["playerId"].map(
        dict(zip(season["playerId"], minutes))) * 90.0
    return long.dropna(subset=["value_p90"])[COLUMNS]


def translate_scores(scores: pd.DataFrame) -> pd.DataFrame:
    """Long frame of Impect's scores: the minutes-weighted mean across a player's position
    rows. `total` is empty -- a rating has no season total."""
    present = [(f"score.{k}", col) for k, (col, _) in SCORES.items() if col in scores.columns]
    work = scores[scores["playDuration"] > 0]
    if work.empty or not present:
        return pd.DataFrame(columns=COLUMNS)
    rows = []
    weights = work.groupby("playerId")["playDuration"].sum()
    for name, col in present:
        weighted = (work[col] * work["playDuration"]).groupby(work["playerId"]).sum() / weights
        rows.append(pd.DataFrame({"playerId": weighted.index, "metric": name,
                                  "value_p90": weighted.to_numpy(), "total": float("nan")}))
    # Per-position rows for the two scores the card shows, plus minutes, so the card can list
    # Impect's own per-position figures under the combined tile. One row per player per
    # position: a mid-season mover's two clubs are combined by minutes. Not used by any
    # percentile.
    if "position" in work.columns:
        g = work.assign(_w=work["playDuration"]).groupby(["playerId", "position"])
        minutes = g["_w"].sum()
        for key in ("offensive", "defensive"):
            col = SCORES[key][0]
            if col in work.columns:
                val = (work[col] * work["playDuration"]).groupby(
                    [work["playerId"], work["position"]]).sum() / minutes
                rows.append(pd.DataFrame({
                    "playerId": val.index.get_level_values(0),
                    "metric": "score_pos." + key + "." + val.index.get_level_values(1).astype(str),
                    "value_p90": val.to_numpy(), "total": float("nan")}))
        rows.append(pd.DataFrame({
            "playerId": minutes.index.get_level_values(0),
            "metric": "score_pos.minutes." + minutes.index.get_level_values(1).astype(str),
            "value_p90": (minutes / 60.0).to_numpy(), "total": float("nan")}))
    return pd.concat(rows, ignore_index=True)[COLUMNS]
