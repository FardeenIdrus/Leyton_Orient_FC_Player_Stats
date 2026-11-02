"""Pixel widths for the ranked list's text columns: content decides, so nothing is cut."""
import numpy as np
import pandas as pd

from lofc.dashboard.tabs.players import column_widths


def test_longest_value_drives_width():
    v = pd.DataFrame({"Scouts": ["1 Sign", "2 Sign · 1 Monitor · 1 Watch", ""]})
    w = column_widths(v, ["Scouts"])["Scouts"]
    assert w >= int(len("2 Sign · 1 Monitor · 1 Watch") * 7.5)
    short = column_widths(pd.DataFrame({"Scouts": ["1 Sign"]}), ["Scouts"])["Scouts"]
    assert w > short


def test_caps_respected():
    v = pd.DataFrame({"Club": ["x" * 400], "League": [""]})
    w = column_widths(v, ["Club", "League"])
    assert w["Club"] <= 360
    assert w["League"] >= 60


def test_numeric_columns_small():
    v = pd.DataFrame({"Composite": [3.2], "Mins": [900], "Player": ["A B"]})
    w = column_widths(v, ["Composite", "Mins", "Player"])
    assert w["Composite"] == "small" and w["Mins"] == "small"
    assert isinstance(w["Player"], int)


def test_empty_nan_and_missing_safe():
    v = pd.DataFrame({"Club": [None, np.nan, pd.NA], "Style": [[], None, ["Ball Winner"]]})
    w = column_widths(v, ["Club", "Style", "Absent"])
    assert w["Club"] >= 60 and w["Style"] >= len("Ball Winner") * 7.5
    assert "Absent" not in w
    empty = pd.DataFrame({"Club": pd.Series([], dtype=object)})
    assert column_widths(empty, ["Club"])["Club"] >= 60


def test_a_missing_rating_shows_a_dash_not_none():
    """Manager visual check, 2026-11-02: a player with no physical data showed the word
    "None" in the Physical column (the colour Styler prints missing values as None)."""
    import pandas as pd
    from lofc.dashboard.tabs.players import styled_ratings
    table = pd.DataFrame({"Player": ["A", "B"], "Composite": [3.52, 3.4],
                          "Physical": [4.48, None]})
    html = styled_ratings(table, ["Composite", "Physical"]).to_html()
    assert "None" not in html and "nan" not in html.lower().replace("nan-", "")
    assert "—" in html and "4.48" in html and "3.52" in html
