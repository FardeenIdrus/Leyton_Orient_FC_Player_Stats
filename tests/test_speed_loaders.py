"""Speed work on the cold paths (TASKS 2.33): the same numbers, fewer reads.

Unit tests stub the loaders. The `real_db` tests compare the new code against the old
algorithm on the live-shaped database in the Docker stack, for every season, and are skipped
where no database is reachable.
"""

from types import SimpleNamespace

import pandas as pd
import pytest

from lofc.dashboard import loaders


# --- warm-up covers every season ----------------------------------------------------
def test_warm_order_puts_default_and_live_first_then_the_rest(monkeypatch):
    monkeypatch.setattr(loaders, "settings", SimpleNamespace(live_season_id=319))
    order = loaders._warm_order([319, 318, 317, 316])
    assert sorted(order) == [316, 317, 318, 319]
    assert order[0] in (318, 319) and set(order[:2]) <= {318, 319}
    assert order[2:] == [317, 316]


def test_warm_up_warms_every_season_not_just_default_and_live(monkeypatch):
    calls = []
    monkeypatch.setattr(loaders, "available_seasons", lambda: [319, 318, 317])
    monkeypatch.setattr(loaders, "settings", SimpleNamespace(live_season_id=319))
    for name in ("load_candidates", "load_percentiles", "load_metric_values",
                 "load_scorecard_percentiles", "load_style_labels", "load_scorecards",
                 "load_previous_ratings", "headline"):
        monkeypatch.setattr(loaders, name,
                            lambda *a, _n=name: calls.append((_n, a[-1])))
    loaders._warm_caches()
    for sid in (319, 318, 317):
        assert ("load_style_labels", sid) in calls and ("load_candidates", sid) in calls


def test_one_failing_loader_does_not_stop_the_rest_of_the_warm_up(monkeypatch):
    seen = []
    monkeypatch.setattr(loaders, "available_seasons", lambda: [318, 317])
    monkeypatch.setattr(loaders, "settings", SimpleNamespace(live_season_id=318))

    def boom(*a):
        raise RuntimeError("x")
    monkeypatch.setattr(loaders, "load_candidates", boom)
    monkeypatch.setattr(loaders, "load_percentiles", lambda *a: seen.append(a[-1]))
    for name in ("load_metric_values", "load_scorecard_percentiles", "load_style_labels",
                 "load_scorecards", "load_previous_ratings", "headline"):
        monkeypatch.setattr(loaders, name, lambda *a: None)
    loaders._warm_caches()
    assert sorted(seen) == [317, 318]


# --- load_candidates builds once for all seasons --------------------------------------
def test_candidates_are_sliced_from_one_all_season_build(monkeypatch):
    loaders.load_candidates.clear()
    monkeypatch.setattr(loaders, "data_version", lambda with_scorecards=False: "speed-test")
    built = []
    frame = pd.DataFrame({"player_id": [1, 2, 3], "competition_id": [5, 5, 5],
                          "season_id": [318, 318, 317]})
    monkeypatch.setattr(loaders, "_candidates_all_seasons",
                        lambda wage: built.append(wage) or frame)
    a = loaders.load_candidates(1.0, 318)
    b = loaders.load_candidates(1.0, 317)
    assert list(a["player_id"]) == [1, 2]
    assert list(b["player_id"]) == [3] and list(b.index) == [0]      # index restarts per season
    assert list(loaders.load_candidates(1.0, None)["player_id"]) == [1, 2, 3]
    loaders.load_candidates.clear()


# --- COPY reader ------------------------------------------------------------------------
@pytest.fixture
def real_db():
    try:
        pd.read_sql("select 1", loaders.get_engine())
    except Exception:                                        # noqa: BLE001
        pytest.skip("no database reachable")


def test_copy_reader_equals_read_sql_for_every_season(real_db):
    for sid in loaders.available_seasons.__wrapped__():
        for sql in (f"SELECT player_id, competition_id, signal, value FROM player_style_signals "
                    f"WHERE season_id = {sid}",
                    f"SELECT player_id, competition_id, metric, percentile FROM "
                    f"player_percentiles WHERE season_id = {sid}"):
            # Neither reader orders rows (no ORDER BY; Postgres may start a scan mid-table),
            # so compare the same rows in the same order.
            keys = ["player_id", "competition_id", sql.split()[3].rstrip(",")]
            got = loaders._read_sql_copy(sql).sort_values(keys).reset_index(drop=True)
            want = pd.read_sql(sql, loaders.get_engine()).sort_values(keys).reset_index(drop=True)
            pd.testing.assert_frame_equal(got, want)


def test_candidates_every_season_slice_matches_the_whole_build(real_db):
    loaders._candidates_all_seasons.clear()
    loaders.load_candidates.clear()
    whole = loaders._candidates_all_seasons.__wrapped__(1.0)
    for sid in loaders.available_seasons.__wrapped__():
        new = loaders.load_candidates(1.0, sid)
        old = whole[whole["season_id"] == sid].reset_index(drop=True)
        pd.testing.assert_frame_equal(new, old)
