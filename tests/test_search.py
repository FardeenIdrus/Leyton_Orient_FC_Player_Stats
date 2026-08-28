"""Tests for the global player search index (dashboard/search.py).

No Streamlit runtime, no database: pure pandas shaping, matching the project convention of
testing data decisions in isolation from the render layer.
"""

import pandas as pd

from lofc.dashboard.search import build_search_index, filter_labels, fold, search_options


def _candidates(rows):
    return pd.DataFrame(rows, columns=["player_id", "competition_id", "season_id",
                                       "player_name", "team_name", "position_group", "league"])


def test_build_search_index_spans_every_position_and_league():
    """The whole point: a striker and a goalkeeper in different leagues both appear in one
    index, so a search never depends on which position/league is currently selected."""
    idx = build_search_index(_candidates([
        (1, 4, 318, "Alan Forward", "Town FC", "Centre Forward", "League One"),
        (2, 901, 318, "Gary Keeper", "Rangers", "Goalkeeper", "Scottish Premiership"),
    ]))
    assert set(idx["player_name"]) == {"Alan Forward", "Gary Keeper"}
    assert set(idx["position_group"]) == {"Centre Forward", "Goalkeeper"}


def test_build_search_index_dedupes_on_player_competition_season():
    idx = build_search_index(_candidates([
        (1, 4, 318, "Alan Forward", "Town FC", "Centre Forward", "League One"),
        (1, 4, 318, "Alan Forward", "Town FC", "Centre Forward", "League One"),  # exact dup
    ]))
    assert len(idx) == 1


def test_build_search_index_keeps_a_mid_season_movers_two_rows():
    """A player who changed club (and league) mid-season has one row per competition --
    that is two genuinely different rows, not a duplicate to collapse."""
    idx = build_search_index(_candidates([
        (1, 4, 318, "Alan Forward", "Town FC", "Centre Forward", "League One"),
        (1, 5, 318, "Alan Forward", "City FC", "Centre Forward", "League Two"),
    ]))
    assert len(idx) == 2


def test_build_search_index_drops_rows_with_no_name_or_position():
    idx = build_search_index(_candidates([
        (1, 4, 318, None, "Town FC", "Centre Forward", "League One"),
        (2, 4, 318, "Gary Keeper", "Town FC", None, "League One"),
        (3, 4, 318, "Alan Forward", "Town FC", "Centre Forward", "League One"),
    ]))
    assert list(idx["player_id"]) == [3]


def test_build_search_index_label_disambiguates_namesakes():
    """Two different players sharing a name are distinguishable by club, position and
    league in the label -- a bare name lookup would silently conflate them."""
    idx = build_search_index(_candidates([
        (1, 4, 318, "Sam Smith", "Town FC", "Centre Forward", "League One"),
        (2, 5, 318, "Sam Smith", "City FC", "Winger", "League Two"),
    ]))
    labels = set(idx["label"])
    assert len(labels) == 2
    assert any("Centre Forward" in l and "Town FC" in l for l in labels)
    assert any("Winger" in l and "City FC" in l for l in labels)


def test_build_search_index_missing_club_and_league_fall_back_to_placeholders():
    idx = build_search_index(_candidates([
        (1, 4, 318, "Alan Forward", None, "Centre Forward", None),
    ]))
    assert "Unknown club" in idx.loc[0, "label"]


def test_search_options_maps_label_back_to_row_position():
    idx = build_search_index(_candidates([
        (1, 4, 318, "Alan Forward", "Town FC", "Centre Forward", "League One"),
        (2, 5, 318, "Beth Winger", "City FC", "Winger", "League Two"),
    ]))
    labels, by_label = search_options(idx)
    assert len(labels) == 2
    for label in labels:
        row = idx.iloc[by_label[label]]
        assert row["label"] == label


# --- fold / filter_labels: accent-, case- and punctuation-insensitive search -------------
# I4 (audit-dashboard.md): typing the ordinary unaccented spelling of a player's name (or
# omitting punctuation nobody types) must find him, not silently miss or -- worse -- surface
# an unrelated player. The widget's own in-browser type-ahead filter matches only the literal
# displayed text, so this narrowing happens in Python before it ever reaches that widget.

def test_fold_strips_diacritics():
    assert fold("Méndez") == fold("Mendez")


def test_fold_is_case_insensitive():
    assert fold("MENDEZ") == fold("mendez") == fold("Mendez")


def test_fold_drops_hyphens_and_apostrophes():
    assert fold("O'Connor") == fold("OConnor") == fold("O-Connor")


def test_fold_drops_internal_whitespace_too():
    """So a hyphenated surname folds the same whether the query has a hyphen, a space, or
    nothing at all: "Mendez Laing", "Mendez-Laing" and "MendezLaing" must all match
    "Méndez-Laing"."""
    assert fold("Mendez Laing") == fold("Mendez-Laing") == fold("MendezLaing")


def test_fold_none_and_empty_are_safe():
    assert fold(None) == ""
    assert fold("") == ""


def test_filter_labels_accented_query_finds_unaccented_label_and_vice_versa():
    labels = ["Nathaniel Méndez-Laing — Cardiff City  ·  Winger  ·  Championship",
              "Emmanuel Fernandez — Glasgow Rangers  ·  Centre Back  ·  Scottish Premiership"]
    for query in ("Mendez", "mendez", "MENDEZ", "Méndez"):
        matches = filter_labels(labels, query)
        assert matches == [labels[0]], f"query {query!r} should find only the accented name"


def test_filter_labels_hyphenated_name_matches_space_or_no_separator():
    labels = ["Nathaniel Méndez-Laing — Cardiff City  ·  Winger  ·  Championship"]
    assert filter_labels(labels, "Mendez Laing") == labels
    assert filter_labels(labels, "MendezLaing") == labels


def test_filter_labels_apostrophe_insensitive():
    labels = ["Seán O'Connor — Town FC  ·  Centre Back  ·  League One"]
    assert filter_labels(labels, "OConnor") == labels
    assert filter_labels(labels, "O'Connor") == labels


def test_filter_labels_blank_query_returns_everything_unfiltered():
    labels = ["Alan Forward — Town FC  ·  Centre Forward  ·  League One",
              "Beth Winger — City FC  ·  Winger  ·  League Two"]
    assert filter_labels(labels, "") == labels
    assert filter_labels(labels, "   ") == labels


def test_filter_labels_no_match_returns_empty_not_an_unrelated_guess():
    """The defect this replaces: an in-browser fuzzy fallback that, finding no real match,
    surfaced an unrelated player instead of nothing. A real substring miss must return
    nothing."""
    labels = ["Emmanuel Fernandez — Glasgow Rangers  ·  Centre Back  ·  Scottish Premiership"]
    assert filter_labels(labels, "Mendez") == []
