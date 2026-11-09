"""A season total is shown only where adding up makes sense (owner, 2026-10-12).

Found on Dan Happe's card: top speed "season total" 995, metres per minute 3,459 -- you cannot
total a speed or a rate. Physical totals were also overstated: they used Impect's minutes,
and SkillCorner tracks fewer. Value metrics (xG, xA, PxT) were rounded to whole numbers, so a
real 0.69 read "1" or "0".

Rules:
  * counts (ball wins, passes, pressures...) -> whole-number total;
  * value metrics (xG, xA, PxT) -> total to 2 decimals;
  * percentages, ratios, speeds, rates, timings -> no total ("—");
  * every physical metric -> no total (its minutes basis is SkillCorner's, not Impect's).
"""

import pytest

from lofc.dashboard.units import season_total

MINUTES = 3126.0   # Dan Happe 25/26


@pytest.mark.parametrize("metric", [
    "psv99_kmh", "top5_psv99_kmh", "meters_per_minute", "time_to_sprint", "agility_505_90",
    "distance_p90", "hsr_distance_p90", "sprint_count_p90",
    "aerial_win_pct", "pass_completion_pct", "goal_conversion_pct", "xg_per_shot"])
def test_no_total_where_adding_up_makes_no_sense(metric):
    assert season_total(metric, 12.3, MINUTES) == "—"


def test_counts_are_whole_numbers():
    assert season_total("ball_wins_p90", 22.946, MINUTES) == "797"


@pytest.mark.parametrize("metric", ["pass_value_p90", "xg_p90", "np_xg_p90", "xa_p90",
                                    "defensive_value_p90", "np_xg_xa_p90", "shot_threat_p90"])
def test_value_metrics_keep_two_decimals(metric):
    assert season_total(metric, 0.02, MINUTES) == "0.69"


def test_no_minutes_no_total():
    assert season_total("ball_wins_p90", 22.9, 0) == "—"


def test_season_total_counts_round_half_up():
    # owner 2026-11-09: half-up everywhere; 0.25 per 90 over 900 minutes = 2.5 -> "3"
    assert season_total("ball_wins_p90", 0.25, 900) == "3"
    assert season_total("ball_wins_p90", 0.45, 900) == "5"
