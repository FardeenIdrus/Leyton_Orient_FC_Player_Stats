"""Squads page: the Transfermarkt as-of line and the player-name search."""
import pandas as pd

from lofc.dashboard.tabs.squads import filter_by_name, transfermarkt_asof


def test_asof_different_dates():
    assert transfermarkt_asof("07 Sep 2026", "18 Sep 2026") == (
        "Transfermarkt data as of 7 Sep 2026 (squads & contracts) · 18 Sep 2026 (loans).")


def test_asof_same_date_shows_one():
    assert transfermarkt_asof("07 Sep 2026", "07 Sep 2026") == "Transfermarkt data as of 7 Sep 2026."


def test_asof_missing_parts_omitted():
    assert transfermarkt_asof("07 Sep 2026", None) == (
        "Transfermarkt data as of 7 Sep 2026 (squads & contracts).")
    assert transfermarkt_asof(None, "18 Sep 2026") == (
        "Transfermarkt data as of 18 Sep 2026 (loans).")
    assert transfermarkt_asof(None, None) is None


def _frame():
    return pd.DataFrame({"Player": ["Nathaniel Méndez-Laing", "Jack O'Connor", None],
                         "Club": ["A", "B", "A"]})


def test_name_filter_accent_case_punctuation():
    assert filter_by_name(_frame(), "mendez")["Player"].tolist() == ["Nathaniel Méndez-Laing"]
    assert filter_by_name(_frame(), "OCONNOR")["Player"].tolist() == ["Jack O'Connor"]


def test_name_filter_empty_is_all_and_combines():
    assert len(filter_by_name(_frame(), "")) == 3
    assert len(filter_by_name(_frame(), "  ")) == 3
    club_a = _frame()[lambda d: d["Club"] == "A"]
    assert filter_by_name(club_a, "connor").empty


def test_controls_row_is_bottom_aligned_and_search_label_is_visible():
    """The search box once had a collapsed label and sat higher than its neighbours."""
    import inspect
    from lofc.dashboard.tabs import squads
    src = inspect.getsource(squads.render)
    assert 'vertical_alignment="bottom"' in src
    assert 'text_input("Player", placeholder="Search a player…")' in src
    assert "collapsed" not in src
