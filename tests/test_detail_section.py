"""The player card's detail sections: Impect scores, zone/lane map, receptions, physical by phase.

DISPLAY ONLY. Percentiles follow the scoring convention exactly -- within league + season +
position, rated (450+ minute) players only, mid-rank (rank - 0.5) / n -- so a "70th" here
means what it means everywhere else on the platform.
"""

import pandas as pd
import pytest

from lofc.dashboard import detail_section as ds


def _pool():
    return pd.DataFrame({
        "player_id": [1, 2, 3, 4, 5],
        "position_group": ["Winger"] * 4 + ["Centre Back"],
        "rankable": [True, True, True, False, True],
        "metric": ["zone.touches.IB"] * 5,
        "value_p90": [1.0, 2.0, 3.0, 9.0, 5.0],
        "total": [10.0, 20.0, 30.0, 90.0, 50.0],
    })


def test_percentiles_are_mid_rank_within_position_over_rated_players():
    out = ds.pool_percentiles(_pool()).set_index("player_id")["pct"]
    assert out[1] == pytest.approx(100 / 6)        # (1 - 0.5) / 3
    assert out[3] == pytest.approx(500 / 6)        # (3 - 0.5) / 3
    assert out[5] == pytest.approx(50.0)           # alone in his position
    assert pd.isna(out[4])                         # not rated: shown, never ranked


def test_lower_is_better_metrics_are_not_inverted_here():
    """No detail metric is lower-is-better; a high zone count is a fact, not a verdict."""
    assert not any(m.startswith(("zone.", "lane.")) and "lost" in m for m in ds.FAMILY_ORDER)


def test_pitch_svg_draws_every_zone_and_marks_the_goal_area_unsupplied():
    cells = {z: ("1.0", 50.0) for z in ds.ZONES}
    svg = ds.pitch_svg(cells)
    for z in ds.ZONES:
        assert f'data-zone="{z}"' in svg
    assert "no data" in svg


def test_a_cell_with_no_percentile_is_neutral_not_coloured_as_low():
    assert ds.cell_fill(None) == ds.NEUTRAL_FILL
    assert ds.cell_fill(5.0) != ds.cell_fill(95.0)


def test_value_format_per_mode():
    assert ds.fmt_value(2.345, "Per 90", "touches") == "2.3"
    assert ds.fmt_value(0.123, "Per 90", "xg") == "0.12"
    assert ds.fmt_value(41.6, "Season total", "touches") == "42"
    assert ds.fmt_value(3.24, "Season total", "xg") == "3.2"


def test_an_empty_pool_gives_an_empty_frame_not_an_error():
    """Scottish Championship has no SkillCorner data: its physical pool is empty."""
    empty = pd.DataFrame()
    out = ds.pool_percentiles(empty)
    assert out.empty and "pct" in out.columns


def test_the_prefix_pattern_escapes_like_wildcards():
    assert ds.like_prefix("phys_") == "phys\\_%"


# --- 2026-10-09: layout built from Impect's zone definitions --------------------------------

def _rect(z):
    return ds._ZONE_RECTS[z]


def _row_span(z):
    x, y, w, h = _rect(z)
    return set(range(y, y + h, ds.ROW_H))


def test_layout_follows_impects_zone_borders():
    """Impect: WL/WR border DM and CM; FB zones border CB; in-behind wide zones border AM and IB."""
    assert _row_span("WL") == _row_span("CM") | _row_span("DM")
    assert _row_span("FBL") == _row_span("CB")
    assert _row_span("IBWL") == _row_span("AM") | _row_span("IB")
    assert _rect("IB")[1] < _rect("AM")[1] < _rect("CM")[1] < _rect("DM")[1] < _rect("CB")[1]


def test_cells_carry_impects_names_not_ours():
    svg = ds.pitch_svg({z: ("1.0", 50.0) for z in ds.ZONES})
    assert "In-Behind Central" in svg
    assert ">Box<" not in svg and "Box, left" not in svg      # the old, wrong labels


def test_per_match_is_total_over_matches():
    assert ds.unit_value(total=73.0, per90=6.37, matches=10.28, mode="Per match") == \
        pytest.approx(7.10, abs=0.01)
    assert ds.unit_value(total=73.0, per90=6.37, matches=10.28, mode="Per 90") == 6.37
    assert ds.unit_value(total=73.0, per90=6.37, matches=10.28, mode="Season total") == 73.0


def test_only_the_two_requested_impect_scores_are_shown():
    """The Head of Recruitment asked for attacking and defensive IMPECT; nothing more is shown."""
    import inspect
    assert ds.SCORE_TILES == ["offensive", "defensive"]
    assert "All Impect scores" not in inspect.getsource(ds.render)


def test_position_breakdown_lists_every_position_by_minutes():
    rows = pd.DataFrame({
        "metric": ["score_pos.offensive.CENTER_FORWARD", "score_pos.defensive.CENTER_FORWARD",
                   "score_pos.minutes.CENTER_FORWARD", "score_pos.offensive.RIGHT_WINGER",
                   "score_pos.defensive.RIGHT_WINGER", "score_pos.minutes.RIGHT_WINGER"],
        "value_p90": [0.73, 0.10, 992.0, -0.06, 0.20, 18.0]})
    table = ds.position_breakdown(rows)
    assert table["Position"].tolist() == ["Centre forward", "Right winger"]
    assert table.iloc[0].to_dict() == {"Position": "Centre forward", "Minutes": 992.0,
                                       "Offensive IMPECT": 0.73, "Defensive IMPECT": 0.10}


def test_verified_impect_platform_name_is_used():
    """Verified 2026-10-09: Impect's 'Progressive Receiving' = BYPASSED_OPPONENTS_RECEIVING_TO,
    22/22 zones for Josh Walker's centre-forward rows."""
    from lofc.ingest.impect_detail import FAMILY_LABELS
    assert FAMILY_LABELS["bypassed_opponents_receiving_to"] == "Progressive Receiving"


def test_map_states_that_all_positions_are_included():
    """Impect's screen defaults to the player's main position; ours includes every position."""
    import inspect
    assert 'f"All positions. Colour: percentile vs' in inspect.getsource(ds.render)


def test_long_zone_names_wrap_instead_of_overflowing():
    """'In-Behind Wide Right' was cut off at the edge of its 90 px cell (owner, 2026-10-12)."""
    lines = ds.wrap_label("In-Behind Wide Right", width=90)
    assert len(lines) >= 2
    assert all(len(l) * ds.CHAR_PX <= 90 - 12 for l in lines)


# --- 2026-10-12: ONE Physical section on the card (owner-approved) --------------------------
# It was split across the Scorecard table (8 rated metrics) and "Physical detail" (an in/out
# table repeating 6 of them, plus a speed table repeating 2). Now one table: every physical
# metric once, marked when it is in the rating, with the scorecard percentile and band.

def _phys_inputs():
    detail = pd.DataFrame({"metric": ["phys_tip.distance_p90", "phys_otip.distance_p90"],
                           "value_p90": [3400.0, 5900.0]})
    neutral = pd.Series({"distance_p90": 10100.0, "top5_psv99_kmh": 30.9, "time_to_sprint": 0.99,
                         "cod_count_p90": 34.6})
    pcts = pd.Series({"distance_p90": 13.0, "top5_psv99_kmh": 69.0, "time_to_sprint": 88.0,
                      "cod_count_p90": 40.0})
    return detail, neutral, pcts


def test_physical_table_lists_each_metric_once_with_its_rating_role():
    detail, neutral, pcts = _phys_inputs()
    t = ds.physical_table(detail, neutral, pcts, scored=["distance_p90", "top5_psv99_kmh"])
    assert t["Metric"].is_unique
    rows = t.set_index("Metric")
    assert rows.loc["Distance (m)", "In rating"] == "✓"
    assert rows.loc["Changes of direction", "In rating"] == ""
    assert list(t.columns) == ["Metric", "In rating", "All phases", "In possession",
                               "Out of possession", "Percentile", "Band"]


def test_physical_table_uses_the_scorecard_percentile_and_bands_only_rated_metrics():
    detail, neutral, pcts = _phys_inputs()
    rows = ds.physical_table(detail, neutral, pcts, scored=["distance_p90", "top5_psv99_kmh"]).set_index("Metric")
    assert rows.loc["Distance (m)", "Percentile"] == 13
    assert rows.loc["Distance (m)", "Band"] == pytest.approx(1.15)
    assert pd.isna(rows.loc["Changes of direction", "Band"])


def test_speed_and_agility_rows_have_no_possession_split():
    detail, neutral, pcts = _phys_inputs()
    rows = ds.physical_table(detail, neutral, pcts, scored=[]).set_index("Metric")
    assert rows.loc["Top speed (km/h)", "All phases"] == 30.9
    assert pd.isna(rows.loc["Top speed (km/h)", "In possession"])
    assert rows.loc["Time to sprint (s)", "Percentile"] == 88


def test_render_shows_no_separate_speed_or_phase_tables():
    import inspect
    src = inspect.getsource(ds.render)
    assert "physical_table(" in src
    assert "speed_table(" not in src and "phase_table(" not in src


def test_card_physical_names_match_the_glossary_and_reference_page():
    """One metric, one name: the card said 'Top-5 average speed' while the glossary and the
    reference page said 'Top-5 peak speed' (2026-10-12)."""
    from lofc.dashboard.glossary_data import PHYSICAL
    for name, label in ds.PHASE_METRICS + [(m, l) for m, l, _ in ds.SPEED_METRICS]:
        base = PHYSICAL[name][0]
        assert label.startswith(base.rstrip(")")), (name, label, base)
        assert label.count("(") <= 1, label



# --- 2026-10-15: approved pitch redesign ------------------------------------------------
# Three colours on the club's thresholds (70th = Elite, below 30th = veto level), a distinct
# style for "no percentile" (a player under 450 minutes must not read as "normal range"),
# faint pitch markings, percentile on hover.

def test_pitch_colours_follow_the_club_thresholds():
    assert ds.cell_fill(70) == ds.HI_FILL
    assert ds.cell_fill(69.9) == ds.MID_FILL == ds.cell_fill(30)
    assert ds.cell_fill(29.9) == ds.LO_FILL


def test_no_percentile_is_not_shown_as_normal_range():
    assert ds.cell_fill(None) == ds.NEUTRAL_FILL
    assert ds.NEUTRAL_FILL not in (ds.HI_FILL, ds.MID_FILL, ds.LO_FILL)


def test_hover_states_the_percentile_and_the_pitch_has_markings():
    svg = ds.pitch_svg({"AM": ("16.8", 18.0), "CM": ("9.6", None)})
    assert "Attacking-Mid: 16.8 · 18th percentile" in svg
    assert "Centre-Mid: 9.6 · no percentile" in svg
    assert 'class="pitch-line"' in svg


def test_legend_shows_the_no_percentile_chip_only_when_needed():
    assert "No percentile" not in ds.legend_html(any_missing=False)
    assert "No percentile" in ds.legend_html(any_missing=True)
    for text in ("70th percentile and above", "30th to 70th", "Below 30th"):
        assert text in ds.legend_html(any_missing=False)


# --- 2026-10-15: the hover did not appear on the card (owner) ---------------------------
# The pitch was inserted through st.markdown, which does not reliably keep SVG <title>
# tooltips, and native tooltips only show after a ~1 s pause and never on touch screens. The
# pitch now renders in its own frame (components.html) with a custom tooltip that appears
# immediately on hover and on tap.

def test_pitch_frame_carries_a_custom_tooltip_for_every_zone():
    page = ds.pitch_frame_html({"AM": ("16.8", 18.0), "CM": ("9.6", None)}, any_missing=True)
    assert 'id="tip"' in page                       # the tooltip box
    assert "mousemove" in page and "click" in page  # hover and tap
    assert 'data-tip="Attacking-Mid: 16.8 · 18th percentile"' in page
    assert 'data-tip="Centre-Mid: 9.6 · no percentile"' in page
    assert "No percentile" in page                  # legend travels with the pitch


def test_render_uses_the_frame_not_markdown_for_the_pitch():
    import inspect
    src = inspect.getsource(ds.render)
    assert "pitch_frame_html(" in src
    assert "st.markdown(pitch_svg" not in src
    # components.html is deprecated in Streamlit 1.64 (scheduled for removal); st.iframe
    # replaces it. The HTML is ours, every text value escaped -- never user input.
    assert "st.iframe(" in src and "components.html(" not in src


# --- 2026-10-15: which physical metrics count must be obvious (owner) -------------------
# The ✓ column was easy to miss and the Scorecard heading ("the stats behind the composite")
# listed Performance only. Now: "Performance — in the rating", "Physical — in the rating"
# and "Other physical metrics". The headings carry the meaning; no ✓ column.

def test_physical_splits_into_rated_and_other():
    detail, neutral, pcts = _phys_inputs()
    table = ds.physical_table(detail, neutral, pcts, scored=["distance_p90", "top5_psv99_kmh"])
    rated, other = ds.split_physical(table)
    assert set(rated["Metric"]) == {"Distance (m)", "Top speed (km/h)"}
    assert "Changes of direction" in set(other["Metric"])
    assert "In rating" not in rated.columns and "In rating" not in other.columns
    assert "Band" in rated.columns and "Band" not in other.columns


def test_card_headings_say_what_counts():
    import inspect
    from lofc.dashboard.tabs import players
    src_ds, src_p = inspect.getsource(ds.render), inspect.getsource(players._render_profile_body)
    assert "Physical — in the rating" in src_ds and "Other physical metrics" in src_ds
    assert "Performance — in the rating" in src_p
    assert "the stats behind the composite" not in src_p


# --- a card with no physical data says why, in one line (owner, 2026-10-26) ---------------

def test_no_physical_line_names_the_league_when_the_league_has_none():
    from lofc.dashboard.detail_section import physical_gap
    assert physical_gap(league_has_physical=False, position="Centre Back") == \
        "no physical data for this league"


def test_no_physical_line_names_the_player_when_the_league_has_it():
    from lofc.dashboard.detail_section import physical_gap
    assert physical_gap(league_has_physical=True, position="Winger") == \
        "no physical data for this player"


def test_goalkeepers_get_no_line():
    """Physical never counts for goalkeepers, so a missing section says nothing."""
    from lofc.dashboard.detail_section import physical_gap
    assert physical_gap(league_has_physical=True, position="Goalkeeper") is None
    assert physical_gap(league_has_physical=False, position="Goalkeeper") is None
