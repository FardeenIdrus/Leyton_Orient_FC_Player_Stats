"""Turning a scout report row into something the platform can store and join.

Every hazard pinned here was measured on the club's live sheet (437 reports, 6 scouts,
350 players), not imagined.

THE DATE. `Fixture Date` is DD-MM-YYYY -- the JotForm field's own placeholder says so.
pandas defaults to MONTH-first, and 25 of the 51 distinct dates in the sheet have both
parts under 13, so a default parse silently reads roughly half of them as a different
day and raises nothing at all. `21-07-2026` is the only kind that would error, and it is
the minority. This is the single most dangerous line in the module.

THE PLACEHOLDER. The form's Player field is a dropdown, and its escape hatch for a
player not on the list is the literal option "A New Player" -- chosen 19 times, the most
"common" player in the sheet. Nineteen unrelated reports would otherwise be joined
together into one nonexistent person.

MULTI-VALUE POSITIONS. 43 rows carry more than one position, newline-separated
("LW\\nCF"). A third position vocabulary, on top of Impect's 8 groups and Transfermarkt's
16 -- 35 distinct codes. It is kept verbatim: inventing a mapping to our groups would
assert something the scout did not say.

THE KEY. `Submission ID` is JotForm's own, unique across all 437 rows, and stable across
edits -- which is why a report can be edited in the sheet and still upsert rather than
duplicate.
"""

import datetime as dt

import pandas as pd
import pytest

from lofc.ingest.scout_reports import (
    PLACEHOLDER_PLAYER,
    is_placeholder_player,
    parse_sheet_date,
    reports_frame,
    split_positions,
)

# A real row, values taken verbatim from the live sheet.
ROW = {
    "Scout": "Gareth Mycock",
    "Live or Video": "Video",
    "Report Type": "Match Report",
    "Player": "Ra'ess Bangura-Williams",
    "Playing For": "Millwall",
    "Foot": "Left",
    "Position(s) Played": "LW",
    "Home Team": "Gillingham",
    "Away Team": "Millwall",
    "Fixture Date": "21-07-2026",
    "Report Comments": "Ra'ees Bangura-Williams (#31) is a left footed, athletic player.",
    "Recommended Position": "LW",
    "Performance Grade": "B",
    "Squad Role": "Core (>70% of Minutes)",
    "Overall Verdict": "Sign",
    "Submission Edit URL": "https://eu.jotform.com/edit/6607479223932953217",
    "Last Update Date": "2026-07-27 8:20:12",
    "Submission Date": "",
    "Submission ID": "6607479223932953217",
}


def _frame(*rows):
    return pd.DataFrame(list(rows) or [ROW])


# --- the date ----------------------------------------------------------------------------

def test_a_day_over_twelve_parses_day_first():
    assert parse_sheet_date("21-07-2026") == dt.date(2026, 7, 21)


def test_an_ambiguous_date_parses_DAY_first_not_month_first():
    """THE DANGEROUS ONE. `03-07-2026` is 3 July, not 7 March. Both readings are valid
    dates, so a wrong parse produces no error -- just a report filed against the wrong
    fixture, four months out."""
    assert parse_sheet_date("03-07-2026") == dt.date(2026, 7, 3)


def test_the_first_of_a_month_parses_day_first():
    assert parse_sheet_date("01-05-2026") == dt.date(2026, 5, 1)


def test_an_impossible_date_is_blank_not_a_silent_shift():
    """Month-first fallback would turn 32-01-2026 into something. Blank is the fact."""
    assert parse_sheet_date("32-01-2026") is None


def test_a_blank_date_is_none():
    for blank in ("", None, float("nan"), "   "):
        assert parse_sheet_date(blank) is None


def test_a_timestamp_column_keeps_its_own_iso_format():
    """`Last Update Date` is ISO (2026-07-27 8:20:12), a different format in the same
    sheet. Forcing day-first on it would fail or mangle it."""
    assert parse_sheet_date("2026-07-27 8:20:12", iso=True) == dt.date(2026, 7, 27)


# --- the placeholder player --------------------------------------------------------------

def test_the_dropdown_escape_hatch_is_recognised():
    assert is_placeholder_player(PLACEHOLDER_PLAYER)
    assert is_placeholder_player("A New Player")


def test_the_check_ignores_case_and_padding():
    assert is_placeholder_player("  a new player  ")


def test_a_real_player_is_not_a_placeholder():
    assert not is_placeholder_player("Ra'ess Bangura-Williams")


def test_a_blank_name_is_treated_as_a_placeholder():
    """A report with no player named cannot be attached to anybody."""
    assert is_placeholder_player("") and is_placeholder_player(None)


def test_placeholder_rows_are_kept_but_never_linked():
    """The report is real -- a scout watched a match and wrote it up. What must not
    happen is 19 different people sharing one identity."""
    out = reports_frame(_frame({**ROW, "Player": "A New Player",
                                "Submission ID": "1"}))
    assert len(out) == 1
    assert out.iloc[0]["linkable"] is False


def test_a_named_player_is_linkable():
    assert reports_frame(_frame()).iloc[0]["linkable"] is True


# --- positions ---------------------------------------------------------------------------

def test_a_single_position_is_a_one_item_list():
    assert split_positions("LW") == ["LW"]


def test_multiple_positions_split_on_the_newline_the_form_writes():
    assert split_positions("RB\nRWB") == ["RB", "RWB"]
    assert split_positions("CM\nAM\nRW") == ["CM", "AM", "RW"]


def test_padding_and_blank_entries_are_dropped():
    assert split_positions(" LW \n\n CF ") == ["LW", "CF"]


def test_no_position_is_an_empty_list_never_a_list_containing_blank():
    for blank in ("", None, float("nan")):
        assert split_positions(blank) == []


def test_the_scouts_vocabulary_is_preserved_verbatim():
    """35 codes, none of which are our 8 position groups. RCB is not "Centre Back" --
    the scout said right-sided centre back in a back three, and flattening that
    discards what he watched."""
    assert split_positions("RCB") == ["RCB"]


# --- the frame ---------------------------------------------------------------------------

def test_the_submission_id_survives_as_the_key():
    out = reports_frame(_frame())
    assert out.iloc[0]["submission_id"] == "6607479223932953217"


def test_columns_are_renamed_to_storable_names():
    out = reports_frame(_frame())
    for column in ("scout", "player_name", "club_name", "fixture_date", "grade",
                   "verdict", "squad_role", "comments", "positions_played",
                   "recommended_positions", "submission_id", "observation"):
        assert column in out.columns, f"{column} missing from the stored frame"


def test_the_fixture_date_is_a_date_object_not_text():
    assert reports_frame(_frame()).iloc[0]["fixture_date"] == dt.date(2026, 7, 21)


def test_a_blank_submission_date_does_not_become_a_fake_timestamp():
    """22 of 437 rows have no Submission Date. Absent is not zero and not now()."""
    assert pd.isna(reports_frame(_frame()).iloc[0]["submitted_at"])


def test_rows_with_no_submission_id_are_dropped():
    """Without the key there is nothing to upsert on -- a keyless row would insert
    afresh on every sync, once a minute, forever."""
    out = reports_frame(_frame({**ROW, "Submission ID": ""}))
    assert out.empty


def test_duplicate_submission_ids_are_collapsed_to_one():
    """`Database` is a duplicate of `Form responses`; if both were ever read, or a row
    were pasted twice, the key must still be unique before it reaches an upsert."""
    out = reports_frame(_frame(ROW, dict(ROW)))
    assert len(out) == 1


def test_an_empty_sheet_yields_an_empty_frame_with_the_right_columns():
    out = reports_frame(pd.DataFrame(columns=list(ROW)))
    assert out.empty
    assert "submission_id" in out.columns


def test_the_caller_frame_is_not_mutated():
    frame = _frame()
    reports_frame(frame)
    assert "submission_id" not in frame.columns


def test_comments_are_stored_verbatim():
    """Stored raw and escaped at render. Escaping here would put &#39; in the database
    and corrupt every export."""
    out = reports_frame(_frame())
    assert out.iloc[0]["comments"] == ROW["Report Comments"]
