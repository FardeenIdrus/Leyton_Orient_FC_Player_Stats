"""Reference page "How playing styles work" (approved design, 2026-10-23).

Built FROM model/styles.py -- the styles, their signals, the thresholds -- so it can never
disagree with the labels, exactly as "What goes into each rating" is built from the scoring.
The worked example uses real players, picked from the data, so it never goes stale.
"""

import pandas as pd

from lofc.dashboard import style_reference as ref
from lofc.model import styles as st


def test_every_style_has_a_plain_description():
    for groups in st.STYLES.values():
        for styles in groups.values():
            for style in styles:
                assert ref.STYLE_DESCRIPTIONS.get(style), style


def test_the_table_lists_every_style_of_the_group_with_its_signals():
    table = ref.style_table("Winger")
    assert table["Style"].tolist() == ["In behind", "Pocket", "Wide", "1v1", "Creator",
                                       "Goalscorer"]
    assert table["Label"].tolist()[:3] == ["Where he plays"] * 3
    wide = table.set_index("Style").loc["Wide", "Signals"]
    assert st.SIGNAL_LABELS["rec_wide_share"] in wide and st.SIGNAL_LABELS["touch_wide_share"] in wide


def test_quality_signals_are_flagged_in_the_table():
    table = ref.style_table("Winger").set_index("Style")
    assert "⚑" in table.loc["1v1", "Signals"]
    assert "⚑" not in table.loc["Wide", "Signals"]
    creator = table.loc["Creator", "Signals"]
    assert st.SIGNAL_LABELS["xa_p90"] + " ⚑" in creator
    assert st.SIGNAL_LABELS["cross_attempts_per_touch"] + " ⚑" not in creator


def test_the_new_dribbler_style_is_on_the_page():
    assert "Dribbler" in ref.style_table("Attacking Mid")["Style"].tolist()


def test_a_single_group_position_shows_no_label_column_values():
    assert set(ref.style_table("Centre Back")["Label"]) == {""}


def test_the_rules_text_follows_the_thresholds():
    rules = ref.label_rules()
    assert f"{st.STRONG:.0f}+" in rules["Strong"] and f"below {st.FLOOR:.0f}" in rules["Strong"]
    assert st.NO_STYLE in rules


def _labels():
    return pd.DataFrame({
        "player_id": [1, 2, 3], "competition_id": 4, "season_id": 318,
        "position_group": "Winger", "player_name": ["A", "B", "C"], "team_name": ["X", "Y", "Z"],
        "fit.Wide": [92.4, 62.9, 30.0],
        "strong_styles": [["Wide"], [], []], "leans_styles": [[], ["Wide"], []]})


def test_the_example_takes_the_clearest_strong_and_a_leans_player():
    ex = ref.example_players(_labels(), "Wide")
    assert ex["player_name"].tolist() == ["A", "B"]
    assert ex["tier"].tolist() == ["Strong", "Leans"]


def test_no_example_when_nobody_qualifies():
    assert ref.example_players(_labels().iloc[[2]], "Wide").empty


def test_the_example_style_has_two_signals_so_the_average_shows():
    """Approved design: wingers show "Wide"; otherwise the first style with two signals."""
    assert ref.example_style("Winger") == "Wide"
    for group in st.STYLES:
        style = ref.example_style(group)
        sigs = {s: v for g in st.STYLES[group].values() for s, v in g.items()}[style]
        assert len(sigs) >= 2
