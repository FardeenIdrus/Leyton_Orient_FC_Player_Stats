"""The current-form caption must not contradict the numbers beside it.

Written when NOBODY in 2026/27 cleared 450 minutes, it hard-coded three claims: that too
little of the season had been played for a composite, and that the dimension tiles below were
from the player's most recent FULL season. By 2026-09-12, 504 players had a 2026/27 composite
— so on those players the caption denied a rating that was on screen directly above it, and
misattributed the tiles to a season they did not come from.

Also trimmed: the caption ran to four lines of explanation on a section already headed
"Current form" beside tiles already labelled Minutes / Goals / Assists.
"""

from lofc.dashboard.tabs.players import current_form_caption


def test_a_player_with_a_rating_is_not_told_he_has_none():
    """The defect: a composite on screen and a caption denying it."""
    text = current_form_caption(has_rating=True)
    assert "450" not in text
    assert "most recent full season" not in text


def test_a_player_without_a_rating_is_told_why():
    text = current_form_caption(has_rating=False)
    assert "450" in text


def test_both_say_the_figures_are_counts_not_a_rating():
    """The one claim worth making in every case -- these are facts, not a score."""
    for has_rating in (True, False):
        assert "not a rating" in current_form_caption(has_rating).lower()


def test_the_caption_stays_short():
    """Excessive disclaimer text is itself a defect -- it trains readers to skip captions,
    including the ones that matter."""
    for has_rating in (True, False):
        assert len(current_form_caption(has_rating)) <= 160
