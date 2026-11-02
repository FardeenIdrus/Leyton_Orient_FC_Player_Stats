"""Compare page: radar axes, the Performance / Physical tables and the summary-table extras.

Pure functions only (no Streamlit runtime, no database)."""

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from lofc.dashboard import compare_tables as ct
from lofc.dashboard.metric_filters import LOWER_IS_BETTER_PHYSICAL, PHYSICAL_GROUPS
from lofc.model import club_framework as cf
from lofc.model.performance_weights import WEIGHTS


# --- radar metrics: High + Mid only ---------------------------------------------------------
@pytest.mark.parametrize("key", list(WEIGHTS))
def test_radar_metrics_are_high_and_mid_only(key):
    position, archetype = key
    expected = [m for m, (tier, _) in WEIGHTS[key].items() if tier in ("High", "Mid")]
    assert ct.radar_metrics(position, archetype) == expected
    assert not any(WEIGHTS[key][m][0] == "Low" for m in ct.radar_metrics(position, archetype))


def test_radar_metrics_use_the_archetype_table_and_fall_back_to_all_metrics():
    assert ct.radar_metrics("Full Back", "Attacking") != ct.radar_metrics("Full Back", "All Metrics")
    assert ct.radar_metrics("Centre Back", "Unknown style") == ct.radar_metrics("Centre Back", "All Metrics")
    assert "counterpressures_p90" not in ct.radar_metrics("Centre Back", "All Metrics")  # a Low


# --- a metric missing for one player keeps the radar ----------------------------------------
def test_missing_metric_for_one_player_is_still_an_axis_with_none():
    metrics = ["a", "b", "c", "d"]
    x = pd.Series({"a": 80.0, "b": 60.0, "c": 40.0, "d": 20.0})
    y = pd.Series({"a": 70.0, "b": np.nan, "c": 30.0, "d": 10.0})
    axes, traces, no_data = ct.radar_inputs({"X": x, "Y": y}, metrics)
    assert axes == metrics and no_data == []
    assert dict(traces)["X"] == [80.0, 60.0, 40.0, 20.0]
    assert dict(traces)["Y"] == [70.0, None, 30.0, 10.0]


def test_metric_missing_for_everyone_is_not_an_axis():
    s = pd.Series({"a": 1.0, "b": 2.0, "c": 3.0, "d": np.nan})
    axes, traces, _ = ct.radar_inputs({"X": s, "Y": s}, ["a", "b", "c", "d"])
    assert axes == ["a", "b", "c"]


def test_player_with_no_percentiles_is_named_not_plotted():
    s = pd.Series({"a": 1.0, "b": 2.0, "c": 3.0})
    axes, traces, no_data = ct.radar_inputs({"X": s, "Ghost": None}, ["a", "b", "c"])
    assert [n for n, _ in traces] == ["X"] and no_data == ["Ghost"]
    # all-NaN row counts as no percentiles too
    _, _, no_data = ct.radar_inputs({"X": s, "Ghost": pd.Series({"a": np.nan})}, ["a", "b", "c"])
    assert no_data == ["Ghost"]


def test_nobody_has_percentiles_gives_no_radar():
    assert ct.radar_inputs({"X": None, "Y": None}, ["a", "b", "c"]) == ([], [], ["X", "Y"])


# --- colouring --------------------------------------------------------------------------
def test_colour_two_players():
    assert ct.colour_classes([80, 40]) == ["best", "worst"]


def test_colour_three_players_middle_stays_neutral():
    assert ct.colour_classes([80, 60, 40]) == ["best", None, "worst"]


def test_colour_ties_get_no_colour():
    assert ct.colour_classes([50, 50]) == [None, None]
    assert ct.colour_classes([50, 50, 50]) == [None, None, None]
    assert ct.colour_classes([80, 80, 40]) == [None, None, "worst"]   # tied top: no green


def test_colour_missing_is_uncoloured_and_needs_two_values():
    assert ct.colour_classes([None, 40]) == [None, None]
    assert ct.colour_classes([None, 40, 70]) == [None, "worst", "best"]
    assert ct.colour_classes([float("nan"), 40, 70]) == [None, "worst", "best"]


def test_colour_compares_displayed_integers():
    # 63.4 and 63.0 both read "63": no colour for a difference the reader cannot see
    assert ct.colour_classes([63.4, 63.0]) == [None, None]


def _row(metric, a, b):
    vals = {"X": pd.Series({metric: a[0]}), "Y": pd.Series({metric: b[0]})}
    pcts = {"X": pd.Series({metric: a[1]}), "Y": pd.Series({metric: b[1]})}
    return ct.build_rows([metric], {}, ["X", "Y"], vals, pcts)[0]


@pytest.mark.parametrize("metric", sorted(cf.LOWER_IS_BETTER))
def test_lower_is_better_best_follows_the_direction_aware_percentile(metric):
    # scorecard.metric_percentiles already inverts these (a smaller time is a HIGHER percentile),
    # so the higher percentile is green even though its raw number is the smaller one.
    row = _row(metric, (1.20, 90.0), (1.80, 10.0))
    assert [c["cls"] for c in row["cells"]] == ["best", "worst"]


def test_every_physical_time_and_agility_metric_is_inverted_upstream():
    assert set(LOWER_IS_BETTER_PHYSICAL) <= cf.LOWER_IS_BETTER


# --- the tables -------------------------------------------------------------------------
def test_table_escapes_html_in_names_labels_and_values():
    rows = [{"label": "<b>x</b>", "tier": "<i>High</i>",
             "cells": [{"text": "<script>1</script>", "pct": 50, "cls": None},
                       {"text": "—", "pct": None, "cls": None}]}]
    html = ct.table_html(["<img src=x>", "Y"], rows)
    for raw in ("<img", "<script", "<b>", "<i>"):
        assert raw not in html
    assert "&lt;img" in html and "&lt;script&gt;" in html


def test_table_cell_shows_value_and_percentile_and_colour_class():
    row = _row("pressures_p90", (12.345, 80.4), (8.0, 20.0))
    html = ct.table_html(["X", "Y"], [row])
    assert "12.35" in html and "P80" in html and "P20" in html
    assert "best" in html and "worst" in html


def test_missing_value_is_a_dash_without_colour():
    row = _row("pressures_p90", (np.nan, np.nan), (8.0, 20.0))
    assert row["cells"][0] == {"text": "—", "pct": None, "cls": None}
    assert row["cells"][1]["cls"] is None            # only one value: nothing to compare


def test_value_formats():
    assert ct.format_value("aerial_win_pct", 0.473) == "47%"
    assert ct.format_value("top5_psv99_kmh", 33.04) == "33.0 km/h"
    assert ct.format_value("time_to_sprint", 1.234) == "1.23 s"
    assert ct.format_value("agility_505_90", 2.5) == "2.50 s"
    assert ct.format_value("distance_p90", 10234.4) == "10,234 m"
    assert ct.format_value("meters_per_minute", 111.2) == "111 m/min"
    assert ct.format_value("pressures_p90", 15.333) == "15.33"
    assert ct.format_value("dribble_carry_value_p90", -0.001) == "0.00"   # never "-0.00"
    assert ct.format_value("dribble_carry_value_p90", -0.04) == "-0.04"
    assert ct.format_value("pressures_p90", None) == "—"
    assert ct.format_value("pressures_p90", float("nan")) == "—"


def test_rating_rows_carry_tier_in_weights_order():
    key = ("Centre Back", "All Metrics")
    mets = ct.rating_metrics(*key)
    assert [m for m, _ in mets] == list(WEIGHTS[key])
    assert {t for _, t in mets} == {"High", "Mid", "Low"}


def test_rows_with_no_value_for_anyone_can_be_dropped():
    vals = {"X": pd.Series({"a": 1.0}), "Y": pd.Series({"a": np.nan})}
    pcts = {"X": pd.Series({"a": 50.0}), "Y": None}
    rows = ct.build_rows(["a", "b"], {}, ["X", "Y"], vals, pcts, drop_empty=True)
    assert [r["metric"] for r in rows] == ["a"]
    assert len(ct.build_rows(["a", "b"], {}, ["X", "Y"], vals, pcts)) == 2


# --- physical ---------------------------------------------------------------------------
def test_physical_rating_rows_exclude_average_match_top_speed():
    mets = ct.physical_rating_metrics("Centre Back")
    assert "psv99_kmh" not in mets and "top5_psv99_kmh" in mets
    assert mets == [m for m in cf.PHYSICAL_METRICS["Centre Back"] if m != "psv99_kmh"]


def test_goalkeeper_has_no_physical_rows():
    assert ct.physical_rating_metrics("Goalkeeper") == []
    assert ct.other_physical_metrics("Goalkeeper") == []


def test_other_physical_excludes_rating_metrics_and_psv99():
    other = ct.other_physical_metrics("Centre Back")
    rating = set(ct.physical_rating_metrics("Centre Back"))
    assert other and not (set(other) & rating) and "psv99_kmh" not in other
    assert set(other) | rating == set(m for ms in PHYSICAL_GROUPS.values() for m in ms) | rating


def test_other_performance_excludes_rating_physical_and_unlabelled_metrics():
    cols = ["pressures_p90", "np_xg_p90", "distance_p90", "time_to_sprint", "mystery_col",
            "gk_conceded_p90", "player_id"]
    other = ct.other_performance_metrics("Centre Back", "All Metrics", cols)
    assert "pressures_p90" not in other                        # in the Centre Back rating
    assert "np_xg_p90" in other
    assert not {"distance_p90", "time_to_sprint", "mystery_col", "player_id"} & set(other)
    # lower-is-better but NOT inverted by the percentile maths: cannot be coloured honestly
    assert "gk_conceded_p90" not in other


# --- summary-table extras -----------------------------------------------------------------
def test_rating_trend_text():
    pts = [(317, 3.21, "League One"), (318, 3.48, "League One"), (319, 4.06, "League One")]
    assert ct.rating_trend_text(pts, "League One") == "3.21 → 3.48 → 4.06"
    pts = [(317, 3.21, "League Two"), (318, 3.48, "League One"), (319, 4.06, "League One")]
    assert ct.rating_trend_text(pts, "League One") == "3.21 (L2) → 3.48 → 4.06"
    assert ct.rating_trend_text([(318, None, "League One"), (319, 4.06, "League One")],
                                "League One") == "4.06"
    assert ct.rating_trend_text([], "League One") == "—"
    assert ct.rating_trend_text([(319, float("nan"), "League One")], "League One") == "—"


def test_style_text():
    row = {"strong_styles": ["Wide"], "leans_styles": ["1v1"], "style_label": "Wide"}
    assert ct.style_text(row) == "Wide · 1v1 (leans)"
    assert ct.style_text({"strong_styles": [], "leans_styles": [], "style_label": "No standout style"}) \
        == "No standout style"
    assert ct.style_text({"strong_styles": [], "leans_styles": [], "style_label": None}) == "—"
    assert ct.style_text(None) == "—"


def test_scout_text():
    assert ct.scout_text(["Sign", "Monitor", "Sign"]) == "2 Sign · 1 Monitor"
    assert ct.scout_text([]) == "—" and ct.scout_text(None) == "—"



def test_extras_cells_are_escaped_in_the_summary_table():
    from lofc.dashboard.tabs.compare import comparison_html
    html = comparison_html([{"Player": "A", "Playing style": "<b>X</b>", "Scout verdicts": "<i>1</i>"},
                            {"Player": "B", "Playing style": "—", "Scout verdicts": "—"}])
    assert "<b>X" not in html and "&lt;b&gt;X" in html and "<i>1" not in html


def test_summary_rows_order():
    from lofc.dashboard.tabs.compare import comparison_html
    keys = ["Overall", "Performance", "Physical", "Rating trend", "Playing style",
            "Scout verdicts"]
    html = comparison_html([{"Player": "A", **{k: "1" for k in keys}},
                            {"Player": "B", **{k: "2" for k in keys}}])
    pos = [html.index(f">{k}<") for k in keys]
    assert pos == sorted(pos)





def test_club_contract_and_loan_rows_are_gone():
    """Owner, 2026-11-02: removed from Compare."""
    from lofc.dashboard.tabs.compare import comparison_html
    html = comparison_html([{"Player": "A", "Club now": "X", "Contract to": "Y", "Loan": "Z"},
                            {"Player": "B"}])
    assert ">Club now<" not in html and ">Contract to<" not in html and ">Loan<" not in html


# --- packing zones (side by side, reuses the player card's pitch) ----------------------------
def _zones(player_id=1, pct=80.0, families=("touches",)):
    rows = [{"player_id": player_id, "position_group": "Centre Back", "rankable": True,
             "metric": f"zone.{f}.{z}", "value_p90": 1.5 + i, "total": 10.0 + i, "pct": pct}
            for f in families for i, z in enumerate(ct.ZONES)]
    return pd.DataFrame(rows)


def test_zone_selector_is_exactly_the_cards_twelve_measures():
    from lofc.ingest.impect_detail import FAMILY_LABELS, MAP_FAMILIES
    assert ct.ZONE_FAMILIES == list(MAP_FAMILIES) and len(ct.ZONE_FAMILIES) == 12
    assert ct.ZONE_FAMILY_LABELS == FAMILY_LABELS


def test_zone_cells_are_the_cards_numbers_per_90():
    from lofc.dashboard import detail_section as ds
    cells = ct.zone_cells(_zones(), "touches")
    assert set(cells) == set(ds.ZONES)
    assert cells["IB"] == (ds.fmt_value(1.5 + list(ds.ZONES).index("IB"), "Per 90", "touches"), 80.0)


def test_zone_pitch_html_is_the_cards_frame_without_its_legend():
    from lofc.dashboard import detail_section as ds
    cells = ct.zone_cells(_zones(), "touches")
    page = ct.zone_pitch_html(cells, False)
    assert ds.pitch_svg(cells) in page and page.count('data-zone="') == 11
    assert ds.legend_html(False) not in page
    assert ct.zone_legend_html(False) == ds.legend_html(False)


def test_zone_pitch_html_escapes_text():
    page = ct.zone_pitch_html({"IB": ('<b>"x"</b>', 50.0)}, False)
    assert "<b>" not in page


def test_zone_cells_none_when_player_has_no_zone_data():
    assert ct.zone_cells(_zones().iloc[0:0], "touches") is None
    # a measure the player lacks while he has others
    assert ct.zone_cells(_zones(), "ball_wins") is None


def test_zone_panels_one_missing_player_does_not_break_others(monkeypatch):
    pool = pd.concat([_zones(1), _zones(2).iloc[0:0]])
    monkeypatch.setattr(ct, "_zone_pool", lambda cid, sid: pool)
    recs = [pd.Series({"player_id": i, "competition_id": 5, "season_id": 9, "player_name": f"P{i}"})
            for i in (1, 2)]
    panels = ct.zone_panels(recs, "touches")
    assert panels[0] is not None and panels[1] is None


def test_the_pitch_scales_to_its_frame_so_it_is_never_clipped():
    """Manager visual check, 2026-11-02: the bottom of each pitch (goalkeeper zone, pitch
    edge) was cut off -- the frame height was fixed and the SVG scaled with the column width.
    The pitch must fit inside the frame at any width."""
    from lofc.dashboard import compare_tables as ct
    cells = {z: ("1.0", 50.0) for z in ["CB", "FBL", "FBR", "DM", "CM", "WL", "WR", "AM",
                                       "IBWL", "IB", "IBWR"]}
    for n, h in ct.ZONE_FRAME_HEIGHT.items():
        out = ct.zone_pitch_html(cells, False, frame_height=h)
        assert f"max-height:{h - 16}px" in out.replace(" ", "")
