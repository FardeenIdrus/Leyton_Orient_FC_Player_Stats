"""The Report page: page shell + JSON endpoints. Every figure comes from `lofc.core.report_page`
(the view of `report.data.build`, the function Streamlit's Report page calls); the downloads are
`report.render.to_html`, the same document Streamlit downloads. Nothing here is stored.

    GET  /report?player=&competition=&season=           page shell
    GET  /api/report/{p}/{c}/{s}                        the report + the form's criteria
                                                        ({"error": {kind, text}} when none)
    POST /api/report/{p}/{c}/{s}           {form}       the report with the author's input
    GET  /api/report/{p}/{c}/{s}/download?variant=data_only|full   the document (HTML)
    POST /api/report/{p}/{c}/{s}/download  {form}       the document with the author's input

Player search is the Players page's `/api/players/search?season=&q=` (the same season-wide
index Streamlit's Report page searches). POSTs need the session and the X-LOFC-Request header
(`write_user`) although they write nothing: the form's text never goes in a URL or a log.
"""
from __future__ import annotations

import logging
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Request
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


@router.get("/api/report/{player_id}/{competition_id}/{season_id}")
async def report_json(player_id: int, competition_id: int, season_id: int,
                      user: WebUser = Depends(current_user)):
    def build():
        base = _base(player_id, competition_id, season_id)
        if base is None:
            return None
        core = _core()
        out = core.view(base, _ids(player_id, competition_id, season_id))
        out["form"] = core.form_spec(base.position)
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
        return _core().view(shown, _ids(player_id, competition_id, season_id))
    return await run_in_threadpool(_page_answer, build)


def _document(base, authored, data_only: bool) -> tuple[str, str]:
    core = _core()
    note = core.not_rated_note(base)
    shown, html, data_only_html = core.variants(base, authored, not_rated=note)
    name = core.safe_filename(shown.player_name, shown.season_label)
    if data_only:
        return core.data_only_filename(name), data_only_html
    return name, html


def _download(name: str, html: str) -> Response:
    from lofc.core.card import csv_disposition
    return Response(html.encode("utf-8"), media_type="text/html; charset=utf-8",
                    headers={"Content-Disposition": csv_disposition(name)})


@router.get("/api/report/{player_id}/{competition_id}/{season_id}/download")
async def report_download(player_id: int, competition_id: int, season_id: int, request: Request,
                          user: WebUser = Depends(current_user)):
    data_only = request.query_params.get("variant") == "data_only"

    def build():
        base = _base(player_id, competition_id, season_id)
        return None if base is None else _document(base, None, data_only)
    got = await run_in_threadpool(build)
    if got is None:
        raise HTTPException(status_code=404, detail="no_such_player_season")
    return _download(*got)


@router.post("/api/report/{player_id}/{competition_id}/{season_id}/download")
async def report_download_authored(player_id: int, competition_id: int, season_id: int,
                                   request: Request, user: WebUser = Depends(write_user)):
    body = await _body(request)

    def build():
        base, authored = _authored_view(user, player_id, competition_id, season_id, body)
        return None if base is None else _document(base, authored, False)
    got = await run_in_threadpool(build)
    if got is None:
        raise HTTPException(status_code=404, detail="no_such_player_season")
    return _download(*got)


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
