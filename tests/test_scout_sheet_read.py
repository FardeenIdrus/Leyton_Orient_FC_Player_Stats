"""Reading the club's scouting sheet: the parts that do not talk to Google.

The sheet is the club's live working document -- six scouts and the Head of Recruitment
edit it daily -- and the platform only ever READS it. That is enforced twice over and
neither layer depends on this code being correct: the service-account token carries only
`spreadsheets.readonly`, so Google answers a write with HTTP 403, and the account is a
Viewer on the file so it has no permission to write in the first place. Verified against
the live sheet 2026-09-28 by attempting a write and confirming the 403.

Three things here are not obvious and each has already bitten, or would have:

RAGGED ROWS. The Sheets API omits trailing empty cells, so a row is only as wide as its
last non-empty value. Measured on the live sheet: `Player Names` returns a NINE-column
header and 4,598 rows of SIX columns. `pd.DataFrame(rows, columns=header)` raises
outright on that -- "9 columns passed, passed data had 6 columns" -- so every row must be
padded to the header's width before a frame exists.

RENAMED TABS. The sheet's tabs are named by people, and a rename is a silent data loss:
the range simply returns nothing and the sync stores six tables instead of seven while
reporting success. The tabs are asserted by name before anything is read.

CHANGE DETECTION. Polled once a minute against a source that changes a few times a day,
so the overwhelmingly common case is "nothing happened". Hashing the payload lets the
job stop before it touches Postgres.
"""

import pandas as pd
import pytest

from lofc.ingest.scout_sheets import (
    REQUIRED_TABS,
    frame_from_values,
    missing_tabs,
    payload_hash,
)


# --- the tab guard ----------------------------------------------------------------------

def test_every_required_tab_present_is_no_complaint():
    assert missing_tabs(list(REQUIRED_TABS)) == []


def test_extra_tabs_are_not_a_problem():
    """The sheet holds 11 tabs; we read 7. The other four are duplicates, subsets or
    form config, and the club may add more at any time."""
    assert missing_tabs(list(REQUIRED_TABS) + ["Teams Watched", "InputFix"]) == []


def test_a_renamed_tab_is_named_in_the_complaint():
    """Not a boolean. "Something is missing" sends someone diffing 11 tabs by eye."""
    available = [t for t in REQUIRED_TABS if t != "Form responses"]
    assert missing_tabs(available) == ["Form responses"]


def test_several_missing_tabs_are_all_reported():
    assert missing_tabs(["Form responses"]) == [
        t for t in REQUIRED_TABS if t != "Form responses"]


def test_the_reports_tab_is_required():
    """The one tab without which the feature has no reason to exist."""
    assert "Form responses" in REQUIRED_TABS


def test_the_duplicate_and_derived_tabs_are_not_read():
    """`Database` is a byte-identical copy of `Form responses` (verified with
    DataFrame.equals on the live export) and would double every report. `Teams Watched`
    is a pivot of `Fixtures Schedule` whose stored numbers are ALREADY stale for 21 of
    156 clubs -- it is computed, never imported. `Fixtures - Video` is a subset."""
    for tab in ("Database", "Teams Watched", "Fixtures - Video", "InputFix"):
        assert tab not in REQUIRED_TABS


# --- building a frame from the API's ragged arrays ---------------------------------------

def test_the_first_row_becomes_the_header():
    out = frame_from_values([["Player", "Foot"], ["A Player", "Right"]])
    assert list(out.columns) == ["Player", "Foot"]
    assert out.iloc[0]["Player"] == "A Player"


def test_a_short_row_is_padded_to_the_header_width():
    """THE DEFECT THIS PREVENTS. Live: `Player Names` sends a 9-wide header and
    4,598 rows 6 wide. Constructing a frame without padding raises."""
    out = frame_from_values([
        ["Player", "DOB", "Link", "ID", "Flagged", "f", "g", "h", "i"],
        ["Aaron Bouwman", "2007-08-28", "", "Aaron Bouwman (39322)", "No", ""],
    ])
    assert out.shape == (1, 9)
    assert out.iloc[0]["Player"] == "Aaron Bouwman"
    assert out.iloc[0]["i"] == ""


def test_a_row_longer_than_the_header_does_not_silently_lose_cells():
    """A column added to the data but not the header. Extra cells get positional names
    rather than being dropped -- data appearing is a question, data vanishing is a bug."""
    out = frame_from_values([["Player"], ["A Player", "surprise"]])
    assert out.shape[1] == 2
    assert "surprise" in out.iloc[0].tolist()


def test_an_empty_range_yields_an_empty_frame_not_an_exception():
    """A renamed or cleared tab returns no `values` key at all."""
    assert frame_from_values([]).empty
    assert frame_from_values(None).empty


def test_a_header_with_no_data_rows_still_gives_the_columns():
    """Start of a season: the form exists, nobody has filed yet. The loader must see
    zero rows with the right shape, not a shapeless frame."""
    out = frame_from_values([["Player", "Foot"]])
    assert out.empty
    assert list(out.columns) == ["Player", "Foot"]


def test_blank_header_cells_get_positional_names():
    """Trailing unnamed columns are ordinary in a spreadsheet. Two columns both named ""
    would collide on assignment."""
    out = frame_from_values([["Player", "", ""], ["A Player", "x", "y"]])
    assert len(set(out.columns)) == 3


def test_values_are_left_as_strings():
    """Type coercion belongs to the parsing layer, which knows that Fixture Date is
    DD-MM-YYYY. Guessing here would let pandas read 03-07-2026 as 7 March."""
    out = frame_from_values([["Fixture Date"], ["03-07-2026"]])
    assert out.iloc[0]["Fixture Date"] == "03-07-2026"


# --- change detection --------------------------------------------------------------------

def test_identical_payloads_hash_the_same():
    payload = {"Form responses": [["a"], ["b"]]}
    assert payload_hash(payload) == payload_hash({"Form responses": [["a"], ["b"]]})


def test_one_changed_cell_changes_the_hash():
    """A scout editing a single verdict must not be mistaken for "nothing happened"."""
    before = {"Form responses": [["Verdict"], ["Monitor"]]}
    after = {"Form responses": [["Verdict"], ["Sign"]]}
    assert payload_hash(before) != payload_hash(after)


def test_a_new_row_changes_the_hash():
    before = {"Form responses": [["Player"], ["A"]]}
    after = {"Form responses": [["Player"], ["A"], ["B"]]}
    assert payload_hash(before) != payload_hash(after)


def test_a_change_in_any_tab_changes_the_hash():
    """One hash covers the whole pull, so an edit to the fixtures list is not missed
    because the reports tab happened to be untouched."""
    before = {"Form responses": [["a"]], "Fixtures Schedule": [["x"]]}
    after = {"Form responses": [["a"]], "Fixtures Schedule": [["y"]]}
    assert payload_hash(before) != payload_hash(after)


def test_key_order_does_not_change_the_hash():
    """batchGet returns ranges in request order; a reordered request is not new data."""
    assert payload_hash({"A": [["1"]], "B": [["2"]]}) == \
           payload_hash({"B": [["2"]], "A": [["1"]]})


def test_an_empty_payload_hashes_without_raising():
    assert isinstance(payload_hash({}), str)
