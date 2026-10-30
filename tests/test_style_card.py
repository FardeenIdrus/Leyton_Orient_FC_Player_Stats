"""The player card's Style line and Style fit section (Step 4, approved design 2026-10-23).

Solid pill = Strong, dashed outline = Leans. Style fit: one bar per style of his position,
grouped Where / What for wingers, markers at 50 (Leans) and 70 (Strong), the signals behind
each bar written underneath.
"""

from lofc.dashboard import style_card
from lofc.model import styles as st


def _winger():
    return {"position_group": "Winger", "style_label": "Wide · 1v1",
            "strong_styles": ["Wide", "1v1"], "leans_styles": [],
            "fit.In behind": 52.3, "fit.Pocket": 9.8, "fit.Wide": 92.4,
            "fit.1v1": 90.2, "fit.Creator": 55.3, "fit.Goalscorer": 40.0}


def test_strong_pills_are_solid_and_leans_pills_are_outlined():
    html = style_card.pills_html(["Wide"], ["1v1"])
    assert html.count("style-pill strong") == 1 and ">Wide<" in html
    assert html.count("style-pill leans") == 1 and ">1v1<" in html


def test_a_player_with_no_standout_style_says_so():
    assert st.NO_STYLE in style_card.pills_html([], [], label=st.NO_STYLE)


def test_the_fit_section_has_a_bar_for_every_style_of_his_position():
    html = style_card.fit_html(_winger(), "League One", "2025/26")
    for style in st.style_options("Winger"):
        assert f">{style}<" in html
    assert "width:92%" in html and "width:10%" in html


def test_the_fit_section_groups_a_winger_by_where_and_what():
    html = style_card.fit_html(_winger(), "League One", "2025/26")
    assert "Where he plays" in html and "What he does" in html


def test_each_bar_names_its_signals_in_plain_english():
    html = style_card.fit_html(_winger(), "League One", "2025/26")
    assert st.SIGNAL_LABELS["dribbles_per_touch"] in html


def test_the_section_states_what_he_is_compared_against():
    html = style_card.fit_html(_winger(), "League One", "2025/26")
    assert "League One" in html and "2025/26" in html


def test_a_player_without_fits_gets_no_section():
    assert style_card.fit_html({"position_group": "Winger"}, "League One", "2025/26") == ""
    assert style_card.fit_html({"position_group": "Goalkeeper"}, "League One", "2025/26") == ""


def test_text_is_escaped():
    html = style_card.fit_html(_winger(), "<b>League</b>", "2025/26")
    assert "<b>League</b>" not in html


def test_the_peer_group_is_named_properly():
    row = {**_winger(), "position_group": "Defensive Mid", "fit.Destroyer": 80.0,
           "fit.Playmaker": 40.0, "fit.Box-to-box": 55.0}
    assert "central midfielders" in style_card.fit_html(row, "League One", "2025/26")
