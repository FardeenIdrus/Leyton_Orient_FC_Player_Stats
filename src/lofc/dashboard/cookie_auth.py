"""The signed "remembered session" cookie: lets a returning browser re-establish its session
without re-entering credentials, so a page refresh does not bounce recruitment staff back to
the sign-in form.

Streamlit keeps session state in server memory, keyed to the websocket connection. A browser
refresh opens a new connection with empty state, so `session.restore_user` finds nothing --
this module is what a fresh connection consults BEFORE giving up and showing the login form.

Deliberately DB-free and Streamlit-free (mirrors `auth.py`): issuing and verifying a token,
and deciding whether a verified token may actually restore a session, are pure functions
taking plain values, so they are unit-tested without a browser and without Postgres.
`session.py` is the only place a browser cookie or a `users` row meets these functions.

SECURITY:
  - `issue_token`/`verify_token` use `hmac` (stdlib) with `lofc.config.settings.session_secret`
    -- never hard-coded, never committed (see `.env.example`). An unset secret means cookie
    persistence is simply not offered (`session.py` checks before calling either function);
    it is never silently disabled by falling through to an insecure default.
  - The token carries a user id and an issue time -- NEVER a password or password hash. Role,
    name and must-change-password are re-read from the LIVE `users` row on every restore
    (`resolve_cookie_restore`), never trusted from the token, so a change to the account since
    the cookie was issued (deactivation, a forced password reset) always takes effect
    immediately.
  - Expiry reuses `auth.SESSION_TTL_MINUTES` / `auth.session_expired` -- the same rule an
    ordinary in-memory session already uses -- rather than inventing a second one.
  - `verify_token` is tamper-evident: `hmac.compare_digest` (constant-time) against a
    recomputed signature. Any change to the payload, or a token signed under a different
    secret, fails closed (returns None), the same as no cookie at all.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
from dataclasses import dataclass
from typing import Protocol

from lofc.dashboard import auth

_SEP = "."


def _sign(payload: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    # URL/cookie-safe: no '+', '/' or '=' padding for a cookie component to worry about.
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def issue_token(user_id: int, logged_in_at: datetime.datetime, secret: str) -> str:
    """A signed token for `user_id`'s session, anchored at `logged_in_at` -- the SAME
    timestamp already stored in `st.session_state["logged_in_at"]` for the in-memory
    session, so a cookie-restored session expires at exactly the moment an in-memory one
    would have (see module docstring: one expiry rule, not two)."""
    payload = f"{user_id}{_SEP}{logged_in_at.isoformat()}"
    return f"{payload}{_SEP}{_sign(payload, secret)}"


@dataclass(frozen=True)
class TokenPayload:
    """What a verified token proves: a user id, as of an issue time. Nothing else -- no
    role, no name, no password -- travels in the cookie itself."""

    user_id: int
    logged_in_at: datetime.datetime


def verify_token(token: str | None, secret: str, now: datetime.datetime) -> TokenPayload | None:
    """The decoded payload if `token` is well-formed, its signature verifies against
    `secret`, and it has not expired -- else None. Every failure mode (missing token,
    malformed token, bad signature, unparseable fields, expired) returns None rather than
    raising: a cookie is untrusted input from the browser, and a corrupt or tampered value
    must fail closed, not crash the login gate."""
    if not token:
        return None
    # Split into exactly 3 logical fields (user id, issue time, signature) by taking the
    # FIRST separator to end the user id and the LAST to start the signature -- everything
    # between is the issue time, however many separators it contains. `datetime.isoformat()`
    # itself contains a '.' before the microseconds (the same character as `_SEP`), so a
    # naive "split into exactly 3 parts" would reject every real token; user id (digits only)
    # and signature (base64url: no '.') can never legitimately contain `_SEP`, so this is
    # unambiguous regardless of how many separators the middle field holds.
    parts = token.split(_SEP)
    if len(parts) < 3:
        return None
    user_id_s, signature, logged_in_at_s = parts[0], parts[-1], _SEP.join(parts[1:-1])
    payload = f"{user_id_s}{_SEP}{logged_in_at_s}"
    if not hmac.compare_digest(signature, _sign(payload, secret)):
        return None
    try:
        user_id = int(user_id_s)
        logged_in_at = datetime.datetime.fromisoformat(logged_in_at_s)
    except ValueError:
        return None
    if auth.session_expired(logged_in_at, now):
        return None
    return TokenPayload(user_id=user_id, logged_in_at=logged_in_at)


class _UserRow(Protocol):
    """Structural stand-in for the live account row a caller passes to
    `resolve_cookie_restore` -- `store.users.ActiveUserRow` in production, a plain stub in
    tests. Kept as a Protocol (not an import of `store.users`) so this module stays free of
    any database dependency, the same way `auth.py` is."""

    full_name: str
    role: str
    is_active: bool
    must_change_password: bool


@dataclass(frozen=True)
class RestoredSession:
    """The `st.session_state` fields a caller should set to bring a cookie-verified session
    back to life -- the same shape a fresh login already populates, so `session.require_login`
    treats the two identically (including still forcing a password change when
    `must_change_password` is set)."""

    user_id: int
    full_name: str
    role: str
    logged_in_at: datetime.datetime
    must_change_password: bool


def resolve_cookie_restore(
        token: TokenPayload | None, user_row: "_UserRow | None") -> RestoredSession | None:
    """Whether a verified cookie may actually restore a session, given the user row as it
    stands RIGHT NOW -- not as it was when the cookie was issued. `user_row` is the result of
    a fresh lookup by `token.user_id` (None if the account no longer exists at all).

    Returns None (never restores) when:
      - the token itself did not verify (`token` is None), or the account is gone
      - the account has since been deactivated (`is_active` is False) -- a cookie issued
        before a deactivation must not go on working after it

    Still returns a RestoredSession (the caller ends up signed in) when `must_change_password`
    is set -- the restore succeeds, but the caller populates the SAME state a fresh sign-in
    would, so `require_login`'s existing forced-password-change screen renders exactly as it
    does for a brand new login. Silently skipping that step on a cookie restore would be a
    second, weaker path to the same account.
    """
    if token is None or user_row is None:
        return None
    if not user_row.is_active:
        return None
    return RestoredSession(
        user_id=token.user_id, full_name=user_row.full_name, role=user_row.role,
        logged_in_at=token.logged_in_at, must_change_password=user_row.must_change_password)
