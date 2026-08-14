"""Turning many submitted assessments into one scoring band per dimension."""

import pandas as pd

from lofc.model.scout_scores import resolve_bands

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


def test_the_most_recent_submitted_wins_when_none_is_signed_off():
    out = resolve_bands(_rows(
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=2.0, status="submitted", updated_at="2026-08-01"),
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=4.5, status="submitted", updated_at="2026-08-09"),
    ))
    assert out.loc[0, "psychological_band"] == 4.5


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
