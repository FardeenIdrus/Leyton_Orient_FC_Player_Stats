"""The Squads & loans page: page shell + JSON + CSV. Every row, figure and option comes from
`lofc.core.squad_lists` (rebuilt 2026-11-16); this module turns the URL into its calls and the
result into JSON.

    GET /squads                     page shell
    GET /api/squads?(state)         tiles, the table, links, option lists, the data-date line
    GET /api/squads.csv?(state)     the same table as CSV

State (all optional): league, club, view (squad | in | out), position, max_age, contract,
loan, foot, q, sort, dir. With neither league nor club, the page opens on Leyton Orient.
"""
from __future__ import annotations

import collections
import datetime
import logging
import threading
import time
from typing import NamedTuple

import pandas as pd
from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, Response

from lofc.core import squad_lists as Q
from lofc.core import webcache
from lofc.web.security import WebUser, current_user

router = APIRouter()
log = logging.getLogger("lofc.web.squads")
TITLE = "Squads, contracts and loans"
EMPTY = "No squad data for this season yet."
FOOTER = "— = unknown. Contracts and loans: the 7 leagues with Transfermarkt data."
HOME_CLUB = "Leyton Orient"


def _num(v, lo: float, hi: float, default: float) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return default if x != x else min(hi, max(lo, x))


class Data(NamedTuple):
    cur: int | None
    cur_name: str
    rows: pd.DataFrame          # squad_lists.build_rows: every row of the season, every view
    today: datetime.date
    impect_date: datetime.date | None
    contracts_date: datetime.date | None
    loans_date: datetime.date | None
    targets: dict               # player_id -> (competition_id, season_id): his best card


@webcache.versioned(maxsize=2)
def _data() -> Data:
    from lofc.core import squads as S
    from lofc.core.infobar import pull_dates
    from lofc.dashboard import loaders as L
    from lofc.dashboard import seasons as SE
    today = datetime.date.today()
    seasons = L.available_seasons()
    if not seasons:
        return Data(None, "", pd.DataFrame(), today, None, None, None, {})
    cur, _prev = S.page_seasons(seasons, None)
    engine = L.get_engine()
    rows = Q.build_rows(Q.load_sources(engine, cur, L.competition_name_by_id()), today)
    contracts, loans = Q.tm_club_dates(engine)
    targets = S.profile_targets(S.all_rated_rows(), rows["player_id"].dropna().unique())
    return Data(cur, SE.season_name_for(cur), rows, today, pull_dates(engine).get("Impect"),
                contracts, loans, targets)


def _home(rows: pd.DataFrame) -> tuple[str, str]:
    """(league, club) of Leyton Orient this season, or (All, All)."""
    hit = rows[(rows["club"] == HOME_CLUB) & rows["league"].notna()]
    return (hit["league"].iloc[0], HOME_CLUB) if len(hit) else (Q.ALL, Q.ALL)


def _view(params, d: Data) -> Q.PageView:
    g = params.get
    league, club = g("league"), g("club")
    if league is None and club is None:
        league, club = _home(d.rows)
    return Q.build_page(
        d.rows, league=league or Q.ALL, club=club or Q.ALL, view=g("view") or "squad",
        position=g("position") or Q.ALL, max_age=int(_num(g("max_age"), 16, 40, 40)),
        contract=g("contract") or "Any", loan=g("loan") or "Any", foot=g("foot") or "Any",
        q=g("q") or "",
        sort=g("sort") or None, descending=(g("dir") or "desc").lower() != "asc",
        season_name=d.cur_name)


def _build(params):
    """(payload, the page view) for one request."""
    t0 = time.perf_counter()
    d = _data()
    payload = {"title": TITLE, "meta": "", "asof": [], "empty": None, "columns": [],
               "rows": [], "links": [], "messages": [], "tiles": [], "stale": False,
               "csv": {"label": "⬇ Download (CSV)", "name": "lofc_squads.csv"},
               "footer": FOOTER, "options": {}, "state": {}}
    if d.cur is None or d.rows.empty:
        payload["empty"] = EMPTY
        return payload, None
    v = _view(params, d)
    payload["meta"] = f"{d.cur_name}. Click a player to open his card."
    payload["asof"] = Q.date_line(d.impect_date, d.contracts_date, d.loans_date, d.today,
                                  v.tm_in_scope)
    payload["stale"] = bool(v.tm_in_scope and Q.is_stale(d.contracts_date or d.loans_date,
                                                          d.today))
    payload["columns"] = v.columns
    payload["rows"] = Q.web_cells(v, d.today)
    payload["links"], payload["messages"] = Q.links(v, d.targets)
    payload["tiles"] = [{"label": k, "value": f"{n:,}"} for k, n in v.tiles]
    payload["csv"]["name"] = Q.export_filename(v.league, v.club, v.view)
    payload["options"] = v.options
    payload["state"] = {"league": v.league, "club": v.club, "view": v.view,
                        "position": v.position, "max_age": v.max_age, "contract": v.contract,
                        "loan": v.loan, "foot": v.foot, "q": v.q, "sort": v.sort,
                        "dir": "desc" if v.descending else "asc"}
    payload["ms"] = round((time.perf_counter() - t0) * 1000)
    return payload, v


# Whole answers keyed by the exact query, as JSON bytes, keyed on web_data_version.
_answers: "collections.OrderedDict[tuple, bytes]" = collections.OrderedDict()
_lock = threading.Lock()
_CACHE_SIZE = 64


def _answer(params) -> bytes:
    from lofc.dashboard import loaders as L
    key = (L.web_data_version(), tuple(sorted(params.multi_items())))
    with _lock:
        hit = _answers.get(key)
        if hit is not None:
            _answers.move_to_end(key)
            return hit
    body = JSONResponse(_build(params)[0]).body
    with _lock:
        _answers[key] = body
        while len(_answers) > _CACHE_SIZE:
            _answers.popitem(last=False)
    return body


@router.get("/api/squads")
async def squads_json(request: Request, user: WebUser = Depends(current_user)):
    body = await run_in_threadpool(_answer, request.query_params)
    return Response(body, media_type="application/json")


@router.get("/api/squads.csv")
async def squads_csv(request: Request, user: WebUser = Depends(current_user)):
    from lofc.core.card import csv_disposition

    def build():
        payload, v = _build(request.query_params)
        table = Q.csv_table(v) if v is not None else pd.DataFrame()
        return table.to_csv(index=False).encode("utf-8"), payload["csv"]["name"]
    data, name = await run_in_threadpool(build)
    return Response(data, media_type="text/csv",
                    headers={"Content-Disposition": csv_disposition(name)})


def warm_squads() -> None:
    """Build the season's rows once and draw the opening page and each league, so the first
    visit after a restart is warm. Never raises."""
    from starlette.datastructures import QueryParams
    t0 = time.perf_counter()
    try:
        d = _data()
        if d.cur is not None and not d.rows.empty:
            leagues = sorted(d.rows["league"].dropna().unique())
            for qs in [{}] + [{"league": lg, "club": Q.ALL} for lg in leagues]:
                _answer(QueryParams(qs))
    except Exception:                                           # noqa: BLE001
        log.warning("squads warm-up failed", exc_info=True)
    logging.getLogger("lofc.web.warmup").warning("squads warm-up done in %.0f s",
                                                 time.perf_counter() - t0)


_AFTER = ("lofc-card-warmup", "lofc-compare-warmup", "lofc-report-warmup",
          "lofc-scout-reports-warmup")


def mount(app, render, shell) -> None:
    """Register the API and the page shell. Called before the generic page loop."""
    app.include_router(router)
    # re-run after any data change (webcache.rewarm_on_change), not only at start-up
    webcache.register_warmup("squads", lambda: warm_squads())

    def warm() -> None:
        # After the other pages' warm-ups, never beside them (one heavy job at a time): wait
        # for Players, then for the card / Compare / Report / Scout reports threads to finish.
        def run() -> None:
            from lofc.web.api import players as players_api
            players_api.PLAYERS_WARM.wait(timeout=900)
            time.sleep(1)
            for _ in range(1800):
                if not any(t.name in _AFTER and t.is_alive()
                           for t in threading.enumerate()):
                    break
                time.sleep(1)
            warm_squads()
        threading.Thread(target=run, name="lofc-squads-warmup", daemon=True).start()
    app.router.on_startup.append(warm)

    @app.get("/squads", response_class=HTMLResponse, name="page_squads")
    async def squads_page(request: Request, user: WebUser = Depends(current_user)):
        from lofc.web import pages
        return render(request, "squads.html", **shell(request, user, "squads",
                                                      page=pages.PAGES["squads"]))
