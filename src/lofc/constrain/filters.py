"""Phase 7: filter players to affordable + on-profile, then rank the shortlist.

Two affordability gates run live:
  - fee gate: real market value <= a transfer budget (a parameter the dashboard drives).
  - wage gate: modelled weekly wage <= the wage-framework ceiling for the player's
    position and age. The wage is a modelled estimate (data/reference/wage_estimates),
    never derived from market value, and is replaced by real club wage data when available.

On-profile means the player clears the identity-profile minimum thresholds for the position.
If nothing passes all gates (common at a tight budget on this top-league demo data), we
return the closest on-profile players as near-misses, so the result is never empty.
"""

from __future__ import annotations

import pandas as pd

DEFAULT_TRANSFER_BUDGET_EUR = 5_000_000
NEAR_MISS_COUNT = 5


def age_band(age: float | None) -> str | None:
    """Map an age to the band used by the wage tables."""
    if age is None or pd.isna(age):
        return None
    if age < 21:
        return "U21"
    if age < 25:
        return "21-24"
    if age < 30:
        return "25-29"
    if age < 33:
        return "30-32"
    return "33+"


def _tiers(scores: pd.Series) -> pd.Series:
    """Split a position's performance scores into Top / Mid / Squad terciles."""
    pct = scores.rank(pct=True)
    return pd.cut(pct, bins=[0, 1 / 3, 2 / 3, 1.0],
                  labels=["Squad", "Mid", "Top"], include_lowest=True).astype(str)


def compute_on_profile(percentiles: pd.DataFrame, floors: pd.DataFrame) -> set[int]:
    """Player ids that clear every minimum-threshold metric for their position.

    A position with no floors has no requirement, so all its players are on-profile.
    """
    player_position = percentiles[["player_id", "position_group"]].drop_duplicates()
    if floors.empty:
        return set(player_position["player_id"])

    needed = floors.groupby("position_group").size().to_dict()
    merged = percentiles.merge(floors, on=["position_group", "metric"], how="inner")
    merged["meets"] = merged["percentile"] >= merged["min_percentile"]
    met_count = merged.groupby("player_id")["meets"].sum()

    on_profile = set()
    for row in player_position.itertuples():
        required = needed.get(row.position_group, 0)
        if required == 0 or met_count.get(row.player_id, 0) == required:
            on_profile.add(row.player_id)
    return on_profile


def apply_gates(candidates: pd.DataFrame, transfer_budget_eur: float) -> pd.DataFrame:
    """Add the two affordability gates and an overall pass flag to every candidate."""
    cand = candidates.copy()
    cand["affordable_fee"] = cand["market_value_eur"] <= transfer_budget_eur
    cand["affordable_wage"] = (cand["estimated_weekly_wage_gbp"] <= cand["wage_ceiling_gbp"]).fillna(False)
    cand["qualifies"] = cand["affordable_fee"] & cand["affordable_wage"] & cand["on_profile"]
    return cand


def rank_position(candidates: pd.DataFrame, transfer_budget_eur: float,
                  near_miss_n: int = NEAR_MISS_COUNT) -> pd.DataFrame:
    """Apply both gates to one position and rank by fit, with a near-miss fallback."""
    cand = apply_gates(candidates, transfer_budget_eur)

    if cand["qualifies"].any():
        out = cand[cand["qualifies"]].sort_values("fit_score", ascending=False).copy()
        out["is_near_miss"] = False
    else:
        # Closest alternatives: best on-profile players (or best overall if none on-profile).
        pool = cand[cand["on_profile"]] if cand["on_profile"].any() else cand
        out = pool.sort_values("fit_score", ascending=False).head(near_miss_n).copy()
        out["is_near_miss"] = True

    out["rank"] = range(1, len(out) + 1)
    out["transfer_budget_eur"] = transfer_budget_eur
    return out


def build_candidates(engine, wage_ceiling_multiplier: float = 1.0) -> pd.DataFrame:
    """Assemble every valued player with scores, age band, tier, wage estimate and ceiling."""
    scores = pd.read_sql("SELECT player_id, competition_id, season_id, position_group, "
                         "performance_score, fit_score FROM player_scores", engine)
    vals = pd.read_sql("SELECT player_id, competition_id, season_id, market_value_eur, "
                       "fair_value_eur, undervaluation_pct, age FROM valuations", engine)
    names = pd.read_sql("SELECT player_id, competition_id, season_id, player_name, team_name, minutes "
                        "FROM player_season_metrics", engine)
    wage_est = pd.read_sql("SELECT position_group, age_band, performance_tier, "
                           "estimated_weekly_wage_gbp FROM wage_estimates", engine)
    ceilings = pd.read_sql("SELECT position_group, age_band, weekly_wage_ceiling_gbp "
                           "FROM wage_framework", engine)
    percentiles = pd.read_sql("SELECT player_id, position_group, metric, percentile "
                              "FROM player_percentiles", engine)
    floors = pd.read_sql("SELECT position_group, metric, min_percentile FROM identity_profiles "
                         "WHERE min_percentile IS NOT NULL", engine)

    keys = ["player_id", "competition_id", "season_id"]
    cand = scores.merge(vals, on=keys, how="inner").merge(names, on=keys, how="left")

    cand["age_band"] = cand["age"].map(age_band)
    cand["performance_tier"] = cand.groupby("position_group")["performance_score"].transform(_tiers)

    cand = cand.merge(wage_est, on=["position_group", "age_band", "performance_tier"], how="left")
    cand = cand.merge(ceilings, on=["position_group", "age_band"], how="left")
    cand["wage_ceiling_gbp"] = cand["weekly_wage_ceiling_gbp"] * wage_ceiling_multiplier

    on_profile_ids = compute_on_profile(percentiles, floors)
    cand["on_profile"] = cand["player_id"].isin(on_profile_ids)
    return cand


def generate(engine, transfer_budget_eur: float = DEFAULT_TRANSFER_BUDGET_EUR,
             wage_ceiling_multiplier: float = 1.0) -> pd.DataFrame:
    """Build and rank a shortlist for every position group."""
    candidates = build_candidates(engine, wage_ceiling_multiplier)
    per_position = [rank_position(group, transfer_budget_eur)
                    for _, group in candidates.groupby("position_group")]
    return pd.concat(per_position, ignore_index=True)
