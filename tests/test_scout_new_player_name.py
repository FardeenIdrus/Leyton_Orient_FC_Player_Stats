"""Recovering the player's name when the scout could not pick him from the dropdown.

THE SOURCE BEHAVIOUR. The JotForm Player field is a dropdown built from the sheet's
`Player Names` tab. When a scout watches somebody not on that list -- almost always an
academy or B-team player -- he selects the escape-hatch option **"A New Player"** and
writes the real name into the Report Comments. The Head of Recruitment then adds that
player to the dropdown by hand, but the report already filed keeps saying "A New Player".

Verified against the LIVE sheet 2026-09-30: 20 of 449 reports, spanning 18 Aug to 22 Sep,
so this is current behaviour and not a historical residue. The sheet's `Database` tab is
byte-identical to `Form responses` and corrects none of them.

THE NAME IS ALWAYS FIRST, in four observed shapes:

    Connor Brooks. Age 18. WHU U21              name, full stop, biography
    Finley Hooper is 18 years old…              name, then a verb
    Raphael Borges Rodrigues (#17 played as…    name, then a shirt number in brackets
    52. Reggie Rose - A 21 year old goalkeeper  shirt number, name, dash

WHY THIS IS SAFE TO DISPLAY BUT NOT TO MATCH ON. A recovered name is read from free text a
scout typed; it is evidence of who was watched, not an identity. It is shown so a recruiter
can tell twenty different players apart instead of seeing twenty rows called "A New Player",
and it is labelled as coming from the report. It NEVER feeds `scout_report_link` -- linking
on a parsed name would attach a rating, an injury history and an assessment to a player on
the strength of a regular expression.

SELF-HEALING. Extraction only fires when the Player field still reads "A New Player". The
moment the Head of Recruitment corrects the row in the sheet, the real name takes over on
the next sync and this code stops applying to it.
"""

import pytest

from lofc.ingest.scout_reports import PLACEHOLDER_PLAYER, name_from_comment


# --- the four real shapes, verbatim from the live sheet -----------------------------------

@pytest.mark.parametrize("comment,expected", [
    ("Connor Brooks. Age 18. WHU U21\nStarted the game well.", "Connor Brooks"),
    ("Jephta Medine. Age 17 Showed courage, speed and aggression", "Jephta Medine"),
    ("Finley Hooper is 18 years old. He has represented England", "Finley Hooper"),
    ("Antoine Kerriou (#25) played as the central defender", "Antoine Kerriou"),
    ("Raphael Borges Rodrigues (#17 played as a centre forward", "Raphael Borges Rodrigues"),
    ("Stephen McMullan played the full game for Waterford.", "Stephen McMullan"),
    ("Teddie Lamb\nGiven the conditions of the game", "Teddie Lamb"),
    ("Finlay Gorman\nMan City have a lot of rotations", "Finlay Gorman"),
    ("Isaac Holland\nDone well on the night scoring 2 goals", "Isaac Holland"),
    ("Yeul Helafu\nScored on the night and had an assist.", "Yeul Helafu"),
    ("52. Reggie Rose - A 21 year old goalkeeper at approx. 6ft", "Reggie Rose"),
    ("68. Luka Bentt - An 18 year old Belgian u19 international", "Luka Bentt"),
    ("54. Andre Grey - A 20 year old left footed Centre-Midfielder", "Andre Grey"),
    ("Cole Simms\nWas Wigan besr player on the day.", "Cole Simms"),
    ("Reece Greenhalgh\nBusy,game energetic type of player", "Reece Greenhalgh"),
    ("Corey Adjetey-Brew Age 18. On loan from QPR", "Corey Adjetey-Brew"),
])
def test_recovers_the_name_from_a_real_report(comment, expected):
    assert name_from_comment(comment) == expected


def test_an_apostrophe_in_a_forename_survives():
    """Kah'vanni Amarni Lincoln is a real player in the sheet."""
    assert name_from_comment("Kah'vanni Amarni Lincoln\nScored and was a handful") == \
        "Kah'vanni Amarni Lincoln"


def test_a_hyphenated_surname_is_kept_whole():
    """Oscar Lewie-Bech Jorgense -- an earlier attempt cut this to "Oscar Lewie"."""
    assert name_from_comment("Oscar Lewie-Bech Jorgense\nAlot of the game was played") == \
        "Oscar Lewie-Bech Jorgense"


# --- refusing rather than guessing --------------------------------------------------------

def test_a_comment_that_does_not_start_with_a_name_returns_nothing():
    """Better twenty rows reading "A New Player" than one row naming the wrong man."""
    assert name_from_comment("The game was played in heavy rain and both sides") is None


def test_a_single_word_is_not_treated_as_a_name():
    """A surname alone cannot be told apart from an ordinary opening word."""
    assert name_from_comment("Excellent performance throughout the first half") is None


def test_a_blank_comment_returns_nothing():
    for blank in ("", "   ", None, float("nan")):
        assert name_from_comment(blank) is None


def test_the_club_name_is_not_mistaken_for_the_player():
    """A real risk, since the report usually opens by setting the scene: several live
    comments run "<name>\nMan City have a lot of rotations...". If a scout instead opens
    with the club, the club must not become the player.

    (An earlier version of this test used an invented all-title-case sentence, which does
    not occur in the sheet. This guard is the one the data actually justifies.)
    """
    assert name_from_comment("Man City Have rotations", club="Man City Have") is None
    assert name_from_comment("Brentford B were the better side", club="Brentford B") is None


def test_the_club_guard_does_not_block_a_real_name():
    assert name_from_comment("Isaac Holland\nDone well on the night",
                             club="Brentford B") == "Isaac Holland"


def test_the_placeholder_itself_is_never_returned():
    assert name_from_comment(f"{PLACEHOLDER_PLAYER} played well") is None


# --- it must never reach the identity matcher ----------------------------------------------

def test_a_recovered_name_does_not_make_a_report_linkable():
    """A name read out of free text is evidence of who was watched, not an identity.
    Linking on it would attach a rating and an injury history on the strength of a regex."""
    import pandas as pd

    from lofc.ingest.scout_reports import reports_frame
    row = {
        "Submission ID": "1", "Scout": "Lindon Lynch", "Live or Video": "Live",
        "Report Type": "Match Report", "Player": "A New Player",
        "Playing For": "West Ham U21", "Foot": "Right", "Position(s) Played": "CM",
        "Home Team": "West Ham U21", "Away Team": "Leyton Orient",
        "Fixture Date": "18-08-2026",
        "Report Comments": "Connor Brooks. Age 18. WHU U21\nStarted the game well.",
        "Recommended Position": "CM", "Performance Grade": "B",
        "Squad Role": "Emerging Talent", "Overall Verdict": "Monitor",
        "Submission Edit URL": "", "Last Update Date": "", "Submission Date": "",
    }
    out = reports_frame(pd.DataFrame([row])).iloc[0]
    assert out["player_name"] == "Connor Brooks"
    assert out["name_from_report"] is True
    assert out["linkable"] is False


def test_a_report_naming_a_real_player_is_untouched_and_linkable():
    """The ordinary case: extraction only fires on the placeholder, so a corrected row in
    the sheet takes over automatically on the next sync."""
    import pandas as pd

    from lofc.ingest.scout_reports import reports_frame
    row = {
        "Submission ID": "2", "Scout": "Gary Finley", "Live or Video": "Live",
        "Report Type": "Match Report", "Player": "Connor Brooks",
        "Playing For": "West Ham U21", "Foot": "Right", "Position(s) Played": "CM",
        "Home Team": "West Ham U21", "Away Team": "Leyton Orient",
        "Fixture Date": "18-08-2026", "Report Comments": "Someone Else. Age 20.",
        "Recommended Position": "CM", "Performance Grade": "B",
        "Squad Role": "Emerging Talent", "Overall Verdict": "Sign",
        "Submission Edit URL": "", "Last Update Date": "", "Submission Date": "",
    }
    out = reports_frame(pd.DataFrame([row])).iloc[0]
    assert out["player_name"] == "Connor Brooks"
    assert out["name_from_report"] is False
    assert out["linkable"] is True


def test_a_placeholder_with_an_unreadable_comment_keeps_the_placeholder():
    import pandas as pd

    from lofc.ingest.scout_reports import reports_frame
    row = {
        "Submission ID": "3", "Player": "A New Player",
        "Report Comments": "The game was played in heavy rain throughout.",
        "Fixture Date": "18-08-2026",
    }
    out = reports_frame(pd.DataFrame([row])).iloc[0]
    assert out["player_name"] == PLACEHOLDER_PLAYER
    assert out["name_from_report"] is False
    assert out["linkable"] is False
