"""A process-wide throttle against username-spray login attempts.

`store.users.authenticate` locks an ACCOUNT after 5 failed attempts against IT (see
`auth.MAX_FAILED_LOGINS`). That does nothing to slow an attacker trying one guessed password
against many DIFFERENT usernames -- no single account ever reaches 5 failures, so no lockout
ever fires, no matter how many usernames are tried.

Source-IP throttling was considered and deliberately rejected. The platform is reached today
through a `cloudflared` quick tunnel straight to the dashboard container (`DEPLOY.md`'s
"fastest way to open it on my phone" path) with no reverse proxy in front of it, and even the
prod compose file's Caddy is a bare TLS-terminating `reverse_proxy` with no forwarded-address
normalisation configured. There is no dependable, non-spoofable client address available to
the app in either deployment: keying a limiter on it would either bucket every visitor behind
the tunnel together (useless -- one bucket for the whole internet) or trust a header an
attacker can simply set themselves (worse than nothing, since it would look like it's working).
Adding a proper trusted-proxy chain is a reverse-proxy/deployment concern, not an app-code fix,
and pulling in a library to do it would break the "no new dependency" constraint -- so this
throttle is deliberately BEHAVIOUR-based rather than address-based: the number of DISTINCT
usernames failing within a short rolling window, process-wide, is the actual signature of a
spray attempt, and it needs no network information at all.

Deliberately a SLOWDOWN, not a lockout: it never blocks a login outright. A real spike of
office mistypes (several people fumbling passwords after a long weekend) must never deny
anyone access -- only `MAX_FAILED_LOGINS` denies, and only the one account that earned it. This
throttle only adds a short synchronous delay to FAILED attempts once the spray signature is
seen: cheap for one honest retry, expensive multiplied across the dozen-plus usernames a spray
needs to try before it can even start guessing passwords properly.

State is a single in-process list, correct for the one dashboard process this app currently
runs as (`docker compose ps` shows one `dashboard` container). If the dashboard is ever run as
multiple replicas behind a load balancer, this stops being effective (each replica would see
only a fraction of the attempts) -- move the limiter to that load balancer/reverse proxy at
that point, where a real client address is more likely to be available.
"""

from __future__ import annotations

import datetime
import threading

WINDOW_MINUTES = 5
# A genuine office is a handful of accounts (Decision 16's four roles); nobody legitimately
# fails logins under 8 DIFFERENT usernames within 5 minutes. A spray attack has to try many.
DISTINCT_USERNAME_THRESHOLD = 8
# Long enough to meaningfully cut an attacker's guesses-per-minute; short enough that a
# genuine user caught in an active spray window is inconvenienced, never blocked.
THROTTLE_SECONDS = 3.0


class SprayThrottle:
    """Pure decision logic (`distinct_recent_usernames`, `delay_seconds`) over a plain list,
    plus the one piece of process-wide mutable state (`_failures`) guarded by a lock -- kept
    in its own small class so the decision logic is unit-testable by constructing an instance
    directly and driving it with explicit timestamps, the same way `auth.lockout_state` is
    tested without a clock or a database."""

    def __init__(self, window_minutes: float = WINDOW_MINUTES,
                 distinct_threshold: int = DISTINCT_USERNAME_THRESHOLD,
                 delay_seconds: float = THROTTLE_SECONDS) -> None:
        self._window = datetime.timedelta(minutes=window_minutes)
        self._threshold = distinct_threshold
        self._delay = delay_seconds
        self._failures: list[tuple[str, datetime.datetime]] = []
        self._lock = threading.Lock()

    def _prune(self, now: datetime.datetime) -> None:
        cutoff = now - self._window
        self._failures = [(u, t) for u, t in self._failures if t >= cutoff]

    def record_failure(self, username: str, now: datetime.datetime) -> None:
        """Note one failed login attempt for `username` at `now`. Call for every non-'ok'
        `AuthResult` -- wrong password, unknown user, locked, or inactive -- so the spray
        signal reflects failed *attempts*, not just wrong passwords."""
        with self._lock:
            self._failures.append((username, now))
            self._prune(now)

    def distinct_recent_usernames(self, now: datetime.datetime) -> set[str]:
        """Every username with a failure inside the rolling window, as of `now`. A single
        username repeatedly failing counts once here -- that pattern is already
        `store.users.authenticate`'s per-account lockout's job; this is about breadth."""
        with self._lock:
            self._prune(now)
            return {u for u, _ in self._failures}

    def delay_seconds(self, now: datetime.datetime) -> float:
        """How long the caller should pause before responding to a failed attempt right now.
        0.0 below the spray threshold -- the common case costs nothing extra."""
        count = len(self.distinct_recent_usernames(now))
        return self._delay if count >= self._threshold else 0.0


# The one shared instance every dashboard session goes through -- process-wide by design (see
# module docstring): the whole point is to see spray attempts across every session, not just
# the one that happens to be running.
_shared = SprayThrottle()


def record_failure(username: str, now: datetime.datetime) -> None:
    _shared.record_failure(username, now)


def delay_seconds(now: datetime.datetime) -> float:
    return _shared.delay_seconds(now)
