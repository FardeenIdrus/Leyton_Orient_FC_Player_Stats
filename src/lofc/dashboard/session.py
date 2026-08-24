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


@dataclass(frozen=True)
class CarriedPlayer:
    """A player selection handed from one page to the Assess page, so the assessment form
    opens on that exact player-season without the assessor re-searching for him."""

    player_id: int
    player_name: str
    competition_id: int
    season_id: int
    position_group: str | None
    minutes: int | None


_PAGES_KEY = "_nav_pages"          # {name: st.Page(...)}, registered once per run by app.py
_CARRY_KEY = "_assess_carry"       # a CarriedPlayer, consumed by the Assess page on read
_CURRENT_KEY = "_assess_current"   # the persistent "currently assessing" player, if any --
                                    # survives a widget-triggered re-run (unlike _CARRY_KEY)


def register_pages(pages: dict[str, object]) -> None:
    """Record this run's `st.Page` objects so any module can `switch_to(...)` a named page
    without importing `app.py` -- which would cycle, since `app.py` imports every tab module.
    Call once from `main()`, before `st.navigation(...).run()`.
    """
    st.session_state[_PAGES_KEY] = pages


def switch_to(name: str) -> None:
    """Navigate to a page registered by `register_pages` (e.g. 'assess')."""
    st.switch_page(st.session_state[_PAGES_KEY][name])


def go_to_assess(player: CarriedPlayer) -> None:
    """Carry `player` to the Assess page and navigate there in one call -- the handoff used
    by 'Assess this player' on the profile and on a watchlist row."""
    st.session_state[_CARRY_KEY] = player
    switch_to("assess")


def resolve_assess_target(
        state, carried: CarriedPlayer | None, *,
        selected: CarriedPlayer | None = None, clear: bool = False) -> CarriedPlayer | None:
    """Decide who the Assess page is currently assessing. Pure and Streamlit-free (`state` is
    any mapping -- Streamlit's session_state, or a plain dict in tests) so the transition is
    unit-tested the same way `restore_user` is.

    Precedence, highest first:
      1. `clear=True`      -- the user explicitly cleared the selection. Always wins: nothing
                               is currently being assessed.
      2. `selected`         -- the user explicitly picked a player from the Assess page's own
                               search box. Always replaces whatever was there.
      3. `carried`          -- a fresh hand-off from another page ('Assess this player').
                               Consumed on arrival, so it wins over a stale `state` value.
      4. `state[_CURRENT_KEY]` -- nothing new happened this run (e.g. the user typed into a
                               band selectbox); keep showing whoever was already selected.
    Falls through to None when none of the above holds -- nothing is being assessed.
    """
    if clear:
        return None
    if selected is not None:
        return selected
    if carried is not None:
        return carried
    return state.get(_CURRENT_KEY)


def get_assess_target(
        *, selected: CarriedPlayer | None = None, clear: bool = False) -> CarriedPlayer | None:
    """The Streamlit-aware wrapper over `resolve_assess_target`: pops any freshly-carried
    player (consumed on read, so a later unrelated visit to Assess does not silently reopen a
    stale player), reconciles it against an explicit `selected` pick or `clear`, then persists
    the result in `_CURRENT_KEY` so it survives the re-run a widget interaction triggers.
    """
    carried = st.session_state.pop(_CARRY_KEY, None)
    target = resolve_assess_target(st.session_state, carried, selected=selected, clear=clear)
    if target is None:
        st.session_state.pop(_CURRENT_KEY, None)
    else:
        st.session_state[_CURRENT_KEY] = target
    return target


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


_JUST_LOGGED_OUT_KEY = "_just_logged_out"


def logout() -> None:
    for key in ("user_id", "full_name", "role", "logged_in_at"):
        st.session_state.pop(key, None)
    # `st.navigation(...).run()` told the browser about the nine pages while this user was
    # signed in. That page list is client-side state Streamlit keeps across an ordinary rerun
    # -- and a rerun is all a button's on_click normally triggers -- so without this, the
    # sidebar page list would keep showing after sign-out even though this run never calls
    # `st.navigation` again. Flag it so `force_reload_after_logout` can force a hard browser
    # reload instead, which is the only thing that clears it.
    st.session_state[_JUST_LOGGED_OUT_KEY] = True


def force_reload_after_logout() -> bool:
    """Call first thing in `main()`, before anything else renders. If the previous run was a
    sign-out, force a full browser reload and return True so the caller renders nothing else
    this pass (the reload is about to blow the page away regardless). Returns False on every
    other run -- a no-op that costs one dict lookup."""
    if not st.session_state.pop(_JUST_LOGGED_OUT_KEY, False):
        return False
    st.iframe("<script>window.top.location.reload();</script>", height=1)
    return True


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


def topbar_identity(user: CurrentUser) -> None:
    """Who is signed in, and the sign-out control -- rendered top-right of the page shell
    (inside `theme.header()`'s right-hand column), the way identity sits in the corner of an
    ordinary website rather than buried in a sidebar. Renders into whatever container is
    active when it is called; it holds no layout of its own."""
    with st.container(key="topbar_identity"):
        st.markdown(
            f"<div class='lofc-identity-name'>{user.full_name}</div>"
            f"<div class='lofc-identity-role'>{user.role}</div>",
            unsafe_allow_html=True)
        st.button("Sign out", on_click=logout)
