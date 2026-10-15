"""Impect's own scores (getPlayerIterationScores) land beside the averages, same rules:
finished season skip-if-landed, live season always re-pulled, an empty payload never landed.
No network: the API is stubbed."""

import sys

import pandas as pd
import pytest

from lofc.config import ImpectTarget
from lofc.ingest import impect

LIVE, FINISHED = 319, 318


@pytest.fixture
def landed(tmp_path, monkeypatch):
    monkeypatch.setattr(impect.landing, "raw_root", lambda: tmp_path)
    monkeypatch.setattr(type(impect.settings), "live_season_id", property(lambda self: LIVE))
    return tmp_path


def _target(season_id):
    return ImpectTarget(iteration_id=9001, label="T", competition_id=4, season_id=season_id,
                        spine_source="impect")


def _stub(monkeypatch, frame=None, exc=None):
    calls = []

    class _FakeIP:
        @staticmethod
        def getPlayerIterationScores(iteration_id, token):
            calls.append(iteration_id)
            if exc is not None:
                raise exc
            return frame if frame is not None else pd.DataFrame({"playerId": [1]})

    monkeypatch.setitem(sys.modules, "impectPy", _FakeIP)
    return calls


def test_scores_land_at_their_own_path(landed, monkeypatch):
    _stub(monkeypatch)
    assert impect.pull_scores(_target(FINISHED), "tok") is True
    assert impect.scores_path(9001).exists()
    assert impect.scores_path(9001) != impect.averages_path(9001)


def test_finished_season_is_not_repulled(landed, monkeypatch):
    calls = _stub(monkeypatch)
    impect.pull_scores(_target(FINISHED), "tok")
    assert impect.pull_scores(_target(FINISHED), "tok") is False
    assert calls == [9001]


def test_live_season_always_repulls(landed, monkeypatch):
    calls = _stub(monkeypatch)
    impect.pull_scores(_target(LIVE), "tok")
    impect.pull_scores(_target(LIVE), "tok")
    assert calls == [9001, 9001]


def test_empty_scores_for_a_finished_season_raise(landed, monkeypatch):
    _stub(monkeypatch, frame=pd.DataFrame())
    with pytest.raises(RuntimeError):
        impect.pull_scores(_target(FINISHED), "tok")
    assert not impect.scores_path(9001).exists()
