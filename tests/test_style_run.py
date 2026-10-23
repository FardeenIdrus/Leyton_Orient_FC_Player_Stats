"""The pipeline step that stores every player's style signals (`player_style_signals`).

Season totals are rebuilt exactly as `impect_translate` rebuilds per-90 metrics: Impect's
per-match averages x matchShare, summed over the player's position rows; minutes are
playDuration (seconds) / 60, summed. Values are stored raw; percentiles are taken when the
page loads, so a style always uses the current minutes and positions.
"""

import pandas as pd
import pytest

from lofc.model import style_run


def _raw():
    # one player, two position rows (he played left wing and right wing)
    return pd.DataFrame({
        "playerId": [7, 7], "position": ["LEFT_WINGER", "RIGHT_WINGER"],
        "matchShare": [2.0, 1.0], "playDuration": [10_800.0, 5_400.0],   # 180 + 90 minutes
        "OFFENSIVE_TOUCHES": [40.0, 10.0], "SHOT_AT_GOAL_NUMBER": [2.0, 4.0],
        "WON_AERIAL_DUELS": [1.0, 1.0], "LOST_AERIAL_DUELS": [1.0, 0.0],
    })


def test_totals_are_value_times_match_share_summed_over_position_rows():
    totals, minutes = style_run.season_totals(_raw())
    assert totals.loc[7, "OFFENSIVE_TOUCHES"] == 90.0          # 40*2 + 10*1
    assert totals.loc[7, "SHOT_AT_GOAL_NUMBER"] == 8.0         # 2*2 + 4*1
    assert minutes.loc[7] == 270.0


def test_signals_come_from_the_season_totals():
    totals, minutes = style_run.season_totals(_raw())
    sig = style_run.season_signals(totals, minutes)
    assert sig.loc[7, "shots_per_touch"] == pytest.approx(8 / 90)
    assert sig.loc[7, "aerial_contested_p90"] == pytest.approx((3 + 2) * 90 / 270)


def test_the_long_frame_keeps_only_linked_players_and_known_values():
    sig = pd.DataFrame({"shots_per_touch": [0.1, 0.2, None]}, index=[7, 8, 9])
    ids = pd.Series({7: 2_000_000_007, 9: 2_000_000_009})   # 8 is not linked to our players
    out = style_run.to_long(sig, ids, competition_id=4, season_id=318)
    assert out.to_dict("records") == [
        {"player_id": 2_000_000_007, "competition_id": 4, "season_id": 318,
         "signal": "shots_per_touch", "value": 0.1}]


def test_two_impect_records_for_one_of_our_players_keep_the_one_with_more_minutes():
    """A duplicate in Impect's feed must not write two rows for one player."""
    sig = pd.DataFrame({"shots_per_touch": [0.1, 0.2]}, index=[7, 8])
    ids = pd.Series({7: 100, 8: 100})
    minutes = pd.Series({7: 900.0, 8: 300.0})
    out = style_run.to_long(sig, ids, 4, 318, minutes=minutes)
    assert out["value"].tolist() == [0.1]


def test_the_pipeline_stores_style_signals_after_the_metric_table():
    """It links players through build_neutral's identities, so it must run after it."""
    from lofc.pipeline import build_steps
    labels = [label for label, _ in build_steps()]
    style = next(i for i, l in enumerate(labels) if "style signals" in l.lower())
    neutral = next(i for i, l in enumerate(labels) if "neutral metric table" in l.lower())
    assert style > neutral
