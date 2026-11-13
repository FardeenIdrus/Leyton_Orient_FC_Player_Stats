"""The Report page: page shell + JSON endpoints. Every figure comes from `lofc.core.report_page`
(the view of `report.data.build`, the function Streamlit's Report page calls). Nothing here is
stored. Both downloads are built in the browser from the page's own preview (owner, 2026-11-13:
the file is what the user sees, and the photo never leaves the browser), so there is no
download route here; Streamlit keeps its own document.

    GET  /report?player=&competition=&season=           page shell
    GET  /api/report/{p}/{c}/{s}                        the report + the form's criteria
                                                        ({"error": {kind, text}} when none)
                                                        + "scouts": each scout's latest verdict
    GET  /api/report/{p}/{c}/{s}?variant=data_only      the data-only report (no form, no scouts)
    POST /api/report/{p}/{c}/{s}           {form}       the report with the author's input

    GET  /api/report/players?season=                    every player of the season, A-Z

Player search (owner 2026-11-13): the empty box lists every player of the season A-Z (the
season-wide index Streamlit's Report page and `/api/players/search` use); typing filters the
same list in the browser on the index's own search key. POSTs need the session and the X-LOFC-Request header
(`write_user`) although they write nothing: the form's text never goes in a URL or a log.
"""
from __future__ import annotations

import functools
import json
import logging
import threading
import time

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, Response

from lofc.web.security import WebUser, current_user, write_user

router = APIRouter()
log = logging.getLogger("lofc.web.warmup")


def _core():
    from lofc.core import report_page
    return report_page


def _season_choices() -> tuple[list[dict], int]:
    from lofc.core import players_pool as pp
    seasons = pp.season_options()
    return seasons, pp.default_season([s["id"] for s in seasons])


def _base(p: int, c: int, s: int):
    """The base report, or None when the player-season does not exist (404). Any other error
    (e.g. `model.medical` refusing a season it has no label for) propagates: a 500, not a
    misleading "no report for this player"."""
    try:
        return _core().base_report(p, c, s)
    except ValueError as exc:
        if str(exc).startswith("no player-season"):
            return None
        raise


async def _body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _ids(p, c, s) -> dict:
    return {"player": p, "competition": c, "season": s}


_page_log = logging.getLogger("lofc.web.report")


def _page_answer(build) -> JSONResponse:
    """The page's JSON. A missing player-season or a report that cannot be built is a state
    the page shows (as Streamlit's page does), so it comes back as {"error": {...}} with 200:
    a 4xx/5xx would also put a console error in the browser."""
    try:
        data = build()
    except Exception:                                           # noqa: BLE001
        _page_log.exception("report could not be built")
        return JSONResponse({"error": {"kind": "failed", "text": "The report could not be built."}})
    if data is None:
        return JSONResponse({"error": {"kind": "missing",
                                       "text": "No report for this player in this season."}})
    return JSONResponse(data)


@functools.lru_cache(maxsize=4)
def _players_json(version: str, season_id: int) -> bytes:
    from lofc.core import players_pool as pp
    return json.dumps({"season": season_id, "rows": pp.season_players(season_id)},
                      ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _data_version() -> str:
    from lofc.dashboard import loaders as L
    return L.data_version(with_scorecards=True)


@router.get("/api/report/players")
async def season_players(request: Request, user: WebUser = Depends(current_user)):
    """Every player of the season A-Z (owner 2026-11-13: the empty search box lists them all;
    typing filters the same list in the browser). Built once per data version and season."""
    try:
        season = int(request.query_params.get("season", ""))
    except ValueError:
        return JSONResponse({"error": "season must be a number"}, status_code=400)
    body = await run_in_threadpool(lambda: _players_json(_data_version(), season))
    return Response(body, media_type="application/json")


@router.get("/api/report/{player_id}/{competition_id}/{season_id}")
async def report_json(player_id: int, competition_id: int, season_id: int, request: Request,
                      user: WebUser = Depends(current_user)):
    data_only = request.query_params.get("variant") == "data_only"

    def build():
        base = _base(player_id, competition_id, season_id)
        if base is None:
            return None
        core = _core()
        if data_only:     # numbers only (owner): no scout verdicts
            from lofc.report.data import as_data_only
            out = core.view(as_data_only(base), _ids(player_id, competition_id, season_id))
            out["scouts"] = []
            return out
        out = core.view(base, _ids(player_id, competition_id, season_id))
        out["form"] = core.form_spec(base.position)
        out["scouts"] = core.player_scout_verdicts(player_id)
        return out
    return await run_in_threadpool(_page_answer, build)


def _authored_view(user: WebUser, p: int, c: int, s: int, body: dict):
    base = _base(p, c, s)
    if base is None:
        return None, None
    return base, _core().authored_from_body(base.position, body, user.full_name, user.role)


@router.post("/api/report/{player_id}/{competition_id}/{season_id}")
async def report_preview(player_id: int, competition_id: int, season_id: int, request: Request,
                         user: WebUser = Depends(write_user)):
    body = await _body(request)

    def build():
        base, authored = _authored_view(user, player_id, competition_id, season_id, body)
        if base is None:
            return None
        from lofc.report.data import with_authored
        shown = with_authored(base, authored) if authored else base
        out = _core().view(shown, _ids(player_id, competition_id, season_id))
        out["scouts"] = _core().player_scout_verdicts(player_id)
        return out
    return await run_in_threadpool(_page_answer, build)


def warm_report_caches() -> None:
    """The season-wide frames every report reads (all players' neutral rows, percentiles and
    style labels: ~2 s per season cold) and the resolved scout bands, newest season first.
    Never raises; logs how long it took."""
    t0 = time.perf_counter()
    try:
        seasons, _ = _season_choices()
        _core().warm(sorted((s["id"] for s in seasons), reverse=True))
    except Exception:                                           # noqa: BLE001
        log.warning("report warm-up failed", exc_info=True)
    log.warning("report warm-up done in %.0f s", time.perf_counter() - t0)


def mount(app, render, shell) -> None:
    app.include_router(router)
    from lofc.core import webcache
    # re-run after any data change (webcache.rewarm_on_change), not only at start-up
    webcache.register_warmup("report", lambda: warm_report_caches())

    def warm() -> None:
        # After the card's warm-up (which runs after the Players one): one heavy job at a time.
        def run() -> None:
            from lofc.web.api import players as players_api
            players_api.PLAYERS_WARM.wait(timeout=900)
            for t in threading.enumerate():
                if t.name == "lofc-card-warmup":
                    t.join(timeout=900)
            warm_report_caches()
        threading.Thread(target=run, name="lofc-report-warmup", daemon=True).start()
    app.router.on_startup.append(warm)

    @app.get("/report", response_class=HTMLResponse, name="page_report")
    async def report_page(request: Request, user: WebUser = Depends(current_user)):
        from lofc.web import pages
        seasons, default = await run_in_threadpool(_season_choices)
        return render(request, "report.html", **shell(
            request, user, "report", page=pages.PAGES["report"], seasons=seasons,
            default_season=default))
