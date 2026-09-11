"""Where a player sits among his real peers — same league, season and position.

The player report has stated this since it was built ("3rd of 92"); the player PROFILE, the
screen recruiters actually work from, did not. Worse, the Players table's "Rank" column is
the row's position in whatever the sidebar currently shows, which is a different number
entirely: on 25/26 centre forwards it ranked Maeda 1, Wakeling 2 and Burrowes 3, when
Wakeling and Burrowes are each FIRST in their own division. Percentiles are league-relative,
so stacking leagues in one list implies a comparison the model never makes.

One function, used by both surfaces, so the report and the profile cannot disagree.
"""

import pandas as pd

from lofc.model.scorecard import rank_in_pool

POOL = pd.DataFrame([
    {"player_id": 1, "competition_id": 4, "season_id": 318, "position_group": "Winger",
     "objective_composite": 4.20},
    {"player_id": 2, "competition_id": 4, "season_id": 318, "position_group": "Winger",
     "objective_composite": 3.80},
    {"player_id": 3, "competition_id": 4, "season_id": 318, "position_group": "Winger",
     "objective_composite": 2.90},
    # Same position and season, DIFFERENT league — must not affect the ranking above.
    {"player_id": 4, "competition_id": 3, "season_id": 318, "position_group": "Winger",
     "objective_composite": 4.90},
    # Same league and season, DIFFERENT position.
    {"player_id": 5, "competition_id": 4, "season_id": 318, "position_group": "Centre Back",
     "objective_composite": 4.95},
    # Same league and position, DIFFERENT season.
    {"player_id": 6, "competition_id": 4, "season_id": 317, "position_group": "Winger",
     "objective_composite": 4.99},
])

KEY = dict(competition_id=4, season_id=318, position_group="Winger")


def test_the_best_player_in_his_pool_is_first():
    assert rank_in_pool(POOL, player_id=1, **KEY) == (1, 3)


def test_rank_counts_only_his_own_league_season_and_position():
    """Four higher composites exist in the frame; none is a peer, so he is still 2nd of 3."""
    assert rank_in_pool(POOL, player_id=2, **KEY) == (2, 3)


def test_the_worst_player_is_last():
    assert rank_in_pool(POOL, player_id=3, **KEY) == (3, 3)


def test_a_player_outside_the_pool_has_no_rank_but_the_pool_size_still_reports():
    rank, peers = rank_in_pool(POOL, player_id=999, **KEY)
    assert rank is None
    assert peers == 3


def test_players_without_a_composite_are_not_peers():
    """An unscored row is not someone you can be ranked against."""
    pool = pd.concat([POOL, pd.DataFrame([
        {"player_id": 7, "competition_id": 4, "season_id": 318, "position_group": "Winger",
         "objective_composite": None}])], ignore_index=True)
    assert rank_in_pool(pool, player_id=1, **KEY) == (1, 3)


def test_an_empty_frame_is_not_an_error():
    assert rank_in_pool(pd.DataFrame(), player_id=1, **KEY) == (None, 0)


def test_ties_take_the_same_rank_rather_than_an_arbitrary_order():
    """Two identical composites are not first and second — nothing separates them, and
    picking one would be an artefact of row order."""
    pool = pd.DataFrame([
        {"player_id": 1, "competition_id": 4, "season_id": 318, "position_group": "Winger",
         "objective_composite": 4.20},
        {"player_id": 2, "competition_id": 4, "season_id": 318, "position_group": "Winger",
         "objective_composite": 4.20},
        {"player_id": 3, "competition_id": 4, "season_id": 318, "position_group": "Winger",
         "objective_composite": 3.10},
    ])
    assert rank_in_pool(pool, player_id=1, **KEY) == (1, 3)
    assert rank_in_pool(pool, player_id=2, **KEY) == (1, 3)
    assert rank_in_pool(pool, player_id=3, **KEY) == (3, 3)


def test_ranking_can_follow_a_different_column():
    """The assessed ranking is opt-in and ranks on a different composite."""
    pool = POOL.copy()
    pool["assessed_composite"] = [1.0, 5.0, 3.0, 9.9, 9.9, 9.9]
    assert rank_in_pool(pool, player_id=2, column="assessed_composite", **KEY) == (1, 3)
