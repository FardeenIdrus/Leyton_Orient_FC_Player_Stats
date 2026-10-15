"""One percentile per metric on the player card, and season totals only where they make sense.

Found 2026-10-12 on Dan Happe's card: "All tracked metrics" and the Strengths/Watch-outs line
read the LEGACY player_percentiles table (rank/n, before the 2026-09-30 centring), while the
Scorecard table reads the composite's own percentiles -- so one card showed Pressures 20 AND
22, Bypassed opponents 25 AND 26, Blocks 1 AND 2. All three now read the scorecard
percentiles. Physical rows leave the Scorecard table for the single Physical section.
"""

import pandas as pd

from lofc.dashboard.tabs import players

KEY = {"player_id": 1, "competition_id": 4, "season_id": 318, "position_group": "Centre Back"}


def _row():
    return pd.Series({**KEY, "minutes": 3126.0})


def _sc():
    return pd.DataFrame([{**KEY, "ball_wins_p90": 80.0, "pressures_p90": 20.0,
                          "pass_value_p90": 23.0, "aerial_win_pct": 69.0,
                          "distance_p90": 13.0, "psv99_kmh": 69.0}])


def _values():
    return pd.DataFrame([{"player_id": 1, "competition_id": 4, "ball_wins_p90": 22.946,
                          "pressures_p90": 9.44, "pass_value_p90": 0.02,
                          "aerial_win_pct": 0.71, "distance_p90": 8961.0,
                          "psv99_kmh": 28.64}])


def test_scorecard_table_holds_performance_rows_only():
    g = players._grand_table(_row(), "Centre Back", "All Metrics", _sc(), _values())
    assert set(g["Dimension"]) == {"Performance"}


def test_scorecard_totals_follow_the_unit_rules():
    g = players._grand_table(_row(), "Centre Back", "All Metrics", _sc(), _values()).set_index("Metric")
    assert g.loc["Ball wins", "Season total"] == "797"
    assert g.loc["Pass value (PxT)", "Season total"] == "0.69"
    assert g.loc["Aerial win %", "Season total"] == "—"


def test_all_tracked_metrics_use_the_scorecard_percentiles():
    t = players._full_stats_table(_row(), _sc(), _values()).set_index("Metric")
    assert t.loc["Pressures", "Percentile"] == 20
    assert t.loc["Ball wins", "Percentile"] == 80
    assert t.loc["Pass value (PxT)", "Season total"] == "0.69"


def test_strengths_read_the_scorecard_percentiles():
    s = pd.Series({"ball_wins_p90": 80.0, "pressures_p90": 20.0, "pass_value_p90": 23.0})
    line = players._strengths_weaknesses(s, ["ball_wins_p90", "pressures_p90", "pass_value_p90"])
    assert "Ball wins (80)" in line and "Pressures (20)" in line
