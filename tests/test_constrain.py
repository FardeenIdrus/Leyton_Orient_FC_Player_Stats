"""Tests for the shortlist gates and ranking. Small fixtures, no database."""

import pandas as pd

from lofc.constrain.filters import age_band, compute_on_profile, rank_position


def test_age_band_boundaries():
    assert age_band(19) == "U21"
    assert age_band(23) == "21-24"
    assert age_band(27) == "25-29"
    assert age_band(31) == "30-32"
    assert age_band(35) == "33+"
    assert age_band(None) is None


def _pct(player_id, percentile, competition_id=4, season_id=318,
         position="Centre Forward", metric="np_xg_p90"):
    return {"player_id": player_id, "competition_id": competition_id, "season_id": season_id,
            "position_group": position, "metric": metric, "percentile": percentile}


def test_on_profile_threshold_and_no_floor_positions():
    percentiles = pd.DataFrame([
        _pct(1, 60),
        _pct(2, 40),
        _pct(3, 10, position="Central Mid", metric="passes_p90"),
    ])
    floors = pd.DataFrame([{"position_group": "Centre Forward", "metric": "np_xg_p90", "min_percentile": 55}])
    on = compute_on_profile(percentiles, floors)

    assert (1, 4, 318) in on          # 60 >= 55 floor
    assert (2, 4, 318) not in on      # 40 < 55 floor
    assert (3, 4, 318) in on          # Central Mid has no floor -> auto pass


def test_on_profile_judges_each_season_row_alone():
    # Regression: a second season that ALSO passes must not flip a player off-profile
    # (the old player-level pass count stopped matching the floor count), and a
    # mid-season mover's rows get independent verdicts.
    percentiles = pd.DataFrame([
        _pct(1, 95, season_id=318),                      # this season: passes
        _pct(1, 63, competition_id=5, season_id=317),    # last season: also passes
        _pct(2, 80, competition_id=4, season_id=318),    # mover: passes in League One...
        _pct(2, 30, competition_id=65, season_id=318),   # ...fails in the National League
    ])
    floors = pd.DataFrame([{"position_group": "Centre Forward", "metric": "np_xg_p90", "min_percentile": 55}])
    on = compute_on_profile(percentiles, floors)

    assert (1, 4, 318) in on and (1, 5, 317) in on
    assert (2, 4, 318) in on
    assert (2, 65, 318) not in on


def _candidate(pid, value, wage, ceiling, on_profile, fit):
    # The gate reads the band around the central wage estimate (0.7x / 1.4x here).
    return {"player_id": pid, "market_value_eur": value, "estimated_weekly_wage_gbp": wage,
            "wage_low_gbp": wage * 0.7, "wage_high_gbp": wage * 1.4,
            "wage_ceiling_gbp": ceiling, "on_profile": on_profile, "fit_score": fit}


def test_qualifying_passes_both_gates_and_profile():
    cand = pd.DataFrame([
        _candidate(1, 1_000_000, 2000, 5000, True, 80),    # cheap, low wage, on profile -> qualifies
        _candidate(2, 50_000_000, 90000, 5000, True, 90),  # too expensive + too high wage
        _candidate(3, 1_000_000, 2000, 5000, False, 95),   # affordable but off profile
    ])
    out = rank_position(cand, transfer_budget_eur=5_000_000)

    assert list(out["player_id"]) == [1]
    assert not out["is_near_miss"].any()
    assert out["rank"].tolist() == [1]


def test_near_miss_fallback_when_nobody_qualifies():
    # Both are on profile but wages blow the ceiling -> nobody qualifies -> near-misses by fit.
    cand = pd.DataFrame([
        _candidate(1, 1_000_000, 90000, 5000, True, 80),
        _candidate(2, 1_000_000, 90000, 5000, True, 90),
    ])
    out = rank_position(cand, transfer_budget_eur=5_000_000)

    assert out["is_near_miss"].all()
    assert list(out["player_id"]) == [2, 1]   # ranked by fit, best first


def test_wage_band_semantics():
    cand = pd.DataFrame([
        _candidate(1, 1_000_000, 3000, 5000, True, 80),   # high band 4200 <= 5000: clean pass
        _candidate(2, 1_000_000, 4500, 5000, True, 85),   # band 3150-6300 straddles: marginal pass
        _candidate(3, 1_000_000, 8000, 5000, True, 90),   # low band 5600 > 5000: fails the gate
    ])
    out = rank_position(cand, transfer_budget_eur=5_000_000)

    assert set(out["player_id"]) == {1, 2}
    marginal = out.set_index("player_id")["wage_marginal"]
    assert not marginal[1]
    assert marginal[2]
