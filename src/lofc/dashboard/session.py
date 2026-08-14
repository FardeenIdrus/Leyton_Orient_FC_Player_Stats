"""The login gate and the current-user session.

The decisions this module makes -- is a stored session still valid, what does a lockout say
-- are pure functions taking a plain dict and a clock, so they are unit-tested without
Streamlit. `require_login` is the only Streamlit-aware function here, and it is a thin
render layer over them.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

import streamlit as st

from lofc.dashboard import auth
from lofc.store import users as store_users


@dataclass(frozen=True)
class CurrentUser:
    """Who is logged in. `role` is a RECORD of who acted, not a restriction on assessing --
    every role may assess both dimensions (Decision 16). Ask `auth.can()` before any gated
    action; never compare `role` to a literal in page code."""

    id: int
    full_name: str
    role: str


def restore_user(state, now: datetime.datetime) -> CurrentUser | None:
    """The logged-in user held in `state`, or None if there is none or it has expired.

    `state` is any mapping (Streamlit's session_state, or a plain dict in tests).
    """
    user_id = state.get("user_id")
    if user_id is None:
        return None
    if auth.session_expired(state.get("logged_in_at"), now):
        return None
    return CurrentUser(id=user_id, full_name=state["full_name"], role=state["role"])


def lockout_message(seconds: int) -> str:
    """The user-facing wait. Rounded UP: telling someone to wait 0 minutes and having the
    next attempt fail is worse than overstating by 30 seconds."""
    minutes = max(1, -(-seconds // 60))
    unit = "minute" if minutes == 1 else "minutes"
    return (f"Too many failed attempts. This account is locked for {minutes} {unit}. "
            "An administrator can reset it sooner.")


def logout() -> None:
    for key in ("user_id", "full_name", "role", "logged_in_at"):
        st.session_state.pop(key, None)


def _password_change_form(user_id: int, engine) -> None:
    st.warning("Your password was set by an administrator. Choose a new one to continue.")
    with st.form("change_password"):
        first = st.text_input("New password", type="password")
        second = st.text_input("Confirm new password", type="password")
        submitted = st.form_submit_button("Set password", type="primary")
    if not submitted:
        return
    if first != second:
        st.error("The two passwords do not match.")
        return
    try:
        store_users.change_password(engine, user_id, first)
    except ValueError as exc:
        st.error(f"Password rejected: {exc}")
        return
    st.session_state["must_change_password"] = False
    st.rerun()


def require_login(engine) -> CurrentUser | None:
    """Render the login gate. Returns the user once authenticated, None until then.

    The caller renders nothing else while this returns None -- that is what makes it a gate
    rather than a banner.
    """
    now = datetime.datetime.now()
    user = restore_user(st.session_state, now)

    if user is not None and st.session_state.get("must_change_password"):
        _password_change_form(user.id, engine)
        return None
    if user is not None:
        return user
    if st.session_state.get("user_id") is not None:
        # Had a session, and restore_user rejected it -- it expired. Clear it so the stale
        # identity cannot linger in state behind the login form.
        logout()
        st.info("Your session has expired. Please sign in again.")

    left, _ = st.columns([1, 1])
    with left:
        st.subheader("Sign in")
        with st.form("login"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", type="primary")
        if submitted:
            result = store_users.authenticate(engine, username, password, now)
            if result.outcome == "ok":
                st.session_state.update({
                    "user_id": result.user_id, "full_name": result.full_name,
                    "role": result.role, "logged_in_at": now,
                    "must_change_password": result.must_change_password})
                st.rerun()
            elif result.outcome == "locked":
                st.error(lockout_message(result.seconds_locked))
            elif result.outcome == "inactive":
                st.error("This account has been deactivated. Contact an administrator.")
            else:
                st.error("Incorrect username or password.")
        st.caption("Accounts are created by an administrator. There is no self-service "
                   "sign-up and no email reset — ask an administrator to reset a "
                   "forgotten password.")
    return None


def sidebar_identity(user: CurrentUser) -> None:
    """Show who is signed in, and the logout control."""
    st.sidebar.markdown(f"**{user.full_name}**  \n`{user.role}`")
    st.sidebar.button("Sign out", on_click=logout, use_container_width=True)
    st.sidebar.divider()
