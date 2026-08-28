"""The login gate and the current-user session.

The decisions this module makes -- is a stored session still valid, what does a lockout say
-- are pure functions taking a plain dict and a clock, so they are unit-tested without
Streamlit. `require_login` is the only Streamlit-aware function here, and it is a thin
render layer over them.
"""

from __future__ import annotations

import datetime
import html
import time
import urllib.parse
from dataclasses import dataclass

import extra_streamlit_components as stx
import streamlit as st

from lofc.config import settings
from lofc.dashboard import auth, cookie_auth, login_throttle
from lofc.store import users as store_users

# Name of the browser cookie that carries the signed "remembered session" token (see
# cookie_auth.py). Only ever read via `st.context.cookies` (a read-only view of the Cookie
# header on the request that opened this connection -- available immediately, with none of
# the mount-delay a custom component's own getter has) and written/cleared via the
# extra_streamlit_components component below, which is the only supported way for a
# Streamlit script to make the BROWSER hold a cookie at all (there is no `st.set_cookie`).
_COOKIE_NAME = "lofc_session"


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


def peek_carry(state) -> CarriedPlayer | None:
    """The player mid-handoff via `go_to_assess`, without consuming the carry
    (`get_assess_target` still does that later, when the Assess page itself renders this same
    run) -- so `app.py` can reseed the sidebar's Season/Position widgets with the right values
    on the one run `st.switch_page` lands on. Pure (`state` is any mapping -- Streamlit's
    session_state, or a plain dict in tests), like `resolve_assess_target` above.

    Confirmed directly against the running app: `st.switch_page` resets THIS Streamlit
    build's widget-backed session state (the Season/Position/Leagues selectboxes) even though
    the sidebar code that creates them runs unconditionally before `st.navigation(...).run()`
    dispatches to any specific page -- but a plain session_state entry like `_CARRY_KEY`
    (never bound to a widget's own `key=`) survives the same navigation untouched. Season was
    the one sidebar filter this was ever REPORTED on (spec/audit), because it is the only one
    without an already-correct value to coincidentally fall back to in the reported repro (a
    Centre Forward carried while Position's own hardcoded default is also "Centre Forward");
    Position resets exactly the same way and needs the same fix for a carried player of any
    OTHER position. Leagues resets too, but its default (every league) is always a superset
    that still includes the carried player's league, so it is self-healing and left alone.
    """
    return state.get(_CARRY_KEY)


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


def _is_https() -> bool:
    """Whether THIS request reached the app over TLS. Behind the club's cloudflared tunnel
    that is true; hitting the container directly (`http://localhost:8501`, e.g. from inside
    the docker network or during local verification) it is not. `Secure`-flagged cookies are
    simply never attached to a plain-HTTP request by the browser -- not "sent but ignored",
    genuinely never sent -- so hard-coding `secure=True` would not make the cookie stricter
    over plain HTTP, it would make it silently non-functional there while still claiming to be
    the safer setting. Deciding from `st.context.url` (no component, no round trip) means the
    flag is the strictest value that ACTUALLY works for however this particular request
    arrived, every time -- Secure behind the tunnel, still HMAC-signed and SameSite=Strict
    (never HttpOnly-capable either way -- see `_issue_cookie`) otherwise."""
    url = st.context.url
    return bool(url) and url.startswith("https://")


def force_reload_after_logout() -> bool:
    """Call first thing in `main()`, before anything else renders. If the previous run was a
    sign-out, force a full browser reload and return True so the caller renders nothing else
    this pass (the reload is about to blow the page away regardless). Returns False on every
    other run -- a no-op that costs one dict lookup.

    Also clears the remembered-session cookie, in the SAME `<script>` block and strictly
    BEFORE the reload statement -- signing out must invalidate the cookie, not just the
    server-side state, or the very reload this triggers would immediately restore the session
    it just tore down. This runs the clear as plain JS rather than through the
    extra_streamlit_components cookie manager on purpose: that component's set/get is a
    round trip to a mounted frontend widget, and nothing here guarantees it has mounted
    before the reload fires one line later; a `document.cookie` assignment inside this same
    inline script is synchronous and always runs first. The attributes (path, SameSite,
    Secure) match how the cookie was set (`_issue_cookie` below) -- a cookie's identity for
    deletion purposes is its name+path, so a mismatched path here would silently fail to
    remove it."""
    if not st.session_state.pop(_JUST_LOGGED_OUT_KEY, False):
        return False
    secure_attr = "; Secure" if _is_https() else ""
    st.iframe(
        "<script>"
        f"document.cookie = '{_COOKIE_NAME}=; Max-Age=0; path=/; SameSite=Strict{secure_attr}';"
        "window.top.location.reload();"
        "</script>", height=1)
    return True


def _cookie_manager() -> stx.CookieManager:
    """The browser-cookie component, used only to WRITE the remembered-session cookie
    (`_issue_cookie`) -- Streamlit has no `st.set_cookie`, so a component that runs JS in the
    browser is the only way to make one exist at all. Reading is deliberately NOT done through
    this: `st.context.cookies` (stdlib Streamlit, no component) gives the cookies sent with
    the very first request on this connection immediately, with none of the "not mounted yet"
    delay a component's own getter has -- exactly what a fresh-refresh restore needs."""
    return stx.CookieManager(key="lofc_cookie_manager")


def restore_from_cookie(engine, now: datetime.datetime) -> None:
    """If this connection has no in-memory session yet, try to revive one from the signed
    cookie the browser sent with its very first request. A no-op (leaves `st.session_state`
    untouched) unless ALL of: a cookie is present, its signature verifies and it has not
    expired (`cookie_auth.verify_token`), AND the account it names is still active right now
    (`cookie_auth.resolve_cookie_restore`, checked against a fresh `users` row -- never
    against anything the cookie itself claims). On success, populates the exact same
    `st.session_state` keys a fresh sign-in does, `must_change_password` included, so
    `require_login` cannot tell a cookie restore apart from a session that never left memory.

    Public (no leading underscore) and idempotent -- `require_login` always calls it, so it is
    safe on its own, but `app.py`'s `main()` also calls it once BEFORE its own pre-`require_login`
    peek at `st.session_state` (the one deciding whether to draw the top-right identity box),
    so that peek sees a cookie-restored identity on the very first paint after a refresh
    instead of one render behind.
    """
    if st.session_state.get("user_id") is not None:
        return          # already have a session this run -- nothing to restore
    if not settings.session_secret:
        return           # no secret configured: cookie persistence is not offered at all
    raw = st.context.cookies.get(_COOKIE_NAME)
    # `st.context.cookies` hands back the cookie value exactly as it arrived on the HTTP
    # `Cookie:` header -- i.e. RAW, not decoded. The cookie component percent-encodes the
    # value when it writes it (our token embeds an ISO timestamp, and ':' is not a valid
    # cookie-octet character in the strict interpretation the underlying JS cookie library
    # uses), so the value that reaches us here is something like "...T11%3A05%3A00...", not
    # "...T11:05:00...". unquote() undoes exactly that; a token with nothing to decode passes
    # through unchanged, so this is safe even if the encoding scheme upstream ever changes.
    token = urllib.parse.unquote(raw) if raw else None
    payload = cookie_auth.verify_token(token, settings.session_secret, now)
    user_row = store_users.get_user(engine, payload.user_id) if payload is not None else None
    restored = cookie_auth.resolve_cookie_restore(payload, user_row)
    if restored is None:
        return
    st.session_state.update({
        "user_id": restored.user_id, "full_name": restored.full_name,
        "role": restored.role, "logged_in_at": restored.logged_in_at,
        "must_change_password": restored.must_change_password})


def _issue_cookie(user_id: int, logged_in_at: datetime.datetime) -> None:
    """(Re-)write the remembered-session cookie for the currently signed-in user. Called on
    every run of an authenticated session (see `require_login`) rather than once at login, so
    a cookie dropped by the browser, or one whose write raced a rerun the first time, gets
    another chance on the very next interaction -- cheap (a local HMAC plus a JS call the
    browser no-ops if the value is unchanged) and idempotent.

    `expires_at` and the token's own embedded expiry both come from `auth.SESSION_TTL_MINUTES`
    -- the ONE expiry rule (see cookie_auth.py); the browser-side attribute is just hygiene so
    an already-invalid cookie does not linger in the browser's jar.

    Flags set as strictly as this component (and this request) allow: `same_site="strict"`
    always; `secure` follows `_is_https()` -- True behind the club's cloudflared tunnel, False
    for a plain-HTTP hit on the container directly, because a browser never attaches a
    `Secure` cookie to a plain-HTTP request at all (see `_is_https` docstring) -- forcing True
    unconditionally would not make the cookie stricter, it would make it silently stop
    working the moment anyone reaches the app without TLS. `HttpOnly` is NOT settable here, or
    by any Streamlit cookie component, regardless of scheme -- HttpOnly can only be set via a
    `Set-Cookie` HTTP response header, and Streamlit exposes no way for app code to add one;
    every such component (this one included) writes cookies through browser JS
    (`document.cookie`), which the HttpOnly spec deliberately keeps out of reach. The cookie
    is still tamper-evident (HMAC-signed, verified server-side) and carries no secret --
    reading it via a hypothetical XSS would hand over nothing but a user id and a timestamp.
    """
    if not settings.session_secret:
        return
    token = cookie_auth.issue_token(user_id, logged_in_at, settings.session_secret)
    expires_at = logged_in_at + datetime.timedelta(minutes=auth.SESSION_TTL_MINUTES)
    _cookie_manager().set(
        _COOKIE_NAME, token, key="lofc_cookie_set", path="/", expires_at=expires_at,
        secure=_is_https(), same_site="strict")


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
    restore_from_cookie(engine, now)
    user = restore_user(st.session_state, now)

    if user is not None:
        # Keep the cookie alive for as long as the in-memory session is -- issued here (not
        # only at login) so it covers a cookie-restored session too, and so a browser that
        # dropped the write the first time gets another chance on every subsequent run.
        _issue_cookie(user.id, st.session_state["logged_in_at"])

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
            if result.outcome != "ok":
                # I4: per-account lockout (above) does nothing against one guessed password
                # sprayed across many usernames -- no single account ever fails 5 times. See
                # `login_throttle` for why this is behaviour-based (distinct usernames
                # failing, process-wide) rather than address-based. A pause on every failed
                # attempt once the spray signature is seen; never a hard block, so a real
                # spike of office mistypes is slowed, not locked out.
                login_throttle.record_failure(username, now)
                delay = login_throttle.delay_seconds(now)
                if delay:
                    time.sleep(delay)
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


def _identity_html(user: CurrentUser) -> str:
    """The escaped markup for the topbar identity chip. Pulled out of `topbar_identity` so it
    is testable without a Streamlit runtime, mirroring `badges._badge_html`.

    `full_name` is set by an admin at account creation (`tabs/users.py`) and is never
    validated as plain text -- the identical field is correctly escaped where it appears in
    `badges.py` (author/approver names on a badge). This call site was rendering the same
    field, unescaped, with `unsafe_allow_html=True`, on every page for every session: an
    admin (or a compromised admin account) could set another user's -- including another
    admin's -- full name to markup that executes in that victim's browser on their next
    sign-in. The session cookie cannot be marked `HttpOnly` (see `_issue_cookie`), so this
    was enough to hijack a session via `document.cookie`. `role` is drawn from a fixed
    internal set (`auth.ROLES`), not user input, but is escaped too for defence in depth."""
    return (f"<div class='lofc-identity-name'>{html.escape(user.full_name)}</div>"
            f"<div class='lofc-identity-role'>{html.escape(user.role)}</div>")


def topbar_identity(user: CurrentUser) -> None:
    """Who is signed in, and the sign-out control -- rendered top-right of the page shell
    (inside `theme.header()`'s right-hand column), the way identity sits in the corner of an
    ordinary website rather than buried in a sidebar. Renders into whatever container is
    active when it is called; it holds no layout of its own."""
    with st.container(key="topbar_identity"):
        st.markdown(_identity_html(user), unsafe_allow_html=True)
        st.button("Sign out", on_click=logout)
