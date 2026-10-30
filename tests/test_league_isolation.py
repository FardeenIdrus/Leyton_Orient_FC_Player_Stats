"""Each league-by-league pipeline step isolates a failing league (owner, 2026-10-26).

For every step: league B fails, leagues A and C still run, the failure is recorded, and the
step exits runs.PARTIAL_EXIT so the orchestrator carries on and reports a partial run.
No network and no database: the step's internals are replaced.
"""

import sys

import pandas as pd
import pytest

from lofc.config import ImpectTarget, SkillCornerTarget
from lofc.store import runs

T = [ImpectTarget(iteration_id=i, label=f"L{i} 2025/26", competition_id=c, season_id=318,
                  spine_source="impect") for i, c in ((1, 4), (2, 5), (3, 65))]


@pytest.fixture(autouse=True)
def quiet_record(monkeypatch):
    rows = []
    monkeypatch.setattr(runs, "record", lambda engine=None, **r: rows.append(r))
    monkeypatch.setattr(sys, "argv", ["step"])
    return rows


class _Settings:
    def __init__(self, impect=None, skillcorner=None):
        self.impect_targets = impect or []
        self.skillcorner_targets = skillcorner or []
        self.live_season_id = 319
        self.impect_only = True


def _fail_on_second(seen, label_of):
    def fn(item, *a, **k):
        seen.append(label_of(item))
        if len(seen) == 2:
            raise RuntimeError("boom")
        return False
    return fn


def _assert_partial(run, seen, rows):
    with pytest.raises(SystemExit) as e:
        run()
    assert e.value.code == runs.PARTIAL_EXIT
    assert len(seen) == 3                                   # all three leagues attempted
    assert [r["status"] for r in rows if r.get("league")].count("failed") == 1


def test_impect_pull(monkeypatch, quiet_record):
    import impectPy
    from lofc.ingest import impect as m
    monkeypatch.setattr(m, "settings", _Settings(impect=T))
    monkeypatch.setattr(m, "_token", lambda: "t")
    monkeypatch.setattr(impectPy, "getIterations", lambda tok: pd.DataFrame())
    monkeypatch.setattr(m.landing, "write_json", lambda *a, **k: None)
    seen = []
    monkeypatch.setattr(m, "pull_iteration", _fail_on_second(seen, lambda t: t.label))
    monkeypatch.setattr(m, "pull_scores", lambda *a, **k: False)
    monkeypatch.setattr(m, "pull_players", lambda *a, **k: False)
    monkeypatch.setattr(m, "fetch_squad_names", lambda *a, **k: {})
    _assert_partial(m.main, seen, quiet_record)


def test_skillcorner_pull(monkeypatch, quiet_record):
    from lofc.ingest import skillcorner_api as m
    sc = [SkillCornerTarget(edition_id=i, label=f"E{i}", competition_id=4, season_id=318)
          for i in (1, 2, 3)]
    monkeypatch.setattr(m, "settings", _Settings(skillcorner=sc))
    monkeypatch.setattr(m, "_client", lambda: object())
    seen = []
    monkeypatch.setattr(m, "pull_edition", _fail_on_second(seen, lambda t: t.label))
    monkeypatch.setattr(m, "pull_split", lambda *a, **k: False)
    _assert_partial(m.main, seen, quiet_record)


def test_build_neutral(monkeypatch, quiet_record, tmp_path):
    from lofc.model import build_neutral as m
    monkeypatch.setattr(m, "settings", _Settings(impect=T))
    monkeypatch.setattr(m, "averages_path", lambda i: tmp_path)          # exists
    monkeypatch.setattr(m, "get_engine", lambda: None)
    seen = []

    def build(engine, target):
        seen.append(target.label)
        if len(seen) == 2:
            raise RuntimeError("boom")
        return pd.DataFrame({"rankable": [True]})
    monkeypatch.setattr(m, "build_for_impect_league", build)
    monkeypatch.setattr(m.reg, "names_for", lambda source: [])    # no metric columns needed
    monkeypatch.setattr(sys, "argv", ["build_neutral"])
    _assert_partial(m.main, seen, quiet_record)


def test_position_shares(monkeypatch, quiet_record):
    from lofc import config
    from lofc.model import position_shares as m
    monkeypatch.setattr(config, "settings", _Settings(impect=T))
    monkeypatch.setattr("lofc.store.load.get_engine", lambda: None)
    seen = []

    def collect(engine, target):
        seen.append(target.label)
        if len(seen) == 2:
            raise RuntimeError("boom")
        return pd.DataFrame()
    monkeypatch.setattr(m, "collect", collect)
    _assert_partial(m.main, seen, quiet_record)


def test_style_signals(monkeypatch, quiet_record, tmp_path):
    from lofc import config
    from lofc.ingest import impect as landing
    from lofc.model import style_run as m
    monkeypatch.setattr(config, "settings", _Settings(impect=T))
    monkeypatch.setattr("lofc.store.load.get_engine", lambda: None)
    monkeypatch.setattr(landing, "averages_path", lambda i: tmp_path / "missing.parquet")
    seen = []
    real = m.main

    def fake_read(path):
        raise AssertionError("not reached")
    # Every league is "missing" except the failure we inject through season_totals:
    monkeypatch.setattr(landing, "averages_path", lambda i: tmp_path)
    monkeypatch.setattr(m.pd, "read_parquet", lambda p: pd.DataFrame())

    def totals(raw):
        seen.append(len(seen))
        if len(seen) == 2:
            raise RuntimeError("boom")
        return pd.DataFrame(), pd.Series(dtype=float)
    monkeypatch.setattr(m, "season_totals", totals)
    monkeypatch.setattr("lofc.model.position_shares._linked_ids", lambda e, t: None)
    _assert_partial(real, seen, quiet_record)
