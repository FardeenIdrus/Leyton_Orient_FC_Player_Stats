"""`login_throttle.SprayThrottle`: the decision logic against a username-spray login attempt
(many different usernames failing in a short window, process-wide), as opposed to the
per-account lockout in `store.users.authenticate` (one username failing repeatedly). See the
module docstring for why this is behaviour-based rather than source-address-based.

Each test builds its own `SprayThrottle` instance and drives it with explicit timestamps --
no clock, no Streamlit, no shared process-wide state (`login_throttle._shared` is never
touched here), matching how `auth.lockout_state` is tested."""

import datetime as dt

from lofc.dashboard.login_throttle import SprayThrottle

NOW = dt.datetime(2026, 8, 24, 12, 0)


def _throttle(**kwargs):
    return SprayThrottle(window_minutes=5, distinct_threshold=3, delay_seconds=2.0, **kwargs)


def test_no_delay_below_the_distinct_username_threshold():
    t = _throttle()
    t.record_failure("alice", NOW)
    t.record_failure("bob", NOW)
    assert t.delay_seconds(NOW) == 0.0


def test_delay_once_the_distinct_username_threshold_is_reached():
    t = _throttle()
    t.record_failure("alice", NOW)
    t.record_failure("bob", NOW)
    t.record_failure("carol", NOW)
    assert t.delay_seconds(NOW) == 2.0


def test_one_username_failing_repeatedly_never_triggers_the_spray_throttle():
    """That pattern is `store.users.authenticate`'s per-account lockout's job (5 failures on
    ONE account). This throttle is about breadth (many DIFFERENT usernames), so hammering a
    single username must never trip it, no matter how many times."""
    t = _throttle()
    for _ in range(20):
        t.record_failure("alice", NOW)
    assert t.delay_seconds(NOW) == 0.0
    assert t.distinct_recent_usernames(NOW) == {"alice"}


def test_failures_outside_the_window_are_pruned_and_do_not_count():
    t = _throttle()
    stale = NOW - dt.timedelta(minutes=10)
    t.record_failure("alice", stale)
    t.record_failure("bob", stale)
    t.record_failure("carol", stale)
    # All three failures are outside the 5-minute window by the time `now` is checked.
    assert t.distinct_recent_usernames(NOW) == set()
    assert t.delay_seconds(NOW) == 0.0


def test_a_fresh_failure_alongside_stale_ones_only_counts_the_fresh_one():
    t = _throttle()
    stale = NOW - dt.timedelta(minutes=10)
    t.record_failure("alice", stale)
    t.record_failure("bob", stale)
    t.record_failure("carol", NOW)
    assert t.distinct_recent_usernames(NOW) == {"carol"}
    assert t.delay_seconds(NOW) == 0.0


def test_delay_seconds_matches_the_configured_value():
    t = SprayThrottle(window_minutes=5, distinct_threshold=1, delay_seconds=7.5)
    t.record_failure("alice", NOW)
    assert t.delay_seconds(NOW) == 7.5
