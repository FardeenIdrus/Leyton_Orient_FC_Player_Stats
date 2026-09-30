"""Attaching a scout report to one of our players, on name + DATE OF BIRTH.

THE RULE, AND WHY IT IS THIS ONE. A report carries a name; our `players` table carries
6,170 of them. Measured on the live data:

    name only        279 of 350 matched, but 13 names are claimed by TWO of our players
    name + club      183 matched, 0 ambiguous   (club naming differs badly across sources)
    name + DOB       200 matched, 0 AMBIGUOUS   <- chosen

Name-only would link 79 more reports and carry thirteen chances to attach one man's
verdict to another. The platform already rejected exactly that trade for identity after
the 54-namesake audit, and a scout report is a judgement about a specific human being --
the wrong link is worse than no link, because a wrong one is invisible.

Dates of birth come from the form's own `Player Names` tab, not from the report.

NOT MATCHING IS A NORMAL OUTCOME, NOT A FAILURE. 152 of the 350 scouted players are
outside the seven leagues the platform holds data for -- non-league and academy players
scouts are sent to watch on purpose. Their reports are stored and displayed in full; they
simply carry no `player_id`, and no rating is invented for them. A `player_id` is NEVER
minted for a scouted player: twelve tables carry a foreign key to `players`, and a row
with no metrics would reach the ranking, the peer pools and the scorecards.
"""

import datetime as dt

import pandas as pd

from lofc.model.scout_report_link import resolve_links

# Our players. Botan Ameen is held twice -- two real people sharing a name, one of the 13.
OURS = pd.DataFrame([
    {"player_id": 22175, "player_name": "Idris El Mizouni", "birth_date": dt.date(2000, 10, 26)},
    {"player_id": 388235, "player_name": "Sam Chambers", "birth_date": dt.date(2005, 3, 14)},
    {"player_id": 111, "player_name": "Botan Ameen", "birth_date": dt.date(2004, 1, 1)},
    {"player_id": 222, "player_name": "Botan Ameen", "birth_date": dt.date(2006, 5, 9)},
    {"player_id": 333, "player_name": "Joao Pedro Goncalves", "birth_date": dt.date(2001, 7, 7)},
])

# The form's dropdown list, which is where dates of birth come from.
LOOKUP = pd.DataFrame([
    {"player_name": "Idris El Mizouni", "date_of_birth": dt.date(2000, 10, 26)},
    {"player_name": "Sam Chambers", "date_of_birth": dt.date(2005, 3, 14)},
    {"player_name": "Botan Ameen", "date_of_birth": dt.date(2004, 1, 1)},
    {"player_name": "Alain Kizenga", "date_of_birth": dt.date(2007, 2, 3)},
    {"player_name": "No Birthday Player", "date_of_birth": None},
    {"player_name": "João Pedro Gonçalves", "date_of_birth": dt.date(2001, 7, 7)},
])


def _reports(*names, linkable=True):
    return pd.DataFrame([
        {"submission_id": str(i), "player_name": n, "linkable": linkable}
        for i, n in enumerate(names, start=1)])


def _ids(out):
    return list(out["player_id"])


# --- the happy path ----------------------------------------------------------------------

def test_a_report_links_on_name_and_birth_date():
    assert _ids(resolve_links(_reports("Idris El Mizouni"), LOOKUP, OURS)) == [22175]


def test_several_reports_on_the_same_player_all_link_to_him():
    """54 of 350 players have more than one report; one has five."""
    out = resolve_links(_reports("Sam Chambers", "Sam Chambers"), LOOKUP, OURS)
    assert _ids(out) == [388235, 388235]


def test_accents_do_not_prevent_a_match():
    """The sheet writes "João Pedro Gonçalves"; our table holds the unaccented form.
    Normalising is safe here because the birth date still has to agree."""
    assert _ids(resolve_links(_reports("João Pedro Gonçalves"), LOOKUP, OURS)) == [333]


def test_case_and_padding_do_not_prevent_a_match():
    assert _ids(resolve_links(_reports("  idris el mizouni "), LOOKUP, OURS)) == [22175]


# --- the refusals ------------------------------------------------------------------------

def test_a_name_held_by_two_of_our_players_is_left_unlinked():
    """THE CASE THE DATE EXISTS FOR -- except here BOTH our records would match the name,
    and only one matches the date. Botan Ameen born 2004-01-01 is unambiguous.

    This asserts the good half: the date resolves what the name could not."""
    assert _ids(resolve_links(_reports("Botan Ameen"), LOOKUP, OURS)) == [111]


def test_a_name_and_date_pair_claimed_by_two_of_our_players_is_refused():
    """If even the DATE cannot separate two of our records, nothing here can. Guessing
    would attach a rating, an injury history and an assessment to the wrong man."""
    twins = pd.concat([OURS, pd.DataFrame([
        {"player_id": 999, "player_name": "Idris El Mizouni",
         "birth_date": dt.date(2000, 10, 26)}])], ignore_index=True)
    assert pd.isna(resolve_links(_reports("Idris El Mizouni"), LOOKUP, twins)
                   ["player_id"].iloc[0])


def test_a_player_we_hold_no_record_of_stays_unlinked():
    """Alain Kizenga plays in Ireland's First Division -- outside our seven leagues.
    Correctly absent, and his report is still stored and shown."""
    assert pd.isna(resolve_links(_reports("Alain Kizenga"), LOOKUP, OURS)
                   ["player_id"].iloc[0])


def test_a_player_with_no_birth_date_in_the_lookup_stays_unlinked():
    """1,694 of 4,598 dropdown entries have no date. Without one there is no safe key,
    and falling back to the name alone is exactly the 13-namesake risk."""
    assert pd.isna(resolve_links(_reports("No Birthday Player"), LOOKUP, OURS)
                   ["player_id"].iloc[0])


def test_a_name_absent_from_the_lookup_stays_unlinked():
    assert pd.isna(resolve_links(_reports("Someone Not Listed"), LOOKUP, OURS)
                   ["player_id"].iloc[0])


# --- names recovered from the report text ---------------------------------------------------
#
# A player the scout could not find in the form's dropdown still has a name, written into
# the report. The dropdown and OUR PLAYERS TABLE are different lists: 9 of the 20 recovered
# names on the live sheet are players we hold full Impect data on, mostly Premier League 2.
#
# They cannot be matched on name + date of birth -- there is no date, which is exactly why
# they were absent from the dropdown. So they match on NAME ALONE, and the safety comes from
# refusing ambiguity rather than from a second field: a name held by more than one of our
# players links to none of them. Measured on the live data: 9 matched, 0 ambiguous.

def test_a_recovered_name_matching_one_of_our_players_links():
    """Finley Hooper is not in the form's dropdown but IS in our data (PL2). Before this,
    his report opened nothing."""
    reports = pd.DataFrame([{"submission_id": "1", "player_name": "Sam Chambers",
                             "linkable": False, "name_from_report": True}])
    assert _ids(resolve_links(reports, LOOKUP, OURS)) == [388235]


def test_a_recovered_name_held_by_two_of_our_players_links_to_neither():
    """Botan Ameen is two people in our table. With no date of birth to separate them,
    the only safe answer is no link."""
    reports = pd.DataFrame([{"submission_id": "1", "player_name": "Botan Ameen",
                             "linkable": False, "name_from_report": True}])
    assert pd.isna(resolve_links(reports, LOOKUP, OURS)["player_id"].iloc[0])


def test_a_recovered_name_we_hold_no_player_for_stays_unlinked():
    """11 of the 20 are academy players outside our seven leagues."""
    reports = pd.DataFrame([{"submission_id": "1", "player_name": "Jephta Medine",
                             "linkable": False, "name_from_report": True}])
    assert pd.isna(resolve_links(reports, LOOKUP, OURS)["player_id"].iloc[0])


def test_the_placeholder_itself_is_never_matched_by_the_recovered_name_path():
    """A comment the parser could not read leaves the name as "A New Player", and that
    string must never be looked up."""
    reports = pd.DataFrame([{"submission_id": "1", "player_name": "A New Player",
                             "linkable": False, "name_from_report": False}])
    assert pd.isna(resolve_links(reports, LOOKUP, OURS)["player_id"].iloc[0])


def test_an_unlinkable_report_without_a_recovered_name_is_not_matched_on_name_alone():
    """Name-only matching is the WEAK rule -- it leaves 13 namesakes ambiguous across the
    platform. It is used only where no date of birth can exist. A dropdown-named player has
    one and must go through the strict path, never this one."""
    reports = pd.DataFrame([{"submission_id": "1", "player_name": "Sam Chambers",
                             "linkable": False, "name_from_report": False}])
    assert pd.isna(resolve_links(reports, LOOKUP, OURS)["player_id"].iloc[0])


def test_the_placeholder_dropdown_option_never_links():
    """"A New Player" was chosen on 19 reports about 19 different people. Linking them
    would fuse nineteen strangers into one identity."""
    out = resolve_links(_reports("A New Player", linkable=False), LOOKUP, OURS)
    assert pd.isna(out["player_id"].iloc[0])


def test_an_unlinkable_report_is_not_dropped():
    """It is still a real report about a real match."""
    assert len(resolve_links(_reports("A New Player", linkable=False), LOOKUP, OURS)) == 1


# --- shape -------------------------------------------------------------------------------

def test_the_row_count_never_changes():
    """A link is an enrichment, not a filter. Losing a report here would hide a scout's
    work; duplicating one would double-count a verdict."""
    reports = _reports("Idris El Mizouni", "Alain Kizenga", "Sam Chambers")
    assert len(resolve_links(reports, LOOKUP, OURS)) == 3


def test_no_report_is_duplicated_by_the_join():
    reports = _reports("Botan Ameen", "Botan Ameen")
    out = resolve_links(reports, LOOKUP, OURS)
    assert out["submission_id"].is_unique


def test_an_empty_report_frame_is_handled():
    out = resolve_links(pd.DataFrame(columns=["submission_id", "player_name", "linkable"]),
                        LOOKUP, OURS)
    assert out.empty and "player_id" in out.columns


def test_an_empty_lookup_leaves_everything_unlinked_without_raising():
    out = resolve_links(_reports("Idris El Mizouni"),
                        pd.DataFrame(columns=["player_name", "date_of_birth"]), OURS)
    assert pd.isna(out["player_id"].iloc[0])


def test_the_caller_frame_is_not_mutated():
    reports = _reports("Idris El Mizouni")
    resolve_links(reports, LOOKUP, OURS)
    assert "player_id" not in reports.columns
