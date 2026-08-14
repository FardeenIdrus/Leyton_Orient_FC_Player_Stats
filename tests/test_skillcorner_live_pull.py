"""In-season ingest behaviour for SkillCorner physical data: the live season always re-pulls.

The mirror of tests/test_live_season_pull.py (Impect). Physical data is a season-to-date
aggregate too, so skip-if-exists -- correct for a finished season -- would freeze it after the
first in-season pull. Both providers share ONE definition of the live season
(config.LIVE_SEASON_ID), so they can never disagree about which season is still accumulating.
No network: the client is stubbed.
"""

import pandas as pd
import pytest

from lofc.config import DEFAULT_SKILLCORNER_TARGETS, SkillCornerTarget
from lofc.ingest import skillcorner_api as sc


LIVE, FINISHED = 319, 318


@pytest.fixture
def landed(tmp_path, monkeypatch):
    """Point the landing root at a temp dir and force LIVE as the live season."""
    monkeypatch.setattr(sc.landing, "raw_root", lambda: tmp_path)
    monkeypatch.setattr(type(sc.settings), "live_season_id", property(lambda self: LIVE))
    return tmp_path


def _target(season_id, edition_id=9101):
    return SkillCornerTarget(edition_id=edition_id, label=f"Test Edition s{season_id}",
                             competition_id=4, season_id=season_id)


class _FakeClient:
    """Stands in for the SkillCorner client, recording calls."""

    def __init__(self, rows=None, exc=None):
        self.rows, self.exc, self.calls = rows, exc, []

    def get_physical(self, params):
        self.calls.append(params["competition_edition"])
        if self.exc is not None:
            raise self.exc
        return self.rows if self.rows is not None else [{"player_id": 1, "distance": 10000}]


def test_finished_season_is_skipped_when_already_landed(landed):
    client = _FakeClient()
    target = _target(FINISHED)
    assert sc.pull_edition(target, client) is True        # first pull lands it
    assert sc.pull_edition(target, client) is False       # second is skipped
    assert len(client.calls) == 1                         # API hit only once


def test_live_season_always_repulls_even_when_landed(landed):
    """The core in-season guarantee: a landed live file is refreshed, not skipped."""
    client = _FakeClient()
    target = _target(LIVE)
    assert sc.pull_edition(target, client) is True
    assert sc.pull_edition(target, client) is True        # re-pulled, NOT skipped
    assert len(client.calls) == 2


def test_live_season_refresh_overwrites_the_landed_file(landed):
    target = _target(LIVE)
    sc.pull_edition(target, _FakeClient(rows=[{"player_id": 1}]))
    sc.pull_edition(target, _FakeClient(rows=[{"player_id": i} for i in range(3)]))
    frame = pd.read_parquet(sc.physical_path(target.edition_id))
    assert len(frame) == 3                                # the newer payload won


def test_live_edition_with_no_data_yet_is_skipped_not_fatal(landed):
    """Configured before kick-off the API errors; that must not crash the whole run."""
    client = _FakeClient(exc=Exception("no data for this competition edition"))
    assert sc.pull_edition(_target(LIVE), client) is False
    assert not sc.physical_path(9101).exists()            # nothing empty was landed


def test_empty_payload_for_a_live_edition_lands_nothing(landed):
    assert sc.pull_edition(_target(LIVE), _FakeClient(rows=[])) is False
    assert not sc.physical_path(9101).exists()


def test_api_failure_on_a_finished_season_still_raises(landed):
    """Only a not-yet-started live season may fail quietly; everything else is loud."""
    with pytest.raises(RuntimeError):
        sc.pull_edition(_target(FINISHED), _FakeClient(exc=RuntimeError("upstream 500")))


def test_empty_payload_for_a_finished_season_raises(landed):
    with pytest.raises(RuntimeError):
        sc.pull_edition(_target(FINISHED), _FakeClient(rows=[]))


def test_is_live_matches_the_shared_live_season_definition(landed):
    assert sc.is_live(_target(LIVE)) is True
    assert sc.is_live(_target(FINISHED)) is False


def test_no_live_season_configured_restores_skip_if_exists(tmp_path, monkeypatch):
    """With LIVE_SEASON_ID unset (out of season) every edition is skip-if-exists again."""
    monkeypatch.setattr(sc.landing, "raw_root", lambda: tmp_path)
    monkeypatch.setattr(type(sc.settings), "live_season_id", property(lambda self: None))
    client = _FakeClient()
    target = _target(LIVE)
    assert sc.pull_edition(target, client) is True
    assert sc.pull_edition(target, client) is False       # no longer force-refreshed
    assert len(client.calls) == 1


def test_configured_live_editions_are_all_marked_live(landed):
    """Guards the pairing between the config and the refresh rule."""
    live = [t for t in DEFAULT_SKILLCORNER_TARGETS if t.season_id == LIVE]
    assert live and all(sc.is_live(t) for t in live)
