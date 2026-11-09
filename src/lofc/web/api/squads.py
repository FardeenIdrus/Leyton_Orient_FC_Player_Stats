"""The Squads & loans page: page shell + JSON + CSV. Every row, figure and filter comes from
`lofc.core.squads` (the same `build_frame` / `sidebar_view` / `build_view` / `squad_display`
the Streamlit page calls); this module only turns the URL into those calls and the result
into JSON.

    GET /squads                     page shell
    GET /api/squads?(state)         tiles, the table, links, option lists
    GET /api/squads.csv?(state)     the same table as CSV (Streamlit's download)

State (all optional): league, club, position, q, show (loan | expiring), sort, dir, and the
sidebar filters this page honours: max_age, leagues (repeated), foot, contract, loan.
"""
from __future__ import annotations

import collections
import logging
import threading
import time
import weakref
from typing import NamedTuple

import pandas as pd
from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, Response

from lofc.core import squads as S
from lofc.core import webcache
from lofc.web.security import WebUser, current_user

router = APIRouter()
log = logging.getLogger("lofc.web.squads")
TITLE = "Squads, contracts and loans"
EMPTY = "No squad data for this season yet."
_RATING = {"This season", "Last season", "Also rated"}
_NUM = {"Age", "Minutes", "Months left"}


def _num(v, lo: float, hi: float, default: float) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return default if x != x else min(hi, max(lo, x))


# --- data, kept until the data changes (webcache: keyed on web_data_version, which tracks
# every table read here, and rolls over daily -- Age and Months left count from today) -------
class Data(NamedTuple):
    cur: int | None
    prev: int | None
    cur_name: str
    prev_name: str
    base: pd.DataFrame          # build_frame: the whole squad, prepared, before any filter
    n_scraped: int              # Transfermarkt squad rows (0 = the appearance fallback)
    asof: str | None
    leagues_all: list


@webcache.versioned(maxsize=2)
def _scraped() -> pd.DataFrame:
    return S.scraped_squads()


@webcache.versioned(maxsize=4)
def _cards(season_id: int) -> pd.DataFrame:
    return S.season_scorecards(season_id)


@webcache.versioned(maxsize=2)
def _data() -> Data:
    from lofc.dashboard import loaders as L
    from lofc.dashboard import seasons as SE
    seasons = L.available_seasons()
    if not seasons:
        return Data(None, None, "", "", pd.DataFrame(), 0, None, L.league_names())
    cur, prev = S.page_seasons(seasons, None)
    scraped = _scraped()
    base = S.build_frame(S.registered_squad_frame(cur, prev, squads=scraped), _cards(cur), cur)
    return Data(cur, prev, SE.season_name_for(cur), SE.season_name_for(prev), base,
                len(scraped), S.transfermarkt_asof(SE.contract_data_date(), SE.loan_data_date()),
                L.league_names())


@webcache.versioned(maxsize=2)
def _loans(cur: int, prev: int) -> pd.DataFrame:
    return S.prepare_loans(S.loans_frame(cur, prev))


@webcache.versioned(maxsize=2)
def _targets(cur: int, prev: int) -> dict:
    """{player_id: (competition_id, season_id)} -- where each row's click opens the card."""
    d = _data()
    ids = list(d.base.get("player_id", pd.Series(dtype=float)))
    ids += list(_loans(cur, prev).get("player_id", pd.Series(dtype=float)))
    return S.profile_targets(S.all_rated_rows(), ids)


def _thin(view: pd.DataFrame, cur: int, prev: int) -> dict:
    return S.thin_pools(view, _cards(cur), _cards(prev), cur, prev)


# --- the request -----------------------------------------------------------------------------
class Query:
    """Query parameters -> a validated request. Anything unknown falls back to the default (a
    stale URL must still open the page, never a 422)."""

    def __init__(self, params, leagues_all) -> None:
        from lofc.core import players_pool as pp
        from lofc.dashboard import seasons as SE
        g = params.get
        self.league = g("league") or S.ALL
        self.club = g("club") or S.ALL
        self.position = g("position") or S.ALL
        self.q = (g("q") or "")[:100]
        self.show = S.show_from_code(g("show"))
        self.max_age = int(_num(g("max_age"), 18, 40, 40))
        chosen = [x for x in params.getlist("leagues") if x in leagues_all]
        # Every league selected = no league filter (the Players page's rule).
        self.leagues = tuple(chosen) if chosen and set(chosen) < set(leagues_all) else ()
        foot = g("foot")
        self.foot = foot if foot in pp.FOOT_CHOICES else "Any"
        c = g("contract")
        self.contract = c if c in SE.CONTRACT_HORIZONS else SE.DEFAULT_CONTRACT_HORIZON
        loan = g("loan")
        self.loan = loan if loan in SE.LOAN_FILTERS else SE.LOAN_ANY
        sort = g("sort")
        self.sort = sort if sort in S.DISPLAY_COLUMNS else None
        self.descending = (g("dir") or "desc").lower() != "asc"

    def filters(self):
        from lofc.dashboard.sidebar_filters import SidebarFilters
        return SidebarFilters(max_age=self.max_age, leagues=self.leagues,
                              contract_horizon=self.contract, loan=self.loan, foot=self.foot)


def _columns(d: Data) -> list[dict]:
    label = {"This season": f"Composite {d.cur_name}", "Last season": f"Composite {d.prev_name}"}
    return [{"key": c, "label": label.get(c, c), "help": S.COLUMN_HELP.get(c),
             "kind": "rating" if c in _RATING else "num" if c in _NUM else "text"}
            for c in S.DISPLAY_COLUMNS]


def _build(params):
    """(payload, table with the withheld composites blanked) for one request."""
    from lofc.dashboard import seasons as SE
    t0 = time.perf_counter()
    d = _data()
    q = Query(params, d.leagues_all)
    f = q.filters()
    payload = {
        "title": TITLE,
        "meta": f"Every registered squad member, {d.cur_name}. Click a row to open the player.",
        "asof": d.asof, "warning": None, "empty": None,
        "columns": _columns(d), "rows": [], "links": [], "messages": [], "player_ids": [],
        "tiles": [{"label": k, "value": v} for k, v in S.tiles(S.summary_counts(
            S.ensure_display_columns(pd.DataFrame())))],
        "csv": {"label": S.DOWNLOAD_LABEL, "help": S.DOWNLOAD_HELP,
                "name": S.export_filename(S.ALL, S.ALL)},
        "footer": S.WEB_FOOTER,
        "options": {"league": [S.ALL], "club": [S.ALL], "position": [S.ALL],
                    "show": [{"code": S.show_code(o), "label": o} for o in S.SHOW_OPTIONS],
                    "leagues": d.leagues_all, "foot": ["Any", "Left", "Right"],
                    "contract": list(SE.CONTRACT_HORIZONS), "loan": list(SE.LOAN_FILTERS),
                    "max_age": {"min": 18, "max": 40, "default": 40}},
    }
    if S.squad_source_warning(d.n_scraped, len(d.base)):
        payload["warning"] = S.incomplete_text(len(d.base))
    state = {"league": S.ALL, "club": S.ALL, "position": S.ALL, "q": q.q,
             "show": S.show_code(q.show), "max_age": q.max_age, "leagues": list(q.leagues),
             "foot": q.foot, "contract": q.contract, "loan": q.loan, "sort": q.sort,
             "dir": "desc" if q.descending else "asc"}
    payload["state"] = state
    if d.base.empty:
        payload["empty"] = EMPTY
        return payload, None
    frame = S.sidebar_view(d.base, f)
    v = S.build_view(frame, f, q.league, q.club, q.position, q.q, q.show,
                     loans=lambda: _loans(d.cur, d.prev))
    view = S.sort_view(v.view, q.sort, q.descending)
    # Every cell, link and CSV value is a property of the row alone, so they are built once for
    # the whole squad (or every loan) and a request only picks its rows, in its order.
    src = _loans(d.cur, d.prev) if v.show == S.SHOW_LOANS else d.base
    pos, cells, links, messages, pids, shown_all = _all_rows(src, d.cur, d.prev)
    order = [pos[i] for i in view.index]
    state.update(league=v.league, club=v.club, position=v.position, show=S.show_code(v.show))
    payload["options"].update(league=v.league_options, club=v.club_options,
                              position=v.position_options)
    payload["tiles"] = [{"label": k, "value": val} for k, val in S.tiles(v.counts)]
    payload["rows"] = [cells[i] for i in order]
    payload["links"] = [links[i] for i in order]
    payload["messages"] = [messages[i] for i in order]
    payload["player_ids"] = [pids[i] for i in order]
    payload["csv"]["name"] = S.export_filename(v.league, v.club)
    shown = (shown_all.iloc[order].reset_index(drop=True) if len(order)
             else S.ensure_display_columns(pd.DataFrame())[S.DISPLAY_COLUMNS])
    payload["ms"] = round((time.perf_counter() - t0) * 1000)
    return payload, shown


_row_cache: dict = {}


def _all_rows(frame: pd.DataFrame, cur: int, prev: int):
    """(index -> position, cells, links, messages, player ids, CSV table) for EVERY row of
    `frame` (the whole squad, or every loan), built once per frame: what Streamlit's
    `squad_display` shows for the row, with the withheld composites, and the row's click."""
    hit = _row_cache.get(id(frame))
    if hit is not None and hit[0]() is frame:
        return hit[1]
    full = frame.reset_index(drop=True)
    if full.empty:
        full = S.ensure_display_columns(full)
    table = S.squad_display(full[S.DISPLAY_COLUMNS])
    thin = _thin(full, cur, prev)
    cells = S.web_cells(full, table, thin)
    links, messages = S.row_links(full, _targets(cur, prev))
    pids = ([None if pd.isna(p) else int(p) for p in full["player_id"]]
            if "player_id" in full.columns else [None] * len(full))
    shown = table.copy()
    for (i, col) in thin:                 # the file is the screen: a withheld composite is "—"
        shown.at[i, col] = "\u2014"
    if not frame.index.is_unique:
        raise ValueError("squad frame index is not unique")
    out = ({idx: i for i, idx in enumerate(frame.index)}, cells, links, messages, pids, shown)
    with _lock:
        if len(_row_cache) > 8:
            _row_cache.clear()
        _row_cache[id(frame)] = (weakref.ref(frame), out)
    return out


# Whole answers keyed by the exact query (back/forward, toggles and the warm-up ask for the
# same one again), as JSON bytes, keyed on web_data_version.
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
        payload, shown = _build(request.query_params)
        if shown is None:
            shown = S.ensure_display_columns(pd.DataFrame())[S.DISPLAY_COLUMNS]
        return S.for_export(shown).to_csv(index=False).encode("utf-8"), payload["csv"]["name"]
    data, name = await run_in_threadpool(build)
    return Response(data, media_type="text/csv",
                    headers={"Content-Disposition": csv_disposition(name)})


def warm_squads() -> None:
    """Read the squad, loans, scorecards and click targets once and draw the default page, so
    the first visit after a restart is warm. Never raises."""
    from starlette.datastructures import QueryParams
    t0 = time.perf_counter()
    try:
        d = _data()
        if d.cur is not None:
            _loans(d.cur, d.prev)
            _targets(d.cur, d.prev)
            _cards(d.prev)
            # the default page, its two other views, and each league (the first choice made)
            leagues = S.league_options(d.base)[1:]
            for qs in [{}, {"show": "loan"}, {"show": "expiring"}] + [{"league": lg} for lg in leagues]:
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
    from lofc.core import webcache
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
