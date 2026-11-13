"""The Physical page (TASKS 2.1e): page shell + one JSON endpoint. Every figure comes from
`lofc.core.physical_page` over the frames the ratings and the card read (SkillCorner API data,
refreshed with each pipeline run); this module only turns the URL into a request.

    GET /physical?season=&league=&position=&metric=&x=&y=&min=&sort=&dir=&view=   page shell
    GET /api/physical?season=&league=&position=&x=&y=&age=&min=     filters, the league-position pool (leaders +
                                                    scatter) and Leyton Orient's squad (both
                                                    views: Physical and Performance)
    GET /api/physical/squad.xlsx?season=            our current squad as a workbook (owner R5)

`league` is a competition id. Metric, scatter axes and the squad sort are drawn in the browser
from the one answer (every value and order is in it), so they need no request.
"""
from __future__ import annotations

import logging
import threading
import time
import types

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, Response

from lofc.core import physical_page as core
from lofc.core import webcache
from lofc.web.security import WebUser, current_user

router = APIRouter()
log = logging.getLogger("lofc.web.warmup")
RANKABLE_MINUTES = 450


def _sources():
    """The frames (tests swap the whole namespace). The season frames are Compare's
    version-keyed copies of the same loaders, so the two pages share one copy in memory."""
    from lofc.core import detail_store, squad
    from lofc.core import players_pool as pp
    from lofc.dashboard import loaders as L
    from lofc.web.api import compare as cmp
    return types.SimpleNamespace(
        seasons=pp.season_options, default_season=pp.default_season,
        candidates=cmp._candidates, values=cmp._metric_values, pcts=cmp._sc_pcts,
        perf_pcts=cmp._sc_pcts,                 # the card's scorecard percentiles (all metrics)
        squad=squad.squad, rated_rows=squad.rated_rows,
        has_physical=detail_store.league_has_physical,
        league_names=L.competition_name_by_id,
        cards=lambda position, sid: _cards_for(position, sid),
        match_counts=_match_counts,
        l1_rank=lambda pid, comp, pos, sid: _l1_rank(pid, comp, pos, sid),
        availability=_availability)


def _l1_rank(pid: int, comp: int, position: str, season_id: int) -> tuple:
    """(rank, n) among rated players of his league and position: the card's `rank_in_pool`."""
    from lofc.model.scorecard import rank_in_pool
    return rank_in_pool(_cards_for(position, season_id), int(pid), int(comp), int(season_id),
                        position)


def _availability(pid: int, comp: int, season_id: int, minutes):
    from lofc.core import card
    from lofc.dashboard import loaders as L
    return card.availability_value(L.get_engine(), int(pid), int(comp), int(season_id), minutes)


@webcache.versioned(maxsize=4)
def _match_counts(season_id: int) -> dict:
    """(player_id, competition_id) -> matches SkillCorner tracked (skillcorner_match_counts)."""
    import pandas as pd
    from lofc.dashboard import loaders as L
    try:
        d = pd.read_sql("SELECT player_id, competition_id, matches FROM skillcorner_match_counts "
                        "WHERE season_id = %(s)s", L.get_engine(), params={"s": int(season_id)})
    except Exception:                                           # noqa: BLE001 (table not migrated)
        return {}
    return {(int(p), int(c)): int(m) for p, c, m in zip(d["player_id"], d["competition_id"], d["matches"])}


def _cards_for(position: str, season_id: int):
    """The position's scorecards for the season, "All Metrics" rows only (one per player)."""
    from lofc.core import card as card_core
    from lofc.model import club_framework as cf
    return card_core.ranking_for(position, cf.DEFAULT_ARCHETYPE, season_id)


# --- cached pieces ----------------------------------------------------------------------------
@webcache.versioned(maxsize=4)
def _counts(season_id: int):
    return core.pool_counts(_sources().pcts(season_id))


@webcache.versioned(maxsize=4)
def _leagues(season_id: int) -> list[int]:
    """Leagues with tracking data this season, in id order (the Players page's league order)."""
    src = _sources()
    cands = src.candidates(season_id)
    ids = sorted({int(c) for c in cands["competition_id"]}) if len(cands) else []
    return [c for c in ids if src.has_physical(c, season_id)]


@webcache.versioned(maxsize=4)
def _squad(season_id: int) -> dict:
    src = _sources()

    def rank_of(pid, comp, pos):
        return core.physical_ranks(src.cards(pos, season_id), comp, season_id, pos).get(
            int(pid), {}).get("text", core.DASH)
    rows = core.squad_rows(src.squad(), src.rated_rows(season_id), src.values(season_id),
                           src.pcts(season_id), _counts(season_id), src.league_names(),
                           _href, rank_of, src.match_counts(season_id))
    return {"title": "Leyton Orient squad", "columns": core.RATED, "rows": rows}


@webcache.versioned(maxsize=4)
def _perf(season_id: int) -> dict:
    """The squad card's Performance view (owner 2026-11-13)."""
    src = _sources()
    name = next((x["name"] for x in src.seasons() if int(x["id"]) == season_id), str(season_id))
    return core.performance_rows(src.squad(), src.rated_rows(season_id), src.perf_pcts(season_id),
                                 season_id, src.league_names(), _href, season_name=name)


@webcache.versioned(maxsize=128)
def _pool(season_id: int, league: int, position: str) -> dict:
    src = _sources()
    frame = core.pool_frame(src.candidates(season_id), src.values(season_id),
                            src.pcts(season_id), league, position)
    counts = _counts(season_id)
    per_metric = {k: core.count_for(counts, league, position, k) for k in core.KEYS}
    orient = {int(p) for p in src.squad()["player_id"]}
    ranks = core.physical_ranks(src.cards(position, season_id), league, season_id, position)
    leaders = {k: core.leaders(frame, k) for k in core.KEYS}
    leaders[core.RATING_KEY] = core.rating_leaders(frame, ranks)
    return {"players": core.pool_players(frame, per_metric, orient, _href, ranks,
                                         src.match_counts(season_id)),
            "leaders": leaders}


def _href(p: int, c: int, s: int) -> str:
    return f"/player/{int(p)}/{int(c)}/{int(s)}"


def clear() -> None:
    for fn in (_counts, _leagues, _squad, _perf, _pool):
        fn.clear()


# --- the answer -------------------------------------------------------------------------------
def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def page_json(season=None, league=None, position=None, x=None, y=None, age=None,
              min_minutes=None) -> dict:
    src = _sources()
    seasons = src.seasons()
    ids = [int(s["id"]) for s in seasons]
    sid = _int(season)
    if sid not in ids:
        sid = src.default_season(ids)
    name = next(s["name"] for s in seasons if int(s["id"]) == sid)
    names = src.league_names()
    leagues = _leagues(sid)
    out = {"filters": {"seasons": seasons, "season": sid,
                       "leagues": [{"id": c, "name": names.get(c, f"League {c}")} for c in leagues],
                       "league": None, "positions": core.positions(), "position": None},
           "metrics": core.metric_list(),
           "defaults": {"metric": core.DEFAULT_METRIC, "x": core.DEFAULT_X, "y": core.DEFAULT_Y},
           "leaders_shown": core.LEADERS_SHOWN, "empty": None, "pool": None, "squad": None,
           "rating": {"key": core.RATING_KEY, "label": "Physical rating",
                      "definition": "The club's Physical rating (1–5) against this league and position."},
           "age_bands": [{"key": k, "label": label} for k, label in core.AGE_BANDS],
           "scatter": None, "perf": None}
    mm = core.min_minutes(min_minutes)
    # owner 2026-11-13: "Min minutes" is a slider, 450 up to the plotted pool's most minutes
    out["min_range"] = {"min": core.MIN_MINUTES[0], "max": max(core.MIN_MINUTES[0], mm), "step": core.MINUTES_STEP}
    out["filters"]["min"] = mm
    bands = {k for k, _ in core.AGE_BANDS}
    out["filters"]["age"] = age if age in bands else ""
    if not leagues:
        out["empty"] = core.no_data_text(name)
        return out
    cid = _int(league)
    if cid not in leagues:
        sq = src.squad()
        cid = core.default_league([int(p) for p in sq["player_id"]], src.rated_rows(sid), leagues)
    pos = position if position in core.positions() else _default_position()
    out["filters"].update(league=cid, position=pos)
    pool = dict(_pool(sid, cid, pos))
    pool.update(title=f"{names.get(cid, f'League {cid}')} {pos}s",
                sub=f"{name} · {RANKABLE_MINUTES}+ minutes",
                none=None if pool["players"] else core.NO_PLAYERS)
    out["pool"] = pool
    xk = x if x in core.KEYS else core.DEFAULT_X
    yk = y if y in core.KEYS else core.DEFAULT_Y
    out["min_range"]["max"] = max(mm, core.minutes_max(pool["players"], xk, yk, out["filters"]["age"]))
    out["scatter"] = dict(core.scatter_summary(pool["players"], xk, yk, out["filters"]["age"], mm),
                          x=xk, y=yk, sub=f"{pool['title']} · {name} · {mm}+ minutes")
    out["squad"] = dict(_squad(sid), sub=f"{name} · percentile vs his league and position")
    out["perf"] = dict(_perf(sid), sub=f"{name} · rated players · percentile vs his league and position")
    return out


def _default_position() -> str:
    from lofc.core.players_pool import DEFAULT_POSITION
    return DEFAULT_POSITION


@router.get("/api/physical")
async def physical_json(request: Request, user: WebUser = Depends(current_user)):
    q = request.query_params
    data = await run_in_threadpool(page_json, q.get("season"), q.get("league"), q.get("position"),
                                   q.get("x"), q.get("y"), q.get("age"), q.get("min"))
    return JSONResponse(data)


def squad_workbook(season=None) -> tuple[bytes, str]:
    """The "Download squad (Excel)" workbook for the season (the page's default if none) and
    its file name. Ratings, rank and availability from the frames the page and the card read."""
    src = _sources()
    seasons = src.seasons()
    ids = [int(s["id"]) for s in seasons]
    sid = _int(season)
    if sid not in ids:
        sid = src.default_season(ids)
    name = next(s["name"] for s in seasons if int(s["id"]) == sid)
    rows = core.squad_export_rows(
        src.squad(), src.rated_rows(sid),
        lambda p, c, pos: src.l1_rank(p, c, pos, sid),
        lambda p, c, m: src.availability(p, c, sid, m))
    return core.squad_xlsx(rows), f"Leyton Orient squad {name.replace('/', '-')}.xlsx"


@router.get("/api/physical/squad.xlsx")
async def physical_squad_xlsx(request: Request, user: WebUser = Depends(current_user)):
    data, filename = await run_in_threadpool(squad_workbook, request.query_params.get("season"))
    return Response(data, media_type=XLSX,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# --- warm-up ----------------------------------------------------------------------------------
_AFTER = ("lofc-card-warmup", "lofc-compare-warmup", "lofc-report-warmup",
          "lofc-scout-reports-warmup", "lofc-watchlist-warmup", "lofc-squads-warmup")


def warm_physical() -> None:
    """Every league and position of every season with tracking data, and the squad: the first
    click after a restart is warm. Never raises."""
    t0 = time.perf_counter()
    try:
        src = _sources()
        for s in src.seasons():
            sid = int(s["id"])
            leagues = _leagues(sid)
            if not leagues:
                continue
            _squad(sid)
            _perf(sid)
            for c in leagues:
                for p in core.positions():
                    _pool(sid, c, p)
        page_json()
    except Exception:                                           # noqa: BLE001
        log.warning("physical warm-up failed", exc_info=True)
    log.warning("physical warm-up done in %.1f s", time.perf_counter() - t0)


def mount(app, render, shell) -> None:
    app.include_router(router)
    from lofc.core import webcache
    # re-run after any data change (webcache.rewarm_on_change), not only at start-up
    webcache.register_warmup("physical", lambda: warm_physical())

    def warm() -> None:
        def run() -> None:
            # After every other page's warm-up, never beside them (one heavy job at a time).
            from lofc.web.api import players as players_api
            players_api.PLAYERS_WARM.wait(timeout=900)
            for t in threading.enumerate():
                if t.name in _AFTER:
                    t.join(timeout=900)
            warm_physical()
        threading.Thread(target=run, name="lofc-physical-warmup", daemon=True).start()
    app.router.on_startup.append(warm)

    @app.get("/physical", response_class=HTMLResponse, name="page_physical")
    async def physical_page(request: Request, user: WebUser = Depends(current_user)):
        from lofc.web import pages
        return render(request, "physical.html", **shell(
            request, user, "physical", page=pages.PAGES["physical"]))
