"""Retry with exponential backoff around provider API calls.

A weekly unattended run should survive a network blip, a provider rate-limit or a short
outage. Only TRANSIENT failures are retried; anything that retrying cannot fix (bad
credentials, missing resource, a bug) fails immediately and loudly, exactly as before.
On the final failure the ORIGINAL exception is re-raised unchanged, so callers' existing
`except` handling (e.g. a live season with no data yet) sees what it always saw.
"""

from __future__ import annotations

import random
import re
import time

import httpx
import requests

# impectPy raises its own HTTPError carrying NO status attribute, only the text
# "Received status code NNN ..." (impectPy/helpers.py make_api_request), so parse it.
_IMPECT_STATUS = re.compile(r"Received status code (\d{3})")


def _status_transient(code: int) -> bool:
    # 429 = rate limited, 5xx = provider-side fault: both clear on their own.
    # Every other 4xx (400/401/403/404...) is a permanent request or auth problem.
    return code == 429 or 500 <= code <= 599


def is_transient(exc: BaseException) -> bool:
    """True if retrying the same call could plausibly succeed."""
    # impectPy: ForbiddenError (403) subclasses HTTPError, so test it first. Never retry
    # an access problem; it would only hammer the API with a request that cannot work.
    try:
        from impectPy.helpers import ForbiddenError, HTTPError as ImpectHTTPError
    except ImportError:  # impectPy is only needed where Impect is used
        ForbiddenError = ImpectHTTPError = None
    if ForbiddenError is not None and isinstance(exc, ForbiddenError):
        return False
    # impectPy HTTPError: status only in the message. 429 here means its own 3 internal
    # retries were exhausted (still worth a longer backoff); 401 and other 4xx are not.
    if ImpectHTTPError is not None and isinstance(exc, ImpectHTTPError):
        m = _IMPECT_STATUS.search(str(exc))
        return bool(m) and _status_transient(int(m.group(1)))

    # SkillCorner uses fitrequest, whose HTTPStatusError carries status_code
    # (fitrequest/errors.py). Same 429/5xx rule.
    try:
        from fitrequest.errors import HTTPStatusError as FitHTTPStatusError
    except ImportError:
        FitHTTPStatusError = None
    if FitHTTPStatusError is not None and isinstance(exc, FitHTTPStatusError):
        return _status_transient(exc.status_code)

    # httpx (SkillCorner transport): HTTPStatusError by its response code ...
    if isinstance(exc, httpx.HTTPStatusError):
        return _status_transient(exc.response.status_code)
    # ... and any TransportError (connect/read/write/pool timeouts, network and protocol
    # errors) is a connectivity fault, never a request bug.
    if isinstance(exc, httpx.TransportError):
        return True

    # requests: HTTPError (from raise_for_status) by response code.
    if isinstance(exc, requests.HTTPError):
        resp = exc.response
        return resp is not None and _status_transient(resp.status_code)
    # requests: a body that is not JSON where JSON is expected is what a gateway's 502/503
    # HTML page looks like to impectPy's error path (response.json()), i.e. an outage.
    if isinstance(exc, requests.exceptions.JSONDecodeError):
        return True
    # requests: connection failures, timeouts, truncated/chunked bodies. Checked after
    # HTTPError/JSONDecodeError because all are RequestException subclasses.
    if isinstance(exc, (requests.ConnectionError, requests.Timeout,
                        requests.exceptions.ChunkedEncodingError,
                        requests.exceptions.ContentDecodingError)):
        return True

    # Builtin socket-level errors (reset, refused, aborted, timeout). Deliberately NOT all
    # of OSError: FileNotFoundError and PermissionError are local bugs, not blips.
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True

    # Everything else (ValueError, KeyError, TypeError, RuntimeError, plain Exception such
    # as impectPy's "returned no data") is a programming or data error: fail at once.
    return False


def with_retries(fn, *, what: str, attempts: int = 4, base_delay: float = 2.0,
                 max_delay: float = 60.0, sleep=None, is_transient=None):
    """Call `fn()`; on a transient failure wait base_delay*2**(n-1) (capped at max_delay,
    plus up to 25% jitter) and retry, up to `attempts` tries in total.

    Non-transient errors, and the last transient one, are re-raised unchanged.
    Messages never include credentials: only the call label, exception class and message.
    """
    classify = is_transient if is_transient is not None else globals()["is_transient"]
    # Looked up at call time (not bound as a default) so a caller's test can patch time.sleep.
    sleep = sleep if sleep is not None else time.sleep
    for n in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:
            if n >= attempts or not classify(exc):
                raise
            delay = min(base_delay * 2 ** (n - 1), max_delay)
            delay = min(delay + random.uniform(0, 0.25) * delay, max_delay)
            print(f"  [retry] {what}: attempt {n} of {attempts} failed with "
                  f"{type(exc).__name__}: {exc} -- waiting {delay:.1f}s")
            sleep(delay)
