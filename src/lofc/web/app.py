"""The web front end's FastAPI app (`uvicorn lofc.web.app:app`). See docs/frontend.md.

`create_app` takes its collaborators (user store, info-bar counts, clock, secret) as arguments
so tests drive it with fakes; the module-level `app` is built lazily on first access so merely
importing this module (tests, tooling) never needs the production secret or a database."""

from __future__ import annotations

import asyncio
import datetime
import html
import logging
import time
import urllib.parse
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from lofc.config import settings
from lofc.dashboard import auth, login_throttle
from lofc.web import pages
from lofc.web.security import (
    WRITE_HEADER, LoginRedirect, WebUser, clear_cookie, current_user, issue_cookie,
    read_session, require_secret, session_user, write_user)

log = logging.getLogger(__name__)
_HERE = Path(__file__).parent
_INFO_TTL_SECONDS = 60


class DbUserStore:
    """The production user store: `store.users` over a lazily-created engine. Tests pass a
    fake with the same three methods."""

    def __init__(self) -> None:
        self._engine = None

    def engine(self):
        if self._engine is None:
            from sqlalchemy import create_engine
            # hide_parameters: same reason as the Streamlit engine -- never echo a password
            # hash into an error page.
            self._engine = create_engine(settings.database_url, hide_parameters=True)
        return self._engine

    def authenticate(self, username: str, password: str, now: datetime.datetime):
        from lofc.store import users
        return users.authenticate(self.engine(), username, password, now)

    def get_user(self, user_id: int):
        from lofc.store import users
        return users.get_user(self.engine(), user_id)

    def change_password(self, user_id: int, new_password: str) -> None:
        from lofc.store import users
        users.change_password(self.engine(), user_id, new_password)

    # --- the Users page (admin): the same store calls as the Streamlit Users page ---------
    def list_users(self, now):
        from lofc.store import users
        return users.list_users(self.engine(), now)

    def create_user(self, username, full_name, role, password):
        from lofc.store import users
        return users.create_user(self.engine(), username, full_name, role, password)

    def reset_password(self, user_id, new_password):
        from lofc.store import users
        users.reset_password(self.engine(), user_id, new_password)

    def clear_lockout(self, user_id):
        from lofc.store import users
        users.clear_lockout(self.engine(), user_id)

    def set_active(self, user_id, active):
        from lofc.store import users
        users.set_active(self.engine(), user_id, active)


class InfoBar:
    """The sticky info bar's items (players / rated / leagues / season), via the same
    `lofc.core.infobar` functions the Streamlit strip uses. Cached briefly: it is on every
    page and the counts only change when data is reloaded. Any failure shows an empty bar,
    never an error page."""

    def __init__(self, store: DbUserStore) -> None:
        self._store = store
        self._cached: tuple[float, list[str]] | None = None

    def items(self) -> list[str]:
        if self._cached and time.monotonic() - self._cached[0] < _INFO_TTL_SECONDS:
            return self._cached[1]
        try:
            from lofc.core import infobar
            from lofc.leagues import is_season_id, season_label
            engine = self._store.engine()
            season = infobar.latest_season_id(engine)
            players, rated, _ = infobar.headline_counts(engine, season)
            label = season_label(season) if season is not None and is_season_id(season) else None
            items = [*infobar.infobar_count_items(players, rated),
                     f"<b>{infobar.league_count(engine)}</b> leagues"]
            if label:
                items.append(f"<b>{html.escape(str(label))}</b> season")
        except Exception:
            log.exception("info bar counts unavailable")
            return []
        self._cached = (time.monotonic(), items)
        return items


def _form(body: bytes) -> dict[str, str]:
    """application/x-www-form-urlencoded body -> first value per key. Parsed by hand so the
    app needs no python-multipart dependency."""
    return {k: v[0] for k, v in urllib.parse.parse_qs(body.decode("utf-8", "replace"),
                                                      keep_blank_values=True).items()}


def lockout_message(seconds: int) -> str:
    """Same wording as the Streamlit login (`dashboard.session.lockout_message`), rounded UP."""
    minutes = max(1, -(-seconds // 60))
    unit = "minute" if minutes == 1 else "minutes"
    return (f"Too many failed attempts. This account is locked for {minutes} {unit}. "
            "An administrator can reset it sooner.")


def role_label(role: str) -> str:
    return role.replace("_", " ").capitalize()


def create_app(*, users=None, secret: str | None = None, info_items=None,
               clock=datetime.datetime.now) -> FastAPI:
    secret = require_secret(settings.session_secret if secret is None else secret)
    app = FastAPI(title="LOFC Recruitment", docs_url=None, redoc_url=None, openapi_url=None)
    store = users if users is not None else DbUserStore()
    # gzip (TASKS 2.36 S-A): HTML, JSON, JS and CSS over ~1 KB. Added first, so the header
    # middleware below wraps it: Server-Timing, CSP and Set-Cookie are set as before.
    from starlette.middleware.gzip import GZipMiddleware
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.state.users = store
    app.state.secret = secret
    app.state.clock = clock
    app.state.info_items = info_items if info_items is not None else (
        InfoBar(store).items if isinstance(store, DbUserStore) else (lambda: []))
    templates = Jinja2Templates(directory=str(_HERE / "templates"))
    from lofc.web import static_version
    templates.env.globals["static_url"] = static_version.url

    # Versioned static files (TASKS 2.36 S-B): /static/v/<version>/<path>, immutable for a year.
    # Only the current version is served, so a page holding an old version can never mix its
    # modules with today's. Registered before the plain /static mount so it wins.
    _static_root = (_HERE / "static").resolve()

    @app.get("/static/v/{ver}/{path:path}", include_in_schema=False)
    async def versioned_static(ver: str, path: str):
        if ver != static_version.current():
            raise HTTPException(status_code=404)
        target = (_static_root / path).resolve()
        if _static_root not in target.parents or not target.is_file():
            raise HTTPException(status_code=404)
        from fastapi.responses import FileResponse
        return FileResponse(target, headers={
            "Cache-Control": "public, max-age=31536000, immutable"})

    app.mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        t0 = time.perf_counter()
        response = await call_next(request)
        h = response.headers
        # How long the server took (DevTools / the browser harness read it), and a log line
        # for any slow answer, so a slow click can be told apart from slow page code.
        ms = (time.perf_counter() - t0) * 1000
        h["Server-Timing"] = f"app;dur={ms:.1f}"
        if ms > 500 and not request.url.path.startswith("/static/"):
            logging.getLogger("lofc.web.slow").warning("slow %s %s: %.0f ms", request.method,
                                                       request.url.path, ms)
        # No inline script anywhere (page code is ES modules from /static), so script-src can
        # be strictly 'self'. Inline style="" is used for bar widths, hence style-src.
        h["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        h["X-Content-Type-Options"] = "nosniff"
        h["X-Frame-Options"] = "DENY"
        h["Referrer-Policy"] = "same-origin"
        if not request.url.path.startswith("/static/"):
            h["Cache-Control"] = "no-store"
        elif not request.url.path.startswith("/static/v/") or response.status_code != 200:
            h["Cache-Control"] = "no-cache"         # unversioned: always revalidate
        return response

    @app.exception_handler(LoginRedirect)
    async def _redirect(request: Request, exc: LoginRedirect):
        return RedirectResponse(exc.to, status_code=303)

    def render(request: Request, name: str, status: int = 200, **ctx):
        return templates.TemplateResponse(request, name, ctx, status_code=status)

    def shell(request: Request, user: WebUser, active: str, **ctx):
        return dict(user=user, role_label=role_label(user.role), active=active,
                    nav=pages.nav_for(user.role, auth.can),
                    info_items=app.state.info_items(), **ctx)

    # ---- unauthenticated -------------------------------------------------------------
    def warm_done() -> bool:
        """Every start-up warm-up has finished: the loaders + Players one (PLAYERS_WARM) and
        each page's `lofc-*-warmup` thread."""
        import threading
        from lofc.web.api import players as players_api
        return players_api.PLAYERS_WARM.is_set() and not any(
            t.name.endswith("-warmup") and t.is_alive() for t in threading.enumerate())

    @app.get("/healthz")
    async def healthz():
        # Liveness (always 200) and whether the warm-up is done, for people and scripts.
        return {"status": "ok", "warm": warm_done()}

    @app.get("/readyz")
    async def readyz():
        # Readiness for the production switch-over (scripts/deploy.sh): 503 until warm.
        ready = warm_done()
        return JSONResponse({"ready": ready}, status_code=200 if ready else 503)

    # Home: the club crest and one link per page in use (TASKS 2.36 U7).
    _HOME_LINES = {
        "players": "Rank every league's players by position",
        "squads": "Squads, loans and contracts",
        "compare": "Up to three players side by side",
        "scout-reports": "The club's scouting sheet",
        "watchlist": "Players the club is tracking",
        "report": "One-page report to send",
        "physical": "SkillCorner tracking data",
    }

    @app.get("/", include_in_schema=False, response_class=HTMLResponse)
    async def root(request: Request, user: WebUser = Depends(current_user)):
        allowed = {p.key for _, items in pages.nav_for(user.role, auth.can) for p in items}
        links = [dict(path=pages.PAGES[k].path, title=pages.PAGES[k].title,
                      group=pages.PAGES[k].group, line=line)
                 for k, line in _HOME_LINES.items() if k in allowed]
        home = pages.Page("home", "/", "Home", "")
        return render(request, "home.html", **shell(request, user, "home", page=home, links=links))

    @app.get("/login", response_class=HTMLResponse)
    async def login_form(request: Request):
        user = read_session(request)
        if user is not None:
            return RedirectResponse("/change-password" if user.must_change_password
                                    else "/players", status_code=303)
        return render(request, "login.html", error=None)

    @app.post("/login")
    async def login_submit(request: Request):
        # No session exists yet, so there is nothing for the X-LOFC-Request header to protect;
        # the form is same-origin (CSP form-action 'self') and a forged login gains nothing.
        form = _form(await request.body())
        username, password = form.get("username", ""), form.get("password", "")
        now = app.state.clock()
        result = await run_in_threadpool(store.authenticate, username, password, now)
        if result.outcome != "ok":
            # Spray throttle exactly as the Streamlit login: a pause, never a block.
            login_throttle.record_failure(username, now)
            delay = login_throttle.delay_seconds(now)
            if delay:
                await asyncio.sleep(delay)
            if result.outcome == "locked":
                msg = lockout_message(result.seconds_locked)
            elif result.outcome == "inactive":
                msg = "This account has been deactivated. Contact an administrator."
            else:
                msg = "Incorrect username or password."
            return render(request, "login.html", status=401, error=msg)
        target = "/change-password" if result.must_change_password else "/players"
        response = RedirectResponse(target, status_code=303)
        issue_cookie(response, request, result.user_id, now, secret)
        return response

    @app.post("/logout")
    async def logout(request: Request, user: WebUser = Depends(session_user)):
        if request.headers.get(WRITE_HEADER) != "1":
            raise HTTPException(status_code=403, detail="missing_request_header")
        response = JSONResponse({"ok": True})
        clear_cookie(response)
        return response

    # ---- forced / voluntary password change ------------------------------------------
    @app.get("/change-password", response_class=HTMLResponse)
    async def change_password_form(request: Request, user: WebUser = Depends(session_user)):
        return render(request, "change_password.html", user=user,
                      forced=user.must_change_password)

    @app.post("/api/change-password")
    async def change_password(request: Request, user: WebUser = Depends(session_user)):
        if request.headers.get(WRITE_HEADER) != "1":
            raise HTTPException(status_code=403, detail="missing_request_header")
        try:
            body = await request.json()
            first, second = str(body["password"]), str(body["confirm"])
        except Exception:
            raise HTTPException(status_code=400, detail="bad_request")
        if first != second:
            return JSONResponse({"ok": False, "error": "The two passwords do not match."},
                                status_code=400)
        try:
            await run_in_threadpool(store.change_password, user.id, first)
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": f"Password rejected: {exc}"},
                                status_code=400)
        return {"ok": True}

    # ---- page shells -----------------------------------------------------------------
    def register(page: pages.Page) -> None:
        async def view(request: Request, user: WebUser = Depends(current_user)):
            needed = pages.PERMISSION_FOR.get(page.key)
            if needed and not auth.can(user.role, needed):
                return render(request, "forbidden.html", status=403,
                              **shell(request, user, page.key, page=page))
            return render(request, "page.html", **shell(request, user, page.key, page=page))
        app.add_api_route(page.path, view, methods=["GET"], response_class=HTMLResponse,
                          name=f"page_{page.key}")

    # Pages with a real implementation are mounted first so their route wins over the
    # "Currently building" placeholder registered below for the same path.
    from lofc.web.api import players as players_api
    players_api.mount(app, render, shell)
    from lofc.web.api import card as card_api
    card_api.mount(app, render, shell)
    from lofc.web.api import compare as compare_api
    compare_api.mount(app, render, shell)
    from lofc.web.api import report as report_api
    report_api.mount(app, render, shell)
    from lofc.web.api import squads as squads_api
    squads_api.mount(app, render, shell)
    from lofc.web.api import scout_reports as scout_reports_api
    scout_reports_api.mount(app, render, shell)
    from lofc.web.api import watchlist as watchlist_api
    watchlist_api.mount(app, render, shell)
    from lofc.web.api import physical as physical_api
    physical_api.mount(app, render, shell)
    from lofc.web.api import users as users_api
    users_api.mount(app, render, shell)
    from lofc.web.api import reference as reference_api
    reference_api.mount(app, render, shell)
    from lofc.web.api import club_vs_league as club_vs_league_api
    club_vs_league_api.mount(app, render, shell)

    for page in pages.PAGES.values():
        register(page)

    def start_rewarm_watcher() -> None:
        # Once every start-up warm-up has finished, watch the data version: any write (a
        # scout-sheet sync, a pipeline load) re-runs every page's warm-up (TASKS 2.36 I1).
        import threading

        def run() -> None:
            from lofc.core import webcache
            from lofc.web.api import players as players_api
            players_api.PLAYERS_WARM.wait(timeout=900)
            for _ in range(3600):
                if not any(t.name.endswith("-warmup") and t.is_alive()
                           for t in threading.enumerate()):
                    break
                time.sleep(1)
            webcache.rewarm_on_change()
        threading.Thread(target=run, name="lofc-rewarm-watch", daemon=True).start()
    app.router.on_startup.append(start_rewarm_watcher)

    return app


_app: FastAPI | None = None


def __getattr__(name: str):
    """`uvicorn lofc.web.app:app` -- built on first access, so a missing SESSION_SECRET stops
    the server with a clear message at start-up rather than breaking every import."""
    global _app
    if name == "app":
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(name)
