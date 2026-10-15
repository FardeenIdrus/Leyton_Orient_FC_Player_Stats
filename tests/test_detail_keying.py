"""Detail rows are keyed to OUR player ids exactly as the neutral layer keys the same player.

A provider id that matched none of our players carries no row (it has no profile to show
on). Two provider ids resolving to one of our players keep the one with more minutes --
the rule build_spine and load_skillcorner already apply -- so a metric can never be
written twice for one player-season.
"""

import pandas as pd

from lofc.model.build_neutral import key_detail


def test_rows_take_our_player_id_and_the_league_season():
    long = pd.DataFrame({"pid": [5, 5, 6], "metric": ["a", "b", "a"],
                         "value_p90": [1.0, 2.0, 3.0], "total": [None, None, None]})
    ids = pd.DataFrame({"pid": [5, 6], "player_id": [100, 200], "minutes": [900, 800]})
    out = key_detail(long, ids, "pid", competition_id=4, season_id=318)
    assert sorted(out["player_id"]) == [100, 100, 200]
    assert set(out["competition_id"]) == {4} and set(out["season_id"]) == {318}
    assert list(out.columns) == ["player_id", "competition_id", "season_id", "metric",
                                 "value_p90", "total"]


def test_unmatched_provider_ids_are_dropped():
    long = pd.DataFrame({"pid": [7], "metric": ["a"], "value_p90": [1.0], "total": [None]})
    ids = pd.DataFrame({"pid": [5], "player_id": [100], "minutes": [900]})
    assert key_detail(long, ids, "pid", 4, 318).empty


def test_two_provider_ids_for_one_player_keep_the_higher_minutes():
    long = pd.DataFrame({"pid": [5, 6], "metric": ["a", "a"], "value_p90": [1.0, 9.0],
                         "total": [None, None]})
    ids = pd.DataFrame({"pid": [5, 6], "player_id": [100, 100], "minutes": [900, 50]})
    out = key_detail(long, ids, "pid", 4, 318)
    assert out["value_p90"].tolist() == [1.0]
