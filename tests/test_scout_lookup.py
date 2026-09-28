"""The `Player Names` tab -- the controlled list behind the form's Player dropdown.

WHY THIS TAB IS THE MOST VALUABLE ONE IN THE SHEET. A scout report carries only a player's
NAME. Matching names alone against `players` links 279 of 350 but leaves 13 names claimed
by two different people -- thirteen chances to attach one man's scout report to another,
which is the precise failure the platform's 54-namesake audit already ruled out for
identity. This tab carries DATE OF BIRTH, and name + date of birth links 200 with ZERO
ambiguity. Fewer matches, no landmines.

A THIRD DATE FORMAT, IN THE SAME WORKBOOK. `Fixture Date` on the reports tab is
DD-MM-YYYY with hyphens; `DOB` here is DD/MM/YYYY with slashes; `Submission Date` is ISO.
Each is parsed explicitly. One row holds the literal text "19 yrs" where a date should
be -- someone typed an age -- which parses to nothing rather than to a guess.

The tab also carries `TrM ID`, `SB ID` and `SkillC ID` columns, EMPTY on all 4,598 rows.
The club made space to link players to Transfermarkt, StatsBomb and SkillCorner and never
filled it in; the name + date-of-birth match is what produces that mapping instead.
"""

import datetime as dt

import pandas as pd

from lofc.ingest.scout_lookup import lookup_frame, parse_lookup_dob

ROW = {
    "Player": "Aaron Bouwman",
    "DOB": "28/08/2007",
    "Age": "",
    "Link": "https://sortitoutsi.b-cdn.net/uploads/face/2000269520.png",
    "ID": "Aaron Bouwman (39322)",
    "Flagged": "No",
    "TrM ID": "",
    "SB ID": "",
    "SkillC ID": "",
}


def _frame(*rows):
    return pd.DataFrame(list(rows) or [ROW])


# --- the date ----------------------------------------------------------------------------

def test_a_slash_separated_date_parses_day_first():
    assert parse_lookup_dob("28/08/2007") == dt.date(2007, 8, 28)


def test_an_ambiguous_slash_date_is_read_DAY_first():
    """`06/08/2003` is 6 August, not 8 June. Both are real dates, so a month-first read
    produces no error -- just a player who fails to match, or worse, matches the wrong one."""
    assert parse_lookup_dob("06/08/2003") == dt.date(2003, 8, 6)


def test_an_age_typed_where_a_date_belongs_is_not_a_date():
    """One live row holds the literal text "19 yrs". A tolerant parser would either
    raise on the whole column or invent a date from the number."""
    assert parse_lookup_dob("19 yrs") is None


def test_a_blank_date_of_birth_is_none():
    for blank in ("", "   ", None, float("nan")):
        assert parse_lookup_dob(blank) is None


def test_an_impossible_date_is_none():
    assert parse_lookup_dob("31/02/2007") is None


# --- the frame ---------------------------------------------------------------------------

def test_the_columns_the_table_stores_are_produced():
    out = lookup_frame(_frame())
    for column in ("player_name", "date_of_birth", "source_ref", "profile_url", "flagged"):
        assert column in out.columns


def test_the_name_and_birth_date_survive():
    row = lookup_frame(_frame()).iloc[0]
    assert row["player_name"] == "Aaron Bouwman"
    assert row["date_of_birth"] == dt.date(2007, 8, 28)


def test_the_clubs_own_reference_is_kept_verbatim():
    """"Aaron Bouwman (39322)" is a sortitoutsi id, not a Transfermarkt or Impect one, so
    it joins to nothing we hold. Kept because it is the club's handle for the player and
    may become joinable if they ever fill in the empty TrM ID column."""
    assert lookup_frame(_frame()).iloc[0]["source_ref"] == "Aaron Bouwman (39322)"


def test_a_player_with_no_birth_date_is_still_kept():
    """1,694 of 4,598 rows have none. They cannot be matched, but they are still valid
    entries in the dropdown a scout picks from -- dropping them would make the platform
    disagree with the form about which players exist."""
    out = lookup_frame(_frame({**ROW, "DOB": ""}))
    assert len(out) == 1
    assert out.iloc[0]["date_of_birth"] is None


def test_a_row_with_no_name_is_dropped():
    """Trailing blank rows are ordinary in a spreadsheet and match nothing."""
    assert lookup_frame(_frame({**ROW, "Player": ""})).empty


def test_names_are_stripped_of_stray_padding():
    assert lookup_frame(_frame({**ROW, "Player": "  Aaron Bouwman "})).iloc[0][
        "player_name"] == "Aaron Bouwman"


def test_the_empty_provider_id_columns_are_not_stored():
    """TrM ID, SB ID and SkillC ID are empty on all 4,598 rows. Storing three always-null
    columns would imply the platform has a link it does not have."""
    out = lookup_frame(_frame())
    for column in ("trm_id", "sb_id", "skillc_id", "TrM ID"):
        assert column not in out.columns


def test_duplicate_name_and_date_pairs_are_collapsed():
    """A name listed twice with the same birth date is one player entered twice. Left in,
    it would make its own key ambiguous and the player would stop matching entirely."""
    out = lookup_frame(_frame(ROW, dict(ROW)))
    assert len(out) == 1


def test_the_same_name_with_different_birth_dates_is_kept_twice():
    """Two real people who share a name. Both stay -- and because the key includes the
    date, both still match correctly."""
    out = lookup_frame(_frame(ROW, {**ROW, "DOB": "01/01/1999"}))
    assert len(out) == 2


def test_an_empty_tab_yields_an_empty_frame_with_the_right_columns():
    out = lookup_frame(pd.DataFrame(columns=list(ROW)))
    assert out.empty and "player_name" in out.columns


def test_the_caller_frame_is_not_mutated():
    frame = _frame()
    lookup_frame(frame)
    assert "player_name" not in frame.columns
