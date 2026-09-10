"""A percentile is only as meaningful as the pool it ranks within.

On 2026-09-07, five matches into 2026/27, 13 of 36 position-league pools held fewer than
five rankable players and 34 players sat in one. A composite built on three peers is not a
weak signal -- it is arbitrary: whoever happens to have played decides the order.
"""

import pandas as pd

from lofc.model.scorecard import (MIN_PEERS_FOR_RANKING, peer_pool_sizes, pool_is_thin)


def test_a_full_season_pool_is_not_thin():
    assert not pool_is_thin(105)


def test_a_three_player_pool_is_thin():
    assert pool_is_thin(3)


def test_the_boundary_is_inclusive():
    assert not pool_is_thin(MIN_PEERS_FOR_RANKING)
    assert pool_is_thin(MIN_PEERS_FOR_RANKING - 1)


def test_an_unknown_pool_is_treated_as_thin():
    """Absence of evidence is not evidence of a usable pool."""
    assert pool_is_thin(None)


def test_pool_sizes_are_counted_per_league_position_and_season():
    frame = pd.DataFrame([
        {"competition_id": 4, "season_id": 319, "position_group": "Winger"},
        {"competition_id": 4, "season_id": 319, "position_group": "Winger"},
        {"competition_id": 4, "season_id": 318, "position_group": "Winger"},
        {"competition_id": 5, "season_id": 319, "position_group": "Winger"},
    ])
    sizes = peer_pool_sizes(frame)
    assert sizes[(4, 319, "Winger")] == 2
    assert sizes[(4, 318, "Winger")] == 1


def test_no_scorecards_yields_no_pools():
    assert peer_pool_sizes(pd.DataFrame()) == {}
