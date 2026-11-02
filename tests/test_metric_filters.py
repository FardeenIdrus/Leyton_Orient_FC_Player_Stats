"""Metric sliders on the Players page (Head of Recruitment, 2026-10-02).

Performance: one MINIMUM-PERCENTILE slider per metric the position is scored on -- the same
percentiles the composite uses, within league + season + position.
Physical: a few RAW per-90 sliders per position. Raw, because km/h and metres mean the same
in every league; a percentile would not.

A player with no value for an ACTIVE filter cannot be judged, so he is excluded -- and
counted, never dropped silently (Scottish Championship has no physical data at all).
"""

import pandas as pd
import pytest

from lofc.dashboard.metric_filters import (LOWER_IS_BETTER_PHYSICAL, PHYSICAL_GROUPS, PHYSICAL_SLIDERS,
                                           PHYSICAL_LABELS, apply_metric_filters,
                                           performance_slider_metrics)
from lofc.model import club_framework as cf
from lofc.model.scorecard import _resolved_performance

KEY = ["player_id", "competition_id", "season_id", "position_group"]


def test_every_position_has_a_physical_list_and_goalkeepers_have_none():
    assert set(PHYSICAL_SLIDERS) == set(cf.PERFORMANCE_METRICS)
    assert PHYSICAL_SLIDERS["Goalkeeper"] == []


def test_every_physical_slider_is_a_physical_metric_with_a_label():
    from lofc.ingest.skillcorner_map import SKILLCORNER_MAP
    physical = {m.name for m in SKILLCORNER_MAP}
    for metrics in PHYSICAL_SLIDERS.values():
        for m in metrics:
            assert m in physical
            assert m in PHYSICAL_LABELS


def test_every_outfield_position_gets_every_physical_metric():
    """Recruiters asked for every physical metric as a filter (2026-11-02). Distance and
    metres per minute are one measurement per 90, but the owner chose to offer both."""
    every = [m for ms in PHYSICAL_GROUPS.values() for m in ms]
    assert len(every) == len(set(every)) == 23
    for position, metrics in PHYSICAL_SLIDERS.items():
        assert metrics == ([] if position == "Goalkeeper" else every)


def test_groups_are_in_the_agreed_order():
    assert list(PHYSICAL_GROUPS) == ["Distance", "Speed", "Intensity", "Acceleration",
                                     "Time to speed", "Agility"]


def test_every_grouped_metric_has_a_glossary_entry_and_a_label():
    from lofc.dashboard.glossary_data import PHYSICAL
    from lofc.dashboard.labels import SC_METRIC_LABELS  # noqa: F401 (labels module imports)
    for ms in PHYSICAL_GROUPS.values():
        for m in ms:
            assert m in PHYSICAL and m in PHYSICAL_LABELS


def test_lower_is_better_is_exactly_the_time_and_agility_metrics():
    assert set(LOWER_IS_BETTER_PHYSICAL) == {
        "time_to_hsr", "time_to_hsr_post_cod", "time_to_sprint", "time_to_sprint_post_cod",
        "agility_505_90", "agility_505_180"}
    assert set(LOWER_IS_BETTER_PHYSICAL) == set(PHYSICAL_GROUPS["Time to speed"]) | \
        set(PHYSICAL_GROUPS["Agility"])


def test_seconds_are_shown_to_two_decimals():
    for m in LOWER_IS_BETTER_PHYSICAL:
        assert PHYSICAL_LABELS[m][1] == "%.2f" and PHYSICAL_LABELS[m][0].endswith("(s)")


def _timed():
    pool = pd.DataFrame({"player_id": [1, 2, 3, 4], "competition_id": [4] * 4,
                         "season_id": [318] * 4, "position_group": ["Winger"] * 4})
    raw = pool[["player_id", "competition_id"]].assign(
        time_to_sprint=[3.9, 4.4, None, 4.1], distance_p90=[9000.0, 11000.0, 10000.0, 10500.0])
    return pool, pool[KEY], raw


def test_a_raw_maximum_keeps_lower_values_and_drops_higher():
    pool, pcts, raw = _timed()
    out, unknown = apply_metric_filters(pool, pcts, raw, {}, {}, raw_maxs={"time_to_sprint": 4.2})
    assert out["player_id"].tolist() == [1, 4]
    assert unknown == 1                      # player 3 has no value: excluded and counted


def test_a_maximum_is_inclusive():
    pool, pcts, raw = _timed()
    out, _ = apply_metric_filters(pool, pcts, raw, {}, {}, raw_maxs={"time_to_sprint": 4.1})
    assert out["player_id"].tolist() == [1, 4]


def test_minimum_and_maximum_combine():
    pool, pcts, raw = _timed()
    out, unknown = apply_metric_filters(pool, pcts, raw, {}, {"distance_p90": 10200.0},
                                        raw_maxs={"time_to_sprint": 4.2})
    assert out["player_id"].tolist() == [4] and unknown == 1


def test_old_call_without_raw_maxs_still_works():
    pool, pcts, raw = _timed()
    out, unknown = apply_metric_filters(pool, pcts, raw, {}, {"distance_p90": 10200.0})
    assert out["player_id"].tolist() == [2, 4] and unknown == 0
    out, unknown = apply_metric_filters(pool, pcts, raw, {}, {}, None)
    assert len(out) == 4 and unknown == 0


def test_a_max_filter_on_a_column_the_pool_already_carries_does_not_crash():
    key = {"competition_id": 4, "season_id": 318, "position_group": "Winger"}
    pool = pd.DataFrame([{**key, "player_id": i, "time_to_sprint": 0.0} for i in range(3)])
    raw = pd.DataFrame([{"player_id": i, "competition_id": 4,
                         "time_to_sprint": [3.8, 4.2, 4.6][i]} for i in range(3)])
    out, _ = apply_metric_filters(pool, pool.iloc[0:0], raw, {}, {}, raw_maxs={"time_to_sprint": 4.3})
    assert out["player_id"].tolist() == [0, 1]
    assert list(out.columns) == list(pool.columns)


def test_hi_metrics_are_defined_in_the_glossary():
    from lofc.dashboard.glossary_data import PHYSICAL
    for m in ("hi_distance_p90", "hi_count_p90"):
        assert m in PHYSICAL and "high-speed" in PHYSICAL[m][1] and "sprint" in PHYSICAL[m][1].lower()


@pytest.mark.parametrize("position", list(cf.PERFORMANCE_METRICS))
def test_performance_sliders_are_exactly_the_scored_metrics(position):
    assert performance_slider_metrics(position, cf.DEFAULT_ARCHETYPE) == \
        _resolved_performance(position, cf.DEFAULT_ARCHETYPE)


def test_an_archetype_lens_follows_its_own_metric_list():
    assert performance_slider_metrics("Winger", "Crossing & Creative Threat") == \
        _resolved_performance("Winger", "Crossing & Creative Threat")


def _frames():
    pool = pd.DataFrame({"player_id": [1, 2, 3], "competition_id": [4, 4, 4],
                         "season_id": [318] * 3, "position_group": ["Winger"] * 3})
    pcts = pool[KEY].assign(shots_p90=[90.0, 40.0, None])
    raw = pool[["player_id", "competition_id"]].assign(psv99_kmh=[33.0, 30.0, None])
    return pool, pcts, raw


def test_no_active_filter_returns_everyone():
    pool, pcts, raw = _frames()
    out, unknown = apply_metric_filters(pool, pcts, raw, {"shots_p90": 0}, {})
    assert out["player_id"].tolist() == [1, 2, 3] and unknown == 0


def test_a_percentile_minimum_filters_and_counts_the_unjudgeable():
    pool, pcts, raw = _frames()
    out, unknown = apply_metric_filters(pool, pcts, raw, {"shots_p90": 50}, {})
    assert out["player_id"].tolist() == [1]
    assert unknown == 1


def test_a_raw_minimum_filters_and_counts_the_unjudgeable():
    pool, pcts, raw = _frames()
    out, unknown = apply_metric_filters(pool, pcts, raw, {}, {"psv99_kmh": 31.0})
    assert out["player_id"].tolist() == [1]
    assert unknown == 1


def test_filters_combine_with_and():
    pool, pcts, raw = _frames()
    out, _ = apply_metric_filters(pool, pcts, raw, {"shots_p90": 30}, {"psv99_kmh": 31.0})
    assert out["player_id"].tolist() == [1]


def test_pool_columns_and_order_are_preserved():
    pool, pcts, raw = _frames()
    pool = pool.assign(objective_composite=[3.1, 4.2, 2.0])
    out, _ = apply_metric_filters(pool, pcts, raw, {"shots_p90": 30}, {})
    assert list(out.columns) == list(pool.columns)
    assert out["objective_composite"].tolist() == [3.1, 4.2]


def test_slider_labels_use_the_glossary_names():
    """One metric, one name; and no unpublished threshold ('15–20 km/h') stated as fact."""
    from lofc.dashboard.glossary_data import PHYSICAL
    for metric, (label, _) in PHYSICAL_LABELS.items():
        assert label.startswith(PHYSICAL[metric][0].rstrip(")")), (metric, label)
        assert "15–20" not in label


def test_a_filter_on_a_metric_the_pool_already_carries_does_not_crash():
    """Found live 2026-11-02 (in a presentation): the Players pool already holds raw
    assists_p90 / xa_p90 / np_xg_p90 (for the goals-and-assists totals). Filtering on one of
    them merged a second column of the same name, pandas renamed both, and the page died
    with KeyError 'xa_p90'. The filter must use the PERCENTILE, not the raw column."""
    import pandas as pd
    from lofc.dashboard import metric_filters as mf
    key = {"competition_id": 4, "season_id": 318, "position_group": "Winger"}
    pool = pd.DataFrame([{**key, "player_id": i, "xa_p90": 0.30 - i * 0.1} for i in range(3)])
    pcts = pd.DataFrame([{**key, "player_id": i, "xa_p90": [20.0, 60.0, 90.0][i]} for i in range(3)])
    raw = pd.DataFrame([{"player_id": i, "competition_id": 4, "xa_p90": 0.3} for i in range(3)])
    out, unknown = mf.apply_metric_filters(pool, pcts, raw, {"xa_p90": 50}, {})
    assert out["player_id"].tolist() == [1, 2] and unknown == 0      # by percentile, not raw
    assert list(out.columns) == list(pool.columns)                    # pool untouched


def test_a_raw_filter_on_a_column_the_pool_already_carries_does_not_crash():
    import pandas as pd
    from lofc.dashboard import metric_filters as mf
    key = {"competition_id": 4, "season_id": 318, "position_group": "Winger"}
    pool = pd.DataFrame([{**key, "player_id": i, "distance_p90": 1.0} for i in range(3)])
    raw = pd.DataFrame([{"player_id": i, "competition_id": 4,
                         "distance_p90": [9000.0, 10000.0, 11000.0][i]} for i in range(3)])
    out, _ = mf.apply_metric_filters(pool, pool.iloc[0:0], raw, {}, {"distance_p90": 9500.0})
    assert out["player_id"].tolist() == [1, 2]


def test_slider_bounds_round_out_to_the_display_precision():
    from lofc.dashboard.metric_filters import slider_bounds
    assert slider_bounds(pd.Series([4.371, 5.019]), "%.2f") == (4.37, 5.02, 0.01)
    assert slider_bounds(pd.Series([30.04, 35.51]), "%.1f") == (30.0, 35.6, 0.1)
    assert slider_bounds(pd.Series([8123.4, 11890.2]), "%.0f") == (8123.0, 11891.0, 1.0)
