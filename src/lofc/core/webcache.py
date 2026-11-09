"""In-process caches for the web front end, keyed on `loaders.web_data_version()`.

Why not the Streamlit caches the dashboard uses: `st.cache_data` unpickles a fresh copy of the
value on every hit (~0.1 s per card for the detail pools alone) and several of the loaders the
web pages read live 60-600 s, so the first click after a quiet minute paid a 1-10 s rebuild.
Here a value is kept until the data it was read from changes (the version token tracks every
table these caches read, within ~30 s of a write), and returned as is -- callers must not
mutate it.

Web-only: Streamlit never calls anything in this module, so its behaviour is unchanged.
"""
from __future__ import annotations

import collections
import functools
import logging
import threading
import time

_LOCK = threading.Lock()
_ALL: list = []
# page key -> its warm-up (`register_warmup`), run in registration order by `rewarm_all`.
_WARMERS: "collections.OrderedDict[str, object]" = collections.OrderedDict()
log = logging.getLogger("lofc.web.warmup")


def versioned(maxsize: int = 64):
    """Cache `fn(*args)` under (web_data_version(), args). LRU of `maxsize` entries; an entry
    of an older version is never returned. Concurrent misses on one key build it once."""
    def deco(fn):
        store: "collections.OrderedDict[tuple, object]" = collections.OrderedDict()
        building: dict[tuple, threading.Lock] = {}

        @functools.wraps(fn)
        def wrapper(*args):
            from lofc.dashboard import loaders as L
            key = (L.web_data_version(),) + args
            with _LOCK:
                if key in store:
                    store.move_to_end(key)
                    return store[key]
                lock = building.setdefault(key, threading.Lock())
            with lock:
                with _LOCK:
                    if key in store:
                        return store[key]
                value = fn(*args)
                with _LOCK:
                    store[key] = value
                    # an older version's entries go first, then the least recently used
                    for k in [k for k in store if k[0] != key[0]]:
                        del store[k]
                    while len(store) > maxsize:
                        store.popitem(last=False)
                    building.pop(key, None)
            return value

        def clear():
            with _LOCK:
                store.clear()
        wrapper.clear = clear
        _ALL.append(wrapper)
        return wrapper
    return deco


def clear_all() -> None:
    for fn in _ALL:
        fn.clear()


# --- re-warm every page when the data version moves (TASKS 2.36 I1) -----------------------
def register_warmup(name: str, fn) -> None:
    """Register a page's warm-up (no arguments, never needs to return anything). A second
    registration under the same name replaces the first (the app factory can run twice)."""
    with _LOCK:
        _WARMERS[name] = fn


def registered_warmups() -> list[str]:
    with _LOCK:
        return list(_WARMERS)


def rewarm_all() -> list[str]:
    """Run every registered warm-up, one after another (one heavy job at a time); a failing
    one is logged and the rest still run. Returns the names run, in order."""
    with _LOCK:
        items = list(_WARMERS.items())
    t0 = time.perf_counter()
    for name, fn in items:
        try:
            fn()
        except Exception:                                       # noqa: BLE001
            log.warning("re-warm of %s failed", name, exc_info=True)
    log.warning("re-warm of %d pages done in %.0f s", len(items), time.perf_counter() - t0)
    return [n for n, _ in items]


def rewarm_on_change(poll_s: float = 30.0, rounds: int | None = None) -> None:
    """Any write to a tracked table (a scout-sheet sync rewrites every row; a pipeline load;
    the daily rollover) changes `web_data_version()` and so empties every page's cache. Poll
    the token and, as soon as it moves, re-run every page's warm-up in the background, so no
    visitor pays the rebuild. `rounds` bounds the loop for tests."""
    from lofc.dashboard import loaders as L
    last = L.web_data_version()
    n = 0
    while rounds is None or n < rounds:
        n += 1
        time.sleep(poll_s)
        try:
            now = L.web_data_version()
        except Exception:                                       # noqa: BLE001
            continue
        if now != last:
            last = now
            rewarm_all()


# --- the web pages' copies of short-TTL dashboard loaders --------------------------------
@versioned(maxsize=8)
def assessment_status(season_id: int | None):
    """`loaders.load_assessment_status`, but kept until an assessment or scorecard changes."""
    from lofc.dashboard import loaders as L
    return L.assessment_status_frame(season_id)


@versioned(maxsize=2)
def scout_consensus():
    """`scout_reports.consensus_by_player`, but kept until a scout report changes."""
    from lofc.dashboard.tabs.scout_reports import consensus_frame
    return consensus_frame()


