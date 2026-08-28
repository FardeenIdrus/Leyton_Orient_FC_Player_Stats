"""Rendering the report to a self-contained HTML document.

The document leaves the building: it is emailed to a chairman and a manager who cannot log
in, cannot query the data, and may print it in black and white. These tests pin the things
that would mislead such a reader, and the things that would stop the file opening at all.
"""

import datetime as dt

from lofc.report import data, render


def _fixture(**overrides):
    base = dict(
        player_name="A Player", position="Central Mid", club="A Club",
        league="League One", season_label="25/26", age=24.1, foot="right",
        height_cm=182, nationality="England", contract_until="30 Jun 2027",
        minutes=2100.0, goals=4.0, assists=6.0, composite=3.9,
        dimension_bands={"Performance": 4.1, "Physical": 3.6,
                         "Psychological": None, "Medical": None},
        rank=7, peer_count=102,
        percentiles={"pass_value_p90": 70.0, "turnovers_p90": 40.0},
        category_scores={"Pressing": 62.0, "Progression": 71.0},
        physical={"distance_p90": 55.0},
        peers=[("A Player", 60.0, 62.0), ("B Player", 30.0, 40.0)],
        availability=0.92, availability_status="measured", matches_missed=3,
        injuries=[], narrative=None,
        stamp=data.STAMP_DATA_ONLY, snapshot_date="28 Aug 2026",
        comparison_text=("25/26 · League One only · compared to 102 League One "
                         "Central Mids over 450 minutes"),
        flags=[])
    base.update(overrides)
    return data.ReportData(**base)


def _narrative(**overrides):
    base = dict(summary="Progresses well under pressure.",
                why_sign="Elite retention for the level.",
                considerations="Limited aerially.",
                assessor="Scout One", assessor_role="scout",
                approver=None, approved_at=None)
    base.update(overrides)
    return data.Narrative(**base)


def test_html_is_self_contained():
    """It is emailed and opened offline. No external stylesheet, no CDN, no remote image."""
    out = render.to_html(_fixture())
    assert "<style" in out
    # An SVG namespace declaration is not a fetch, so assert on the things that actually
    # reach the network: linked stylesheets, scripts, images and CSS url() references.
    assert "<link" not in out
    assert "<script" not in out
    assert 'src="http' not in out
    assert "url(http" not in out


def test_the_stamp_appears_on_the_page():
    """A reader must see at a glance whether this is data alone, one scout's view, or the
    department's position."""
    out = render.to_html(_fixture(stamp=data.STAMP_PROVISIONAL))
    assert data.STAMP_PROVISIONAL in out


def test_the_comparison_set_appears_on_the_page():
    """A percentile with no stated peer group is meaningless to someone who cannot ask."""
    out = render.to_html(_fixture())
    assert "League One" in out and "450" in out and "102" in out


def test_absent_narrative_says_so_rather_than_leaving_a_gap():
    out = render.to_html(_fixture(narrative=None))
    assert "No scout assessment recorded" in out


def test_a_present_narrative_is_shown_with_its_author():
    """Provenance is what makes a judgement usable outside the recruitment room."""
    out = render.to_html(_fixture(narrative=_narrative(),
                                  stamp=data.STAMP_PROVISIONAL))
    assert "Progresses well under pressure." in out
    assert "Scout One" in out


def test_absent_bio_reads_as_not_recorded_never_zero():
    """A player with no recorded height is not 0cm."""
    out = render.to_html(_fixture(height_cm=None, foot=None))
    assert "not recorded" in out.lower()
    assert ">0cm<" not in out


def test_an_absent_band_is_not_drawn_as_zero():
    """Psychological with no assessment is unmeasured, not a band of zero."""
    out = render.to_html(_fixture())
    assert ">0.00<" not in out


def test_player_name_is_escaped():
    out = render.to_html(_fixture(player_name="A <script>alert(1)</script>"))
    assert "<script>alert" not in out


def test_print_css_sets_landscape_a4():
    out = render.to_html(_fixture())
    assert "@page" in out and "landscape" in out


def test_flags_name_the_dimension_rather_than_warning_vaguely():
    out = render.to_html(_fixture(
        flags=["Resale 1.58 is below the club minimum of 2.00"]))
    assert "Resale 1.58" in out


def test_the_snapshot_date_appears():
    """A reader needs to know how current the data is."""
    out = render.to_html(_fixture())
    assert "28 Aug 2026" in out


# --- position split, assist definition and the Leyton Orient benchmark ----------------
# All three exist because the page is read by people who cannot query the data and cannot
# ask a follow-up question. Each pins something that would otherwise mislead them.

def test_the_position_split_is_shown_when_he_played_more_than_one():
    out = render.to_html(_fixture(position_shares=[
        ("Full Back", 373.0, 0.387, 0.0, 0.0), ("Attacking Mid", 282.0, 0.293, 2.0, 2.0),
        ("Winger", 189.0, 0.196, 2.0, 1.0), ("Centre Forward", 120.0, 0.125, 0.0, 0.0)]))
    assert "Attacking Mid" in out and "39%" in out


def test_a_minority_position_says_so_in_words():
    """Scoring him as a Full Back on 39% of his minutes is defensible; presenting that
    label as the whole truth is not."""
    out = render.to_html(_fixture(position="Full Back", position_shares=[
        ("Full Back", 373.0, 0.387, 0.0, 0.0), ("Attacking Mid", 282.0, 0.293, 2.0, 2.0)]))
    assert "under half his minutes" in out


def test_a_settled_player_gets_no_split_and_no_note():
    out = render.to_html(_fixture(position_shares=[("Central Mid", 2100.0, 1.0, 4.0, 6.0)]))
    assert "under half his minutes" not in out


def test_the_assist_definition_is_on_the_page():
    """Impect counts won penalties, deflections and forced own goals as assists;
    Transfermarkt counts none of them. A reader checking one against the other must be
    told why they differ, on the page, because they cannot ask."""
    out = render.to_html(_fixture())
    assert "forced own goals" in out.lower()


def test_chances_created_is_shown_beside_assists():
    out = render.to_html(_fixture(chances_created=12.0))
    assert "Chances created" in out


def test_the_benchmark_states_how_many_players_it_rests_on():
    """Leyton Orient have one rankable Attacking Mid. A median over one player is a
    single player's number and must not read as a squad standard."""
    out = render.to_html(_fixture(benchmark={"pass_value_p90": 55.0}, benchmark_n=1,
                                  benchmark_league="League One"))
    assert "n=1" in out


def test_a_cross_league_benchmark_says_the_two_percentiles_are_different_scales():
    out = render.to_html(_fixture(league="Premier League 2",
                                  benchmark={"pass_value_p90": 55.0}, benchmark_n=4,
                                  benchmark_league="League One"))
    assert "Percentiles are within a league" in out


def test_a_same_league_benchmark_does_not_add_the_caveat():
    out = render.to_html(_fixture(league="League One",
                                  benchmark={"pass_value_p90": 55.0}, benchmark_n=4,
                                  benchmark_league="League One"))
    assert "Percentiles are within a league" not in out


def test_no_benchmark_draws_no_legend_entry():
    out = render.to_html(_fixture(benchmark={}, benchmark_n=0))
    assert "Leyton Orient median" not in out


def test_no_league_average_ring_is_drawn_on_the_radar():
    """It was [50] * 8 -- a perfect octagon for every player by construction, because the
    axes are percentiles and the median is 50 on each by definition. It looked like data
    and was a gridline."""
    out = render.to_html(_fixture(physical={"distance_p90": 55.0}))
    assert "League average" not in out


def test_goals_are_attributed_to_the_position_they_were_scored_in():
    """Nothing is removed from his profile: these are the same goals, said out loud
    against the position he was playing. It matters because the percentiles above compare
    him with one position's peers."""
    out = render.to_html(_fixture(position="Full Back", goals=4.0, position_shares=[
        ("Full Back", 373.0, 0.387, 0.0, 0.0),
        ("Attacking Mid", 282.0, 0.293, 2.0, 2.0),
        ("Winger", 189.0, 0.196, 2.0, 1.0)]))
    assert "2 goals as attacking mid" in out
    assert "2 goals as winger" in out


def test_a_player_who_scored_only_in_his_own_position_gets_no_whence_line():
    out = render.to_html(_fixture(position="Winger", goals=2.0, position_shares=[
        ("Winger", 2000.0, 0.9, 2.0, 1.0), ("Centre Forward", 200.0, 0.1, 0.0, 0.0)]))
    assert "as centre forward" not in out


def test_the_physical_band_key_prints_its_ranges():
    out = render.to_html(_fixture(league="League One", physical={"distance_p90": 72.0}))
    assert "Physical bands, League One" in out
    assert "Elite (80-100)" in out and "Subpar (0-25)" in out


def test_physical_percentiles_are_printed_as_numbers():
    """The whole point of the rebuild: readable figures, not a polygon to eyeball."""
    out = render.to_html(_fixture(physical={"distance_p90": 72.4}))
    assert "72.4" in out
