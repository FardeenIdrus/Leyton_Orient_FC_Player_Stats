"""SkillCorner possession splits land beside the all-phase file, same live-season rules.
No network: the client is stubbed."""

import pandas as pd
import pytest

from lofc.config import SkillCornerTarget
from lofc.ingest import skillcorner_api as sc

LIVE, FINISHED = 319, 318


@pytest.fixture
def landed(tmp_path, monkeypatch):
    monkeypatch.setattr(sc.landing, "raw_root", lambda: tmp_path)
    monkeypatch.setattr(type(sc.settings), "live_season_id", property(lambda self: LIVE))
    return tmp_path


class _Client:
    def __init__(self):
        self.params = []

    def get_physical(self, params):
        self.params.append(params)
        return [{"player_id": 1, "total_distance_full_tip": 3000.0}]


def _target(season_id):
    return SkillCornerTarget(edition_id=9101, label="T", competition_id=4, season_id=season_id)


@pytest.mark.parametrize("phase", ["tip", "otip"])
def test_split_asks_for_the_phase_and_lands_at_its_own_path(landed, phase):
    client = _Client()
    assert sc.pull_split(_target(FINISHED), client, phase) is True
    assert client.params[0]["possession"] == phase
    assert sc.split_path(9101, phase).exists()
    assert sc.split_path(9101, phase) != sc.physical_path(9101)


def test_finished_split_is_not_repulled(landed):
    client = _Client()
    sc.pull_split(_target(FINISHED), client, "tip")
    assert sc.pull_split(_target(FINISHED), client, "tip") is False


def test_live_split_always_repulls(landed):
    client = _Client()
    sc.pull_split(_target(LIVE), client, "tip")
    sc.pull_split(_target(LIVE), client, "tip")
    assert len(client.params) == 2


def test_the_all_phase_pull_sends_no_possession_parameter(landed):
    client = _Client()
    sc.pull_edition(_target(FINISHED), client)
    assert "possession" not in client.params[0]
