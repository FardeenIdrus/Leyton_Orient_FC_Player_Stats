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
