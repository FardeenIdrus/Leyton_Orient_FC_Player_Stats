"""Tests for in-season ingest behaviour: the season being PLAYED must always re-pull.

Impect returns season-to-date aggregates, so a landed file for a live season is stale the
moment the next round is played. Skip-if-exists (right for a finished season, whose data can
never change) would silently freeze the data after the first in-season pull -- the bug these
tests exist to prevent. No network: the API call is stubbed.
"""

import pandas as pd
import pytest

from lofc.config import DEFAULT_IMPECT_TARGETS, ImpectTarget
from lofc.ingest import impect


LIVE, FINISHED = 319, 318


@pytest.fixture
def landed(tmp_path, monkeypatch):
    """Point the landing root at a temp dir and force LIVE as the live season."""
    monkeypatch.setattr(impect.landing, "raw_root", lambda: tmp_path)
    monkeypatch.setattr(type(impect.settings), "live_season_id",
                        property(lambda self: LIVE))
    return tmp_path


def _target(season_id, iteration_id=9001):
    return ImpectTarget(iteration_id=iteration_id, label=f"Test League s{season_id}",
                        competition_id=4, season_id=season_id, spine_source="impect")


def _stub_api(monkeypatch, frame=None, exc=None):
    """Stub impectPy.getPlayerIterationAverages, recording the calls it receives."""
    calls = []

    class _FakeIP:
        @staticmethod
        def getPlayerIterationAverages(iteration_id, token):
            calls.append(iteration_id)
            if exc is not None:
                raise exc
            return frame if frame is not None else pd.DataFrame({"playerId": [1]})

    monkeypatch.setitem(__import__("sys").modules, "impectPy", _FakeIP)
    return calls


def test_finished_season_is_skipped_when_already_landed(landed, monkeypatch):
    calls = _stub_api(monkeypatch)
    target = _target(FINISHED)
    assert impect.pull_iteration(target, "tok") is True          # first pull lands it
    assert impect.pull_iteration(target, "tok") is False          # second is skipped
    assert len(calls) == 1                                        # API hit only once


def test_live_season_always_repulls_even_when_landed(landed, monkeypatch):
    """The core in-season guarantee: a landed live-season file is refreshed, not skipped."""
    calls = _stub_api(monkeypatch)
    target = _target(LIVE)
    assert impect.pull_iteration(target, "tok") is True
    assert impect.pull_iteration(target, "tok") is True           # re-pulled, NOT skipped
    assert len(calls) == 2


def test_live_season_refresh_overwrites_the_landed_file(landed, monkeypatch):
    """A re-pull must actually replace the file, not silently keep the stale one."""
    target = _target(LIVE)
    _stub_api(monkeypatch, frame=pd.DataFrame({"playerId": [1]}))
    impect.pull_iteration(target, "tok")
    _stub_api(monkeypatch, frame=pd.DataFrame({"playerId": [1, 2, 3]}))
    impect.pull_iteration(target, "tok")
    landed_frame = pd.read_parquet(impect.averages_path(target.iteration_id))
    assert len(landed_frame) == 3                                 # the newer payload won


def test_live_season_with_no_data_yet_is_skipped_not_fatal(landed, monkeypatch):
    """Configured before kick-off, the API raises 'no data'. That must not crash the run."""
    _stub_api(monkeypatch, exc=Exception("The Players endpoint returned no data/ an empty list."))
    assert impect.pull_iteration(_target(LIVE), "tok") is False
    assert not impect.averages_path(9001).exists()                # nothing empty was landed


def test_empty_frame_for_a_live_season_lands_nothing(landed, monkeypatch):
    _stub_api(monkeypatch, frame=pd.DataFrame())
    assert impect.pull_iteration(_target(LIVE), "tok") is False
    assert not impect.averages_path(9001).exists()


def test_api_failure_on_a_finished_season_still_raises(landed, monkeypatch):
    """Only a not-yet-started live season may fail quietly; everything else is loud."""
    _stub_api(monkeypatch, exc=RuntimeError("upstream 500"))
    with pytest.raises(RuntimeError):
        impect.pull_iteration(_target(FINISHED), "tok")


def test_empty_frame_for_a_finished_season_raises(landed, monkeypatch):
    _stub_api(monkeypatch, frame=pd.DataFrame())
    with pytest.raises(RuntimeError):
        impect.pull_iteration(_target(FINISHED), "tok")


# --- the configured targets themselves -------------------------------------------------

def test_every_league_has_a_2026_27_target():
    """The live season must cover all seven leagues, or a league silently stops updating."""
    live = [t for t in DEFAULT_IMPECT_TARGETS if t.season_id == 319]
    assert {t.competition_id for t in live} == {3, 4, 5, 65, 901, 902, 903}
    assert all(t.spine_source == "impect" for t in live)   # no StatsBomb 2026/27 exists


def test_iteration_ids_are_unique_across_targets():
    ids = [t.iteration_id for t in DEFAULT_IMPECT_TARGETS]
    assert len(ids) == len(set(ids))
