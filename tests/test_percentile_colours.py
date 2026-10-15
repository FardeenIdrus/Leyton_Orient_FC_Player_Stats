"""Percentile colours, on the club's own thresholds: 70th = Elite (green), below 30th = the
veto level, band 2.0 (red), between = normal range (grey). Used by the player card's
Performance profile bars (owner, 2026-10-12)."""

from lofc.dashboard.charts import PCT_GREEN, PCT_GREY, PCT_RED, bar_chart, percentile_colour


def test_thresholds_are_the_clubs():
    assert percentile_colour(70) == PCT_GREEN
    assert percentile_colour(69.9) == PCT_GREY
    assert percentile_colour(30) == PCT_GREY
    assert percentile_colour(29.9) == PCT_RED


def test_bars_are_coloured_per_value():
    fig = bar_chart(["a", "b", "c"], [85.0, 50.0, 10.0])
    assert list(fig.data[0].marker.color) == [PCT_GREEN, PCT_GREY, PCT_RED]
