"""Midfield fallback pool (owner-approved 2026-11-16).

A Defensive / Central / Attacking Mid whose own league-season pool holds fewer than
MIN_PEERS_FOR_RANKING rankable players is rated against ALL the league-season's rankable
midfielders combined -- percentiles from the combined pool, metrics and weights still his own
position's. A combined pool below the floor is still not rated. Every pool already at the
floor, and every non-midfield pool, is untouched. Small fixtures, no DB."""

import numpy as np
import pandas as pd
import pytest

from lofc.model import performance_weights as pw
from lofc.model import scorecard

METRICS = ["ball_wins_p90", "pressures_p90", "xa_p90", "ground_duel_win_pct",
           "distance_p90", "hsr_count_p90"]


def _players(position, n, start, comp=1, season=1, rankable=True, seed=0):
    rng = np.random.default_rng(seed + start)
    return [{"player_id": start + i, "competition_id": comp, "season_id": season,
             "position_group": position, "rankable": rankable,
             **{m: float(v) for m, v in zip(METRICS, rng.random(len(METRICS)) * 10)}}
            for i in range(n)]


def _frame(*groups):
    return pd.DataFrame([r for g in groups for r in g])


@pytest.fixture
def league():
    """12 DMs (a full pool), 4 CMs and 3 AMs (both thin; 19 midfielders combined), 4 Wingers
    (thin, not midfield) and 2 unrankable CMs who must count nowhere."""
    return _frame(_players("Defensive Mid", 12, 100), _players("Central Mid", 4, 200),
                  _players("Attacking Mid", 3, 300), _players("Winger", 4, 400),
                  _players("Central Mid", 2, 500, rankable=False))


def _plain(frame):
    """Mid-rank percentiles inside the frame as ONE pool -- the definition, written out."""
    frame = frame.set_index("player_id")
    return pd.DataFrame({m: (frame[m].rank() - 0.5) / frame[m].count() * 100.0
                         for m in METRICS})


def test_a_thin_central_mid_is_ranked_against_every_rankable_midfielder(league):
    pcts = scorecard.metric_percentiles(league).reset_index().set_index("player_id")
    mids = league[league["position_group"].isin(scorecard.MIDFIELD_POSITIONS)
                  & league["rankable"]]
    expected = _plain(mids)
    for pid in range(200, 204):
        for m in METRICS:
            assert pcts.loc[pid, m] == pytest.approx(expected.loc[pid, m]), (pid, m)


def test_a_full_pool_is_unchanged_byte_for_byte(league):
    """The Defensive Mids (12) keep exactly the percentiles they get with no midfield
    fallback anywhere in the league: the combined pool is used only for the thin groups."""
    full = scorecard.metric_percentiles(league)
    alone = scorecard.metric_percentiles(league[league["position_group"] == "Defensive Mid"])
    pd.testing.assert_frame_equal(full.loc[alone.index], alone)


def test_a_thin_winger_is_never_pooled_with_anyone(league):
    full = scorecard.metric_percentiles(league)
    alone = scorecard.metric_percentiles(league[league["position_group"] == "Winger"])
    pd.testing.assert_frame_equal(full.loc[alone.index], alone)


def test_a_combined_pool_below_the_floor_changes_nothing():
    small = _frame(_players("Defensive Mid", 3, 100), _players("Central Mid", 2, 200),
                   _players("Attacking Mid", 2, 300))
    full = scorecard.metric_percentiles(small)
    for pos in scorecard.MIDFIELD_POSITIONS:
        alone = scorecard.metric_percentiles(small[small["position_group"] == pos])
        pd.testing.assert_frame_equal(full.loc[alone.index], alone)


def test_pools_never_mix_leagues_or_seasons():
    """Nine CMs in league 1 and nine DMs in league 2: no league has ten midfielders."""
    frame = _frame(_players("Central Mid", 9, 100, comp=1), _players("Defensive Mid", 9, 200, comp=2),
                   _players("Attacking Mid", 9, 300, comp=1, season=2))
    full = scorecard.metric_percentiles(frame)
    for pos in scorecard.MIDFIELD_POSITIONS:
        alone = scorecard.metric_percentiles(frame[frame["position_group"] == pos])
        pd.testing.assert_frame_equal(full.loc[alone.index], alone)


def test_the_thin_central_mid_keeps_central_mid_metrics_and_weights(league):
    sc = scorecard.build_scorecards(league).set_index("player_id")
    pcts = scorecard.metric_percentiles(league).reset_index().set_index("player_id")
    row = pcts.loc[201]
    cm, _, _ = scorecard._dimension_band(row, scorecard._resolved_performance("Central Mid"),
                                         pw.weights_for("Central Mid", "All Metrics"))
    dm, _, _ = scorecard._dimension_band(row, scorecard._resolved_performance("Defensive Mid"),
                                         pw.weights_for("Defensive Mid", "All Metrics"))
    assert cm != dm                         # the fixture can tell the two weightings apart
    assert sc.loc[201, "performance_band"] == cm


def test_each_scorecard_records_the_pool_it_was_rated_in(league):
    sc = scorecard.build_scorecards(league).set_index("player_id")
    assert sc.loc[200, "peer_pool"] == scorecard.POOL_MIDFIELD
    assert sc.loc[200, "peer_pool_size"] == 19
    assert sc.loc[300, "peer_pool"] == scorecard.POOL_MIDFIELD
    assert sc.loc[100, "peer_pool"] == scorecard.POOL_POSITION
    assert sc.loc[100, "peer_pool_size"] == 12
    assert sc.loc[400, "peer_pool"] == scorecard.POOL_POSITION
    assert sc.loc[400, "peer_pool_size"] == 4
    assert 500 not in sc.index              # unrankable: no scorecard, counted nowhere


def test_combined_below_the_floor_is_recorded_as_his_own_thin_pool():
    small = _frame(_players("Defensive Mid", 3, 100), _players("Central Mid", 2, 200))
    sc = scorecard.build_scorecards(small).set_index("player_id")
    assert sc.loc[200, "peer_pool"] == scorecard.POOL_POSITION
    assert sc.loc[200, "peer_pool_size"] == 2
    assert scorecard.pool_is_thin(sc.loc[200, "peer_pool_size"])


def test_peer_pool_sizes_are_the_pool_actually_used(league):
    """Every consumer (Players page, card, squads, watchlist) reads pool sizes from here, so a
    thin Central Mid rated against 19 midfielders must read 19, not 4."""
    sc = scorecard.build_scorecards(league)
    sizes = scorecard.peer_pool_sizes(sc)
    assert sizes[(1, 1, "Central Mid")] == 19
    assert sizes[(1, 1, "Defensive Mid")] == 12
    assert sizes[(1, 1, "Winger")] == 4
    # one position's rows only (the card reads just his position): the stored size still wins
    only_cm = sc[sc["position_group"] == "Central Mid"]
    assert scorecard.peer_pool_sizes(only_cm)[(1, 1, "Central Mid")] == 19
    assert scorecard.peer_pool_scopes(only_cm)[(1, 1, "Central Mid")] == scorecard.POOL_MIDFIELD


def test_peer_pool_sizes_without_the_stored_columns_apply_the_same_rule(league):
    """Rows scored before the migration have no peer_pool_size: counted, with the same rule."""
    sc = scorecard.build_scorecards(league).drop(columns=["peer_pool", "peer_pool_size"])
    sizes = scorecard.peer_pool_sizes(sc)
    assert sizes[(1, 1, "Central Mid")] == 19 and sizes[(1, 1, "Defensive Mid")] == 12
    assert scorecard.peer_pool_scopes(sc)[(1, 1, "Attacking Mid")] == scorecard.POOL_MIDFIELD


def test_the_rank_of_a_fallback_player_is_not_quoted(league):
    """His composite is from the combined pool but his own position holds only 4: a rank
    among 4 would be a ranking from a pool below the floor, and a rank among all midfielders
    would order players scored on different metrics. Neither is quoted."""
    sc = scorecard.build_scorecards(league)
    assert scorecard.rank_in_pool(sc, 201, 1, 1, "Central Mid")[0] is None
    assert scorecard.rank_in_pool(sc, 101, 1, 1, "Defensive Mid")[0] is not None
