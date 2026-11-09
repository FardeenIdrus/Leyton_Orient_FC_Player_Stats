"""The player card: page shell + JSON endpoints. All numbers come from `lofc.core.card` and
`lofc.core.squad` (the same functions the Streamlit card is built on); this module only turns
the URL into a request and the result into JSON.

    GET  /player/{player_id}/{competition_id}/{season_id}?back=&rank_as=&money=   page shell
    GET  /api/card/{p}/{c}/{s}?rank_as=&money=            every section (blanks are null)
    GET  /api/card/{p}/{c}/{s}/squad?season=&rank_as=     "Against our <position>s" (season switch)
    GET  /api/card/{p}/{c}/{s}/csv?kind=scorecard|metrics&rank_as=   the two CSV downloads
    POST /api/card/{p}/{c}/{s}/watchlist   {"action": "add" | "remove"}   (session + header)

The Players page links to the page shell with `?back=<url-encoded players URL>`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, Response

from lofc.web.security import WebUser, current_user, write_user

router = APIRouter()

_TRUE = {"1", "true", "on", "yes"}


def _flag(v: str | None) -> bool:
    return (v or "").strip().lower() in _TRUE


# Indirection so tests can swap the data layer without a database.
def get_engine():
    from lofc.dashboard import loaders as L
    return L.get_engine()


def _core():
    from lofc.core import card
    return card


def _squad():
    from lofc.core import squad
    return squad


def _watchlist():
    from lofc.store import watchlist
    return watchlist


# Card answers built ahead of a click (TASKS 2.36 S-C): see lofc.web.prefetch.
from lofc.web.prefetch import Handoff  # noqa: E402

HANDOFF = Handoff(ttl=30.0, maxsize=16)
PREFETCH_HEADER = "X-LOFC-Prefetch"


def forget_prefetched() -> None:
    """A watchlist write changes what a card shows: drop every card built ahead."""
    HANDOFF.clear()


def _handed(request: Request, key, build):
    """A prefetch builds and keeps the answer; a normal request takes a kept one, else builds."""
    if request.headers.get(PREFETCH_HEADER) == "1":
        return HANDOFF.produce(key, build)
    got = HANDOFF.consume(key)
    return got if got is not None else build()


def _version():
    try:
        from lofc.dashboard import loaders as L
        return L.web_data_version()
    except Exception:                                           # noqa: BLE001
        return None


@router.get("/api/card/{player_id}/{competition_id}/{season_id}")
async def card_json(player_id: int, competition_id: int, season_id: int, request: Request,
                    user: WebUser = Depends(current_user)):
    q = request.query_params
    rank_as, money = (q.get("rank_as") or None), _flag(q.get("money"))

    def build():
        data = _core().build_card(get_engine(), player_id, competition_id, season_id,
                                  rank_as=rank_as, show_money=money)
        return None if data is None else JSONResponse(data).body

    key = ("card", player_id, competition_id, season_id, rank_as, money, _version())
    body = await run_in_threadpool(_handed, request, key, build)
    if body is None:
        raise HTTPException(status_code=404, detail="no_such_player_season")
    return Response(body, media_type="application/json")


@router.get("/api/card/{player_id}/{competition_id}/{season_id}/squad")
async def squad_json(player_id: int, competition_id: int, season_id: int, request: Request,
                     user: WebUser = Depends(current_user)):
    q = request.query_params

    def build():
        core = _core()
        row, lens, _ = core.card_row(player_id, competition_id, season_id, q.get("rank_as"))
        if row is None:
            return None
        try:
            season = int(q.get("season"))
        except (TypeError, ValueError):
            season = int(row["season_id"])
        return JSONResponse(core.clean(_squad().section(
            int(row["player_id"]), str(row["player_name"]), str(row["position_group"]), season,
            lens, birth=row.get("birth_date"), contract=row.get("contract_until")))).body
    key = ("squad", player_id, competition_id, season_id, q.get("season") or None,
           q.get("rank_as") or None, _version())
    body = await run_in_threadpool(_handed, request, key, build)
    if body is None:
        raise HTTPException(status_code=404, detail="no_such_player_season")
    return Response(body, media_type="application/json")


@router.get("/api/card/{player_id}/{competition_id}/{season_id}/csv")
async def card_csv(player_id: int, competition_id: int, season_id: int, request: Request,
                   user: WebUser = Depends(current_user)):
    q = request.query_params
    kind = "metrics" if q.get("kind") == "metrics" else "scorecard"
    got = await run_in_threadpool(lambda: _core().scorecard_csv(
        get_engine(), player_id, competition_id, season_id, kind, q.get("rank_as")))
    if got is None:
        raise HTTPException(status_code=404, detail="nothing_to_download")
    name, text = got
    from lofc.core.card import csv_disposition
    return Response(text.encode("utf-8"), media_type="text/csv",
                    headers={"Content-Disposition": csv_disposition(name)})


@router.post("/api/card/{player_id}/{competition_id}/{season_id}/watchlist")
async def watchlist_toggle(player_id: int, competition_id: int, season_id: int, request: Request,
                           user: WebUser = Depends(write_user)):
    """Add / remove the player-season: the same `store.watchlist` functions the Streamlit
    button calls (which has no role check -- any signed-in user may watch)."""
    try:
        action = (await request.json()).get("action")
    except Exception:
        action = None
    if action not in ("add", "remove"):
        raise HTTPException(status_code=400, detail="action must be add or remove")

    def run():
        # Add: only a player-season the card can open (no rows for ids that do not exist).
        # Remove: also any row already on the list (the Watchlist page's Remove: a watched
        # player-season may have no card, e.g. under 450 minutes).
        row, _lens, _reason = _core().card_row(player_id, competition_id, season_id)
        wl, engine = _watchlist(), get_engine()
        if row is None and not (action == "remove"
                                and wl.is_watched(engine, player_id, competition_id, season_id)):
            return None
        if action == "add":
            wl.add(engine, player_id, competition_id, season_id)
        else:
            wl.remove(engine, player_id, competition_id, season_id)
        return bool(wl.is_watched(engine, player_id, competition_id, season_id))
    watched = await run_in_threadpool(run)
    forget_prefetched()
    if watched is None:
        raise HTTPException(status_code=404, detail="no_such_player_season")
    return {"ok": True, "watched": watched}


def warm_card_caches() -> None:
    """Fill everything a card reads that is not per player, so no first card -- and no Rank as
    or squad-season click -- pays a cold read: the scorecard rankings for every season x
    position x lens, the squad section's rows for every lens, the detail pools of every
    league-season (`core.detail_store`), and the card's own loaders. Measured 2026-11-09 on an
    idle server: first cards took 3-10 s, from the 60-600 s Streamlit loaders having lapsed.
    Never raises; logs how long it took."""
    import logging
    import time
    log = logging.getLogger("lofc.web.warmup")
    t0 = time.perf_counter()
    try:
        from lofc.core import card as card_core
        from lofc.core import detail_store, squad, webcache
        from lofc.dashboard import loaders as L
        from lofc.model import club_framework as cf
        from lofc.core.players_pool import POSITION_ORDER
        steps = [L.load_trajectory, L.load_current_form, L.load_loan_status,
                 L.load_current_clubs, card_core.stored_scorecards, squad.squad,
                 webcache.scout_consensus]
        seasons = sorted(L.available_seasons(), reverse=True)
        for sid in seasons:
            steps.append(lambda sid=sid: card_core.stored_scorecards(sid))
            steps.append(lambda sid=sid: webcache.assessment_status(sid))
            for position in POSITION_ORDER:
                for lens in cf.archetypes_for(position):
                    steps.append(lambda p=position, a=lens, sid=sid: card_core.ranking_for(p, a, sid))
        for sid in squad.season_options():
            steps += [lambda sid=sid: squad.rated_rows(sid), lambda sid=sid: squad.style_map(sid)]
            for position in POSITION_ORDER:
                for lens in cf.archetypes_for(position):
                    steps.append(lambda p=position, a=lens, sid=sid: squad.rated_rows(sid, p, a))
        for fn in steps:
            try:
                fn()
            except Exception:                                   # noqa: BLE001
                log.warning("card warm-up step failed", exc_info=True)
        detail_store.warm()
        # one whole card per season: the first card also pays one-off imports (~1.5 s)
        for sid in seasons:
            cand = L.load_candidates(1.0, sid)
            if len(cand):
                r = cand.iloc[0]
                card_core.build_card(L.get_engine(), int(r["player_id"]), int(r["competition_id"]), sid)
    except Exception:                                           # noqa: BLE001
        log.warning("card cache warm-up failed", exc_info=True)
    # Everything warmed so far lives as long as the data version: move it out of the garbage
    # collector's view, so a full collection no longer walks it (0.3-0.7 s pauses on random
    # requests before, measured 2026-11-09).
    # (unfreeze first: a re-warm after a data change lets the old version's objects go)
    import gc
    gc.unfreeze()
    gc.collect()
    gc.freeze()
    log.warning("card warm-up done in %.0f s", time.perf_counter() - t0)


def mount(app, render, shell) -> None:
    """Register the API and the page shell. Called before the generic page loop."""
    app.include_router(router)
    from lofc.core import webcache
    # re-run after any data change (webcache.rewarm_on_change), not only at start-up
    webcache.register_warmup("card", lambda: warm_card_caches())

    def warm() -> None:
        # After the Players warm-up (which waits for the loaders'), never beside it: one heavy
        # job at a time, so the first users are not slowed by three warm-ups fighting for CPU.
        import threading
        from lofc.web.api import players as players_api

        def run() -> None:
            players_api.PLAYERS_WARM.wait(timeout=900)
            warm_card_caches()
        threading.Thread(target=run, name="lofc-card-warmup", daemon=True).start()
    app.router.on_startup.append(warm)

    @app.get("/player/{player_id}/{competition_id}/{season_id}", response_class=HTMLResponse,
             name="page_card")
    async def card_page(player_id: int, competition_id: int, season_id: int, request: Request,
                        user: WebUser = Depends(current_user)):
        from lofc.web import pages
        # Highlighted under Players: the card is where a Players row leads.
        return render(request, "card.html", **shell(
            request, user, "players", page=pages.PAGES["players"],
            ids=dict(player=player_id, competition=competition_id, season=season_id)))
