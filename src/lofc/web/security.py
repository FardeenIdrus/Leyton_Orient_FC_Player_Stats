"""Session cookie, current-user dependency and write protection for the web front end.

Reuses the Streamlit app's building blocks (`dashboard.cookie_auth` token, `auth` expiry and
permissions, `store.users` accounts) -- nothing is re-implemented, so the two front ends can
never disagree about who may sign in. The cookie carries only a signed user id + login time;
role, name, active and must-change-password are re-read from the live row on every request, so
a deactivation or forced reset takes effect on the very next click."""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from fastapi import HTTPException, Request

from lofc.dashboard import auth, cookie_auth

COOKIE_NAME = "lofc_web"
WRITE_HEADER = "X-LOFC-Request"


@dataclass(frozen=True)
class WebUser:
    id: int
    full_name: str
    role: str
    logged_in_at: datetime.datetime
    must_change_password: bool


class LoginRedirect(Exception):
    """Raised by `current_user` for a page request with no valid session."""

    def __init__(self, to: str = "/login") -> None:
        self.to = to


def is_https(request: Request) -> bool:
    # Behind the club's TLS proxy the app sees http; honour the proxy's scheme header too.
    # Only ever used to ADD the Secure flag, so a spoofed header cannot weaken anything.
    return (request.url.scheme == "https"
            or request.headers.get("x-forwarded-proto", "").lower() == "https")


def issue_cookie(response, request: Request, user_id: int, logged_in_at: datetime.datetime,
                 secret: str) -> None:
    """Set the session cookie. Absolute 12 h: the token is anchored at login and is never
    re-issued later. Secure follows the request scheme (a browser never sends a Secure cookie
    over plain http, so forcing it would break local use rather than tighten it)."""
    response.set_cookie(
        COOKIE_NAME, cookie_auth.issue_token(user_id, logged_in_at, secret),
        max_age=auth.SESSION_TTL_MINUTES * 60, path="/", httponly=True, samesite="strict",
        secure=is_https(request))


def clear_cookie(response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="strict")


def read_session(request: Request) -> WebUser | None:
    """The signed-in user for this request, or None. Fails closed on every problem."""
    state = request.app.state
    now = state.clock()
    payload = cookie_auth.verify_token(request.cookies.get(COOKIE_NAME), state.secret, now)
    if payload is None:
        return None
    row = state.users.get_user(payload.user_id)
    restored = cookie_auth.resolve_cookie_restore(payload, row)   # None if deactivated/gone
    if restored is None:
        return None
    return WebUser(restored.user_id, restored.full_name, restored.role,
                   restored.logged_in_at, restored.must_change_password)


def _is_api(request: Request) -> bool:
    return request.url.path.startswith("/api/")


def _fail(request: Request, status: int, detail: str, redirect: str):
    if _is_api(request):
        raise HTTPException(status_code=status, detail=detail)
    raise LoginRedirect(redirect)


def session_user(request: Request) -> WebUser:
    """Dependency: any valid session, including one that still owes a password change (the
    change-password page itself needs that). Pages redirect to /login; the API gets 401."""
    user = read_session(request)
    if user is None:
        _fail(request, 401, "not_signed_in", "/login")
    return user


def current_user(request: Request) -> WebUser:
    """Dependency for every normal page and endpoint: a valid session AND no pending forced
    password change (pages go to /change-password; the API gets 403)."""
    user = session_user(request)
    if user.must_change_password:
        _fail(request, 403, "password_change_required", "/change-password")
    return user


def write_user(request: Request) -> WebUser:
    """Dependency for every POST that changes anything: the session AND the custom header.
    A cross-site form cannot add a custom header, so this is CSRF protection on top of
    SameSite=Strict."""
    user = current_user(request)
    if request.headers.get(WRITE_HEADER) != "1":
        raise HTTPException(status_code=403, detail="missing_request_header")
    return user


def require_secret(secret: str | None) -> str:
    if not secret:
        raise RuntimeError(
            "SESSION_SECRET is not set: the web front end will not start without it "
            "(it signs the login cookie). Set SESSION_SECRET in .env.")
    return secret
