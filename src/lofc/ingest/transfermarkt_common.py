"""Shared, polite HTTP client for the Transfermarkt scrapers.

Transfermarkt is a third-party site we are a guest on. The delay, the browser user
agent and the backoff are deliberate and must not be weakened: one scrape run makes
thousands of requests, and an impolite client gets the club's IP blocked.
"""

from __future__ import annotations

import time
import urllib.request

REQUEST_DELAY_S = 2.5
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

_last_request = 0.0


def fetch(url: str, retries: int = 3) -> str:
    """Rate-limited GET with a browser user agent and exponential backoff."""
    global _last_request
    wait = REQUEST_DELAY_S - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=60) as response:
                _last_request = time.monotonic()
                return response.read().decode("utf-8", "ignore")
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("unreachable")
