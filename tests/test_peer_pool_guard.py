"""A percentile is only as meaningful as the pool it ranks within.

On 2026-09-07, five matches into 2026/27, 13 of 36 position-league pools held fewer than
five rankable players and 34 players sat in one. A composite built on three peers is not a
weak signal -- it is arbitrary: whoever happens to have played decides the order.
"""

import pandas as pd

from lofc.model.scorecard import (MIN_PEERS_FOR_RANKING, peer_pool_sizes, pool_is_thin,
                                  with_peer_counts)


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


# --- the count a recruiter actually sees, and the gate it drives -----------------------
#
# Gating the ranking on pool size without SHOWING the pool size would leave a recruiter
# unable to tell why a player is absent, or what a 4.90 is worth. The report already states
# its peer count for exactly this reason (report/data.py); the ranked list did not.

def test_every_row_carries_the_size_of_its_own_pool():
    scorecards = pd.DataFrame(
        [{"competition_id": 4, "season_id": 319, "position_group": "Winger"}] * 12 +
        [{"competition_id": 3, "season_id": 319, "position_group": "Winger"}] * 2)
    sizes = peer_pool_sizes(scorecards)

    rows = with_peer_counts(pd.DataFrame([
        {"player_id": 1, "competition_id": 4, "season_id": 319, "position_group": "Winger"},
        {"player_id": 2, "competition_id": 3, "season_id": 319, "position_group": "Winger"},
    ]), sizes)

    assert list(rows["peer_count"]) == [12, 2]


def test_a_row_with_no_pool_of_its_own_carries_no_count():
    """A player with no scorecard must read as 'not known', never as a pool of zero."""
    rows = with_peer_counts(pd.DataFrame([
        {"player_id": 1, "competition_id": 9, "season_id": 319, "position_group": "Winger"},
    ]), {})
    assert pd.isna(rows["peer_count"].iloc[0])


def test_the_original_frame_is_not_mutated():
    frame = pd.DataFrame([{"competition_id": 4, "season_id": 319, "position_group": "Winger"}])
    with_peer_counts(frame, {(4, 319, "Winger"): 12})
    assert "peer_count" not in frame.columns


def test_a_player_alone_in_his_pool_is_gated_out_of_the_ranking():
    """Yousef Salech, the only rankable Championship centre forward in 2026/27: scored 4.90
    because he was ranked against himself, and sorted above every genuinely-earned score."""
    rows = with_peer_counts(pd.DataFrame([
        {"player_id": 1, "competition_id": 3, "season_id": 319, "position_group": "Centre Forward"},
    ]), {(3, 319, "Centre Forward"): 1})
    assert rows["peer_count"].map(pool_is_thin).all()


def test_a_healthy_pool_is_still_ranked():
    rows = with_peer_counts(pd.DataFrame([
        {"player_id": 1, "competition_id": 65, "season_id": 319, "position_group": "Centre Forward"},
    ]), {(65, 319, "Centre Forward"): 13})
    assert not rows["peer_count"].map(pool_is_thin).any()
