"""SkillCorner volume metrics are PER APPEARANCE and must be converted to per 90.

`*_full_all` is an average per match PLAYED, over the minutes actually played -- not a
per-90 figure. Measured on the raw pull (6,378 player-seasons): minutes per appearance
explains 97% of the variance in "distance per match" (r = +0.98). A player averaging
69 minutes was credited with 69 minutes of running, so the Physical dimension ranked
starters above substitutes rather than work rate above work rate.

Converted with `minutes_full_all` (average minutes per appearance): value / minutes * 90.
Among 450+ minute players this takes distance's minutes correlation from +0.97 to -0.26,
the same size as metres-per-minute (-0.26), a rate the score already used.
"""

import inspect
import math

import pandas as pd
import pytest

from lofc.ingest import skillcorner_map as scm
from lofc.ingest.skillcorner_map import PER_APPEARANCE, to_per90

VOLUMES = {
    "distance_p90", "running_distance_p90", "hsr_distance_p90", "sprint_distance_p90",
    "hi_distance_p90", "hsr_count_p90", "sprint_count_p90", "hi_count_p90", "cod_count_p90",
    "medium_accel_count_p90", "high_accel_count_p90", "medium_decel_count_p90",
    "high_decel_count_p90", "explosive_accel_to_hsr_p90", "explosive_accel_to_sprint_p90",
}
UNCHANGED = {"meters_per_minute", "psv99_kmh", "top5_psv99_kmh", "time_to_hsr",
             "time_to_hsr_post_cod", "time_to_sprint", "time_to_sprint_post_cod",
             "agility_505_90", "agility_505_180"}


def test_every_volume_metric_is_converted_and_nothing_else():
    assert PER_APPEARANCE == VOLUMES


def test_the_map_is_fully_classified():
    assert PER_APPEARANCE | UNCHANGED == {m.name for m in scm.SKILLCORNER_MAP}


def test_a_volume_is_scaled_to_90_minutes():
    frame = pd.DataFrame({"minutes_full_all": [45.0, 90.0], "distance_p90": [5000.0, 10000.0],
                          "sprint_count_p90": [10.0, 10.0]})
    out = to_per90(frame)
    assert out["distance_p90"].tolist() == [10000.0, 10000.0]
    assert out["sprint_count_p90"].tolist() == [20.0, 10.0]


def test_rates_peaks_and_timings_are_untouched():
    frame = pd.DataFrame({"minutes_full_all": [45.0], "meters_per_minute": [111.0],
                          "psv99_kmh": [31.0], "time_to_sprint": [2.1]})
    out = to_per90(frame)
    assert out["meters_per_minute"].iloc[0] == 111.0
    assert out["psv99_kmh"].iloc[0] == 31.0
    assert out["time_to_sprint"].iloc[0] == 2.1


@pytest.mark.parametrize("minutes", [0.0, None])
def test_no_minutes_gives_no_value_not_infinity(minutes):
    out = to_per90(pd.DataFrame({"minutes_full_all": [minutes], "distance_p90": [5000.0]}))
    assert math.isnan(out["distance_p90"].iloc[0])


def test_input_frame_is_not_mutated():
    frame = pd.DataFrame({"minutes_full_all": [45.0], "distance_p90": [5000.0]})
    to_per90(frame)
    assert frame["distance_p90"].iloc[0] == 5000.0


def test_the_neutral_build_applies_the_conversion():
    from lofc.model import build_neutral
    assert "to_per90" in inspect.getsource(build_neutral.load_skillcorner)
