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


def test_a_full_name_with_angle_brackets_does_not_emit_raw_markup():
    """`full_name` is admin-entered and not validated as plain text (mirrors
    `test_badges.test_a_name_with_angle_brackets_does_not_emit_raw_markup`, same underlying
    `users.full_name` field). Rendered with `unsafe_allow_html=True`, an unescaped '<' or '>'
    would inject markup into every page for every session -- and since the session cookie
    cannot be HttpOnly, that markup could steal a session via document.cookie."""
    user = sess.CurrentUser(
        id=1, full_name="<img src=x onerror=alert(1)>", role="admin")
    markup = sess._identity_html(user)
    assert "<img" not in markup
    assert "&lt;img" in markup


def test_a_role_with_angle_brackets_does_not_emit_raw_markup():
    """`role` is drawn from a fixed internal set today, but is escaped for defence in depth --
    this locks that in."""
    user = sess.CurrentUser(id=1, full_name="J. Smith", role="<script>alert(1)</script>")
    markup = sess._identity_html(user)
    assert "<script>" not in markup
    assert "&lt;script&gt;" in markup


PLAYER_A = sess.CarriedPlayer(
    player_id=1, player_name="A. Player", competition_id=10, season_id=100,
    position_group="CB", minutes=900)
PLAYER_B = sess.CarriedPlayer(
    player_id=2, player_name="B. Player", competition_id=10, season_id=100,
    position_group="CM", minutes=1200)


def test_resolve_assess_target_selects_a_freshly_carried_player():
    """'Assess this player' on the profile or a watchlist row hands off a CarriedPlayer --
    arriving with one, with nothing else in state, opens it."""
    assert sess.resolve_assess_target({}, PLAYER_A) == PLAYER_A


def test_resolve_assess_target_keeps_the_current_selection_across_a_rerun():
    """Streamlit re-runs the whole script on every widget interaction (e.g. typing a band).
    That re-run carries nothing fresh, so the persisted selection must survive -- this is the
    bug: the old pop-on-read carry vanished on exactly this re-run."""
    state = {sess._CURRENT_KEY: PLAYER_A}
    assert sess.resolve_assess_target(state, None) == PLAYER_A


def test_resolve_assess_target_shows_nothing_with_no_carry_and_no_current_selection():
    """Assess opened directly from the navigation, with no hand-off and nothing previously
    selected: the search box, not a stale player."""
    assert sess.resolve_assess_target({}, None) is None


def test_resolve_assess_target_lets_an_explicit_pick_replace_the_current_selection():
    """Choosing a different player from the Assess page's own search box always wins, even
    over an existing current selection or an (unrelated, stale) carry."""
    state = {sess._CURRENT_KEY: PLAYER_A}
    assert sess.resolve_assess_target(state, None, selected=PLAYER_B) == PLAYER_B
    assert sess.resolve_assess_target(state, PLAYER_A, selected=PLAYER_B) == PLAYER_B


def test_resolve_assess_target_clear_always_empties_the_selection():
    """Explicitly clearing wins over everything -- a current selection, a fresh carry, and
    even a simultaneous (nonsensical) explicit pick -- there is nothing left to show."""
    state = {sess._CURRENT_KEY: PLAYER_A}
    assert sess.resolve_assess_target(state, None, clear=True) is None
    assert sess.resolve_assess_target(state, PLAYER_B, clear=True) is None
    assert sess.resolve_assess_target(state, None, selected=PLAYER_B, clear=True) is None


# --- peek_carry: I5 (audit-dashboard.md) -- the sidebar Season/Position reseed after ---------
# `st.switch_page` fix. `app.py` reads this BEFORE `get_assess_target` (assess.py) pops the
# same key later in the same run, so the read here must never consume it.

def test_peek_carry_reads_a_fresh_carry():
    state = {sess._CARRY_KEY: PLAYER_A}
    assert sess.peek_carry(state) == PLAYER_A


def test_peek_carry_does_not_consume_the_carry():
    """The whole point: `get_assess_target`'s own pop, later in the same run, must still see
    the carry -- a peek that consumed it would silently break the Assess page it was meant
    for."""
    state = {sess._CARRY_KEY: PLAYER_A}
    sess.peek_carry(state)
    assert state[sess._CARRY_KEY] == PLAYER_A


def test_peek_carry_is_none_with_no_carry():
    assert sess.peek_carry({}) is None
