"""The shared "what did the scout actually score" component (Problem 2): the pure half only
-- `criterion_rows`, `comparison_table`, `entries_table`, `dimension_status`. The Streamlit
rendering half (`render_flags`, `render_criterion_detail`) is not unit-tested, matching the
rest of the dashboard's render layer."""

import datetime as dt

import pandas as pd

from lofc.dashboard import assessment_detail as ad
from lofc.dashboard import badges
from lofc.model.scout_scores import CONFLICT, MEDICAL, PSYCHOLOGICAL, REJECTED

KEY = ["player_id", "competition_id", "season_id"]


def _assessments(*rows) -> pd.DataFrame:
    frame = pd.DataFrame(list(rows),
                         columns=KEY + ["dimension", "band", "status", "updated_at"])
    frame["updated_at"] = pd.to_datetime(frame["updated_at"])
    return frame


# --- criterion_rows -------------------------------------------------------------------


def test_criterion_rows_lists_every_psychological_criterion_for_the_position():
    rows = ad.criterion_rows("Centre Forward", PSYCHOLOGICAL)
    assert len(rows) == 2
    assert rows[0][1] == "Clinical finishing mentality; converts chances under pressure"


def test_criterion_rows_medical_lists_only_screening_criteria():
    """Availability is a computed figure and protocol is a club process step (Decision 7) --
    neither is ever scored by the assessor, so neither belongs in a comparison table."""
    rows = ad.criterion_rows("Centre Back", MEDICAL)
    keys = [k for k, _ in rows]
    texts = [t for _, t in rows]
    assert not any("availability" in t.lower() for t in texts)
    assert not any("undergo" in t.lower() for t in texts)
    assert len(rows) == 1  # Centre Back medical: one screening criterion (knee ligament)


def test_criterion_rows_unknown_dimension_returns_nothing():
    assert ad.criterion_rows("Centre Back", "Something Else") == []


# --- comparison_table ------------------------------------------------------------------


def test_comparison_table_one_row_per_criterion_one_column_per_entry():
    table = ad.comparison_table(
        "Centre Forward", PSYCHOLOGICAL, ["Scout A — band 5.0", "Scout B — band 2.5"],
        [{"clinical-finishing-mentality-converts-chances-under-pressure": (5, None),
          "work-rate-willingness-presses-without-complaint": (5, None)},
         {"clinical-finishing-mentality-converts-chances-under-pressure": (2, None),
          "work-rate-willingness-presses-without-complaint": (3, None)}])
    assert list(table.columns) == ["Scout A — band 5.0", "Scout B — band 2.5"]
    assert len(table) == 2
    assert table.iloc[0]["Scout A — band 5.0"] == "5"
    assert table.iloc[0]["Scout B — band 2.5"] == "2"


def test_comparison_table_missing_criterion_reads_as_a_dash_not_a_crash():
    table = ad.comparison_table("Centre Forward", PSYCHOLOGICAL, ["Scout A"], [{}])
    assert (table["Scout A"] == "—").all()


def test_comparison_table_medical_shows_meets_or_does_not_meet():
    key = ad.criterion_rows("Centre Back", MEDICAL)[0][0]
    table = ad.comparison_table("Centre Back", MEDICAL, ["Scout A", "Scout B"],
                                [{key: (None, True)}, {key: (None, False)}])
    assert table.iloc[0]["Scout A"] == "Meets"
    assert table.iloc[0]["Scout B"] == "Does not meet"


def test_comparison_table_empty_for_a_dimension_with_no_criteria():
    assert ad.comparison_table("Centre Back", "Something Else", ["Scout A"], [{}]).empty


# --- entries_table -----------------------------------------------------------------------


def _entries_frame(*rows) -> pd.DataFrame:
    frame = pd.DataFrame(list(rows), columns=[
        "author_name", "author_role", "band", "status", "created_at",
        "approver_name", "approved_at"])
    frame["created_at"] = pd.to_datetime(frame["created_at"])
    frame["approved_at"] = pd.to_datetime(frame["approved_at"])
    return frame


def test_entries_table_empty_input_returns_the_right_columns():
    table = ad.entries_table(pd.DataFrame())
    assert list(table.columns) == ["Entered by", "Role", "Band", "Status", "Date"]
    assert table.empty


def test_entries_table_one_row_per_assessment():
    frame = _entries_frame(
        ("Scout One", "scout", 4.0, "submitted", "2026-08-01", None, None))
    table = ad.entries_table(frame)
    assert table.loc[0, "Entered by"] == "Scout One"
    assert table.loc[0, "Band"] == "4.00"
    assert "awaiting sign-off" in table.loc[0, "Status"].lower()


def test_entries_table_band_none_reads_as_a_dash():
    frame = _entries_frame(
        ("Scout One", "scout", None, "draft", "2026-08-01", None, None))
    table = ad.entries_table(frame)
    assert table.loc[0, "Band"] == "—"


def test_entries_table_status_matches_the_badge_module_exactly():
    """The queue and the profile must never describe the same assessment two different ways
    -- this pins that `entries_table` reuses `badges.for_status` rather than inventing its
    own wording."""
    frame = _entries_frame(
        ("Scout One", "scout", 4.0, "signed_off", "2026-08-01", "HoR", "2026-08-05"))
    table = ad.entries_table(frame)
    expected = badges.for_status("signed_off", "Scout One", "HoR",
                                 pd.Timestamp("2026-08-05")).text
    assert table.loc[0, "Status"] == expected


def test_entries_table_rejected_status_reads_as_rejected():
    frame = _entries_frame(
        ("Scout One", "scout", 3.0, REJECTED, "2026-08-01", "HoR", "2026-08-05"))
    table = ad.entries_table(frame)
    assert "rejected" in table.loc[0, "Status"].lower()


# --- dimension_status --------------------------------------------------------------------


def test_dimension_status_returns_none_with_nothing_scoring():
    assert ad.dimension_status(_assessments(), PSYCHOLOGICAL) is None


def test_dimension_status_reads_conflict_from_two_disagreeing_submissions():
    frame = _assessments(
        (1, 4, 318, PSYCHOLOGICAL, 2.0, "submitted", "2026-08-01"),
        (1, 4, 318, PSYCHOLOGICAL, 4.0, "submitted", "2026-08-02"))
    assert ad.dimension_status(frame, PSYCHOLOGICAL) == CONFLICT


def test_dimension_status_a_signed_off_row_beside_extra_submitted_ones_is_not_a_conflict():
    """Decision 17: a signed-off row is never in conflict, even with several newer
    `submitted` re-assessments sitting beside it -- this is exactly the case a naive
    `len(submitted) > 1` check would misclassify."""
    frame = _assessments(
        (1, 4, 318, PSYCHOLOGICAL, 4.0, "signed_off", "2026-08-01"),
        (1, 4, 318, PSYCHOLOGICAL, 2.0, "submitted", "2026-08-05"),
        (1, 4, 318, PSYCHOLOGICAL, 3.0, "submitted", "2026-08-06"))
    assert ad.dimension_status(frame, PSYCHOLOGICAL) == "signed_off"


def test_dimension_status_a_rejected_row_never_creates_a_conflict():
    """A rejected assessment must not count toward Decision 17's disagreement -- rejecting
    one side of a two-way conflict should leave the other as the sole submitted assessment,
    not a lingering conflict against a row that no longer scores."""
    frame = _assessments(
        (1, 4, 318, PSYCHOLOGICAL, 4.0, "submitted", "2026-08-01"),
        (1, 4, 318, PSYCHOLOGICAL, 2.0, REJECTED, "2026-08-02"))
    assert ad.dimension_status(frame, PSYCHOLOGICAL) == "submitted"
