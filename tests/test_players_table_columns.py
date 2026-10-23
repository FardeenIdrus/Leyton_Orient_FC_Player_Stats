"""The Players table carries only what the list is for; the player card carries the rest.

Removed at the Head of Recruitment's request (2026-10-02):
  * Measured % -- read as confusing. A rating with no physical data already shows a blank
    Physical cell beside it.
  * Peers, Contract, Months left -- the player card states all three ("3rd of 92 in this
    league", the contract chip with months remaining).
  * Player type, and its filter -- the clustering behind it is weak (register P4) and is to
    be rebuilt from the recruitment team's own profile definitions. Hidden until then.
"""

import inspect

import pytest

from lofc.dashboard.tabs import players
from lofc.dashboard.tabs.players import players_table_columns

REMOVED = ["Measured", "Peers", "Player type", "Contract", "Months left"]


@pytest.mark.parametrize("lens", [False, True])
@pytest.mark.parametrize("show_money", [False, True])
@pytest.mark.parametrize("loan_column", [False, True])
def test_removed_columns_never_appear(lens, show_money, loan_column):
    cols = players_table_columns(lens=lens, show_money=show_money, loan_column=loan_column)
    for gone in REMOVED:
        assert gone not in cols


def test_default_columns_in_order():
    """2026-10-12: 'Mins' for Minutes; League stays its own column (owner). 2026-10-23:
    Style after League (approved design)."""
    assert players_table_columns(lens=False, show_money=False, loan_column=False) == [
        "#", "Player", "Club", "League", "Style", "Age", "Mins", "Composite",
        "Performance", "Physical", "Top speed", "Scouts"]


def test_assessed_column_is_hidden_for_now():
    """Owner, 2026-10-12: assessments are not in use; the column is hidden, not deleted."""
    for money in (False, True):
        assert "Assessed" not in players_table_columns(lens=False, show_money=money,
                                                       loan_column=False)


def test_rating_colours_follow_the_club_thresholds():
    """Veto < 2.0, minimum 3.0 (league median), elite 4.0 (70th percentile)."""
    from lofc.dashboard.tabs.players import band_colour
    assert band_colour(1.9) == band_colour(1.0) != band_colour(2.0)
    assert band_colour(2.9) != band_colour(3.0) != band_colour(4.0)
    assert band_colour(None) == ""


def test_archetype_lens_adds_all_round_beside_composite():
    cols = players_table_columns(lens=True, show_money=False, loan_column=False)
    assert cols[cols.index("Composite") + 1] == "All-round"


def test_loan_column_follows_club():
    cols = players_table_columns(lens=False, show_money=False, loan_column=True)
    assert cols[cols.index("Club") + 1] == "On loan at"


def test_money_columns_only_with_affordability_on():
    money = ["Market value", "Est. wage", "Below fair value", "Fee in budget", "Wages in budget"]
    assert not set(money) & set(players_table_columns(lens=False, show_money=False,
                                                      loan_column=False))
    assert players_table_columns(lens=False, show_money=True, loan_column=False)[-5:] == money


def test_player_type_filter_is_gone():
    source = inspect.getsource(players)
    assert '"Player type"' not in source
    assert "Group by type" not in source


def test_list_caption_drops_the_money_sentence():
    assert "Money is off" not in inspect.getsource(players)


def test_the_card_uses_the_new_styles_not_the_retired_clusters():
    """2026-10-23: the k-means "Player type" clusters stay hidden (register P4); the card
    shows the rule-based styles from model/styles.py instead."""
    source = inspect.getsource(players._render_profile_body)
    assert "cluster_label" not in source
    assert "style_card.fit_html" in source


def test_player_types_page_is_not_offered():
    from lofc.dashboard import app
    source = inspect.getsource(app.main)
    assert 'st.Page(_player_types_page' not in source
