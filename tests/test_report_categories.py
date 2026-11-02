"""Report categories: grouping the club's own per-position metrics into the five or six
bands a reader can hold in their head. Pure — no database, no Streamlit."""

import pytest

from lofc.model import report_categories as rc
from lofc.model.scorecard import _resolved_performance


def test_every_position_has_categories():
    from lofc.model import club_framework as cf
    for pos in cf.PERFORMANCE_METRICS:
        assert pos in rc.CATEGORIES, f"{pos} has no categories"
        assert rc.CATEGORIES[pos], f"{pos} has empty categories"


def test_category_metrics_are_all_real_resolved_metrics():
    """No invented metrics. Every member must be a metric the scoring layer actually
    resolves for that position — otherwise the category is measuring something the club
    never asked for."""
    for pos, cats in rc.CATEGORIES.items():
        resolved = set(_resolved_performance(pos, "All Metrics"))
        for cat, metrics in cats.items():
            for m in metrics:
                assert m in resolved, f"{pos}/{cat}: {m} is not a resolved metric"


def test_no_metric_appears_in_two_categories_for_one_position():
    """Double-counting a metric would weight it twice in the same reader's mental model."""
    for pos, cats in rc.CATEGORIES.items():
        seen = [m for metrics in cats.values() for m in metrics]
        assert len(seen) == len(set(seen)), f"{pos} double-counts a metric"


def test_category_score_is_the_mean_of_member_percentiles_when_weights_are_equal():
    pcts = {"pass_value_p90": 80.0, "deep_progressions_p90": 60.0,
            "packing_bypassed_opponents_p90": 70.0, "dribble_carry_value_p90": 50.0}
    eq = {m: 1.0 for m in rc.CATEGORIES["Central Mid"]["Progression"]}
    assert rc.category_score(pcts, "Central Mid", "Progression", eq) == 65.0


def test_category_score_is_the_weighted_mean_using_the_rating_weights():
    """Croasdale-style: Ground-duel win % weighs 7% and is at p1; Aerial 4% at p2.
    Plain mean would be (p1+p2)/2; the strip must follow the rating's weights."""
    from lofc.model.performance_weights import weights_for
    w = weights_for("Central Mid", "All Metrics")
    pcts = {"ground_duel_win_pct": 30.0, "aerial_win_pct": 80.0}
    expect = round((30.0 * w["ground_duel_win_pct"] + 80.0 * w["aerial_win_pct"])
                   / (w["ground_duel_win_pct"] + w["aerial_win_pct"]), 1)
    assert rc.category_score(pcts, "Central Mid", "Duels") == expect
    assert expect < 55.0   # pulled toward the heavier ground-duel metric


def test_explicit_weights_override_the_default():
    pcts = {"ground_duel_win_pct": 30.0, "aerial_win_pct": 80.0}
    got = rc.category_score(pcts, "Central Mid", "Duels",
                            {"ground_duel_win_pct": 3.0, "aerial_win_pct": 1.0})
    assert got == 42.5


def test_weighted_missing_member_renormalises_over_present_weights():
    from lofc.model.performance_weights import weights_for
    # only Aerial present -> its own percentile, whatever its weight
    assert rc.category_score({"aerial_win_pct": 80.0}, "Central Mid", "Duels") == 80.0


def test_weighted_turnovers_are_still_inverted():
    from lofc.model.performance_weights import weights_for
    w = weights_for("Central Mid", "All Metrics")
    pcts = {"pass_completion_pct": 80.0, "turnovers_p90": 90.0}
    a, b = w["pass_completion_pct"], w["turnovers_p90"]
    assert rc.category_score(pcts, "Central Mid", "Retention") == round(
        (80.0 * a + 10.0 * b) / (a + b), 1)


def test_central_mid_has_a_scoring_category_and_the_rated_metrics_in_it():
    cm = rc.CATEGORIES["Central Mid"]
    assert cm["Scoring"] == ["goals_p90", "shots_p90", "touches_in_box_p90"]
    assert "dribble_count_p90" in cm["Progression"]
    assert "cross_bypassed_opponents_p90" in cm["Creation"]


def test_every_rated_metric_is_in_a_category_or_listed_as_also_in_the_rating():
    """Nothing in the Performance rating may be silently invisible on the report."""
    from lofc.model import club_framework as cf
    for pos in cf.PERFORMANCE_METRICS:
        shown = {m for ms in rc.CATEGORIES[pos].values() for m in ms}
        for m in _resolved_performance(pos, "All Metrics"):
            assert m in shown or m in rc.unlisted_metrics(pos), f"{pos}: {m} invisible"


def test_unlisted_metrics_known_cases():
    assert rc.unlisted_metrics("Defensive Mid") == ["goals_p90"]
    assert rc.unlisted_metrics("Centre Back") == ["touches_in_box_p90"]
    assert rc.unlisted_metrics("Central Mid") == []


def test_every_category_member_has_a_rating_weight():
    from lofc.model.performance_weights import weights_for
    for pos, cats in rc.CATEGORIES.items():
        w = weights_for(pos, "All Metrics")
        assert w, f"{pos} has no weights"
        for ms in cats.values():
            for m in ms:
                assert m in w, f"{pos}: {m} has no weight"


def test_a_metric_where_lower_is_better_is_inverted():
    """Turnovers: a player in the 90th percentile for turnovers is BAD at retention.
    Without inversion the category would reward giving the ball away."""
    assert "turnovers_p90" in rc.INVERTED
    pcts = {"pass_completion_pct": 80.0, "turnovers_p90": 90.0}
    # equal weights: retention = mean(80, 100-90) = 45.0
    assert rc.category_score(pcts, "Central Mid", "Retention",
                             {"pass_completion_pct": 1, "turnovers_p90": 1}) == 45.0


def test_a_missing_metric_drops_out_and_the_rest_renormalise():
    """Same rule the composite already uses: absent dimensions drop out, they do not
    count as zero."""
    pcts = {"pass_value_p90": 80.0, "deep_progressions_p90": 60.0}
    eq = {m: 1.0 for m in rc.CATEGORIES["Central Mid"]["Progression"]}
    assert rc.category_score(pcts, "Central Mid", "Progression", eq) == 70.0


def test_a_category_with_no_populated_metrics_returns_none():
    """None, never 0.0 — a category we cannot measure is not a category the player scored
    zero in."""
    assert rc.category_score({}, "Central Mid", "Progression") is None


def test_category_scores_omits_unmeasurable_categories():
    scores = rc.category_scores({"pass_completion_pct": 50.0}, "Central Mid")
    assert "Retention" in scores
    assert "Progression" not in scores


def test_scatter_axes_exist_for_every_position_and_name_real_categories():
    for pos, (x, y) in rc.SCATTER_AXES.items():
        assert x in rc.CATEGORIES[pos], f"{pos} x-axis {x} is not a category"
        assert y in rc.CATEGORIES[pos], f"{pos} y-axis {y} is not a category"
        assert x != y


def test_unknown_position_raises():
    """Never score a player against categories that do not exist for his position."""
    with pytest.raises(KeyError):
        rc.category_score({}, "Sweeper Keeper", "Progression")
