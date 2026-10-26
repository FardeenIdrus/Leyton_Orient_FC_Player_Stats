"""Run record + per-league failure isolation (owner, 2026-10-26).

Before: `pipeline.main` stopped at the first failed step, so ONE broken league froze every
league's data, and the only trace was a file on the server. With 30+ competitions that is
unacceptable. Now each league-by-league step runs every league inside a guard: a failure is
recorded in `pipeline_runs` and the other leagues carry on. The step then exits PARTIAL_EXIT,
the pipeline carries on with the next steps, and finishes as "partial", naming the leagues.
Shared steps (migrations, ratings) still stop the run: continuing after those would build
on wrong data. A failed league keeps last week's rows, so the ratings stay consistent.
"""

import subprocess
import sys

import pytest

from lofc import pipeline
from lofc.store import runs


class _Recorder:
    def __init__(self):
        self.rows = []

    def __call__(self, **row):
        self.rows.append(row)


@pytest.fixture
def recorded(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(runs, "record", lambda engine=None, **row: rec(**row))
    return rec


def _item(label, comp=4, season=318):
    return {"label": label, "competition_id": comp, "season_id": season}


def test_every_league_runs_and_success_is_recorded(recorded):
    failures = runs.for_each_league(
        "impect", [_item("League One"), _item("League Two", 5)],
        label=lambda x: x["label"], keys=lambda x: (x["competition_id"], x["season_id"]),
        fn=lambda x: 10)
    assert failures == []
    assert [r["status"] for r in recorded.rows] == ["success", "success"]
    assert recorded.rows[0]["rows"] == 10 and recorded.rows[0]["league"] == "League One"


def test_one_failing_league_does_not_stop_the_others(recorded):
    seen = []

    def fn(x):
        seen.append(x["label"])
        if x["label"] == "League Two":
            raise RuntimeError("Impect returned no averages")
        return 5
    failures = runs.for_each_league(
        "impect", [_item("League One"), _item("League Two", 5), _item("National League", 65)],
        label=lambda x: x["label"], keys=lambda x: (x["competition_id"], x["season_id"]), fn=fn)
    assert seen == ["League One", "League Two", "National League"]
    assert failures == ["League Two"]
    bad = next(r for r in recorded.rows if r["status"] == "failed")
    assert bad["league"] == "League Two" and "RuntimeError" in bad["error"]
    assert "Impect returned no averages" in bad["error"]


def test_a_logging_failure_never_breaks_the_pipeline(monkeypatch):
    """If the database itself is unreachable, recording must not raise."""
    def boom():
        raise ConnectionError("db down")
    monkeypatch.setattr(runs, "_engine", boom)
    runs.record(step="x", status="success")     # must not raise


def test_the_error_text_is_capped():
    assert len(runs.error_text(RuntimeError("x" * 5000))) <= runs.MAX_ERROR_CHARS


def test_finish_exits_partial_when_a_league_failed(recorded):
    with pytest.raises(SystemExit) as e:
        runs.finish_step("impect", ["League Two"])
    assert e.value.code == runs.PARTIAL_EXIT


def test_finish_returns_quietly_when_nothing_failed(recorded):
    runs.finish_step("impect", [])


# --- the orchestrator ------------------------------------------------------------------------

def _fake_steps(monkeypatch, codes):
    steps = [(f"step {i}", ["true"]) for i in range(len(codes))]
    monkeypatch.setattr(pipeline, "build_steps", lambda: steps)
    calls = []

    def fake_run(cmd, env=None):
        calls.append(env.get(runs.RUN_ID_ENV) if env else None)
        return subprocess.CompletedProcess(cmd, codes[len(calls) - 1])
    monkeypatch.setattr(pipeline.subprocess, "run", fake_run)
    return calls


def test_a_partial_step_lets_the_pipeline_continue_and_finish_partial(monkeypatch, recorded):
    monkeypatch.setattr(runs, "failed_leagues", lambda run_id: ["impect: League Two"])
    calls = _fake_steps(monkeypatch, [0, runs.PARTIAL_EXIT, 0])
    with pytest.raises(SystemExit) as e:
        pipeline.main()
    assert len(calls) == 3
    assert e.value.code == runs.PARTIAL_EXIT


def test_a_failed_shared_step_still_stops_the_run(monkeypatch, recorded):
    calls = _fake_steps(monkeypatch, [0, 1, 0])
    with pytest.raises(SystemExit) as e:
        pipeline.main()
    assert len(calls) == 2
    assert e.value.code not in (0, None, runs.PARTIAL_EXIT)


def test_every_step_gets_the_same_run_id(monkeypatch, recorded):
    calls = _fake_steps(monkeypatch, [0, 0])
    pipeline.main()
    assert calls[0] and calls[0] == calls[1]


def test_steps_are_recorded(monkeypatch, recorded):
    _fake_steps(monkeypatch, [0])
    pipeline.main()
    assert any(r["step"] == "step 0" and r["status"] == "success" and r.get("league") is None
               for r in recorded.rows)


# --- age reference dates follow the season rule -------------------------------------------

def test_season_midpoints_are_unchanged_and_extend_by_rule():
    import pandas as pd
    from lofc.config import SEASON_REF_DATE
    assert SEASON_REF_DATE[317] == pd.Timestamp("2025-01-01")
    assert SEASON_REF_DATE[318] == pd.Timestamp("2026-01-01")
    assert SEASON_REF_DATE[319] == pd.Timestamp("2027-01-01")
    assert SEASON_REF_DATE[320] == pd.Timestamp("2028-01-01")


# --- gaps found by the verifier (2026-10-26) ------------------------------------------------

@pytest.mark.parametrize("bad", ["label", "keys", "nan_rows", "sys_exit", "bad_str"])
def test_nothing_raised_for_one_league_escapes_the_guard(recorded, bad):
    class Unprintable(Exception):
        def __str__(self):
            raise RuntimeError("cannot print me")

    def label(x):
        if bad == "label" and x == 2:
            raise TypeError("no label")
        return f"L{x}"

    def keys(x):
        if bad == "keys" and x == 2:
            raise ZeroDivisionError("no keys")
        return (4, 318)

    def fn(x):
        if x != 2:
            return 1
        if bad == "nan_rows":
            return float("nan")
        if bad == "sys_exit":
            raise SystemExit(1)
        if bad == "bad_str":
            raise Unprintable()
        return 1
    failures = runs.for_each_league("s", [1, 2, 3], label=label, keys=keys, fn=fn)
    assert len(recorded.rows) == 3                          # every league recorded
    if bad != "nan_rows":                                   # a NaN count is not a failure
        assert len(failures) == 1


def test_ctrl_c_still_stops_the_run(recorded):
    def fn(x):
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        runs.for_each_league("s", [1], label=str, keys=lambda x: (1, 1), fn=fn)
