"""Tests for the Impect -> internal per-90 translation. No network, no database.

Covers the two corrections the translator exists for (per-90 from Impect's
per-match averages, and the minutes floor) plus the ratio path and multi-position
aggregation. Columns the map references but the test omits default to 0, so a
minimal frame is enough.
"""

import numpy as np
import pandas as pd

from lofc.ingest.impect_map import IMPECT_MAP, gaps, impect_columns_used, mappable
from lofc.ingest.impect_translate import translate_frame


def _row(**kw):
    base = {"playerId": 1, "playerName": "Test Player", "birthdate": "2000-01-01",
            "squadName": "Club", "position": "CENTER_FORWARD",
            "matchShare": 0.0, "playDuration": 0.0}
    base.update(kw)
    return base


def test_per90_from_per_match_average():
    # 0.6 goals per match x 30 matches = 18 season goals over 3000 minutes
    # -> 18 / 3000 * 90 = 0.54 per 90.
    frame = pd.DataFrame([_row(matchShare=30.0, playDuration=180000.0, GOALS=0.6)])
    out = translate_frame(frame, competition_id=4, season_id=318)
    assert out.at[0, "minutes"] == 3000.0
    assert out.at[0, "goals_p90"] == pytest_approx(0.54)
    assert bool(out.at[0, "rankable"]) is True
    assert out.at[0, "competition_id"] == 4 and out.at[0, "season_id"] == 318


def test_minutes_floor_flags_small_samples():
    # 300 minutes (< 450) must be non-rankable, even with a flashy rate.
    frame = pd.DataFrame([_row(matchShare=3.0, playDuration=18000.0, GOALS=0.6)])
    out = translate_frame(frame)
    assert out.at[0, "minutes"] == 300.0
    assert bool(out.at[0, "rankable"]) is False


def test_ratio_is_matchshare_weighted_and_scale_free():
    # 40 successful, 10 unsuccessful per match -> 0.8 completion, regardless of
    # matchShare (it cancels in a ratio).
    frame = pd.DataFrame([_row(matchShare=25.0, playDuration=150000.0,
                               SUCCESSFUL_PASSES=40.0, UNSUCCESSFUL_PASSES=10.0)])
    out = translate_frame(frame)
    assert out.at[0, "pass_completion_pct"] == pytest_approx(0.8)


def test_multi_position_rows_aggregate():
    # Same player across two positions: goals total 0.6*20 + 0.0*5 = 12 over
    # (120000+30000)/60 = 2500 minutes -> 12/2500*90 = 0.432.
    frame = pd.DataFrame([
        _row(playerId=7, matchShare=20.0, playDuration=120000.0, GOALS=0.6,
             position="CENTER_FORWARD"),
        _row(playerId=7, matchShare=5.0, playDuration=30000.0, GOALS=0.0,
             position="LEFT_WINGER"),
    ])
    out = translate_frame(frame)
    assert len(out) == 1
    assert out.at[0, "minutes"] == 2500.0
    assert out.at[0, "goals_p90"] == pytest_approx(0.432)
    assert out.at[0, "position"] == "CENTER_FORWARD"   # dominant by matchShare


def test_club_shown_is_by_total_minutes_not_single_row_matchshare():
    # A player who splits a season across two clubs (a real case: Dan Crowley, League
    # Two 2024/25 -- 1,662 min at Notts County concentrated in one position row with a
    # big matchShare, 1,710 min at Milton Keynes Dons split across two rows each with a
    # smaller individual matchShare). The naive per-row matchShare-argmax picks the
    # club with FEWER total minutes, because matchShare doesn't respect a mid-season
    # move; summing playDuration per squad first gets the club right.
    frame = pd.DataFrame([
        _row(playerId=1, squadName="Club A", position="CENTRAL_MIDFIELD",
             matchShare=9.0, playDuration=56000.0),
        _row(playerId=1, squadName="Club B", position="CENTRAL_MIDFIELD",
             matchShare=4.5, playDuration=28000.0),
        _row(playerId=1, squadName="Club B", position="DEFENSE_MIDFIELD",
             matchShare=5.5, playDuration=34000.0),
    ])
    out = translate_frame(frame)
    assert out.at[0, "team_name"] == "Club B"                 # more total minutes
    assert out.at[0, "position"] == "CENTRAL_MIDFIELD"        # identity untouched: still matchShare-dominant row
    assert out.at[0, "minutes"] == pytest_approx((56000.0 + 28000.0 + 34000.0) / 60.0)


def test_none_metrics_are_not_produced():
    frame = pd.DataFrame([_row(matchShare=30.0, playDuration=180000.0, GOALS=0.5)])
    out = translate_frame(frame)
    for m in gaps():
        assert m.name not in out.columns          # StatsBomb-only, never from Impect
    for m in mappable():
        assert m.name in out.columns              # every mappable metric present


def test_map_has_no_duplicate_names():
    names = [m.name for m in IMPECT_MAP]
    assert len(names) == len(set(names))


# tiny local approx helper so the test file needs no extra import symbol
def pytest_approx(x, tol=1e-6):
    import pytest
    return pytest.approx(x, abs=tol)
