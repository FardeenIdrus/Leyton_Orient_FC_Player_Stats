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

    identity_by_pos = {pos: g for pos, g in identity.groupby("position_group")}

    records = []
    for (player_id, competition_id, season_id, position_group), row in wide.iterrows():
        role_metrics = [m for m in ROLE_METRICS.get(POSITION_ROLE[position_group], []) if m in wide.columns]
        performance = row[role_metrics].mean(skipna=True)  # equal-weight broad quality

        profile = identity_by_pos.get(position_group)
        fit = 0.0
        if profile is not None:
            for _, p in profile.iterrows():
                value = row.get(p["metric"])
                if pd.notna(value):
                    fit += p["weight"] * value

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
