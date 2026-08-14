"""Tests for the club-framework composite scorecard: the band mapping anchored on the
club's own thresholds, the framework's structural invariants, and the scoring engine's
dimension aggregation / present-weight renormalisation / veto logic. Small fixtures, no DB."""

import pandas as pd
import pytest

from lofc.model import club_framework as cf
from lofc.model import scorecard


# --- the framework itself -------------------------------------------------------------

def test_band_is_anchored_on_the_clubs_own_thresholds():
    assert cf.band(50) == 3.0    # league median = "minimum standard" = 3.0
    assert cf.band(70) == 4.0    # 70th percentile = "elite" = 4.0
    assert cf.band(90) == 5.0
    assert cf.band(30) == 2.0    # bottom-third = the veto line
    assert cf.band(10) == 1.0


def test_band_clamps_to_one_and_five():
    assert cf.band(0) == 1.0
    assert cf.band(100) == 5.0


def test_every_weighted_position_has_a_performance_list():
    """Guards the class of bug where a position has weights but no metric list (which
    silently zeroes its Performance score)."""
    for position in cf.DIMENSION_WEIGHTS:
        assert position in cf.PERFORMANCE_METRICS, position
        assert cf.PERFORMANCE_METRICS[position], position


def test_dimension_weights_sum_to_one_per_position():
    for position, weights in cf.DIMENSION_WEIGHTS.items():
        assert round(sum(weights.values()), 6) == 1.0, position


def test_goalkeeper_has_no_physical_dimension():
    assert cf.PHYSICAL_METRICS["Goalkeeper"] == []
    assert cf.PHYSICAL not in cf.DIMENSION_WEIGHTS["Goalkeeper"]
    assert cf.PHYSICAL in cf.DIMENSION_WEIGHTS["Centre Back"]


def test_metric_with_no_impect_equivalent_drops_out():
    """long_ball_pct has no stored successor, so it is excluded from the live list."""
    live = dict(cf.performance_metrics_live("Goalkeeper"))
    assert "long_ball_pct" not in [club for club in live]
    # save_pct resolves to its successor
    assert cf.resolve_metric("save_pct") == "gk_shot_stopping_pct"


# --- the scoring engine ---------------------------------------------------------------

def _neutral(rows):
    return pd.DataFrame(rows)


def test_resolved_performance_deduplicates_collapsed_successors():
    """Several club metrics can collapse onto one stored metric (e.g. counterpressures +
    pressures-in-opposing-half); the resolved list must not double-count it."""
    resolved = scorecard._resolved_performance("Centre Forward")
    assert len(resolved) == len(set(resolved))
    # Centre Forward lists both counterpressures and pressures-opp-half (-> counterpressures)
    # and both pass_value and xg_buildup (-> pass_value): each appears once.
    assert resolved.count("counterpressures_p90") == 1
    assert resolved.count("pass_value_p90") == 1


def test_archetypes_only_for_full_back_and_winger():
    assert cf.archetypes_for("Full Back") == ["All Metrics", "Attacking", "Progressive Build & Recovery"]
    assert cf.archetypes_for("Winger")[0] == "All Metrics" and len(cf.archetypes_for("Winger")) == 3
    # positions with a single profile expose only the default
    assert cf.archetypes_for("Centre Forward") == ["All Metrics"]
    assert cf.archetypes_for("Goalkeeper") == ["All Metrics"]


def test_archetype_is_a_strict_subset_of_all_metrics():
    base = cf.performance_metrics_for_archetype("Full Back", "All Metrics")
    atk = cf.performance_metrics_for_archetype("Full Back", "Attacking")
    prog = cf.performance_metrics_for_archetype("Full Back", "Progressive Build & Recovery")
    assert set(atk) < set(base) and set(prog) < set(base)      # strict subsets
    # Attacking drops the deep-defending metrics; Progressive keeps them
    assert "padj_tackles_interceptions_p90" not in atk
    assert "padj_tackles_interceptions_p90" in prog
    # Progressive drops the attacking/carrying metrics; Attacking keeps them
    assert "dribble_carry_value_p90" not in prog
    assert "dribble_carry_value_p90" in atk
    # 'All Metrics' (or an unknown archetype) returns the full list
    assert cf.performance_metrics_for_archetype("Full Back", "unknown") == base


def test_archetype_changes_only_the_selected_position(monkeypatch):
    """An archetype override re-scores Performance for that position only; others are unchanged."""
    # aerial_win_pct is dropped by the Attacking archetype and is a directly-stored metric.
    rows = ([{"player_id": i, "competition_id": 1, "season_id": 1, "position_group": "Full Back",
              "rankable": True, "aerial_win_pct": float(i), "pass_completion_pct": float(9 - i)}
             for i in range(5)]
            + [{"player_id": 100 + i, "competition_id": 1, "season_id": 1, "position_group": "Centre Forward",
                "rankable": True, "np_xg_p90": float(i)} for i in range(5)])
    neutral = pd.DataFrame(rows)
    base = scorecard.build_scorecards(neutral).set_index("player_id")["performance_band"]
    atk = scorecard.build_scorecards(
        neutral, archetype_by_position={"Full Back": "Attacking"}).set_index("player_id")["performance_band"]
    # Full Back Performance changes (Attacking drops padj_tackles_interceptions)
    assert not base.loc[:4].equals(atk.loc[:4])
    # Centre Forward Performance is identical
    assert base.loc[100:].equals(atk.loc[100:])


def test_lower_is_better_metric_is_inverted():
    """turnovers: the player with the FEWEST should get the highest percentile."""
    rows = [{"player_id": i, "competition_id": 1, "season_id": 1, "position_group": "Centre Back",
             "rankable": True, "turnovers_p90": float(i)} for i in range(5)]
    pcts = scorecard.metric_percentiles(_neutral(rows))
    # player 0 (fewest turnovers) -> highest percentile; player 4 -> lowest.
    p0 = pcts.xs(0, level="player_id")["turnovers_p90"].iloc[0]
    p4 = pcts.xs(4, level="player_id")["turnovers_p90"].iloc[0]
    assert p0 > p4


def test_composite_renormalises_when_physical_absent():
    """A player with only Performance data still gets a composite equal to his Performance
    band (present-weight renormalisation), not a deflated one."""
    # 3 centre-backs, one performance metric, no physical columns at all.
    rows = [{"player_id": i, "competition_id": 1, "season_id": 1, "position_group": "Centre Back",
             "rankable": True, "pass_completion_pct": float(i)} for i in range(3)]
    sc = scorecard.build_scorecards(_neutral(rows))
    top = sc[sc.player_id == 2].iloc[0]
    assert pd.isna(top["physical_band"])
    assert top["objective_composite"] == top["performance_band"]   # renormalised to Performance alone
    assert top["objective_weight_covered"] == pytest.approx(
        cf.DIMENSION_WEIGHTS["Centre Back"][cf.PERFORMANCE], abs=0.01)


def test_missing_value_player_is_still_scored():
    """No financial_resale row for a player -> he keeps a composite (never excluded)."""
    rows = [{"player_id": i, "competition_id": 901, "season_id": 1, "position_group": "Winger",
             "rankable": True, "np_xg_p90": float(i)} for i in range(3)]
    sc = scorecard.build_scorecards(_neutral(rows), financial_resale=None)
    assert sc["objective_composite"].notna().all()


def test_objective_ignores_financial_resale_but_full_includes_them():
    """The objective composite is Performance+Physical only; the full composite folds in the
    modelled Financial/Resale, so the two differ when those bands are present and extreme."""
    rows = [{"player_id": i, "competition_id": 1, "season_id": 1, "position_group": "Centre Back",
             "rankable": True, "pass_completion_pct": float(i)} for i in range(3)]
    fr = pd.DataFrame([{"player_id": 2, "competition_id": 1, "season_id": 1,
                        "financial_band": 1.0, "resale_band": 1.0}])
    sc = scorecard.build_scorecards(_neutral(rows), financial_resale=fr)
    top = sc[sc.player_id == 2].iloc[0]
    # objective unaffected by the (poor) financial/resale bands; full is dragged down by them.
    assert top["objective_composite"] == top["performance_band"]
    assert top["full_composite"] < top["objective_composite"]
    assert top["full_weight_covered"] > top["objective_weight_covered"]


def test_veto_flag_when_a_dimension_is_below_two():
    """The bottom player in a one-metric dimension bands to 1.0 (<2.0) -> veto."""
    rows = [{"player_id": i, "competition_id": 1, "season_id": 1, "position_group": "Centre Back",
             "rankable": True, "pass_completion_pct": float(i)} for i in range(10)]
    sc = scorecard.build_scorecards(_neutral(rows))
    bottom = sc.sort_values("performance_band").iloc[0]
    assert bottom["performance_band"] < cf.VETO_BAND
    assert bool(bottom["veto"]) is True


def test_composite_renormalises_so_the_both_or_neither_guard_must_live_in_the_caller():
    """_composite happily renormalises over whatever is present -- give it Psychological
    without Medical and it returns a number. That is why Decision 9's both-or-neither rule
    is enforced in build_scorecards before calling it, not inside it. This test exists so
    nobody "simplifies" the guard away believing _composite already handles it."""
    from lofc.model.scorecard import _composite
    from lofc.model import club_framework as cf

    weights = cf.DIMENSION_WEIGHTS["Winger"]
    partial = {cf.PERFORMANCE: 4.0, cf.PHYSICAL: 3.5, cf.PSYCHOLOGICAL: 3.8}
    value, covered = _composite(partial, weights, cf.DATA_DIMENSIONS + cf.SCOUT_DIMENSIONS)
    assert value is not None and covered < 1.0


def test_assessed_composite_excludes_financial_and_resale():
    """Decision 15: assessed_composite = Performance + Physical + Psychological + Medical --
    never the modelled Financial and Resale dimensions. Financial and Resale are present in
    `bands` here, exactly as they would be for a real player with a market value, precisely to
    prove they are NOT picked up: ASSESSED_DIMENSIONS never names them, so `covered` stops at
    0.86, not 1.0, and the two modelled bands cannot move `value`."""
    from lofc.model.scorecard import ASSESSED_DIMENSIONS, _composite
    from lofc.model import club_framework as cf

    weights = cf.DIMENSION_WEIGHTS["Winger"]
    bands = {cf.PERFORMANCE: 4.0, cf.PHYSICAL: 3.5, cf.FINANCIAL: 3.0,
             cf.RESALE: 4.0, cf.PSYCHOLOGICAL: 3.8, cf.MEDICAL: 3.0}
    value, covered = _composite(bands, weights, ASSESSED_DIMENSIONS)
    assert covered == pytest.approx(0.86, abs=0.01)
    assert value == pytest.approx(3.66, abs=0.01)


def test_assessed_composite_does_not_move_when_the_money_bands_change():
    """The regression Decision 15 exists to catch: if changing Financial or Resale ever moved
    assessed_composite, modelled money would have leaked back into the assessed tier."""
    from lofc.model.scorecard import ASSESSED_DIMENSIONS, _composite
    from lofc.model import club_framework as cf

    weights = cf.DIMENSION_WEIGHTS["Winger"]
    base = {cf.PERFORMANCE: 4.0, cf.PHYSICAL: 3.5, cf.PSYCHOLOGICAL: 3.8, cf.MEDICAL: 3.0}
    cheap = dict(base, **{cf.FINANCIAL: 1.0, cf.RESALE: 1.0})
    expensive = dict(base, **{cf.FINANCIAL: 5.0, cf.RESALE: 5.0})
    no_market_value = dict(base)  # Scottish/PL2 player: Financial and Resale absent entirely

    assert (_composite(base, weights, ASSESSED_DIMENSIONS)
            == _composite(cheap, weights, ASSESSED_DIMENSIONS)
            == _composite(expensive, weights, ASSESSED_DIMENSIONS)
            == _composite(no_market_value, weights, ASSESSED_DIMENSIONS))


def test_objective_and_full_composites_are_unchanged_by_scout_bands():
    """The default ranking must not move when an assessment lands."""
    from lofc.model.scorecard import _composite
    from lofc.model import club_framework as cf

    weights = cf.DIMENSION_WEIGHTS["Winger"]
    without = {cf.PERFORMANCE: 4.0, cf.PHYSICAL: 3.5, cf.FINANCIAL: 3.0, cf.RESALE: 4.0}
    with_scout = dict(without, **{cf.PSYCHOLOGICAL: 3.8, cf.MEDICAL: 3.0})

    assert (_composite(without, weights, [cf.PERFORMANCE, cf.PHYSICAL])
            == _composite(with_scout, weights, [cf.PERFORMANCE, cf.PHYSICAL]))
    assert (_composite(without, weights, cf.DATA_DIMENSIONS)
            == _composite(with_scout, weights, cf.DATA_DIMENSIONS))
