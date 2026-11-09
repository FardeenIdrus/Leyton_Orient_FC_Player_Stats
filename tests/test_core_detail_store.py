"""The web card's precomputed detail pools return exactly what the Streamlit card's
`detail_section._player_rows` returns (REAL database; skipped without one), and the web cache
helpers key on the data version."""
import pandas as pd
import pytest
from sqlalchemy import create_engine

from lofc.config import settings

CASES = [(39154, 5, 318), (39154, 5, 317), (47357, 5, 319), (391964, 903, 318),
         (3581, 3, 318), (44875, 3, 318)]


@pytest.fixture(scope="module")
def engine():
    try:
        e = create_engine(settings.database_url)
        e.connect().close()
    except Exception:
        pytest.skip("no database")
    return e


def _key(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.sort_values("metric", kind="stable").reset_index(drop=True)


@pytest.mark.parametrize("case", CASES, ids=[f"{p}/{c}/{s}" for p, c, s in CASES])
def test_player_rows_equal_streamlit(engine, case):
    from lofc.core import detail_store
    from lofc.dashboard import detail_section as ds
    p, c, s = case
    row = pd.Series({"player_id": p, "competition_id": c, "season_id": s})
    for prefix in detail_store.PREFIXES:
        want = ds._player_rows(row, prefix)
        got = detail_store.player_rows(row, prefix)
        pd.testing.assert_frame_equal(_key(got), _key(want), check_dtype=True)


def test_whole_pool_equals_streamlit(engine):
    """Every row of one league-season, not just one player's: the percentiles are ranks within
    the pool, so the pool must be identical."""
    from lofc.core import detail_store
    from lofc.dashboard import detail_section as ds
    pools = detail_store.pools(5, 318)
    for prefix in detail_store.PREFIXES:
        want = ds.pool_percentiles(ds._pool(5, 318, prefix))
        p = pools[prefix]
        got = p.frame.astype(p.dtypes)
        k = lambda f: f.sort_values(["player_id", "metric"], kind="stable").reset_index(drop=True)
        pd.testing.assert_frame_equal(k(got), k(want), check_dtype=True)


def test_league_has_physical_equal(engine):
    from lofc.core import detail_store
    from lofc.dashboard import detail_section as ds
    for c, s in ((5, 318), (5, 317), (3, 318)):
        assert detail_store.league_has_physical(c, s) == ds._league_has_physical(c, s)


def test_versioned_cache_rebuilds_on_new_version(monkeypatch):
    from lofc.core import webcache
    from lofc.dashboard import loaders as L
    version = {"v": "a"}
    monkeypatch.setattr(L, "web_data_version", lambda: version["v"])
    calls = []

    @webcache.versioned(maxsize=4)
    def f(x):
        calls.append(x)
        return [x]
    first = f(1)
    assert f(1) is first and calls == [1]            # a hit returns the same object
    version["v"] = "b"
    assert f(1) == [1] and calls == [1, 1]           # a new data version re-reads
    for i in range(10):
        f(i)
    assert len(calls) == 11                          # 0 is new, 1 hit, 2..9 new
