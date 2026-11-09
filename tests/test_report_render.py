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
        physical={"distance_p90": 55.0},
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


# --- authored reports ---------------------------------------------------------------------

def _authored_fixture(**overrides):
    author = data.Authored(author_name="Scout One", author_role="scout",
                           created_at=dt.datetime(2026, 11, 2, 9, 0), summary="Mine.",
                           why_sign=None, considerations=None, psych_band=3.5,
                           medical_band=None)
    base = dict(stamp="Report by Scout One · 02 Nov 2026", authored=author,
                narrative=data.Narrative(summary="Mine.", why_sign=None,
                                         considerations=None, assessor=None,
                                         assessor_role=None, approver=None,
                                         approved_at=None),
                dimension_bands={"Performance": 4.1, "Physical": 3.6,
                                 "Psychological": 3.5, "Medical": None})
    base.update(overrides)
    return _fixture(**base)


def test_authored_report_labels_tiles_and_footer():
    out = render.to_html(_authored_fixture())
    assert "Report by Scout One" in out
    # the stamp names the author once; the footer once; tiles are plain
    assert "<dt>Psychological</dt>" in out and "<dt>Medical</dt>" in out
    body = out.split("</head>")[1]
    assert "'s view" not in body and "&#39;s view" not in body
    flat = " ".join(__import__("html").unescape(body).split())
    assert ("Psychological, Medical and medical checks are Scout One's assessment "
            "and do not change any rating.") in flat
    assert flat.count("Scout One's assessment") == 1   # footer names him once
    assert "Mine." in out


def test_authored_blank_band_shows_dash_not_assessed_wording():
    out = render.to_html(_authored_fixture())
    medical = out.split("<dt>Medical</dt>")[1].split("</div>")[0]
    assert "&mdash;" in medical and "not assessed" not in medical


def test_non_authored_report_has_no_author_labels():
    out = render.to_html(_fixture())
    assert "Psychological (" not in out and "Medical (" not in out
    assert "Medical checks" not in out and "assessment and do not" not in out
    assert "do not change any rating" not in out


def test_authored_text_is_escaped():
    evil = "<script>alert(1)</script>"
    author = data.Authored(author_name="Eve <b>", author_role="scout",
                           created_at=dt.datetime(2026, 11, 2), summary=evil,
                           why_sign=evil, considerations=evil, psych_band=None,
                           medical_band=None)
    nar = data.Narrative(summary=evil, why_sign=evil, considerations=evil, assessor=None,
                         assessor_role=None, approver=None, approved_at=None)
    out = render.to_html(_fixture(authored=author, narrative=nar,
                                  stamp="Report by Eve <b> · 02 Nov 2026"))
    assert "<script>alert(1)" not in out
    assert "&lt;script&gt;" in out
    assert "Eve <b>" not in out


def test_screening_answers_render_with_marks_and_escape():
    author = data.Authored(author_name="Scout One", author_role="scout",
                           created_at=dt.datetime(2026, 11, 2), summary="x",
                           why_sign=None, considerations=None, psych_band=None,
                           medical_band=None,
                           screening={"Ankle stability clear": "Meets",
                                      "No <i>hamstring</i> injury": "Does not meet"})
    out = render.to_html(_fixture(authored=author))
    assert "Medical checks:" in out and "Screening" not in out
    assert "✓ Ankle stability clear" in out
    assert "✗ No &lt;i&gt;hamstring&lt;/i&gt; injury" in out
    assert "<i>hamstring" not in out


def test_no_screening_section_when_none_answered_or_data_only():
    assert "Medical checks" not in render.to_html(_fixture())
    author = data.Authored(author_name="S", author_role=None,
                           created_at=dt.datetime(2026, 11, 2), summary="x",
                           why_sign=None, considerations=None, psych_band=None,
                           medical_band=None)
    assert "Medical checks:" not in render.to_html(_fixture(authored=author))


# --- playing style (replaces the category strips and the category scatter) ---------------

def _style(position, label, strong=(), leans=(), **fits):
    """What data.build stores for a player: the style row of model/styles.assign_styles."""
    return {"position_group": position, "style_label": label,
            "strong_styles": list(strong), "leans_styles": list(leans),
            **{f"fit.{k}": v for k, v in fits.items()}}


def _winger():
    from lofc.model import styles as st
    fits = {s: 40.0 for g in st.STYLES["Winger"].values() for s in g}
    fits.update({"Wide": 82.0, "1v1": 75.0, "Pocket": 55.0})
    return _fixture(position="Winger", style=_style(
        "Winger", "Wide \u00b7 1v1", strong=["Wide", "1v1"], **fits))


def test_winger_style_section_has_both_groups_and_one_bar_per_style():
    from lofc.model import styles as st
    out = render.to_html(_winger())
    assert "Playing style" in out
    assert "Where he plays" in out and "What he does" in out
    n = sum(len(g) for g in st.STYLES["Winger"].values())
    assert out.count('class="style-row"') == n
    assert "Wide \u00b7 1v1" in out


def test_centre_back_style_section_has_one_bar_per_style_and_signals():
    from lofc.model import styles as st
    fits = {s: 60.0 for s in st.STYLES["Centre Back"]["Style"]}
    out = render.to_html(_fixture(position="Centre Back", style=_style(
        "Centre Back", "Leans " + next(iter(fits)), leans=[next(iter(fits))], **fits)))
    assert out.count('class="style-row"') == len(st.STYLES["Centre Back"]["Style"])
    assert "Where he plays" not in out
    first = next(iter(st.STYLES["Centre Back"]["Style"].values()))[0]
    assert st.SIGNAL_LABELS[first] in out
    assert f"{next(iter(fits))} (leans)" in out


def test_quality_signals_carry_a_flag_and_others_do_not():
    from lofc.model import styles as st
    out = render.to_html(_winger())
    quality = next(s for g in st.STYLES["Winger"].values() for sg in g.values()
                   for s in sg if s in st.QUALITY_SIGNALS)
    assert f"\u2691 {st.SIGNAL_LABELS[quality]}" in out or "\u2691" in out
    plain = next(s for g in st.STYLES["Winger"].values() for sg in g.values()
                 for s in sg if s not in st.QUALITY_SIGNALS)
    assert f"\u2691 {st.SIGNAL_LABELS[plain]}" not in out


def test_goalkeeper_has_no_style_section():
    out = render.to_html(_fixture(position="Goalkeeper"))
    assert "<h2>Playing style</h2>" not in out


def test_no_style_data_omits_the_section():
    assert "Playing style" not in render.to_html(_fixture())


def test_unrated_player_reads_not_enough_minutes_without_bars():
    out = render.to_html(_fixture(position="Winger", style=_style(
        "Winger", "Not enough minutes")))
    assert "Not enough minutes" in out
    assert 'class="style-row"' not in out


def test_no_standout_style_still_shows_the_bars():
    out = render.to_html(_fixture(position="Centre Back", style=_style(
        "Centre Back", "No standout style", **{"Ball-playing": 30.0})))
    assert "No standout style" in out and 'class="style-row"' in out


def test_style_text_is_escaped(monkeypatch):
    from lofc.model import styles as st
    sig = next(iter(next(iter(st.STYLES["Centre Back"]["Style"].values()))))
    monkeypatch.setitem(st.SIGNAL_LABELS, sig, "<b>x</b> & y")
    fits = {s: 60.0 for s in st.STYLES["Centre Back"]["Style"]}
    out = render.to_html(_fixture(position="Centre Back", style=_style(
        "Centre Back", "No standout style", **fits)))
    assert "<b>x</b>" not in out and "&lt;b&gt;x&lt;/b&gt; &amp; y" in out


def test_data_only_report_keeps_the_style_section():
    """Style is measured data, not a scout's opinion, so a data-only report keeps it."""
    base = _winger()
    out = render.to_html(data.as_data_only(base))
    assert "Playing style" in out


def test_footer_explains_style_fit_and_strips_are_gone():
    out = render.to_html(_winger())
    assert ("Playing style: fit = average percentile of the style\u2019s signals vs the "
            "same position, league and season; Strong \u2265 70, Leans \u2265 50.") in out
    assert "weighted as in the rating" not in out
    assert "Category strips" not in out


def test_categories_strips_and_scatter_are_gone():
    out = render.to_html(_winger())
    assert 'class="strip' not in out and "Also in the rating" not in out
    assert "<h2>Style</h2>" not in out and "peers</span>" not in out
    assert 'class="scatter' not in out


def test_report_no_longer_imports_report_categories():
    import inspect
    assert "report_categories" not in inspect.getsource(render)
    assert "report_categories" not in inspect.getsource(data)


# --- TASKS 2.36 ------------------------------------------------------------------------
def test_minutes_goals_assists_and_chances_round_half_up():
    """Owner decision D2 (2026-11-09): every minutes / goals figure rounds half-up. Python's
    format rounds half to even, so 1,026.5 minutes read 1,026 and 2.5 goals read 2."""
    out = render.to_html(_fixture(minutes=1026.5, goals=2.5, assists=0.5,
                                  chances_created=4.5))
    assert "1,027" in out and "1,026<" not in out
    counts = out[out.index('class="counts"'):out.index("</dl>", out.index('class="counts"'))]
    assert "<dd>3</dd>" in counts and "<dd>1</dd>" in counts and "<dd>5</dd>" in counts


def test_goals_by_position_round_half_up():
    shares = [("Winger", 900.0, 0.6, 2.5, 0.0), ("Centre Forward", 600.0, 0.4, 0.5, 0.0)]
    assert render.goals_by_position(shares) == ["3 goals as winger", "1 goal as centre forward"]


def test_not_rated_hides_composite_rank_and_data_bands():
    """A thin peer pool (< MIN_PEERS_FOR_RANKING) is never shown as a rating (owner D1): no
    composite, no rank, no Performance / Physical band, and a note saying why. Scout bands
    stay: they are not computed from the pool."""
    d = _fixture(composite=4.49, rank=1, peer_count=8,
                 dimension_bands={"Performance": 4.1, "Physical": 3.6,
                                  "Psychological": 3.0, "Medical": None},
                 flags=["Composite 1.90 is below the club's 3.00 minimum standard",
                        "Physical 1.50 is below the club minimum of 2.00"])
    out = render.to_html(d, not_rated="Not rated: only 8 comparable players (needs 10)")
    assert "4.49" not in out and "4.10" not in out and "3.60" not in out
    assert "1st of 8" not in out
    assert "Not rated: only 8 comparable players (needs 10)" in out
    assert "3.00" in out                                  # Psychological kept
    assert "below the club" not in out


def test_without_not_rated_the_document_is_unchanged():
    assert render.to_html(_fixture()) == render.to_html(_fixture(), not_rated=None)


def test_bar_inputs_are_the_drawn_bars():
    """The web page draws the same bars as the document: same metrics, labels, flipped
    turnovers and Orient ticks."""
    d = _fixture(position="Central Mid", percentiles={"turnovers_p90": 30.0},
                 benchmark={"turnovers_p90": 60.0}, benchmark_n=3)
    rows = render.bar_inputs(d)
    t = next(r for r in rows if r["metric"] == "turnovers_p90")
    assert t["inverted"] and t["shown"] == 70.0 and t["orient"] == 40.0
    assert t["label"].endswith("(fewer is better)")
    missing = [r for r in rows if r["metric"] != "turnovers_p90"]
    assert missing and all(r["shown"] is None for r in missing)
