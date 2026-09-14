"""The ranked Players list shows whether a player has been assessed.

The player card has always shown the full assessment -- bands, who assessed, who signed off,
criterion detail, notes. The ranked LIST showed nothing, so telling an assessed player from an
unassessed one meant opening each one in turn.

DISPLAY ONLY. The column never reorders the list and never touches a score: scout input must
not influence `objective_composite`, which stays the ranking. `assessment_status.attach` is a
LEFT join for the same reason -- showing the column must never drop a player.
"""

import pandas as pd

from lofc.dashboard.tabs.players import assessed_column
from lofc.model import assessment_status


def test_an_unassessed_player_says_so():
    assert assessed_column(pd.Series([assessment_status.NOT_ASSESSED]))[0] != ""


def test_each_status_maps_to_its_own_words():
    values = [assessment_status.NOT_ASSESSED, assessment_status.AWAITING,
              assessment_status.CONFLICTED, assessment_status.SIGNED_OFF]
    out = list(assessed_column(pd.Series(values)))
    assert len(set(out)) == 4, f"statuses collapsed onto the same text: {out}"


def test_the_words_carry_the_meaning_not_just_a_colour():
    """Accessibility rule from the design spec: colour never carries meaning alone."""
    signed = assessed_column(pd.Series([assessment_status.SIGNED_OFF]))[0]
    assert any(ch.isalpha() for ch in signed)


def test_a_missing_status_does_not_render_as_nan():
    """A player with no row in the status frame must read as unassessed, not 'nan'."""
    out = assessed_column(pd.Series([None]))
    assert "nan" not in str(out[0]).lower()


def test_an_empty_pool_is_handled():
    assert list(assessed_column(pd.Series(dtype=object))) == []
