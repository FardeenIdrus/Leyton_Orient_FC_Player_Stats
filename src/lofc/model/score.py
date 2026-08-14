"""Two scores per player, both 0-100, both ranked within position and league.

  performance_score - how GOOD the player is. The average of their percentiles across a
      broad set of stats relevant to their role, equally weighted. Data only, no club
      opinion. This is the objective "is he any good" number.

  fit_score - how well the player matches Leyton Orient's identity. The identity-weighted
      sum of their percentiles on the profile metrics. This reflects our constructed
      identity (a stand-in for the club's real one), so it is configurable, not objective.

A player can be high on one and low on the other: a lethal finisher who never presses
scores high performance but lower fit for a pressing team.
"""

from __future__ import annotations

import pandas as pd

from lofc.config import settings

# Phase C: StatsBomb-only metric -> its validated Impect successor (correlations and
# rationale in impect_map's "none" tier). Applied to BOTH the quality role sets and the
# fit identity profiles when settings.impect_only is on, so scoring needs no StatsBomb.
# interceptions and ball recoveries both map to ball wins (Impect does not separate them),
# so a role carrying both collapses to one ball-wins term after de-duplication.
IMPECT_SUCCESSOR = {
    "tackles_p90": "ground_duels_won_p90",
    "interceptions_p90": "ball_wins_p90",
    "ball_recoveries_p90": "ball_wins_p90",
    "progressive_passes_p90": "packing_bypassed_opponents_p90",
    "passes_into_final_third_p90": "deep_progressions_p90",
    "progressive_carries_p90": "dribble_carry_value_p90",
    "dribbles_completed_p90": "dribble_carry_value_p90",
    "gk_saves_p90": "gk_gsaa_p90",
    "save_pct": "gk_shot_stopping_pct",
}


def _successor_metrics(metrics: list[str]) -> list[str]:
    """Map StatsBomb-only metrics to Impect successors, de-duplicated, order preserved."""
    seen, out = set(), []
    for m in metrics:
        s = IMPECT_SUCCESSOR.get(m, m)
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _successor_profile(profile: pd.DataFrame) -> pd.DataFrame:
    """Map a fit identity profile onto Impect successors, summing weights that collapse
    onto the same successor (e.g. interceptions + ball recoveries -> one ball-wins term)."""
    p = profile.copy()
    p["metric"] = p["metric"].map(lambda m: IMPECT_SUCCESSOR.get(m, m))
    agg = {"weight": "sum"}
    if "min_percentile" in p.columns:
        agg["min_percentile"] = "max"   # keep the strictest floor if two collapse
    return p.groupby("metric", as_index=False).agg(agg)


# Coarse role per position group, used only for the broad performance score.
POSITION_ROLE = {
    "Goalkeeper": "goalkeeper",
    "Centre Back": "defender",
    "Full Back": "defender",
    "Defensive Mid": "midfielder",
    "Central Mid": "midfielder",
    "Winger": "attacker",
    "Attacking Mid": "attacker",
    "Centre Forward": "attacker",
}

# Broad, relevance-based stat sets for the performance score (equal weight within a role).
# "Relevance" (which stats judge quality at this role), not "priority" (what LOFC wants).
ROLE_METRICS = {
    "goalkeeper": [
        "save_pct", "gk_saves_p90", "pass_completion_pct", "passes_p90",
    ],
    "defender": [
        "tackles_p90", "interceptions_p90", "blocks_p90", "clearances_p90",
        "ball_recoveries_p90", "pressures_p90", "pass_completion_pct",
        "progressive_passes_p90", "passes_into_final_third_p90", "progressive_carries_p90",
    ],
    "midfielder": [
        "tackles_p90", "interceptions_p90", "ball_recoveries_p90", "pressures_p90",
        "pass_completion_pct", "progressive_passes_p90", "passes_into_final_third_p90",
        "key_passes_p90", "xa_p90", "progressive_carries_p90",
    ],
    "attacker": [
        "np_xg_p90", "np_goals_p90", "shots_p90", "xa_p90", "key_passes_p90",
        "passes_into_box_p90", "dribbles_completed_p90", "progressive_carries_p90",
        "pressures_p90",
    ],
}

KEY_COLUMNS = ["player_id", "competition_id", "season_id", "position_group"]


def compute_scores(wide: pd.DataFrame, identity: pd.DataFrame) -> pd.DataFrame:
    """Performance and fit scores per player, with ranks within position + league.

    wide: percentile-per-metric frame from normalise.compute_percentiles_wide.
    identity: rows of (position_group, metric, weight) from the identity_profiles table.
    """

    # Phase C: in Impect-only mode, swap StatsBomb-only metrics for Impect successors in
    # BOTH the quality role sets and the fit identity profiles, once up front.
    role_sets = ROLE_METRICS
    if settings.impect_only:
        role_sets = {role: _successor_metrics(ms) for role, ms in ROLE_METRICS.items()}
        identity = pd.concat([_successor_profile(g).assign(position_group=pos)
                              for pos, g in identity.groupby("position_group")], ignore_index=True)

    identity_by_pos = {pos: g for pos, g in identity.groupby("position_group")}

    records = []
    for (player_id, competition_id, season_id, position_group), row in wide.iterrows():
        role_metrics = [m for m in role_sets.get(POSITION_ROLE[position_group], []) if m in wide.columns]
        performance = row[role_metrics].mean(skipna=True)  # equal-weight broad quality

        profile = identity_by_pos.get(position_group)
        fit = 0.0
        if profile is not None:
            weighted, present_w, total_w = 0.0, 0.0, 0.0
            for _, p in profile.iterrows():
                total_w += p["weight"]
                value = row.get(p["metric"])
                if pd.notna(value):
                    weighted += p["weight"] * value
                    present_w += p["weight"]
            # Renormalise by the weight of the metrics actually present, so a player
            # missing some identity metrics is not deflated (an Impect-spined league has
            # no StatsBomb-sourced metric; a rare EFL player misses one). The present
            # metrics are scaled up to the full profile weight -- a no-op when every
            # metric is present (present_w == total_w), so EFL fit scores are unchanged.
            fit = weighted * total_w / present_w if present_w > 0 else 0.0

        records.append({
            "player_id": player_id,
            "competition_id": competition_id,
            "season_id": season_id,
            "position_group": position_group,
            "performance_score": round(float(performance), 1) if pd.notna(performance) else None,
            "fit_score": round(float(fit), 1),
        })

    scores = pd.DataFrame(records)

    # Rank best-to-worst within each competition + position group.
    by_group = scores.groupby(["competition_id", "position_group"])
    scores["performance_rank"] = by_group["performance_score"].rank(ascending=False, method="min").astype("Int64")
    scores["fit_rank"] = by_group["fit_score"].rank(ascending=False, method="min").astype("Int64")
    return scores
