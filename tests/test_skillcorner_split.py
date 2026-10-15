"""SkillCorner physical split by possession phase: in possession (tip) / out of possession (otip).

DISPLAY ONLY -- nothing here reaches the composite.

Volumes are per 90 minutes PLAYED (the all-phase `minutes_full_all`), not per minute in
possession, so in + out sum to roughly the all-phase figure a recruiter already sees.
Measured: in-possession distance is a median 34% of total distance (League One 2025/26).
Metres per minute is already a rate within the phase and is kept as SkillCorner gives it.
"""

import pandas as pd
import pytest

from lofc.ingest.skillcorner_map import PER_APPEARANCE, SPLIT_PHASES, split_to_long


def _frames():
    full = pd.DataFrame({"player_id": [10, 11], "minutes_full_all": [45.0, 90.0]})
    tip = pd.DataFrame({"player_id": [10, 11],
                        "total_distance_full_tip": [1500.0, 3000.0],
                        "total_metersperminute_full_tip": [95.0, 98.0],
                        "sprint_count_full_tip": [2.0, 3.0]})
    return full, tip


def test_phases_are_in_and_out_of_possession():
    assert SPLIT_PHASES == {"tip": "In possession", "otip": "Out of possession"}


def test_volumes_are_per_90_minutes_played():
    full, tip = _frames()
    out = split_to_long(tip, full, "tip").set_index(["sc_player_id", "metric"])
    assert out.loc[(10, "phys_tip.distance_p90"), "value_p90"] == pytest.approx(3000.0)
    assert out.loc[(11, "phys_tip.distance_p90"), "value_p90"] == pytest.approx(3000.0)
    assert out.loc[(10, "phys_tip.sprint_count_p90"), "value_p90"] == pytest.approx(4.0)


def test_metres_per_minute_is_kept_as_given():
    full, tip = _frames()
    out = split_to_long(tip, full, "tip").set_index(["sc_player_id", "metric"])
    assert out.loc[(10, "phys_tip.meters_per_minute"), "value_p90"] == 95.0


def test_only_volume_metrics_and_metres_per_minute_are_produced():
    full, tip = _frames()
    names = {m.split(".", 1)[1] for m in split_to_long(tip, full, "tip")["metric"]}
    assert names <= PER_APPEARANCE | {"meters_per_minute"}


def test_a_player_missing_from_the_full_file_gets_no_values():
    full, tip = _frames()
    out = split_to_long(tip, full[full.player_id == 11], "tip")
    assert set(out["sc_player_id"]) == {11}
