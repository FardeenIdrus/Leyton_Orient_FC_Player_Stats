"""Clicking a squad row must open a profile that actually exists.

THE BUG (found 2026-09-18, pre-dating the loan work). `squads.py` carried THIS season's
competition_id with LAST season's season_id -- one from each. Phillip Chinedu is at Leyton
Orient (League One) in 2026/27, so the click looked him up in League One 2025/26, where he
played 14 minutes and is not rankable. No profile rendered.

It hits any player who changed league over the summer and has no rankable row in his CURRENT
league LAST season -- which is most of a 2026/27 squad, and exactly the cohort a recruiter
cares about.

THE RULE, deliberately simple: his most recent season with a rating, and within it the league
he played most minutes in. That is the row that best represents him, and it is guaranteed to
exist because it is chosen FROM the rows he has.
"""

import pandas as pd

from lofc.dashboard.tabs.squads import best_profile_target

# Phillip Chinedu's real rows
CHINEDU = pd.DataFrame([
    {"competition_id": 4,  "season_id": 318, "minutes": 14,   "objective_composite": None},
    {"competition_id": 5,  "season_id": 318, "minutes": 676,  "objective_composite": 2.49},
    {"competition_id": 65, "season_id": 318, "minutes": 1249, "objective_composite": 3.87},
    {"competition_id": 4,  "season_id": 319, "minutes": 473,  "objective_composite": 2.71},
])


def test_it_picks_the_most_recent_season_with_a_rating():
    """He is rankable at Leyton Orient in 2026/27 -- that is where he should open."""
    assert best_profile_target(CHINEDU) == (4, 319)


def test_it_never_returns_a_row_without_a_rating():
    """The bug: League One 2025/26, 14 minutes, no composite. Opening there shows nothing."""
    assert best_profile_target(CHINEDU) != (4, 318)


def test_within_a_season_it_picks_the_league_with_most_minutes():
    """Two ranked rows in one season (a loanee). 1,249 minutes beats 676."""
    last_season_only = CHINEDU[CHINEDU["season_id"] == 318]
    assert best_profile_target(last_season_only) == (65, 318)


def test_it_falls_back_to_an_earlier_season_when_this_one_is_unrated():
    """Under 450 minutes this season: open the last season he was actually rated in."""
    rows = CHINEDU.copy()
    rows.loc[rows["season_id"] == 319, "objective_composite"] = None
    assert best_profile_target(rows) == (65, 318)


def test_a_player_with_no_rating_anywhere_returns_none():
    """The caller must show a message, never open somebody else's profile."""
    rows = CHINEDU.copy()
    rows["objective_composite"] = None
    assert best_profile_target(rows) is None


def test_an_empty_frame_returns_none():
    assert best_profile_target(pd.DataFrame(
        columns=["competition_id", "season_id", "minutes", "objective_composite"])) is None


def test_the_result_is_plain_ints():
    """It is stashed in session state and used as a lookup key."""
    comp, season = best_profile_target(CHINEDU)
    assert isinstance(comp, int) and isinstance(season, int)
