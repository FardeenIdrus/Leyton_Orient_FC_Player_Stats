"""The info bar above the Players page must name BOTH player counts.

It read "4,376 players analysed" -- every player with any data, including the 1,147 under the
450-minute floor who carry no rating. The table beneath it lists only rated players. The Head
of Recruitment divided 1,687 (ratings at or above 3.0) by 4,376 and concluded only a minority
meet the benchmark; against the 3,345 ratings that exist it is 50.4%.

Fixed in the label: the count the table is drawn from sits beside the wider one.
"""

from lofc.aggregate.player_season import RANKABLE_MINUTES
from lofc.dashboard.tabs.players import infobar_count_items


def test_both_counts_are_named():
    assert infobar_count_items(4376, 3229) == [
        "<b>4,376</b> players",
        "<b>3,229</b> rated (450+ mins)",
    ]


def test_the_minutes_floor_comes_from_the_scoring_constant():
    assert f"{RANKABLE_MINUTES}+ mins" in infobar_count_items(10, 5)[1]


def test_the_word_analysed_is_gone():
    """'Analysed' implied every counted player was scored."""
    assert not any("analysed" in item for item in infobar_count_items(4376, 3229))


def test_zero_rated_is_stated_not_hidden():
    """Early in a season nobody passes 450 minutes; 0 is a fact worth showing."""
    assert infobar_count_items(1034, 0)[1] == "<b>0</b> rated (450+ mins)"
