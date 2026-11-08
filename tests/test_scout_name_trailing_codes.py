"""2.31f: a name read from report text must not keep a trailing club or position code
("Antonio Arena AS Roma", "David Mantle RCB"). Live cases from the 2026-11-06 check."""

import pytest

from lofc.ingest.scout_reports import name_from_comment


@pytest.mark.parametrize("comment, expected", [
    ("Antonio Arena AS Roma", "Antonio Arena"),
    ("Daniele Paul AS Roma", "Daniele Paul"),
    ("Giampaolo Bonifazi AS Roma", "Giampaolo Bonifazi"),
    ("David Mantle RCB Age 19 Ht 6'2\"? on loan from Coventry City U21s", "David Mantle"),
])
def test_trailing_club_or_position_code_is_stripped(comment, expected):
    assert name_from_comment(comment) == expected


@pytest.mark.parametrize("comment, expected", [
    ("Archie Stevens. Age 17.", "Archie Stevens"),
    ("Connor Brooks. Age 18. WHU U21", "Connor Brooks"),
    ("Finley Hooper is 18 years old", "Finley Hooper"),
    ("Max Little. Age 20", "Max Little"),
    ("Kendry Paez. Age 18", "Kendry Paez"),
    ("Frenkie de Jong. Age 28", "Frenkie de Jong"),
    ("Raphael Borges Rodrigues (#17 played as", "Raphael Borges Rodrigues"),
    ("Kah'vanni Amarni Lincoln\nScored and was a handful", "Kah'vanni Amarni Lincoln"),
])
def test_clean_names_are_unchanged(comment, expected):
    assert name_from_comment(comment) == expected


def test_never_strips_below_two_words():
    # The code is the second word, so there is nothing to strip down to: kept whole.
    assert name_from_comment("Joe RCB Age 19") == "Joe RCB"
    # A capitals token as the 2nd word is never touched either.
    assert name_from_comment("Joe SMITH Age 19") == "Joe SMITH"
