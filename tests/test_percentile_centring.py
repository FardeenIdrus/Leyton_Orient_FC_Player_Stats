"""The percentile scale must be centred on 50, so an average player scores exactly 3.00.

THE DEFECT. `metric_percentiles` used pandas `rank(pct=True)`, which returns rank / n with
ranks running 1..n. In a pool of n players the percentiles therefore run 100/n .. 100, and
their mean is 50 + 50/n -- ABOVE 50, never equal to it.

Fed through the club's band formula (3 + (percentile - 50) / 20) that lifts every rating,
and the lift is larger the smaller the pool:

    pool of   6   mean band 3.333
    pool of  20   mean band 3.100
    pool of 116   mean band 3.017
    pool of 300   mean band 3.007

Measured on the live 2025/26 data before the fix: pools under 30 players averaged 3.14 while
pools of 100+ averaged 3.01, and pool size correlated -0.725 with mean rating. A Scottish
Championship central midfielder (6 in the pool) averaged 3.30 against a League Two centre
back's 3.02 -- a third of a band, for no footballing reason.

That matters because the club's whole framework is anchored on 3.00 meaning "league median,
the Minimum Standard". A pool where the median player scores 3.30 has quietly moved the bar.

THE FIX is the standard mid-rank convention: (rank - 0.5) / n. The scale then runs
50/n .. 100 - 50/n, symmetric about 50, and every pool averages exactly 3.00 whatever its
size. Ordering within a pool is unchanged; a handful of players near the 1 and 5 caps shift
by one or two places because the clamp boundaries move.
"""

import pandas as pd
import pytest

from lofc.model import club_framework as cf
from lofc.model.scorecard import metric_percentiles

KEYS = {"competition_id": 1, "season_id": 1, "position_group": "Centre Back", "rankable": True}


def _pool(values, metric="ball_wins_p90"):
    return pd.DataFrame([{**KEYS, "player_id": i, metric: float(v)}
                         for i, v in enumerate(values)])


def _pcts(values, metric="ball_wins_p90"):
    return metric_percentiles(_pool(values, metric))[metric]


# --- the defect ---------------------------------------------------------------------------

@pytest.mark.parametrize("n", [6, 20, 50, 116, 300])
def test_the_mean_percentile_is_50_whatever_the_pool_size(n):
    """THE DEFECT. rank/n gives 50 + 50/n; a 6-player pool averaged 58.3."""
    assert _pcts(range(n)).mean() == pytest.approx(50.0)


@pytest.mark.parametrize("n", [6, 20, 50, 116, 300])
def test_the_mean_band_is_exactly_3_whatever_the_pool_size(n):
    """3.00 is the club's Minimum Standard -- the league median by definition. A pool whose
    median player scores 3.30 has moved the bar the whole framework is anchored on."""
    assert _pcts(range(n)).map(cf.band).mean() == pytest.approx(3.0)


def test_a_small_pool_is_not_scored_higher_than_a_large_one():
    """Directly: the six-player pool used to average 3.33 against the large pool's 3.01."""
    small = _pcts(range(6)).map(cf.band).mean()
    large = _pcts(range(300)).map(cf.band).mean()
    assert small == pytest.approx(large)


def test_the_scale_is_symmetric_about_50():
    """The best player should sit as far above 50 as the worst sits below it. Under rank/n
    the top player got exactly 100 while the bottom got 100/n, so it never was."""
    p = sorted(_pcts(range(10)))
    assert p[0] == pytest.approx(100 - p[-1])


def test_the_top_player_no_longer_sits_exactly_on_100():
    """100 is the ceiling of the scale, not a rank anyone occupies -- and it is what pushed
    the top of every pool hard against the band cap."""
    assert max(_pcts(range(20))) < 100.0


def test_the_bottom_player_is_above_zero():
    assert min(_pcts(range(20))) > 0.0


# --- what must not change ------------------------------------------------------------------

def test_a_metric_missing_for_some_players_is_ranked_among_those_who_have_it():
    """The divisor is the number of players with the METRIC, not the size of the pool.

    Physical metrics are absent for 318 outfielders and every goalkeeper, so this is the
    ordinary case, not an edge one. Dividing by the pool size instead deflates every such
    metric toward zero -- four players inside a pool of ten came out at 5, 15, 25, 35
    instead of 12.5, 37.5, 62.5, 87.5, which through the band formula is a rating of 1.0
    for all four.
    """
    rows = [{**KEYS, "player_id": i,
             "ball_wins_p90": (float(i) if i < 4 else float("nan"))} for i in range(10)]
    out = metric_percentiles(pd.DataFrame(rows))["ball_wins_p90"].dropna()
    assert len(out) == 4
    assert sorted(round(v, 1) for v in out) == [12.5, 37.5, 62.5, 87.5]
    assert out.mean() == pytest.approx(50.0)


def test_players_without_the_metric_get_no_percentile():
    """Absent stays absent -- `_dimension_band` drops it, so a missing metric never
    deflates a dimension."""
    rows = [{**KEYS, "player_id": i,
             "ball_wins_p90": (float(i) if i < 4 else float("nan"))} for i in range(10)]
    out = metric_percentiles(pd.DataFrame(rows))["ball_wins_p90"]
    assert out.isna().sum() == 6


def test_order_within_a_pool_is_preserved():
    """The fix is a monotonic rescaling. It must not reorder anybody."""
    values = [5.0, 1.0, 9.0, 3.0, 7.0]
    out = _pcts(values)
    assert list(out.rank()) == list(pd.Series(values).rank())


def test_lower_is_better_metrics_are_still_inverted():
    """Regression: turnovers -- fewest should score highest."""
    out = _pcts([0.0, 1.0, 2.0, 3.0, 4.0], metric="turnovers_p90")
    assert out.iloc[0] > out.iloc[4]


def test_lower_is_better_metrics_are_also_centred_on_50():
    """The inversion is 100 - p, so an off-centre scale was off-centre the other way --
    the two biases partly cancelled and hid the defect."""
    assert _pcts(range(50), metric="turnovers_p90").mean() == pytest.approx(50.0)


def test_tied_values_still_share_a_percentile():
    """Three players with identical output must be ranked identically."""
    out = _pcts([1.0, 1.0, 1.0, 5.0])
    assert out.iloc[0] == out.iloc[1] == out.iloc[2]


def test_a_single_player_pool_sits_at_the_middle():
    """One player is neither above nor below his peers -- there are none. 100 was a claim
    the data could not support."""
    assert _pcts([4.0]).iloc[0] == pytest.approx(50.0)


def test_each_league_and_position_is_ranked_separately():
    """Regression: the grouping must survive the change."""
    rows = ([{**KEYS, "player_id": i, "ball_wins_p90": float(i)} for i in range(4)]
            + [{**KEYS, "competition_id": 2, "player_id": 10 + i,
                "ball_wins_p90": float(i) * 100} for i in range(4)])
    out = metric_percentiles(pd.DataFrame(rows))["ball_wins_p90"]
    assert sorted(out.xs(1, level="competition_id")) == sorted(out.xs(2, level="competition_id"))
