"""The Players page must open on a season it can actually rank.

2026/27 became partly scorable in September 2026 (378 players past 450 minutes), which put it
at the top of `available_seasons()` and therefore made it the landing default. Five matches in,
19 of its 36 league-position pools held fewer than ten players and two held exactly one -- and a
pool of one scores 4.90 by construction, higher than any centre forward managed across a
complete 46-game season. The default must be the last COMPLETE season; the live one stays
selectable, it is just no longer what a recruiter lands on without asking.
"""

from lofc.dashboard.seasons import default_season_id


def test_the_default_is_the_last_complete_season_not_the_live_one():
    assert default_season_id([319, 318, 317], live_season_id=319) == 318


def test_the_live_season_is_still_offered_just_not_as_the_default():
    """Nothing is hidden -- the guard is about what opens, not about what exists."""
    seasons = [319, 318, 317]
    assert 319 in seasons
    assert default_season_id(seasons, live_season_id=319) != 319


def test_the_newest_season_wins_when_none_is_live():
    """Out of season (LIVE_SEASON_ID unset) every season held is complete."""
    assert default_season_id([318, 317], live_season_id=None) == 318


def test_the_live_season_is_used_when_it_is_the_only_one_held():
    """A fresh database holding only the season under way must still open on something."""
    assert default_season_id([319], live_season_id=319) == 319


def test_order_of_the_input_does_not_matter():
    assert default_season_id([317, 319, 318], live_season_id=319) == 318
