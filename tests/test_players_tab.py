"""Tests for the Players tab's profile-page pure helpers (dashboard/tabs/players.py).

No Streamlit runtime and no database: these exercise plain pandas logic directly, per the
project's convention of keeping data-decision functions testable in isolation from the UI
layer that renders them.
"""

import pandas as pd

from lofc.dashboard.tabs.players import (
    _current_form_summary, _full_stats_table, _metrics_held_by_anyone, _output_tile_plan,
    _veto_reasons)


def test_metrics_held_by_anyone_drops_globally_null_columns():
    """A metric that is NULL for every row in the population (a retired StatsBomb column
    with no Impect successor, once StatsBomb is out of scoring) is not 'held'."""
    values = pd.DataFrame({
        "player_id": [1, 2, 3],
        "competition_id": [5, 5, 5],
        "ground_duels_won_p90": [1.2, None, 3.4],   # at least one real value: held
        "tackles_p90": [None, None, None],          # nobody has it: not held
    })
    held = _metrics_held_by_anyone(values, ["ground_duels_won_p90", "tackles_p90"])
    assert held == {"ground_duels_won_p90"}


def test_metrics_held_by_anyone_ignores_columns_not_present():
    """A metric name with no matching column at all (not just null) is silently excluded --
    the same 'no data, no row' outcome as an all-null column, just cheaper to check."""
    values = pd.DataFrame({"player_id": [1], "competition_id": [5], "goals_p90": [0.4]})
    held = _metrics_held_by_anyone(values, ["goals_p90", "not_a_real_column"])
    assert held == {"goals_p90"}


def test_metrics_held_by_anyone_is_pure_data_driven_not_a_hard_coded_list():
    """The decision comes purely from what's in the frame -- flip which column is empty and
    the answer flips with it, with no metric-name special-casing anywhere in the function."""
    values = pd.DataFrame({
        "player_id": [1], "competition_id": [5],
        "metric_a": [None], "metric_b": [7.0],
    })
    assert _metrics_held_by_anyone(values, ["metric_a", "metric_b"]) == {"metric_b"}


def _percentiles(rows):
    return pd.DataFrame(rows, columns=["player_id", "competition_id", "metric", "percentile"])


def test_full_stats_table_drops_metric_null_for_every_player():
    """The end-to-end table for one player omits a metric nobody in the season holds a
    value for -- no placeholder row, no '6 of 8' commentary, just absent."""
    row = pd.Series({"player_id": 1, "competition_id": 5, "minutes": 900.0})
    metric_values = pd.DataFrame({
        "player_id": [1, 2],
        "competition_id": [5, 5],
        "goals_p90": [0.30, 0.10],
        "tackles_p90": [None, None],   # retired StatsBomb column: nobody has it
    })
    percentiles = _percentiles([
        (1, 5, "goals_p90", 80.0),
        (1, 5, "tackles_p90", 50.0),   # even if a stray percentile row exists, no value backs it
        (2, 5, "goals_p90", 20.0),
    ])
    table = _full_stats_table(row, percentiles, metric_values)
    assert table is not None
    assert "tackles_p90" not in set(table["Metric"])
    assert list(table["Metric"]) == [labels_for("goals_p90")]


def test_full_stats_table_keeps_metric_held_by_someone_but_null_for_this_player():
    """A metric genuinely absent for THIS player (e.g. save % for an outfielder) but held by
    someone else in the population (a goalkeeper) is still correctly skipped for him -- the
    population-level filter only decides table MEMBERSHIP, not per-player presence."""
    row = pd.Series({"player_id": 1, "competition_id": 5, "minutes": 900.0})
    metric_values = pd.DataFrame({
        "player_id": [1, 2],
        "competition_id": [5, 5],
        "goals_p90": [0.30, None],
        "save_pct": [None, 0.71],   # only player 2 (a goalkeeper) has this
    })
    percentiles = _percentiles([
        (1, 5, "goals_p90", 80.0),
        (2, 5, "save_pct", 60.0),
    ])
    table = _full_stats_table(row, percentiles, metric_values)
    assert table is not None
    assert set(table["Metric"]) == {labels_for("goals_p90")}


def labels_for(metric: str) -> str:
    from lofc.dashboard.labels import LABELS
    return LABELS[metric]


# --- _current_form_summary (2026/27 current-season plain facts, never a rating) --------
#
# `player_metrics_neutral` (the only table carrying season_id 319, the Impect-sourced
# combined table) has minutes and per-90 rates, but no raw season totals and no match-played
# count -- goals/assists are derived from the rate, exactly as `_full_stats_table` above
# already derives a season total for a non-EFL league with no raw total column.


def _current_form_rows(rows):
    return pd.DataFrame(rows, columns=["player_id", "competition_id", "season_id",
                                       "minutes", "goals_p90", "assists_p90"])


def test_current_form_summary_none_when_player_has_no_row_this_season():
    """A player who has not appeared, or whose league has not started, has no row in the
    live-season frame at all -- the caller must say so plainly, not show zeros."""
    rows = _current_form_rows([(2, 4, 319, 180, 0.50, 0.00)])
    assert _current_form_summary(rows, player_id=1) is None


def test_current_form_summary_derives_totals_from_the_per90_rate():
    # 0.50 goals/90 over 180 minutes -> 1.0 goals; 1.00 assists/90 over 180 -> 2.0 assists.
    rows = _current_form_rows([(1, 4, 319, 180, 0.50, 1.00)])
    assert _current_form_summary(rows, player_id=1) == {
        "minutes": 180, "goals": 1, "assists": 2}


def test_current_form_summary_sums_across_a_mid_season_move():
    """A player who has already changed clubs (and so leagues) mid-season has one row per
    competition -- the summary is his combined season, not just the latest club's, and each
    row's total is computed from that row's OWN minutes, not an average rate."""
    rows = _current_form_rows([(1, 4, 319, 120, 0.75, 0.00), (1, 5, 319, 60, 0.00, 1.50)])
    # Row 1: 0.75/90 * 120 = 1.0 goal. Row 2: 1.50/90 * 60 = 1.0 assist.
    assert _current_form_summary(rows, player_id=1) == {
        "minutes": 180, "goals": 1, "assists": 1}


def test_current_form_summary_treats_missing_rate_as_zero_not_none():
    rows = _current_form_rows([(1, 4, 319, 45, None, None)])
    assert _current_form_summary(rows, player_id=1) == {
        "minutes": 45, "goals": 0, "assists": 0}


# --- _veto_reasons (advisory: which dimension tripped the flag, and by how much) --------


def _scorecard_row(**bands):
    """A minimal row carrying only the band columns `_veto_reasons` reads."""
    return pd.Series(bands)


def test_veto_reasons_names_the_single_tripped_dimension():
    """The reported defect: a player flagged only by Resale (money display off, so nothing
    else on the profile explains it) must get a message that names Resale and its value --
    not a generic 'a dimension'."""
    row = _scorecard_row(performance_band=3.2, physical_band=4.1,
                         financial_band=3.4, resale_band=1.58)
    assert _veto_reasons(row) == ["Resale Potential 1.58 is below the club minimum of 2.00"]


def test_veto_reasons_lists_every_tripped_dimension_in_framework_order():
    row = _scorecard_row(performance_band=1.9, physical_band=4.1,
                         financial_band=1.0, resale_band=3.0)
    assert _veto_reasons(row) == [
        "Performance 1.90 is below the club minimum of 2.00",
        "Financial Fit 1.00 is below the club minimum of 2.00",
    ]


def test_veto_reasons_boundary_is_exclusive():
    """Exactly the club minimum (2.00) does not trip it -- matches
    `club_framework.VETO_BAND` (`< 2.0`, never `<=`)."""
    row = _scorecard_row(performance_band=2.0, physical_band=5.0)
    assert _veto_reasons(row) == []


def test_veto_reasons_skips_a_dimension_absent_from_this_row():
    """A dimension whose band column never reached this row (e.g. financial_band/resale_band
    missing from an older view) is silently skipped, never guessed at -- absent data must
    never render as a value."""
    row = _scorecard_row(performance_band=1.5)   # no physical/financial/resale/... at all
    assert _veto_reasons(row) == ["Performance 1.50 is below the club minimum of 2.00"]


# --- _output_tile_plan (retired-metric season-output tiles must never render empty) -----


def _metric_values(**cols):
    n = len(next(iter(cols.values()))) if cols else 0
    return pd.DataFrame({"player_id": list(range(n)), "competition_id": [5] * n, **cols})


def test_output_tile_plan_hides_goalkeeper_tiles_nobody_holds():
    values = _metric_values(save_pct=[None, None], gk_saves_p90=[None, None])
    assert _output_tile_plan("goalkeeper", values) == {"save_pct": False, "gk_saves_p90": False}


def test_output_tile_plan_shows_a_goalkeeper_tile_once_someone_holds_it():
    values = _metric_values(save_pct=[0.71, None], gk_saves_p90=[None, None])
    assert _output_tile_plan("goalkeeper", values) == {"save_pct": True, "gk_saves_p90": False}


def test_output_tile_plan_hides_defender_tiles_nobody_holds():
    values = _metric_values(tackles_p90=[None], interceptions_p90=[None])
    assert _output_tile_plan("defender", values) == {"tackles_p90": False, "interceptions_p90": False}


def test_output_tile_plan_empty_for_a_role_with_no_known_dead_tiles():
    """Midfielder/attacker tiles (Goals/Assists) are live data -- this plan only ever governs
    the two roles with a known-retired pair, so it returns no opinion for any other role."""
    values = _metric_values(goals_p90=[0.3])
    assert _output_tile_plan("midfielder", values) == {}
    assert _output_tile_plan("attacker", values) == {}


# --- LABELS: the dashboard's display vocabulary must never name a metric with no data ---


def test_labels_excludes_every_metric_empty_for_every_player():
    """Every one of these was confirmed NULL for every row of `player_metrics_neutral` (all
    leagues, all seasons) once StatsBomb left scoring -- see labels.py's LABELS docstring.
    A name earns a place in LABELS only once real data backs it, so a profile card built
    from `LABELS.items()` can never be empty by construction."""
    from lofc.dashboard.labels import LABELS
    retired = {
        "progressive_passes_p90", "passes_into_final_third_p90", "dribbles_p90",
        "dribbles_completed_p90", "carries_p90", "progressive_carries_p90",
        "tackles_p90", "interceptions_p90", "ball_recoveries_p90", "gk_saves_p90",
        "dribble_success_pct", "save_pct",
    }
    assert not (retired & LABELS.keys())
