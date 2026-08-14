"""Tests for the StatsBomb season-stats gap wiring. No network, no database."""

import pandas as pd

from lofc.ingest.statsbomb_season import STATSBOMB_GAP_MAP, translate_frame


def test_gap_map_covers_the_true_gaps_only():
    # These are the metrics Impect has no equivalent for (post-verification).
    assert set(STATSBOMB_GAP_MAP) == {
        "pressures_opp_half_p90", "aggressive_actions_p90",
        "padj_tackles_interceptions_p90", "padj_pressures_p90",
        "xg_buildup_p90", "pressured_pass_pct", "successful_box_cross_pct",
        "dribbles_p90", "dribble_success_pct", "gk_claims_pct",
        "gk_aggressive_distance", "long_ball_pct",
    }


def _endpoint_row(player_id, minutes, xgbuildup, aggressive=5.0):
    return {"player_id": player_id, "player_season_minutes": minutes,
            "player_season_fhalf_pressures_90": 4.2,
            "player_season_aggressive_actions_90": aggressive,
            "player_season_padj_tackles_and_interceptions_90": 3.3,
            "player_season_padj_pressures_90": 20.5,
            "player_season_xgbuildup_90": xgbuildup,
            "player_season_pressured_passing_ratio": 0.71,
            "player_season_box_cross_ratio": 0.18,
            "player_season_total_dribbles_90": 2.4,
            "player_season_dribble_ratio": 0.55,
            "player_season_clcaa": 0.8,
            "player_season_da_aggressive_distance": 12.5,
            "player_season_long_ball_ratio": 0.6}


def test_translate_renames_and_keys():
    frame = pd.DataFrame([_endpoint_row(405034, 2000, 0.44, aggressive=6.1)])
    out = translate_frame(frame, competition_id=4, season_id=318)
    assert out.at[0, "player_id"] == 405034
    assert out.at[0, "competition_id"] == 4 and out.at[0, "season_id"] == 318
    assert out.at[0, "xg_buildup_p90"] == 0.44
    assert out.at[0, "aggressive_actions_p90"] == 6.1
    # our internal names present; raw StatsBomb names not
    assert "player_season_xgbuildup_90" not in out.columns


def test_mid_season_mover_is_minutes_weighted_into_one_row():
    # Same player, two clubs: 1000 min @ xgbuildup 0.6 and 500 min @ 0.3
    # -> one row, weighted mean = (0.6*1000 + 0.3*500)/1500 = 0.5.
    frame = pd.DataFrame([_endpoint_row(7, 1000, 0.6), _endpoint_row(7, 500, 0.3)])
    out = translate_frame(frame, 4, 318)
    assert len(out) == 1
    assert out.at[0, "xg_buildup_p90"] == pytest_approx(0.5)


def test_translate_fills_missing_column_with_na():
    frame = pd.DataFrame([{"player_id": 1, "player_season_minutes": 900,
                           "player_season_aggressive_actions_90": 5.0}])
    out = translate_frame(frame, 4, 318)
    assert out.at[0, "aggressive_actions_p90"] == 5.0
    assert pd.isna(out.at[0, "xg_buildup_p90"])


def pytest_approx(x, tol=1e-6):
    import pytest
    return pytest.approx(x, abs=tol)
