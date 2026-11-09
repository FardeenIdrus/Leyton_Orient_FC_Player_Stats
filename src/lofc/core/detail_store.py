"""The card's Impect detail rows (scores, per-position scores, packing zones, matches,
receptions, physical in/out of possession), precomputed per league-season for the web.

`detail_section._player_rows(row, prefix)` -- what the Streamlit card calls -- reads the whole
league-season pool for a prefix (`_pool`, 10-minute TTL), ranks it (`pool_percentiles`) and keeps
one player's rows, on every card. Measured 2026-11-09: ~1.3 s for the six pools of a league not
read in the last ten minutes, and 0.1 s of unpickling even when cached. Here each pool is read
ONCE per data version (one query per league-season for all six prefixes), ranked with the same
`pool_percentiles`, and kept sorted by player, so a card slices its rows in well under 1 ms.

`player_rows` returns the same rows, columns, values and dtypes as `_player_rows`
(tests/test_core_detail_store.py; row order and index are not part of that contract: every
caller looks rows up by metric). Web-only: Streamlit keeps calling `detail_section`.
"""
from __future__ import annotations

import functools
import io
import logging
import threading

import numpy as np
import pandas as pd

PREFIXES = ("score.", "score_pos.", "zone.", "meta.", "avail.", "phys_")
_COLUMNS = ["player_id", "position_group", "rankable", "metric", "value_p90", "total"]
_TEXT = {"metric": "str", "position_group": "str"}

log = logging.getLogger(__name__)


def _sql(competition_id: int, season_id: int) -> str:
    """Literal SQL (COPY takes no bind parameters): ints and this module's constant prefixes."""
    from lofc.dashboard.detail_section import like_prefix
    like = " OR ".join(f"d.metric LIKE '{like_prefix(p)}'" for p in PREFIXES)
    return ("SELECT d.player_id, n.position_group, n.rankable::int AS rankable, d.metric, "
            "d.value_p90, d.total "
            "FROM player_detail_metrics d JOIN player_metrics_neutral n "
            "  ON n.player_id = d.player_id AND n.competition_id = d.competition_id "
            " AND n.season_id = d.season_id "
            f"WHERE d.competition_id = {int(competition_id)} AND d.season_id = {int(season_id)} "
            f"AND ({like})")


def _read(competition_id: int, season_id: int) -> pd.DataFrame:
    """Every row the six `_pool` reads return for one league-season, via COPY (several times
    faster than read_sql for ~100k narrow rows)."""
    from lofc.dashboard import loaders as L
    sql = _sql(competition_id, season_id)
    raw = L.get_engine().raw_connection()
    try:
        buf = io.StringIO()
        raw.cursor().copy_expert(f"COPY ({sql}) TO STDOUT WITH (FORMAT csv, HEADER true)", buf)
    finally:
        raw.close()
    buf.seek(0)
    frame = pd.read_csv(buf, keep_default_na=False, na_values=[""],
                        dtype={"metric": str, "position_group": str, "player_id": "int64",
                               "rankable": "int64", "value_p90": "float64", "total": "float64"})
    frame["rankable"] = frame["rankable"].astype(bool)
    return frame


def _as_read_sql(sub: pd.DataFrame) -> pd.DataFrame:
    """The dtypes `pd.read_sql` gives the same rows: a column that is NULL throughout comes back
    as object None, not float NaN (it matters for `total`, e.g. Impect scores have none)."""
    sub = sub.reset_index(drop=True)
    for col in _TEXT:
        sub[col] = sub[col].astype("str")
    for col in ("value_p90", "total"):
        if len(sub) and sub[col].isna().all():
            sub[col] = pd.Series([None] * len(sub), dtype=object)
    return sub


class _Pool:
    """One prefix's ranked pool, sorted by player (categoricals keep 8M rows near 300 MB)."""
    __slots__ = ("ids", "frame", "dtypes")

    def __init__(self, ranked: pd.DataFrame):
        self.dtypes = {c: ranked[c].dtype for c in _TEXT}
        ranked = ranked.sort_values("player_id", kind="stable").reset_index(drop=True)
        for col in _TEXT:
            ranked[col] = ranked[col].astype("category")
        self.frame, self.ids = ranked, ranked["player_id"].to_numpy()

    def rows(self, player_id: int) -> pd.DataFrame:
        i, j = np.searchsorted(self.ids, player_id, "left"), np.searchsorted(self.ids, player_id, "right")
        return self.frame.iloc[i:j].astype(self.dtypes)


def _build(competition_id: int, season_id: int) -> dict[str, _Pool]:
    from lofc.dashboard import detail_section as ds
    frame = _read(competition_id, season_id)
    out = {}
    for prefix in PREFIXES:
        sub = frame[frame["metric"].str.startswith(prefix)][_COLUMNS]
        out[prefix] = _Pool(ds.pool_percentiles(_as_read_sql(sub)))
    return out


_LOCK = threading.Lock()
_pairs: dict[tuple, dict[str, _Pool]] = {}      # (version, competition, season) -> pools
_building: dict[tuple, threading.Lock] = {}


def pools(competition_id: int, season_id: int) -> dict[str, _Pool]:
    from lofc.dashboard import loaders as L
    key = (L.web_data_version(), int(competition_id), int(season_id))
    with _LOCK:
        hit = _pairs.get(key)
        if hit is not None:
            return hit
        lock = _building.setdefault(key, threading.Lock())
    with lock:
        with _LOCK:
            if key in _pairs:
                return _pairs[key]
        built = _build(int(competition_id), int(season_id))
        with _LOCK:
            for k in [k for k in _pairs if k[0] != key[0]]:   # an older data version
                del _pairs[k]
            _pairs[key] = built
            _building.pop(key, None)
    return built


def player_rows(row, prefix: str) -> pd.DataFrame:
    """`detail_section._player_rows(row, prefix)` from the precomputed pools."""
    return pools(int(row["competition_id"]), int(row["season_id"]))[prefix].rows(int(row["player_id"]))


@functools.lru_cache(maxsize=512)
def _has_physical(version: str, competition_id: int, season_id: int) -> bool:
    from lofc.dashboard import detail_section as ds
    return ds.league_has_physical_uncached(competition_id, season_id)


def league_has_physical(competition_id: int, season_id: int) -> bool:
    """`detail_section._league_has_physical`, kept per data version instead of 10 minutes."""
    from lofc.dashboard import loaders as L
    return _has_physical(L.web_data_version(), int(competition_id), int(season_id))


def warm() -> None:
    """Build every league-season's pools (newest season first). Never raises."""
    from lofc.dashboard import loaders as L
    try:
        pairs = pd.read_sql("SELECT DISTINCT competition_id, season_id FROM player_detail_metrics "
                            "ORDER BY season_id DESC, competition_id", L.get_engine())
    except Exception:                                           # noqa: BLE001
        log.warning("detail warm-up could not list league-seasons", exc_info=True)
        return
    for c, s in zip(pairs["competition_id"], pairs["season_id"]):
        try:
            pools(int(c), int(s))
            league_has_physical(int(c), int(s))
        except Exception:                                       # noqa: BLE001
            log.warning("detail warm-up of %s/%s failed", c, s, exc_info=True)
