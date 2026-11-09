"""The Scout reports page: page shell + JSON endpoints. Every value comes from
`lofc.core.scout_reports_page` over the same query, comparison, filters and display table the
Streamlit page uses (`dashboard/tabs/scout_reports.py`); this module turns the URL into a request
and the result into JSON.

    GET  /scout-reports?tab=&q=&league=&max_age=&foot=&scout=&verdict=&grade=&position=&club=
                        &seen=&data=&dvs=&open=                         page shell
    GET  /api/scout-reports?<same>        sync line, tabs, filter options, caption, the tab's rows
    GET  /api/scout-reports/report/{id}   one report in full + the card it opens
    POST /api/scout-reports/sync          "Refresh": reads the scouting sheet (session + header)

Refresh is open to every signed-in role, as the Streamlit button (no `auth.can` check there).
Scout text is sent raw; the page escapes it (textContent / esc()).
"""
from __future__ import annotations

import logging
import threading
import time

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse

from lofc.core import webcache
from lofc.web.security import WebUser, current_user, write_user

router = APIRouter()
log = logging.getLogger("lofc.web.warmup")

EMPTY_TEXT = "No scout reports have been synced yet."
# The Streamlit captions in one line each (text rule): same facts.
NOT_LINKED = "Not in our data: no rating or peer comparison exists for him."
NO_RATED_SEASON = "In our data, but no rated season yet: no card to open."
COLUMNS = ["Watched", "Player", "Fixture", "Club", "Position", "Scout", "Seen", "Grade",
           "Verdict", "Rating", "This season", "Data vs scout"]


# ---- indirection: tests swap these (no database, never the club's sheet) -----------------
def get_engine():
    from lofc.dashboard import loaders as L
    return L.get_engine()


def _sheet_sync():
    from lofc.store.scout_reports import sync
    return sync


def _synced_at():
    from lofc.dashboard.tabs.scout_reports import last_sync_row
    row = last_sync_row()
    return None if row is None else row["synced_at"]


def _after_sync() -> None:
    """What the Streamlit button clears after a sync: the reports and the Players page's
    scout consensus (the web copies)."""
    _cached_bundle.clear()
    webcache.scout_consensus.clear()


def _seasons() -> tuple[int, int | None]:
    from lofc.config import settings
    from lofc.core import scout_reports_page as sp
    from lofc.dashboard import loaders as L
    prev, _cur = sp.rating_seasons(L.available_seasons())
    return prev, settings.live_season_id


def _bundle():
    return _cached_bundle(*_seasons())


# ---- data ---------------------------------------------------------------------------------
def build_bundle(raw: pd.DataFrame, prev: int, live_id, names: dict,
                 scorecards: pd.DataFrame, rated_rows: pd.DataFrame) -> dict | None:
    """Everything the page reads that does not depend on the filters, or None when no report
    has been synced. `scorecards` = the rating season's (pool sizes); `rated_rows` = every
    linked player's rated rows (the card each name opens)."""
    from lofc.core import scout_reports_page as sp
    from lofc.dashboard.seasons import season_name_for
    if raw.empty:
        return None
    rating = season_name_for(prev)
    live = sp.live_label(prev, rating, live_id)
    frame = sp.prepare(raw, rating, live, names, thin=sp.thin_sizes(raw, scorecards, prev))
    c = sp.counts(frame)
    return {"frame": frame, "names": names, "counts": c, "tabs": sp.tab_labels(c),
            "options": sp.filter_options(frame), "rating_label": rating, "live_label": live,
            "show_live": live != rating, "help": sp.column_help(rating, live),
            "targets": sp.best_targets(rated_rows)}


@webcache.versioned(maxsize=4)
def _cached_bundle(prev: int, live_id):
    from lofc.core import scout_reports_page as sp
    from lofc.dashboard import loaders as L
    from lofc.dashboard.tabs.scout_reports import reports_query
    raw = reports_query(prev, live_id or prev)
    linked = raw["player_id"].dropna().astype(int).unique().tolist() if len(raw) else []
    return build_bundle(raw, prev, live_id, L.competition_name_by_id(), L.load_scorecards(prev),
                        sp.rated_rows_for(get_engine(), linked))


def _href(targets: dict, pid) -> str | None:
    if pid is None or pd.isna(pid) or int(pid) not in targets:
        return None
    c, s = targets[int(pid)]
    return f"/player/{int(pid)}/{c}/{s}"


def _sync_block(done: dict | None = None) -> dict:
    from lofc.core import scout_reports_page as sp
    line, warn = sp.sync_line(_synced_at(), done)
    return {"line": line, "warn": bool(warn)}


def _rows(b: dict, view: pd.DataFrame) -> list[dict]:
    from lofc.core import scout_reports_page as sp
    from lofc.dashboard.tabs.scout_reports import verdict_tone
    table = sp.display_table(view, b["names"])
    out = []
    for (_, src), (_, shown) in zip(view.iterrows(), table.iterrows()):
        out.append({"id": str(src["submission_id"]),
                    "cells": {c: (str(shown[c]).strip() or "—") for c in COLUMNS if c in table.columns},
                    "tone": verdict_tone(src.get("verdict")),
                    "href": _href(b["targets"], src.get("player_id"))})
    return out


def page_json(query: dict) -> dict:
    from lofc.core import scout_reports_page as sp
    from lofc.dashboard.tabs.scout_reports import scout_activity
    b = _bundle()
    if b is None:
        return {"empty": True, "text": EMPTY_TEXT, "sync": _sync_block()}
    tab = query.get("tab") if query.get("tab") in sp.TABS else "all"
    frame, c = b["frame"], b["counts"]
    cols = [{"key": k, "label": (f"Rating ({b['rating_label']})" if k == "Rating" else
                                 f"Rating ({b['live_label']})" if k == "This season" else k),
             "help": b["help"].get(k)} for k in COLUMNS if k != "This season" or b["show_live"]]
    out = {"empty": False, "sync": _sync_block(), "tab": tab,
           "tabs": [{"key": k, "label": lab} for k, lab in zip(sp.TABS, b["tabs"])],
           "options": b["options"], "columns": cols, "rows": [], "caption": None}
    if tab == "activity":
        act = scout_activity(frame)
        out["activity"] = {"columns": list(act.columns),
                           "rows": [[v.item() if hasattr(v, "item") else v for v in r]
                                    for r in act.itertuples(index=False)]}
        return out
    if tab == "disagree":
        view = sp.disagree_view(frame)
        out["caption"] = sp.disagree_caption(len(view))
    else:
        view = sp.apply_filters(frame, query)
        out["caption"] = sp.browse_caption(len(view), c)
    out["rows"] = _rows(b, view)
    if not b["show_live"]:
        for r in out["rows"]:
            r["cells"].pop("This season", None)
    return out


def detail_json(submission_id: str) -> dict | None:
    from lofc.core import scout_reports_page as sp
    b = _bundle()
    if b is None:
        return None
    frame = b["frame"]
    hit = frame[frame["submission_id"].astype(str) == str(submission_id)]
    if hit.empty:
        return None
    row = hit.iloc[0]
    card = sp.report_card(row)
    card = {k: card[k] for k in ("tone", "accent", "player", "club", "meta", "verdict",
                                 "facts", "body")}
    card = {k: ("" if v is None or (isinstance(v, float) and pd.isna(v)) else v)
            for k, v in card.items()}
    card["facts"] = [[str(k), str(v)] for k, v in card["facts"]]
    out = {"id": str(submission_id), "card": card, "open": None, "caption": None}
    if pd.isna(row.get("player_id")):
        out["caption"] = NOT_LINKED
    else:
        href = _href(b["targets"], row.get("player_id"))
        if href is None:
            out["caption"] = NO_RATED_SEASON
        else:
            out["open"] = {"href": href, "label": "Open card"}
    return out


# ---- routes -------------------------------------------------------------------------------
@router.get("/api/scout-reports")
async def scout_reports_json(request: Request, user: WebUser = Depends(current_user)):
    q = dict(request.query_params)
    return JSONResponse(await run_in_threadpool(page_json, q))


@router.get("/api/scout-reports/report/{submission_id}")
async def scout_report_json(submission_id: str, user: WebUser = Depends(current_user)):
    data = await run_in_threadpool(detail_json, submission_id)
    if data is None:
        raise HTTPException(status_code=404, detail="no_such_report")
    return JSONResponse(data)


@router.post("/api/scout-reports/sync")
async def scout_reports_sync(user: WebUser = Depends(write_user)):
    """Reads the scouting sheet (`store.scout_reports.sync`, force=False), exactly as the
    Streamlit "Refresh" button. A failure is shown on the page, as Streamlit's st.error."""
    def run():
        result = _sheet_sync()(get_engine(), force=False)
        _after_sync()
        return result
    try:
        result = await run_in_threadpool(run)
    except Exception as exc:                                    # noqa: BLE001 - shown to the user
        return JSONResponse({"ok": False, "error": f"Could not read the scouting sheet: {exc}"})
    return JSONResponse({"ok": True, "sync": await run_in_threadpool(_sync_block, result)})


def warm_scout_reports() -> None:
    t0 = time.perf_counter()
    try:
        _bundle()
    except Exception:                                           # noqa: BLE001
        log.warning("scout reports warm-up failed", exc_info=True)
    log.warning("scout reports warm-up done in %.1f s", time.perf_counter() - t0)


def mount(app, render, shell) -> None:
    app.include_router(router)
    from lofc.core import webcache
    # re-run after any data change (webcache.rewarm_on_change), not only at start-up
    webcache.register_warmup("scout-reports", lambda: warm_scout_reports())

    def warm() -> None:
        # After the other warm-ups, one heavy job at a time.
        def run() -> None:
            from lofc.web.api import players as players_api
            players_api.PLAYERS_WARM.wait(timeout=900)
            for t in threading.enumerate():
                if t.name in ("lofc-card-warmup", "lofc-report-warmup"):
                    t.join(timeout=900)
            warm_scout_reports()
        threading.Thread(target=run, name="lofc-scout-reports-warmup", daemon=True).start()
    app.router.on_startup.append(warm)

    @app.get("/scout-reports", response_class=HTMLResponse, name="page_scout_reports")
    async def scout_reports_page(request: Request, user: WebUser = Depends(current_user)):
        from lofc.web import pages
        return render(request, "scout_reports.html", **shell(
            request, user, "scout-reports", page=pages.PAGES["scout-reports"]))
