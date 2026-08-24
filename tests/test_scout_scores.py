"""Turning many submitted assessments into one scoring band per dimension."""

import pandas as pd

from lofc.model.scout_scores import CONFLICT, resolve_bands

PSY, MED = "Psychological", "Medical Risk"


def _rows(*records) -> pd.DataFrame:
    frame = pd.DataFrame(list(records))
    frame["updated_at"] = pd.to_datetime(frame["updated_at"])
    return frame


def test_a_submitted_assessment_scores_without_sign_off():
    # Decision 14: sign-off is not a gate on scoring.
    out = resolve_bands(_rows(
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=3.8, status="submitted", updated_at="2026-08-01"),
        dict(player_id=1, competition_id=4, season_id=318, dimension=MED,
             band=3.0, status="submitted", updated_at="2026-08-01"),
    ))
    assert out.loc[0, "psychological_band"] == 3.8
    assert out.loc[0, "medical_band"] == 3.0
    assert out.loc[0, "psychological_status"] == "submitted"


def test_a_signed_off_assessment_beats_a_newer_submitted_one():
    out = resolve_bands(_rows(
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=4.0, status="signed_off", updated_at="2026-08-01"),
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=2.0, status="submitted", updated_at="2026-08-09"),
    ))
    assert out.loc[0, "psychological_band"] == 4.0
    assert out.loc[0, "psychological_status"] == "signed_off"


def test_a_draft_never_scores():
    out = resolve_bands(_rows(
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=5.0, status="draft", updated_at="2026-08-09"),
    ))
    assert out.empty or pd.isna(out.loc[0, "psychological_band"])


def test_the_two_dimensions_resolve_independently():
    out = resolve_bands(_rows(
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=3.0, status="submitted", updated_at="2026-08-01"),
        dict(player_id=1, competition_id=4, season_id=318, dimension=MED,
             band=2.0, status="signed_off", updated_at="2026-08-02"),
    ))
    assert out.loc[0, "psychological_status"] == "submitted"
    assert out.loc[0, "medical_status"] == "signed_off"


def test_the_same_player_in_two_seasons_resolves_separately():
    out = resolve_bands(_rows(
        dict(player_id=1, competition_id=4, season_id=317, dimension=PSY,
             band=2.0, status="submitted", updated_at="2026-08-01"),
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=4.0, status="submitted", updated_at="2026-08-01"),
    )).set_index("season_id")
    assert out.loc[317, "psychological_band"] == 2.0
    assert out.loc[318, "psychological_band"] == 4.0


def test_an_empty_frame_returns_an_empty_result_with_the_right_columns():
    out = resolve_bands(pd.DataFrame(columns=[
        "player_id", "competition_id", "season_id", "dimension",
        "band", "status", "updated_at"]))
    assert out.empty
    assert {"psychological_band", "medical_band"} <= set(out.columns)


def test_an_unrecognised_dimension_is_skipped_not_filed_as_medical():
    # Regression: an if/else previously treated anything that wasn't exactly
    # "Psychological" as Medical Risk, so a typo (lowercase "psychological") would
    # silently land in medical_band instead of being caught. dimension has no
    # database CHECK constraint, so this is one typo away from mis-filing every
    # psychological assessment as medical.
    out = resolve_bands(_rows(
        dict(player_id=1, competition_id=4, season_id=318, dimension="psychological",
             band=4.0, status="submitted", updated_at="2026-08-01"),
    ))
    assert out.empty or (
        pd.isna(out.loc[0, "psychological_band"]) and pd.isna(out.loc[0, "medical_band"])
    )


def test_a_null_band_on_the_winning_assessment_yields_nan_not_a_crash():
    # An assessment can exist without a band while it is still being filled in.
    out = resolve_bands(_rows(
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=None, status="submitted", updated_at="2026-08-01"),
    ))
    assert pd.isna(out.loc[0, "psychological_band"])
    assert out.loc[0, "psychological_status"] == "submitted"


def test_identical_approval_times_among_signed_off_resolve_deterministically():
    # Not which one wins -- only that a tie on updated_at among signed-off rows doesn't
    # crash and doesn't vary between runs (stable sort takes the last row). Recency no
    # longer decides anything among *submitted* rows (see below), but a tie strictly
    # within the signed-off pool is still just a tiebreak, not the deciding rule.
    out = resolve_bands(_rows(
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=3.0, status="signed_off", updated_at="2026-08-01"),
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=4.0, status="signed_off", updated_at="2026-08-01"),
    ))
    assert out.loc[0, "psychological_band"] == 4.0
    assert out.loc[0, "psychological_status"] == "signed_off"


# --- Decision 17: conflict resolution -----------------------------------------------


def test_one_submitted_assessment_still_scores():
    """Unchanged: no disagreement, nothing to decide."""
    out = resolve_bands(_rows(
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=3.5, status="submitted", updated_at="2026-08-01"),
    ))
    assert out.loc[0, "psychological_band"] == 3.5
    assert out.loc[0, "psychological_status"] == "submitted"


def test_two_submitted_assessments_do_not_score():
    """Decision 17. Replaces the old 'most recent wins' tiebreak -- a junior scout assessing
    later must not silently override a senior's earlier assessment."""
    out = resolve_bands(_rows(
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=2.0, status="submitted", updated_at="2026-08-01"),
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=4.5, status="submitted", updated_at="2026-08-09"),
    ))
    assert pd.isna(out.loc[0, "psychological_band"])
    assert out.loc[0, "psychological_status"] == CONFLICT


def test_two_submitted_assessments_conflict_even_when_close():
    """3.0 and 3.5 is still two people who have not agreed. No threshold anywhere."""
    out = resolve_bands(_rows(
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=3.0, status="submitted", updated_at="2026-08-01"),
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=3.5, status="submitted", updated_at="2026-08-02"),
    ))
    assert pd.isna(out.loc[0, "psychological_band"])
    assert out.loc[0, "psychological_status"] == CONFLICT


def test_a_signed_off_assessment_beats_any_number_of_submitted_ones():
    """A signed-off assessment is never in conflict."""
    out = resolve_bands(_rows(
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=4.0, status="signed_off", updated_at="2026-08-01"),
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=1.0, status="submitted", updated_at="2026-08-05"),
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=5.0, status="submitted", updated_at="2026-08-06"),
    ))
    assert out.loc[0, "psychological_band"] == 4.0
    assert out.loc[0, "psychological_status"] == "signed_off"


def test_the_most_recently_approved_signed_off_assessment_wins():
    """Two signed-off assessments are not a conflict: signing off is deliberate, so a later
    one is a considered revision, not an accidental race between scouts."""
    out = resolve_bands(_rows(
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=2.0, status="signed_off", updated_at="2026-08-01"),
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=4.0, status="signed_off", updated_at="2026-08-10"),
    ))
    assert out.loc[0, "psychological_band"] == 4.0
    assert out.loc[0, "psychological_status"] == "signed_off"


def test_a_conflict_on_one_dimension_does_not_affect_the_other():
    """Psychological and Medical resolve independently."""
    out = resolve_bands(_rows(
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=2.0, status="submitted", updated_at="2026-08-01"),
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=4.0, status="submitted", updated_at="2026-08-02"),
        dict(player_id=1, competition_id=4, season_id=318, dimension=MED,
             band=3.0, status="submitted", updated_at="2026-08-01"),
    ))
    assert pd.isna(out.loc[0, "psychological_band"])
    assert out.loc[0, "psychological_status"] == CONFLICT
    assert out.loc[0, "medical_band"] == 3.0
    assert out.loc[0, "medical_status"] == "submitted"


def test_drafts_never_create_a_conflict():
    """Rule 5: two drafts plus one submitted is one scoring assessment, not a conflict."""
    out = resolve_bands(_rows(
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=1.0, status="draft", updated_at="2026-08-01"),
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=5.0, status="draft", updated_at="2026-08-02"),
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=3.0, status="submitted", updated_at="2026-08-03"),
    ))
    assert out.loc[0, "psychological_band"] == 3.0
    assert out.loc[0, "psychological_status"] == "submitted"


def test_recency_no_longer_decides_anything():
    """Guard against the old rule being reintroduced. Two submitted assessments with
    different updated_at values must BOTH fail to score -- if the newer one wins, the
    recency tiebreak is back."""
    out = resolve_bands(_rows(
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=2.0, status="submitted", updated_at="2026-01-01"),
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=4.5, status="submitted", updated_at="2026-08-15"),
    ))
    assert pd.isna(out.loc[0, "psychological_band"])
    assert out.loc[0, "psychological_status"] == CONFLICT


def test_a_rejected_assessment_never_scores():
    """Problem 3: rejecting is a terminal review outcome, not a fourth status this module
    resolves among -- it must behave exactly like a draft here: absent."""
    out = resolve_bands(_rows(
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=5.0, status="rejected", updated_at="2026-08-09"),
    ))
    assert out.empty or pd.isna(out.loc[0, "psychological_band"])


def test_a_rejected_assessment_does_not_keep_a_conflict_alive():
    """Rejecting one side of a two-way disagreement must leave the other as the sole
    submitted assessment, scoring normally -- not a lingering conflict against a row that no
    longer counts."""
    out = resolve_bands(_rows(
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=4.0, status="submitted", updated_at="2026-08-01"),
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=2.0, status="rejected", updated_at="2026-08-02"),
    ))
    assert out.loc[0, "psychological_band"] == 4.0
    assert out.loc[0, "psychological_status"] == "submitted"
