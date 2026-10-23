"""The Style lab: a LOCAL-ONLY page to test and tune the playing-style rules before they go
live (owner, 2026-10-23). Thresholds move with sliders; the checks that decided every signal
(quality correlation, overlap) are shown live so a tweak cannot quietly break them.
"""

import pandas as pd
import pytest

from lofc.config import Settings
from lofc.dashboard import style_lab
from lofc.model import styles as st


def test_the_lab_is_off_unless_switched_on():
    """Off by default, so the server never shows it unless someone sets SHOW_STYLE_LAB."""
    assert Settings.model_fields["show_style_lab"].default is False


def test_every_signal_has_a_plain_english_name():
    assert set(st.SIGNAL_LABELS) == set(st.SIGNALS)
    assert all(label and "_" not in label for label in st.SIGNAL_LABELS.values())


def _frame(n=12):
    """Twelve rated wingers in one league, with a rating and every winger signal."""
    sigs = {s for g in st.STYLES["Winger"].values() for v in g.values() for s in v}
    rows = []
    for i in range(n):
        row = {"player_id": i, "competition_id": 4, "season_id": 318,
               "position_group": "Winger", "rankable": True, "player_name": f"P{i}",
               "team_name": "T", "objective_composite": 2 + i / 10, "performance_band": 2 + i / 10}
        row.update({s: float((i * 7 + hash(s) % 5) % n) for s in sigs})
        rows.append(row)
    return pd.DataFrame(rows)


def test_the_lab_labels_every_rated_player_of_the_chosen_group():
    lab = style_lab.build_lab(_frame(), "Winger", strong=70, floor=50)
    assert len(lab) == 12
    assert {"Player", "Club", "Rating", "Style", "fit.Wide"} <= set(lab.columns)


def test_moving_the_strong_threshold_changes_the_labels_and_nothing_else():
    tight = style_lab.build_lab(_frame(), "Winger", strong=90, floor=50)
    loose = style_lab.build_lab(_frame(), "Winger", strong=55, floor=50)
    assert (loose["tier"] == "Strong").sum() > (tight["tier"] == "Strong").sum()
    assert tight["Rating"].tolist() == loose["Rating"].tolist()


def test_the_summary_counts_add_up_to_every_player():
    lab = style_lab.build_lab(_frame(), "Winger", strong=70, floor=50)
    s = style_lab.summary(lab)
    assert s["Players"] == 12
    assert s["Strong"] + s["Leans"] + s["No standout style"] + s["Not enough minutes"] == 12


def test_the_checks_report_each_signals_correlation_with_quality_and_flag_quality_signals():
    checks = style_lab.signal_checks(_frame(), "Winger")
    row = checks.set_index("Signal").loc[st.SIGNAL_LABELS["dribbles_per_touch"]]
    assert row["Quality metric"] == "yes"
    assert -1 <= row["Correlation with rating"] <= 1
    assert set(checks["Style"]) == {"In behind", "Pocket", "Wide", "1v1", "Creator"}


def test_central_midfield_lab_takes_defensive_and_central_midfielders():
    f = _frame()
    f["position_group"] = ["Defensive Mid"] * 6 + ["Central Mid"] * 6
    for s in {s for v in st.STYLES["Central midfield"]["Style"].values() for s in v}:
        f[s] = range(12)
    assert len(style_lab.build_lab(f, "Central midfield", strong=70, floor=50)) == 12
