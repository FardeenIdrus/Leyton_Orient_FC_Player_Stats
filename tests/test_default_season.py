"""Which season the Players page opens on, and which season counts as the last complete one.

History: in September 2026, five matches into 2026/27, 19 of its 36 league-position pools held
fewer than ten players, so the page was made to open on the last COMPLETE season (2025/26).

Owner, 2026-10-16: open on 2026/27. About ten matches in, 1,282 players are past 450 minutes on
the server; 13 of 51 pools are under the floor (55 players), and those are withheld by
`pool_is_thin` with a notice, not shown. The thin-pool guard is what protects the ranking --
the opening season is a choice of what a recruiter lands on, and the live season is it.

`last_complete_season_id` keeps the old rule under its own name, because the "season under
way" notice still points at the complete season as the alternative.
"""

from lofc.dashboard.seasons import default_season_id, last_complete_season_id


def test_the_page_opens_on_the_newest_season_held():
    assert default_season_id([319, 318, 317], live_season_id=319) == 319


def test_order_of_the_input_does_not_matter():
    assert default_season_id([317, 319, 318], live_season_id=319) == 319


def test_out_of_season_it_opens_on_the_newest():
    assert default_season_id([318, 317], live_season_id=None) == 318


def test_the_last_complete_season_skips_the_live_one():
    assert last_complete_season_id([319, 318, 317], live_season_id=319) == 318


def test_the_last_complete_season_is_the_newest_when_none_is_live():
    assert last_complete_season_id([318, 317], live_season_id=None) == 318


def test_the_last_complete_season_falls_back_when_only_the_live_one_is_held():
    assert last_complete_season_id([319], live_season_id=319) == 319
