"""Card prefetch hand-off (TASKS 2.36 S-C).

When the pointer rests on a link to a player card, the page asks for the card's JSON with the
header `X-LOFC-Prefetch: 1`. The answer cannot go into the browser's HTTP cache (/api/ is
no-store), so the server keeps the built answer here for a short time, and the card page's
own request takes it -- once. A request that arrives while the prefetch is still being built
waits for it instead of building the card a second time. The client may abort its prefetch
(the pointer moved on, or the click navigated away); the build carries on and is kept.

Single use + a 30 s life + clearing on any watchlist write keep a hand-off from ever showing
stale state."""
from __future__ import annotations

import collections
import threading
import time


class Handoff:
    def __init__(self, ttl: float = 30.0, maxsize: int = 8) -> None:
        self.ttl, self.maxsize = ttl, maxsize
        self._lock = threading.Lock()
        self._items: "collections.OrderedDict[object, dict]" = collections.OrderedDict()

    def _fresh(self, it: dict) -> bool:
        return time.monotonic() - it["t"] <= self.ttl

    def produce(self, key, build):
        """Build (or reuse a fresh / in-flight build of) the answer for `key` and keep it."""
        with self._lock:
            it = self._items.get(key)
            if it is not None and self._fresh(it):
                mine = False
            else:
                it = {"t": time.monotonic(), "done": threading.Event(), "value": None}
                self._items[key] = it
                while len(self._items) > self.maxsize:
                    self._items.popitem(last=False)
                mine = True
        if mine:
            try:
                it["value"] = build()
            finally:
                it["done"].set()
        else:
            it["done"].wait(30)
        return it["value"]

    def consume(self, key, wait: float = 20.0):
        """The kept answer for `key` (waiting for one still being built), removed; else None."""
        with self._lock:
            it = self._items.get(key)
            if it is None:
                return None
        it["done"].wait(wait)
        with self._lock:
            if self._items.get(key) is it:
                del self._items[key]
        return it["value"] if self._fresh(it) else None

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
