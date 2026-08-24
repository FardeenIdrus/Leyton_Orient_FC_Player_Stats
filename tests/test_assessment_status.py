"""Deriving one assessment status per player-season, for the watchlist and the Players list.

The status is DERIVED by joining on the same (player, competition, season) triple both
tables already use -- no new column, no new table, and therefore no way for the watchlist
and the profile to disagree."""

import pandas as pd

from lofc.model import assessment_status as astat
from lofc.model import scout_scores

KEY = ["player_id", "competition_id", "season_id"]


def _rows(*rows) -> pd.DataFrame:
    return pd.DataFrame(list(rows),
                        columns=KEY + ["dimension", "band", "status", "updated_at"])


def test_a_player_with_no_assessment_is_absent():
    result = astat.per_player(_rows())
    assert result.empty
    assert "assessment_status" in result.columns


def test_one_dimension_only_is_still_awaiting_sign_off_not_signed_off():
    """A single submitted dimension is real work and must show as such -- but it is not
    signed off, and assessed_composite stays NULL until BOTH exist (Decision 9)."""
    result = astat.per_player(_rows(
        (1, 4, 318, scout_scores.PSYCHOLOGICAL, 4.0, "submitted", "2026-08-14")))
    assert result.iloc[0]["assessment_status"] == "Awaiting sign-off"


def test_both_dimensions_signed_off_is_signed_off():
    result = astat.per_player(_rows(
        (1, 4, 318, scout_scores.PSYCHOLOGICAL, 4.0, "signed_off", "2026-08-14"),
        (1, 4, 318, scout_scores.MEDICAL, 3.0, "signed_off", "2026-08-14")))
    assert result.iloc[0]["assessment_status"] == "Signed off"


def test_one_signed_off_and_one_submitted_is_awaiting_sign_off():
    """The weaker of the two governs. Reporting 'Signed off' when half the assessment is
    still unreviewed would overstate what a director is being shown."""
    result = astat.per_player(_rows(
        (1, 4, 318, scout_scores.PSYCHOLOGICAL, 4.0, "signed_off", "2026-08-14"),
        (1, 4, 318, scout_scores.MEDICAL, 3.0, "submitted", "2026-08-14")))
    assert result.iloc[0]["assessment_status"] == "Awaiting sign-off"


def test_drafts_alone_do_not_count_as_assessed():
    """Decision 14: a draft never scores. It must not read as assessed either."""
    result = astat.per_player(_rows(
        (1, 4, 318, scout_scores.PSYCHOLOGICAL, None, "draft", "2026-08-14")))
    assert result.empty


def test_statuses_are_separate_per_season():
    """A player assessed in 25/26 must not show as assessed in 26/27."""
    result = astat.per_player(_rows(
        (1, 4, 318, scout_scores.PSYCHOLOGICAL, 4.0, "submitted", "2026-08-14"),
        (1, 4, 318, scout_scores.MEDICAL, 3.0, "submitted", "2026-08-14")))
    assert len(result) == 1
    assert result.iloc[0]["season_id"] == 318


def test_two_disagreeing_submitted_rows_read_as_conflicted():
    """Task 10 B1: the aggregate must surface a Decision 17 conflict, not silently collapse
    it into 'Awaiting sign-off' -- the watchlist badge has to say the same thing the profile
    and the sign-off queue say."""
    result = astat.per_player(_rows(
        (1, 4, 318, scout_scores.PSYCHOLOGICAL, 4.0, "submitted", "2026-08-14"),
        (1, 4, 318, scout_scores.PSYCHOLOGICAL, 2.0, "submitted", "2026-08-15"),
        (1, 4, 318, scout_scores.MEDICAL, 3.0, "submitted", "2026-08-14")))
    assert result.iloc[0]["assessment_status"] == astat.CONFLICTED


def test_a_signed_off_dimension_beside_a_conflicted_one_still_reads_as_conflicted():
    """Conflict takes priority: Medical being resolved doesn't hide that Psychological is
    still contested and unscored."""
    result = astat.per_player(_rows(
        (1, 4, 318, scout_scores.PSYCHOLOGICAL, 4.0, "submitted", "2026-08-14"),
        (1, 4, 318, scout_scores.PSYCHOLOGICAL, 2.0, "submitted", "2026-08-15"),
        (1, 4, 318, scout_scores.MEDICAL, 3.0, "signed_off", "2026-08-14")))
    assert result.iloc[0]["assessment_status"] == astat.CONFLICTED


def test_a_signed_off_assessment_is_never_itself_a_conflict():
    """Decision 17: signing one off resolves the disagreement -- a signed-off dimension
    beside other unsigned ones on the SAME dimension is not a conflict."""
    result = astat.per_player(_rows(
        (1, 4, 318, scout_scores.PSYCHOLOGICAL, 4.0, "signed_off", "2026-08-14"),
        (1, 4, 318, scout_scores.PSYCHOLOGICAL, 2.0, "submitted", "2026-08-15"),
        (1, 4, 318, scout_scores.MEDICAL, 3.0, "submitted", "2026-08-14")))
    assert result.iloc[0]["assessment_status"] == astat.AWAITING


def test_a_signed_off_dimension_beside_a_superseded_submission_still_reads_as_signed_off():
    """Reproduced live: player 80945, competition 5, season 318 -- both dimensions were
    signed off, but `resolve_bands` returns 'both signed off' while the old raw-group check
    saw a newer, superseded `submitted` row sitting beside the signed-off Psychological
    assessment and flipped the aggregate to Awaiting sign-off. Decision 17: a signed-off row
    beats any number of submitted ones on the same dimension, so this must read Signed off,
    matching the profile (which resolves via `resolve_bands` too) and unhiding the player
    from the 'Signed-off assessments only' filter."""
    result = astat.per_player(_rows(
        (1, 4, 318, scout_scores.PSYCHOLOGICAL, 4.0, "signed_off", "2026-08-01"),
        (1, 4, 318, scout_scores.PSYCHOLOGICAL, 3.0, "submitted", "2026-08-14"),
        (1, 4, 318, scout_scores.MEDICAL, 3.0, "signed_off", "2026-08-01")))
    assert result.iloc[0]["assessment_status"] == astat.SIGNED_OFF


def test_attach_leaves_unassessed_rows_as_not_assessed():
    frame = pd.DataFrame([{"player_id": 1, "competition_id": 4, "season_id": 318},
                          {"player_id": 2, "competition_id": 4, "season_id": 318}])
    statuses = astat.per_player(_rows(
        (1, 4, 318, scout_scores.PSYCHOLOGICAL, 4.0, "submitted", "2026-08-14"),
        (1, 4, 318, scout_scores.MEDICAL, 3.0, "submitted", "2026-08-14")))
    merged = astat.attach(frame, statuses)
    assert merged.set_index("player_id").loc[2, "assessment_status"] == "Not assessed"


def test_attach_never_drops_a_row():
    """A LEFT join, not an inner one: filtering the Players list down to assessed players is
    an explicit opt-in mode, never a side effect of showing the badge column."""
    frame = pd.DataFrame([{"player_id": i, "competition_id": 4, "season_id": 318}
                          for i in range(50)])
    merged = astat.attach(frame, astat.per_player(_rows()))
    assert len(merged) == 50


def test_a_rejected_only_dimension_does_not_count_as_assessed():
    """Problem 3: a rejected assessment must not make a player read as assessed -- it is
    excluded the same way a draft is."""
    result = astat.per_player(_rows(
        (1, 4, 318, scout_scores.PSYCHOLOGICAL, 2.0, "rejected", "2026-08-14")))
    assert result.empty


def test_a_rejected_assessment_beside_a_submitted_one_still_reads_as_awaiting():
    """The rejected row simply drops out -- the remaining submitted assessment scores this
    dimension normally, same as if the rejected one had never existed."""
    result = astat.per_player(_rows(
        (1, 4, 318, scout_scores.PSYCHOLOGICAL, 2.0, "rejected", "2026-08-14"),
        (1, 4, 318, scout_scores.PSYCHOLOGICAL, 4.0, "submitted", "2026-08-15")))
    assert result.iloc[0]["assessment_status"] == astat.AWAITING
