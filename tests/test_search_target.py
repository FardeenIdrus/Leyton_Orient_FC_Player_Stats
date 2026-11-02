"""A searched player must open whatever the sidebar says (dashboard/search_target.py).

Pure pandas / dict logic: no Streamlit runtime, no database.
"""

import pandas as pd

from lofc.dashboard.search_target import (
    NOT_IN_LIST_CAPTION, choose_detail_row, clear_all_table_selections, clear_table_selection, resolve_search_target,
    search_caption)

KEY = (303856, 2, 319)   # Dom Ballard-style: Centre Forward, rated


def _cands():
    return pd.DataFrame({
        "player_id": [303856, 7, 8], "competition_id": [2, 2, 2], "season_id": [319, 319, 319],
        "player_name": ["Dom Ballard", "Unrated Una", "Mid Mick"],
        "position_group": ["Centre Forward", "Centre Forward", "Attacking Mid"],
        "minutes": [800, 300, 900]})


def _cards(n_peers=12):
    rows = [(303856, 2, 319, "Centre Forward", 3.6, "All Metrics")]
    rows += [(1000 + i, 2, 319, "Centre Forward", 3.0, "All Metrics") for i in range(n_peers - 1)]
    rows += [(303856, 2, 319, "Centre Forward", 2.0, "Other Lens")]   # must be ignored
    return pd.DataFrame(rows, columns=["player_id", "competition_id", "season_id",
                                       "position_group", "objective_composite", "archetype"])


def test_finds_player_of_another_position_than_sidebar():
    row, reason = resolve_search_target(_cands(), _cards(), KEY)
    assert reason == "ok"
    assert row["player_name"] == "Dom Ballard"
    assert row["objective_composite"] == 3.6          # the All Metrics row, not the lens row
    assert row["peer_count"] == 12


def test_unrated_player_opens_without_scores():
    row, reason = resolve_search_target(_cands(), _cards(), (7, 2, 319))
    assert reason == "not_rated"
    assert row["player_name"] == "Unrated Una"
    assert pd.isna(row["objective_composite"])


def test_thin_pool_is_not_presented_as_a_ranking():
    _, reason = resolve_search_target(_cands(), _cards(n_peers=3), KEY)
    assert reason == "not_rated"


def test_unknown_player_not_found():
    row, reason = resolve_search_target(_cands(), _cards(), (999, 2, 319))
    assert row is None and reason == "not_found"


def test_captions():
    assert search_caption("ok", in_view=True) is None
    assert search_caption("ok", in_view=False) == NOT_IN_LIST_CAPTION
    assert search_caption("not_rated", in_view=False, minutes=300).startswith("Not rated")
    assert "450" in search_caption("not_rated", in_view=True, minutes=300)


def test_pick_clears_table_selection():
    state = {"players_x__nonce": 2}
    clear_table_selection(state, "players_x")
    assert state["players_x__nonce"] == 3
    clear_table_selection(state, "other")
    assert state["other__nonce"] == 1


def test_searched_player_beats_row_zero_and_table_click_beats_search():
    view = pd.DataFrame({"player_id": [1, 2], "player_name": ["First", "Second"]})
    searched = pd.Series({"player_id": 303856, "player_name": "Dom Ballard"})
    # nothing clicked -> the searched player, not row 0
    assert choose_detail_row([], view, searched)["player_name"] == "Dom Ballard"
    # a click on row 1 after the search wins
    assert choose_detail_row([1], view, searched)["player_name"] == "Second"
    # stale index beyond the view falls back to the search
    assert choose_detail_row([9], view, searched)["player_name"] == "Dom Ballard"
    assert choose_detail_row([], view, None) is None


def test_pick_clears_selection_of_every_table_instance_including_other_positions():
    # The pick switches Position, so the table that renders next has a different base key.
    state = {"players_Winger_All Metrics_False_False__0": object(),
             "players_Centre Forward_All Metrics_False_False__3": object(),
             "players_Centre Forward_All Metrics_False_False__nonce": 3,
             "unrelated__1": 1}
    clear_all_table_selections(state)
    assert state["players_Winger_All Metrics_False_False__nonce"] == 1
    assert state["players_Centre Forward_All Metrics_False_False__nonce"] == 4
    assert "unrelated__nonce" not in state
