"""The Watchlist page: page shell + JSON endpoints. Every value comes from
`lofc.core.watchlist_page` (what the Streamlit Watchlist page now calls), over the same
`store.watchlist` rows, read fresh on every request so an edit shows at once.

    GET  /watchlist?money=&open=      page shell
    GET  /api/watchlist?money=        tiles + rows
    GET  /api/watchlist/csv?money=    the table as CSV (lofc_watchlist.csv)
    POST /api/watchlist/{p}/{c}/{s}  {"note", "status"}   Save (session + X-LOFC-Request)

Remove is the card's `POST /api/card/{p}/{c}/{s}/watchlist {"action": "remove"}`. Like the
Streamlit page, any signed-in role may edit (no `auth.can` check there).

Web only (owner 2026-11-16): scout_assessments is not used, so the assessment status --
Streamlit's "Assessment status" filter, "Assessed" column and "Not yet assessed" tile -- is not
read or shown here; an old `?status=` link lists everyone. The Streamlit page keeps them.
"""
from __future__ import annotations

import types

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, Response

from lofc.core import webcache
from lofc.web.security import WebUser, current_user, write_user

router = APIRouter()
RATINGS = ["Composite", "Performance", "Physical"]
_RATING_SRC = {"Composite": "objective_composite", "Performance": "performance_band",
               "Physical": "physical_band"}
# Column hover tips (Streamlit's help texts, shortened; facts kept).
COLUMN_HELP = {
    "Composite": "The club's objective composite (1-5): Performance + Physical, as the Players ranking.",
    "Performance": "Performance dimension (1-5).",
    "Physical": "Physical dimension (1-5), where tracking data exists.",
    "Injury": "Most recent recorded spell (Transfermarkt). None on file is not a fitness guarantee.",
    "Market value": "Transfermarkt, latest known valuation.",
    "Months left": "Calendar months until the contract expires. Under 6: free to sign a pre-contract.",
    "Status": "Your own tracking status.",
}


@webcache.versioned(maxsize=8)
def _season_scorecards(season_id: int) -> pd.DataFrame:
    """`loaders.load_scorecards`, kept until the scorecards change."""
    from lofc.dashboard import loaders as L
    return L.load_scorecards(season_id)


@webcache.versioned(maxsize=8)
def _openable(season_id: int) -> frozenset:
    """(player, competition, season) the card can open: the season's `load_candidates`."""
    from lofc.dashboard import loaders as L
    cand = L.load_candidates(1.0, season_id)
    return frozenset(zip(cand["player_id"].astype(int), cand["competition_id"].astype(int),
                         cand["season_id"].astype(int)))


def _sources():
    """The store and loaders (tests swap the whole namespace)."""
    from lofc.config import settings
    from lofc.dashboard import loaders as L
    from lofc.dashboard.tabs.watchlist import load_valuations_for_players
    from lofc.store import watchlist

    class Openable:
        def __contains__(self, key):
            return key in _openable(int(key[2]))
    return types.SimpleNamespace(
        engine=L.get_engine(), store=watchlist,
        live_season_id=settings.live_season_id, current_form=L.load_current_form,
        injuries_for=L.load_injuries_for_players, scorecards_for=_season_scorecards,
        names=L._competition_name_by_id(), valuations=load_valuations_for_players,
        openable=Openable(), now=None)


def _money(request: Request) -> bool:
    return (request.query_params.get("money") or "").lower() in ("1", "true", "on")


# The retired assessment status (see the module note): `enrich` joins an empty frame, so
# nothing reads scout_assessments; its column and tile are dropped below.
_NO_ASSESSMENTS = pd.DataFrame(columns=["player_id", "competition_id", "season_id",
                                        "assessment_status"])
_RETIRED_COLUMNS = ["Assessed"]
_RETIRED_TILES = {"not_assessed"}


def build(money: bool):
    """(state, src, df, frame, header, alerts): state "empty" | "ok"."""
    from lofc.core import watchlist_page as wp
    src = _sources()
    df = src.store.load(src.engine)
    if df.empty:
        return "empty", src, None, None, None, None
    df, header = wp.enrich(df, assessment=_NO_ASSESSMENTS, live_season_id=src.live_season_id,
                           current_form=src.current_form, injuries_for=src.injuries_for,
                           scorecards_for=src.scorecards_for, now=src.now)
    # Honesty rule (D1): no rating from a pool below MIN_PEERS_FOR_RANKING.
    thin = wp.thin_sizes(df, src.scorecards_for)
    notes = wp.pool_notes(df, src.scorecards_for, src.names)
    df = wp.apply_pool_floor(df, thin)
    df["thin_n"] = thin
    frame = wp.display_frame(df, header, money, src.names, valuations=src.valuations)
    frame = frame.drop(columns=_RETIRED_COLUMNS)
    # after the display frame: the not-rated line and the midfield-pool tag are not columns
    df["not_rated_line"], df["pool_tag"] = notes["not_rated"], notes["pool_tag"]
    return "ok", src, df, frame, header, wp.alerts(df)


def page_json(money: bool) -> dict:
    from lofc.core import watchlist_page as wp
    state, src, df, frame, header, alerts = build(money)
    out = {"empty": state == "empty", "money": money,
           "manual_statuses": list(src.store.WATCHLIST_STATUSES)}
    if state == "empty":
        out["text"] = wp.EMPTY
        return out
    out.update(form_header=header, help=COLUMN_HELP)
    out["tiles"] = [{"label": label, "value": alerts[key], "help": tip}
                    for label, key, tip in wp.TILES if key not in _RETIRED_TILES]
    out["columns"] = list(frame.columns)
    rows = []
    for i in range(len(df)):
        r, shown = df.iloc[i], frame.iloc[i]
        p, c, s = int(r["player_id"]), int(r["competition_id"]), int(r["season_id"])
        cells = {}
        for col in frame.columns:
            if col in RATINGS:
                v = r[_RATING_SRC[col]]
                cells[col] = "—" if pd.isna(v) else f"{float(v):.2f}"
            elif col in ("Note", "Transfermarkt"):
                continue
            else:
                cells[col] = str(shown[col])
        note = r["note"] if isinstance(r["note"], str) else ""
        tm = shown["Transfermarkt"]
        rows.append({
            "key": f"{p}-{c}-{s}", "ids": {"player": p, "competition": c, "season": s},
            "cells": cells, "note": note, "status": str(r["status"]),
            "ratings": {k: (None if pd.isna(r[_RATING_SRC[k]]) else float(r[_RATING_SRC[k]]))
                        for k in RATINGS},
            "not_rated": r["not_rated_line"] if isinstance(r["not_rated_line"], str) else None,
            "pool_tag": r["pool_tag"] if isinstance(r["pool_tag"], str) else None,
            "href": f"/player/{p}/{c}/{s}" if (p, c, s) in src.openable else None,
            "tm": tm if isinstance(tm, str) and tm.startswith("https://") else None})
    out["rows"] = rows
    return out


@router.get("/api/watchlist")
async def watchlist_json(request: Request, user: WebUser = Depends(current_user)):
    data = await run_in_threadpool(page_json, _money(request))
    return JSONResponse(data)


@router.get("/api/watchlist/csv")
async def watchlist_csv(request: Request, user: WebUser = Depends(current_user)):
    def run():
        state, _src, _df, frame, *_ = build(_money(request))
        return frame.drop(columns=[c for c in ("thin_n",) if c in frame.columns]) \
            if state == "ok" else None
    frame = await run_in_threadpool(run)
    if frame is None:
        raise HTTPException(status_code=404, detail="nothing_to_download")
    from lofc.core.card import csv_disposition
    return Response(frame.to_csv(index=False).encode("utf-8"), media_type="text/csv",
                    headers={"Content-Disposition": csv_disposition("lofc_watchlist.csv")})


@router.post("/api/watchlist/{player_id}/{competition_id}/{season_id}")
async def watchlist_save(player_id: int, competition_id: int, season_id: int, request: Request,
                         user: WebUser = Depends(write_user)):
    """Save: the note (blank = none) and the status, with the same `store.watchlist` calls as
    the Streamlit dialog's Save button."""
    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="bad_request")
    note, status = body.get("note"), body.get("status")

    def run():
        src = _sources()
        if not isinstance(note, str) or status not in src.store.WATCHLIST_STATUSES:
            return 400
        if not src.store.is_watched(src.engine, player_id, competition_id, season_id):
            return 404
        src.store.set_note(src.engine, player_id, competition_id, season_id, note.strip() or None)
        src.store.set_status(src.engine, player_id, competition_id, season_id, status)
        return 200
    code = await run_in_threadpool(run)
    from lofc.web.api.card import forget_prefetched
    forget_prefetched()
    if code == 400:
        raise HTTPException(status_code=400, detail="note must be text and status one of the list")
    if code == 404:
        raise HTTPException(status_code=404, detail="not_on_the_watchlist")
    return {"ok": True}


def warm_watchlist() -> None:
    """The season frames the list reads (scorecards, candidates, current form, valuations):
    ~5 s cold. Never raises."""
    import logging
    import time
    log = logging.getLogger("lofc.web.warmup")
    t0 = time.perf_counter()
    try:
        page_json(True)
    except Exception:                                           # noqa: BLE001
        log.warning("watchlist warm-up failed", exc_info=True)
    log.warning("watchlist warm-up done in %.1f s", time.perf_counter() - t0)


def mount(app, render, shell) -> None:
    app.include_router(router)
    from lofc.core import webcache
    # re-run after any data change (webcache.rewarm_on_change), not only at start-up
    webcache.register_warmup("watchlist", lambda: warm_watchlist())

    def warm() -> None:
        import threading

        def run() -> None:
            # after the scout reports warm-up (itself after the others): one at a time
            from lofc.web.api import players as players_api
            players_api.PLAYERS_WARM.wait(timeout=900)
            for t in threading.enumerate():
                if t.name in ("lofc-card-warmup", "lofc-report-warmup",
                              "lofc-scout-reports-warmup"):
                    t.join(timeout=900)
            warm_watchlist()
        threading.Thread(target=run, name="lofc-watchlist-warmup", daemon=True).start()
    app.router.on_startup.append(warm)

    @app.get("/watchlist", response_class=HTMLResponse, name="page_watchlist")
    async def watchlist_page(request: Request, user: WebUser = Depends(current_user)):
        from lofc.web import pages
        return render(request, "watchlist.html", **shell(
            request, user, "watchlist", page=pages.PAGES["watchlist"]))
