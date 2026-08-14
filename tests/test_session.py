"""Session-state logic for the login gate. The Streamlit rendering is not tested -- these
cover the decisions the gate makes, which is where the behaviour actually lives."""

import datetime as dt

from lofc.dashboard import session as sess

NOW = dt.datetime(2026, 8, 14, 12, 0)


def test_restore_returns_none_for_an_empty_state():
    assert sess.restore_user({}, NOW) is None


def test_restore_returns_the_user_for_a_fresh_session():
    state = {"user_id": 3, "full_name": "J. Smith", "role": "scout", "logged_in_at": NOW}
    user = sess.restore_user(state, NOW)
    assert user == sess.CurrentUser(id=3, full_name="J. Smith", role="scout")


def test_restore_returns_none_for_an_expired_session():
    stale = NOW - dt.timedelta(minutes=sess.auth.SESSION_TTL_MINUTES + 1)
    state = {"user_id": 3, "full_name": "J. Smith", "role": "scout", "logged_in_at": stale}
    assert sess.restore_user(state, NOW) is None


def test_restore_returns_none_when_the_timestamp_is_missing():
    """A state carrying an identity but no timestamp is malformed, not a valid session."""
    state = {"user_id": 3, "full_name": "J. Smith", "role": "scout"}
    assert sess.restore_user(state, NOW) is None


def test_lockout_message_states_the_wait_in_whole_minutes():
    assert "15 minutes" in sess.lockout_message(15 * 60)


def test_lockout_message_rounds_a_part_minute_up():
    """Rounding down would tell a user to try again in 0 minutes and have it fail."""
    assert "1 minute" in sess.lockout_message(30)
