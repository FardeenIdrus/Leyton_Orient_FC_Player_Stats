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

from lofc.dashboard.metric_filters import (PHYSICAL_SLIDERS, PHYSICAL_LABELS, apply_metric_filters,
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


def test_no_position_gets_distance_and_metres_per_minute_together():
    """Per 90 they are one measurement (r = 1.00): two sliders would be one filter twice."""
    for metrics in PHYSICAL_SLIDERS.values():
        assert not {"distance_p90", "meters_per_minute"} <= set(metrics)


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
