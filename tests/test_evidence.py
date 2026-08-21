"""The evidence panel's pure logic: which spells count, what each caption says. The Streamlit
rendering is not tested; every decision the panel makes lives in these functions."""

import pandas as pd
import pytest

from lofc.dashboard import evidence
from lofc.model.medical import AvailabilityEvidence, AvailabilityStatus

WINDOW = ("24/25", "25/26")


def _spells(*rows) -> pd.DataFrame:
    return pd.DataFrame(list(rows), columns=["season_label", "injury_type_raw",
                                             "injury_category", "date_from", "date_until",
                                             "days_out", "games_missed", "source"])


def test_spell_rows_marks_in_window_spells():
    frame = evidence.spell_rows(
        _spells(("25/26", "Ankle injury", "ankle", "2025-10-01", "2025-12-01", 61, 9,
                 "transfermarkt")), WINDOW)
    assert frame["in_window"].tolist() == [True]


def test_spell_rows_keeps_out_of_window_spells_and_marks_them():
    """Shown greyed, never hidden -- a scout wants the history even when the figure does not
    count it (spec section 6, point 3)."""
    frame = evidence.spell_rows(
        _spells(("22/23", "Broken leg", "leg", "2022-09-01", "2023-02-01", 153, 22,
                 "transfermarkt")), WINDOW)
    assert len(frame) == 1
    assert frame["in_window"].tolist() == [False]


def test_spell_rows_handles_an_empty_history():
    frame = evidence.spell_rows(_spells(), WINDOW)
    assert frame.empty
    assert "in_window" in frame.columns


def test_spell_rows_preserves_provenance():
    frame = evidence.spell_rows(
        _spells(("25/26", "Knock", "other", "2025-10-01", "2025-10-08", 7, 1, "manual")),
        WINDOW)
    assert frame["source"].tolist() == ["manual"]


def test_source_labels_name_the_actual_source_not_internal_jargon():
    """"Scraped" was internal jargon on a panel that appears in reports leaving the
    building; the label must name the real source instead, and the two sources must
    still read as distinct from one another."""
    assert evidence.SOURCE_LABELS["transfermarkt"] == "Transfermarkt"
    assert evidence.SOURCE_LABELS["manual"] == "Entered by hand"
    assert evidence.SOURCE_LABELS["transfermarkt"] != evidence.SOURCE_LABELS["manual"]
    assert "scraped" not in evidence.SOURCE_LABELS["transfermarkt"].lower()


def test_availability_caption_says_measured_with_the_window():
    ev = AvailabilityEvidence(status=AvailabilityStatus.MEASURED, value=0.87)
    caption = evidence.availability_caption(ev, WINDOW)
    assert "87%" in caption
    assert "24/25" in caption and "25/26" in caption


def test_availability_caption_for_unknown_never_says_clean():
    """The single most important line on the panel. A blank record must never read as a
    perfect one -- that is defect R8, and this caption is what closes it on screen."""
    ev = AvailabilityEvidence(status=AvailabilityStatus.UNKNOWN, value=None)
    caption = evidence.availability_caption(ev, WINDOW)
    assert "Not known" in caption
    assert "100%" not in caption
    assert "1.0" not in caption


def test_availability_caption_for_confirmed_by_minutes_says_why():
    ev = AvailabilityEvidence(status=AvailabilityStatus.CONFIRMED_BY_MINUTES, value=1.0)
    caption = evidence.availability_caption(ev, WINDOW)
    assert "minutes" in caption.lower()


def test_availability_caption_for_measured_but_unscored_league_explains_itself():
    """MEASURED with value None means the league has no scheduled-games constant -- there IS
    injury evidence, but no denominator. Distinct from UNKNOWN, and must not read as it."""
    ev = AvailabilityEvidence(status=AvailabilityStatus.MEASURED, value=None)
    caption = evidence.availability_caption(ev, WINDOW)
    assert "not scored" in caption.lower()
    assert "Not known" not in caption


def test_coverage_caption_names_the_league_share():
    caption = evidence.coverage_caption(4)          # League One
    assert "39%" in caption


def test_coverage_caption_for_a_thin_league_is_blunt():
    caption = evidence.coverage_caption(65)         # National League
    assert "18%" in caption


def test_coverage_caption_handles_an_unmapped_competition():
    caption = evidence.coverage_caption(999999)
    assert caption
    assert "no coverage figure" in caption.lower()


def test_resolve_window_returns_the_window_for_a_mapped_season():
    assert evidence.resolve_window(318) == ("24/25", "25/26")


def test_resolve_window_returns_none_rather_than_raising_for_an_unmapped_season():
    """CRITICAL 1: `available_seasons()` can offer 317 (2024/25) before `_SEASON_LABELS` has
    the season one step further back (316) that a two-season window needs -- `window_labels`
    then raises. The player profile and the Assess page both call through here, so this must
    come back as a plain None the caller can degrade on, not propagate the exception and take
    the whole page down."""
    assert evidence.resolve_window(317) is None
