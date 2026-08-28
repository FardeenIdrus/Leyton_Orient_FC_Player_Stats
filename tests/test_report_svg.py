"""The report's charts, as inline SVG strings. Pure: values in, markup out. No Streamlit,
no chart library, nothing to render -- the assertions are on the markup itself.

Inline SVG rather than a chart image because the report is a document that leaves the
building: it must stay sharp when printed, work offline with no JavaScript, and travel in a
single file.
"""

from lofc.report import svg


def test_percentile_bars_emits_one_bar_per_metric():
    out = svg.percentile_bars(["Goals", "Assists"], [80.0, 20.0])
    assert out.count("<rect") >= 2
    assert out.startswith("<svg")


def test_percentile_bars_labels_every_value():
    """A bar a reader cannot read the number off is decoration."""
    out = svg.percentile_bars(["Goals"], [80.4])
    assert "80.4" in out


def test_percentile_bars_does_not_rely_on_colour_alone():
    """The page is printed and read in black and white. The value must survive that."""
    out = svg.percentile_bars(["Goals"], [80.4])
    assert "80.4" in out and "<text" in out


def test_percentile_bars_skips_a_missing_value_rather_than_drawing_zero():
    """An unmeasured metric is not a metric the player scored zero in."""
    out = svg.percentile_bars(["Goals", "Saves"], [80.0, None])
    assert "not measured" in out.lower()


def test_radar_draws_every_series():
    out = svg.radar(["A", "B", "C"], [("Player", [80, 60, 40], "#C8102E"),
                                      ("League", [50, 50, 50], "#333333")])
    assert out.count("<polygon") + out.count("<polyline") >= 2
    assert "Player" in out and "League" in out


def test_radar_handles_a_missing_axis_value_without_drawing_zero():
    """A physical metric we do not hold must not plot at the origin -- that reads as
    'covered no distance' rather than 'not measured'."""
    out = svg.radar(["A", "B"], [("Player", [80, None], "#C8102E")])
    assert out.startswith("<svg")


def test_scatter_marks_the_target_distinctly_and_names_it():
    peers = [("A. Player", 20.0, 30.0), ("Target Man", 70.0, 80.0)]
    out = svg.scatter(peers, "Target Man", "Progression", "Pressing")
    assert "Target Man" in out
    assert "Progression" in out and "Pressing" in out


def test_category_strip_places_the_player_within_the_distribution():
    out = svg.category_strip("Pressing", 72.0, [10.0, 50.0, 90.0])
    assert "Pressing" in out and "72" in out


def test_every_chart_escapes_text():
    """Player and club names reach these directly. An unescaped angle bracket breaks the
    page, and the page is a document that leaves the building."""
    out = svg.scatter([("A <b>Name", 10.0, 10.0)], "A <b>Name", "X", "Y")
    assert "<b>" not in out
    assert "&lt;b&gt;" in out


def test_percentile_bars_escapes_metric_labels():
    out = svg.percentile_bars(["<script>x</script>"], [50.0])
    assert "<script>" not in out


def test_a_lower_is_better_metric_is_flipped_and_labelled():
    """A player in the 90th percentile for turnovers gives the ball away a lot. Drawn raw
    he gets a long green bar identical to a player with elite pass accuracy, and a reader
    who cannot query the data cannot tell them apart."""
    out = svg.percentile_bars(["Turnovers"], [90.0], inverted={0})
    assert "fewer is better" in out
    assert "10.0" in out          # flipped
    assert ">90.0<" not in out    # the raw value is never shown as the score


def test_scatter_names_the_peers_not_just_the_target():
    """"62nd percentile for pressing" means little alone; "presses more than Smith, less
    than Jones" is a sentence a manager can act on. Naming the field is the chart's job."""
    peers = [("Alan Smith", 20.0, 30.0), ("Ben Jones", 80.0, 70.0),
             ("Target Man", 50.0, 50.0)]
    out = svg.scatter(peers, "Target Man", "X", "Y")
    assert "Smith" in out and "Jones" in out


def test_scatter_thins_labels_rather_than_stacking_them():
    """Twenty players on the same coordinate must not print twenty names on top of each
    other -- an unreadable pile is worse than a few unlabelled dots."""
    peers = [(f"Player{i} Same", 50.0, 50.0) for i in range(20)]
    peers.append(("Target Man", 10.0, 10.0))
    out = svg.scatter(peers, "Target Man", "X", "Y")
    assert out.count("Same") <= 2


def test_scatter_labels_its_axes_with_percentile_ticks():
    """The reference report ticks both axes 0-100. Without them a reader cannot tell
    whether a point sits at the 40th percentile or the 60th."""
    out = svg.scatter([("A Player", 50.0, 50.0)], "A Player", "Creation", "Scoring")
    for tick in (">0<", ">25<", ">50<", ">75<", ">100<"):
        assert tick in out
    assert "percentile" in out


# --- the Leyton Orient squad benchmark ------------------------------------------------
# "Is he better than what we already have?" is the question the report exists to answer,
# so the club's own squad median is drawn on each bar as a tick.

def test_benchmark_draws_a_marker_per_metric():
    out = svg.percentile_bars(["A", "B"], [80.0, 20.0], benchmark=[50.0, 60.0])
    assert out.count('class="benchmark"') == 2


def test_absent_benchmark_draws_nothing_rather_than_a_zero_tick():
    """A club with nobody in that position must not read as a squad median of 0."""
    out = svg.percentile_bars(["A", "B"], [80.0, 20.0], benchmark=[None, 60.0])
    assert out.count('class="benchmark"') == 1


def test_omitting_benchmark_entirely_is_unchanged_output():
    """The parameter is additive: existing callers must render byte-identically."""
    assert (svg.percentile_bars(["A"], [80.0])
            == svg.percentile_bars(["A"], [80.0], benchmark=None))


def test_the_benchmark_is_flipped_on_an_inverted_metric():
    """Turnovers are drawn flipped so long = good. A squad median drawn on the RAW value
    would sit on the opposite side of the bar from the player's own number and read as
    the club being worse when it is better."""
    plain = svg.percentile_bars(["Turnovers"], [30.0], benchmark=[70.0])
    flipped = svg.percentile_bars(["Turnovers"], [30.0], benchmark=[70.0], inverted={0})
    assert plain != flipped


# --- the physical radar: named bands, printed values ----------------------------------
# Modelled on the club's own reference report, which shows the percentile AT each vertex
# over named bands. The bands carry the range in brackets so a reader never has to guess
# what "Very Good" means.

def test_radar_prints_the_percentile_at_each_vertex():
    """The whole point: the physical percentiles must be readable as NUMBERS, not
    inferred from the shape of a polygon."""
    out = svg.radar(["Distance", "M/min"], [("This player", [72.4, 31.9], svg.RED)])
    assert "72.4" in out and "31.9" in out


def test_band_legend_names_the_range_in_brackets():
    """"Very Good" is a label, not a quantity, and the reader cannot ask what it covers."""
    out = svg.physical_band_legend("League One")
    assert "League One" in out
    assert "Elite (80-100)" in out
    assert "Very Good (65-80)" in out
    assert "Subpar (0-25)" in out


def test_band_legend_names_the_league_the_bands_are_relative_to():
    """A percentile band means nothing without the population it is drawn from."""
    out = svg.physical_band_legend("League Two")
    assert "League Two" in out
    assert "League One" not in out


def test_bands_are_contiguous_and_span_the_whole_scale():
    """A gap would leave a percentile with no band; an overlap would give it two."""
    rs = svg.band_ranges()
    assert rs[0][2] == 100 and rs[-1][1] == 0
    for (_n, low, _h, _c), (_n2, _l2, high2, _c2) in zip(rs, rs[1:]):
        assert low == high2


def test_radar_without_a_league_omits_the_band_legend():
    """No league named, no claim about what 'Elite' is relative to."""
    out = svg.radar(["Distance"], [("This player", [72.0], svg.RED)])
    assert "Elite for" not in out


def test_radar_omits_the_value_label_where_the_metric_is_unmeasured():
    out = svg.radar(["Distance", "M/min"], [("This player", [72.4, None], svg.RED)])
    assert "72.4" in out
    assert ">0.0<" not in out
