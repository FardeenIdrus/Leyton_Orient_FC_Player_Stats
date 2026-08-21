"""Tests for the Players tab's profile-page pure helpers (dashboard/tabs/players.py).

No Streamlit runtime and no database: these exercise plain pandas logic directly, per the
project's convention of keeping data-decision functions testable in isolation from the UI
layer that renders them.
"""

import pandas as pd

from lofc.dashboard.tabs.players import _full_stats_table, _metrics_held_by_anyone


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
