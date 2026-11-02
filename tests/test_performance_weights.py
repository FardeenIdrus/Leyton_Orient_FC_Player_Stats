"""Per-metric Performance weights (formula meeting; workbook "Weightings to be assigned 5",
owner 2026-11-02).

Before: every Performance metric weighed the same. Now each carries the club's High / Mid /
Low weight, per position and per archetype. Physical stays equal-weighted (no weights yet)
and the 57/43 split is unchanged.

The workbook's tiers were not applied exactly everywhere (a High at 0.07 beside 0.075s, a Low
at 0.02 beside 0.015s, a +0.003 added to every weight when an archetype dropped a metric).
Owner: make it accurate. Each such table keeps its tier RATIO and is scaled to sum to exactly
1; the Winger "Crossing & Creative Threat" table is the All Metrics table without the dropped
metric, rescaled in proportion. Weights are exact fractions, so the sums are exactly 1.
"""

from fractions import Fraction

import pandas as pd
import pytest

from lofc.model import club_framework as cf
from lofc.model import performance_weights as pw
from lofc.model import scorecard as sc

TABLES = [(p, a) for p in cf.PERFORMANCE_METRICS for a in cf.archetypes_for(p)]


@pytest.mark.parametrize("position,archetype", TABLES)
def test_every_scored_metric_has_a_weight_and_nothing_else_does(position, archetype):
    assert set(pw.WEIGHTS[(position, archetype)]) == \
        set(sc._resolved_performance(position, archetype))


@pytest.mark.parametrize("position,archetype", TABLES)
def test_every_table_sums_to_exactly_one(position, archetype):
    assert sum(w for _, w in pw.WEIGHTS[(position, archetype)].values()) == Fraction(1)


@pytest.mark.parametrize("position,archetype", TABLES)
def test_one_tier_one_weight_within_a_table(position, archetype):
    by_tier = {}
    for tier, w in pw.WEIGHTS[(position, archetype)].values():
        by_tier.setdefault(tier, set()).add(w)
    assert all(len(ws) == 1 for ws in by_tier.values()), by_tier


def test_the_corrected_tables_keep_their_tier_ratios():
    fb_att = pw.WEIGHTS[("Full Back", "Attacking")]
    assert fb_att["pressures_p90"] == ("High", Fraction(5, 67))
    assert fb_att["assists_p90"] == ("Mid", Fraction(3, 67))
    fb_pbr = pw.WEIGHTS[("Full Back", "Progressive Build & Recovery")]
    assert fb_pbr["ball_wins_p90"] == ("Mid", Fraction(1, 22))
    assert fb_pbr["pressures_p90"] == ("High", Fraction(1, 11))
    gk = pw.WEIGHTS[("Goalkeeper", "All Metrics")]
    assert gk["gk_catches_p90"] == ("High", Fraction(9, 41))
    cf_ = pw.WEIGHTS[("Centre Forward", "All Metrics")]
    assert cf_["ball_wins_p90"] == ("Low", Fraction(3, 199))


def test_crossing_and_creative_is_all_metrics_without_carrying_rescaled():
    full = pw.WEIGHTS[("Winger", "All Metrics")]
    cct = pw.WEIGHTS[("Winger", "Crossing & Creative Threat")]
    assert "dribble_carry_value_p90" not in cct
    kept = sum(w for m, (_, w) in full.items() if m in cct)
    assert all(cct[m][1] == full[m][1] / kept for m in cct)


def test_tables_the_workbook_got_right_are_taken_as_written():
    assert pw.WEIGHTS[("Centre Back", "All Metrics")]["ball_wins_p90"] == ("High", Fraction(1, 10))
    assert pw.WEIGHTS[("Winger", "All Metrics")]["ball_wins_p90"] == ("Low", Fraction(7, 400))


# --- the score --------------------------------------------------------------------------

def test_the_performance_band_is_the_weighted_average_of_the_metric_bands():
    row = pd.Series({"a": 90.0, "b": 50.0})                       # bands 5.0 and 3.0
    band, n, total = sc._dimension_band(row, ["a", "b"], {"a": 0.75, "b": 0.25})
    assert band == 4.5 and (n, total) == (2, 2)


def test_a_missing_metric_drops_out_and_the_other_weights_are_rescaled():
    row = pd.Series({"a": 90.0, "b": 50.0, "c": float("nan")})
    band, n, total = sc._dimension_band(row, ["a", "b", "c"], {"a": 0.3, "b": 0.1, "c": 0.6})
    assert band == 4.5 and (n, total) == (2, 3)


def test_without_weights_the_average_stays_equal():
    """Physical: no weights yet (formula meeting, 2026-11-02)."""
    row = pd.Series({"a": 90.0, "b": 50.0})
    assert sc._dimension_band(row, ["a", "b"])[0] == 4.0


def test_the_scorecard_uses_the_weights_of_the_position_and_archetype(monkeypatch):
    seen = []
    real = sc._dimension_band

    def spy(row, metrics, weights=None):
        seen.append(weights)
        return real(row, metrics, weights)
    monkeypatch.setattr(sc, "_dimension_band", spy)
    metrics = sc._resolved_performance("Centre Back")
    neutral = pd.DataFrame([{"player_id": i, "competition_id": 4, "season_id": 318,
                             "position_group": "Centre Back", "rankable": True,
                             **{m: float(i) for m in metrics}} for i in range(12)])
    sc.build_scorecards(neutral)
    assert seen[0] == pw.weights_for("Centre Back", "All Metrics")
    assert seen[1] is None                                       # physical: equal weights
