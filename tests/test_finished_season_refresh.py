"""Finished seasons are re-downloaded once their landed file is over 30 days old.

Impect REVISES finished seasons: National League 2025/26 had 34 players changed between the
July download and 2026-10-09 (median 0.3%). Skip-if-exists froze those corrections out
forever. A month is short enough to pick corrections up before a transfer window and long
enough not to hammer the API every Monday. No network: the APIs are stubbed.
"""

import os
import sys
import time

import pandas as pd
import pytest

from lofc.config import ImpectTarget, SkillCornerTarget
from lofc.ingest import impect
from lofc.ingest import skillcorner_api as sc

FINISHED = 318


@pytest.fixture
def landed(tmp_path, monkeypatch):
    monkeypatch.setattr(impect.landing, "raw_root", lambda: tmp_path)
    monkeypatch.setattr(sc.landing, "raw_root", lambda: tmp_path)
    monkeypatch.setattr(type(impect.settings), "live_season_id", property(lambda self: 319))
    return tmp_path


def _age(path, days):
    old = time.time() - days * 86400
    os.utime(path, (old, old))


def _stub_impect(monkeypatch):
    calls = []

    class _FakeIP:
        @staticmethod
        def getPlayerIterationAverages(iteration_id, token):
            calls.append(iteration_id)
            return pd.DataFrame({"playerId": [1]})

    monkeypatch.setitem(sys.modules, "impectPy", _FakeIP)
    return calls


def _t():
    return ImpectTarget(iteration_id=9001, label="T", competition_id=4, season_id=FINISHED,
                        spine_source="impect")


def test_a_fresh_finished_file_is_not_repulled(landed, monkeypatch):
    calls = _stub_impect(monkeypatch)
    impect.pull_iteration(_t(), "tok")
    _age(impect.averages_path(9001), 10)
    assert impect.pull_iteration(_t(), "tok") is False
    assert calls == [9001]


def test_a_finished_file_older_than_30_days_is_repulled(landed, monkeypatch):
    calls = _stub_impect(monkeypatch)
    impect.pull_iteration(_t(), "tok")
    _age(impect.averages_path(9001), 31)
    assert impect.pull_iteration(_t(), "tok") is True
    assert calls == [9001, 9001]


class _Client:
    def __init__(self):
        self.calls = 0

    def get_physical(self, params):
        self.calls += 1
        return [{"player_id": 1}]


def test_skillcorner_finished_file_older_than_30_days_is_repulled(landed):
    t = SkillCornerTarget(edition_id=9101, label="T", competition_id=4, season_id=FINISHED)
    c = _Client()
    sc.pull_edition(t, c)
    _age(sc.physical_path(9101), 31)
    assert sc.pull_edition(t, c) is True and c.calls == 2


def test_the_threshold_is_30_days():
    assert impect.FINISHED_REFRESH_DAYS == 30 and sc.FINISHED_REFRESH_DAYS == 30
