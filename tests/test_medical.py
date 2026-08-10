"""The availability rule -- the objective input to the club's Medical dimension."""

import pandas as pd
import pytest

from lofc.model.medical import (
    availability,
    games_missed_in_window,
    window_labels,
)

CHAMPIONSHIP = 3
SCOTTISH_PREM = 901


def test_a_player_who_missed_nothing_is_fully_available():
    assert availability(0, CHAMPIONSHIP) == 1.0


def test_the_club_minimum_bar():
    # 60% availability is the club's stated minimum: 40% of 92 games = 36.8 missed.
    assert availability(37, CHAMPIONSHIP) == pytest.approx(0.5978, abs=0.001)


def test_availability_is_clamped_at_zero():
    # More games missed than the window holds (long-term injury spanning seasons).
    assert availability(200, CHAMPIONSHIP) == 0.0


def test_half_the_window_missed():
    assert availability(46, CHAMPIONSHIP) == 0.5


def test_league_without_a_scheduled_games_constant_returns_none():
    # Scottish/PL2 have no Transfermarkt coverage; the criterion is unscored, not
    # defaulted -- a guessed availability would be worse than an honest gap.
    assert availability(5, SCOTTISH_PREM) is None


def test_window_labels_covers_the_season_and_the_one_before():
    assert window_labels(318) == ("24/25", "25/26")
    assert window_labels(319) == ("25/26", "26/27")


def test_games_missed_only_counts_the_window():
    injuries = pd.DataFrame({
        "season_label": ["23/24", "24/25", "25/26"],
        "games_missed": [99, 4, 6],
    })
    # 23/24 is outside a two-season window ending at 2025/26, so its 99 is ignored.
    assert games_missed_in_window(injuries, 318) == 10


def test_games_missed_with_no_injuries():
    empty = pd.DataFrame(columns=["season_label", "games_missed"])
    assert games_missed_in_window(empty, 318) == 0
