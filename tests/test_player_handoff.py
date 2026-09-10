"""Carrying a player from the Squads view to his profile.

The carry is the player_id, never the search LABEL. The label is a formatted string
("Name — Club · Position · League") built in search.build_search_index; reconstructing it
at a call site would break silently the moment the format changed, and a label that fails
to match resolves to nobody -- or to a different row. That exact class of bug already
opened the wrong player's report once.
"""

import pandas as pd

from lofc.dashboard.session import (peek_open_player, resolve_open_player,
                                    take_open_player)


def _index():
    return pd.DataFrame([
        {"player_id": 1, "competition_id": 4, "season_id": 318, "label": "A — Orient · Winger · League One",
         "position_group": "Winger", "league": "League One"},
        {"player_id": 2, "competition_id": 5, "season_id": 318, "label": "B — Walsall · Full Back · League Two",
         "position_group": "Full Back", "league": "League Two"},
        {"player_id": 2, "competition_id": 903, "season_id": 318, "label": "B — Villa U21 · Full Back · Premier League 2",
         "position_group": "Full Back", "league": "Premier League 2"},
    ])


def test_an_exact_match_resolves_to_that_row():
    got = resolve_open_player(_index(), (1, 4, 318))
    assert got == ("A — Orient · Winger · League One", "Winger", "League One")


def test_the_position_and_league_come_back_so_the_sidebar_can_be_switched():
    """Opening a Winger while the sidebar shows Centre Backs would show an empty page."""
    _, position, league = resolve_open_player(_index(), (1, 4, 318))
    assert position == "Winger" and league == "League One"


def test_a_player_carried_from_a_league_he_is_not_indexed_in_still_resolves():
    """The squad view is CURRENT-season; the ranked index is last season. A loanee may be
    at a different club now than the one he is indexed under."""
    got = resolve_open_player(_index(), (2, 999, 318))
    assert got is not None and got[1] == "Full Back"


def test_an_unknown_player_resolves_to_nothing_rather_than_a_guess():
    """293 players appear only in the current season and have no ranked row at all.
    Opening somebody else would be far worse than opening nobody."""
    assert resolve_open_player(_index(), (12345, 4, 318)) is None


def test_an_empty_index_resolves_to_nothing():
    assert resolve_open_player(pd.DataFrame(), (1, 4, 318)) is None


def test_no_carry_resolves_to_nothing():
    assert resolve_open_player(_index(), None) is None


def test_the_carry_is_consumed_so_it_does_not_reopen_on_the_next_click():
    state = {"_open_player": (1, 4, 318)}
    assert peek_open_player(state) == (1, 4, 318)
    assert take_open_player(state) == (1, 4, 318)
    assert take_open_player(state) is None
