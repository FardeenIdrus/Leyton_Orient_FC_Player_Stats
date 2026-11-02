"""Version-keyed long caching for `dashboard/loaders.py`.

Owner requirement: a cache must NEVER serve data older than the database. The long-lived
loaders are keyed on `data_version()` (a hash of Postgres write counters), so a pipeline
write is a new cache key rather than something we wait out a TTL for. No live Postgres: the
database is stubbed at `pd.read_sql`.
"""

import threading

import pandas as pd
import pytest

from lofc.dashboard import loaders
from lofc.model import scorecard as scorecard_mod


# --- the version token -------------------------------------------------------------
def _stats(**counts):
    return pd.DataFrame({"relname": list(counts), "writes": list(counts.values())})


def test_hash_changes_when_a_tracked_table_count_changes():
    tables = ("a", "b")
    one = loaders._hash_stats(_stats(a=10, b=5), "t0", tables)
    assert one == loaders._hash_stats(_stats(b=5, a=10), "t0", tables)   # row order is irrelevant
    assert one != loaders._hash_stats(_stats(a=11, b=5), "t0", tables)


def test_hash_ignores_untracked_tables_and_changes_with_postmaster_start():
    tables = ("a",)
    base = loaders._hash_stats(_stats(a=1, other=1), "t0", tables)
    assert base == loaders._hash_stats(_stats(a=1, other=999), "t0", tables)
    # a stats reset (restart) can bring counters back to a past value
    assert base != loaders._hash_stats(_stats(a=1, other=1), "t1", tables)


def test_data_version_falls_back_to_a_time_window_token_on_error(monkeypatch):
    loaders._table_stats.clear()

    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(loaders.pd, "read_sql", boom)
    monkeypatch.setattr(loaders.time, "time", lambda: 6000.0)
    first = loaders._compute_data_version(with_scorecards=False)
    assert first.startswith("fallback-")
    monkeypatch.setattr(loaders.time, "time", lambda: 6000.0 + 30)
    assert loaders._compute_data_version(False) == first            # same 10-minute window
    monkeypatch.setattr(loaders.time, "time", lambda: 6000.0 + 700)
    assert loaders._compute_data_version(False) != first            # never stale-forever


def test_scorecards_table_only_moves_the_scorecard_version():
    # assessments UPDATE player_scorecards; that must not empty the heavy candidate cache
    assert "player_scorecards" not in loaders._CORE_TABLES
    assert "player_scorecards" in loaders._SCORECARD_TABLES
    assert set(loaders._CORE_TABLES) <= set(loaders._SCORECARD_TABLES)


# --- the versioned cache -----------------------------------------------------------
def test_versioned_loader_rereads_only_when_the_version_changes(monkeypatch):
    version = ["v1"]
    monkeypatch.setattr(loaders, "data_version", lambda with_scorecards=False: version[0])
    calls = []

    @loaders._versioned()
    def _probe_versioned_reads(x):
        calls.append(x)
        return pd.DataFrame({"x": [x, len(calls)]})

    a = _probe_versioned_reads(1)
    _probe_versioned_reads(1)
    assert calls == [1]                       # served from cache, same version
    version[0] = "v2"
    b = _probe_versioned_reads(1)
    assert calls == [1, 1]                    # new version -> re-read
    assert list(a["x"]) != list(b["x"])
    _probe_versioned_reads.clear()


def test_user_written_loaders_stay_short_ttl_and_unversioned():
    for name in ["load_assessment_status", "load_scorecards", "load_scorecards_archetype",
                 "_stored_scorecards"]:
        assert not getattr(getattr(loaders, name), "_is_versioned", False), name
    for name in ["load_candidates", "load_scorecard_percentiles", "load_percentiles",
                 "load_metric_values", "load_style_inputs", "load_style_labels",
                 "available_seasons", "headline"]:
        assert getattr(getattr(loaders, name), "_is_versioned", False), name


# --- load_scorecard_percentiles reads one season -----------------------------------
def _neutral():
    rows = []
    for sid in (1, 2):
        for pid in range(1, 7):
            rows.append({"player_id": pid + 10 * sid, "competition_id": 5, "season_id": sid,
                         "position_group": "Winger", "rankable": True, "minutes": 900,
                         "player_name": "n", "team_name": "t",
                         "xg_p90": pid * 0.1 * sid, "tackles_p90": 7.0 - pid})
    return pd.DataFrame(rows)


def test_scorecard_percentiles_queries_one_season_and_matches_old_result(monkeypatch):
    neutral = _neutral()
    seen = {}

    def fake_read_sql(sql, con, params=None, **k):
        seen["sql"], seen["params"] = sql, params
        assert "season_id = %(s)s" in sql
        return neutral[neutral["season_id"] == params["s"]].reset_index(drop=True)

    monkeypatch.setattr(loaders.pd, "read_sql", fake_read_sql)
    monkeypatch.setattr(loaders, "get_engine", lambda: None)
    got = loaders.load_scorecard_percentiles.__wrapped__(1)
    old = scorecard_mod.metric_percentiles(neutral[neutral["season_id"] == 1]).reset_index()
    pd.testing.assert_frame_equal(got, old)
    assert seen["params"] == {"s": 1}


# --- warm-up -----------------------------------------------------------------------
def test_warm_up_never_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("nope")
    monkeypatch.setattr(loaders, "load_candidates", boom)
    monkeypatch.setattr(loaders, "available_seasons", boom)
    loaders._warm_caches()                                    # must swallow everything


def test_warm_up_runs_at_most_once_at_a_time(monkeypatch):
    started, release, runs = threading.Event(), threading.Event(), []

    def slow_warm(*a, **k):
        runs.append(1)
        started.set()
        release.wait(5)
    monkeypatch.setattr(loaders, "_warm_caches", slow_warm)
    monkeypatch.setattr(loaders, "_last_warmed_version", None)
    monkeypatch.setattr(loaders, "data_version", lambda with_scorecards=False: "v1")
    t = loaders.start_warmup_if_needed()
    assert t is not None and started.wait(5)
    monkeypatch.setattr(loaders, "data_version", lambda with_scorecards=False: "v2")
    assert loaders.start_warmup_if_needed() is None           # one already running
    release.set()
    t.join(5)
    assert len(runs) == 1
    # the lock is free again: a further version change may warm again
    t2 = loaders.start_warmup_if_needed()
    assert t2 is not None
    t2.join(5)


def test_a_rebuilt_table_changes_the_version_even_with_the_same_counts():
    """Verifier, 2026-11-02: a table dropped and recreated (a database restore, a TRUNCATE)
    restarts its write counter, so equal counts could keep an old token. The table's file id
    (pg_class.relfilenode) changes on every rebuild and is part of the token."""
    import pandas as pd
    from lofc.dashboard import loaders as ld
    before = pd.DataFrame({"relname": ["players"], "writes": [100], "relfilenode": [16384]})
    after = before.assign(relfilenode=[20001])
    assert ld._hash_stats(before, "t0", ["players"]) != ld._hash_stats(after, "t0", ["players"])
