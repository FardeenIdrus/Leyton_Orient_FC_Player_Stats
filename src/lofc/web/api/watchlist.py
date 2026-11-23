"""The Watchlist page (owner 2026-11-23 redesign): one shared department list, one entry per
player, grouped by position with our best (League One) for reference only; stages, owner (a
platform user), next step, due date, shared notes; "Suggested from scout reports"; "What changed
since added". Every value comes from `lofc.core.watchlist_page` over `store.watchlist`, read
fresh on every request so an edit shows at once.

    GET  /watchlist                                   page shell
    GET  /api/watchlist?sugg=all                      the page (suggestions: last 30 days or all)
    GET  /api/watchlist/csv                           the list as CSV (lofc_watchlist.csv)
    POST /api/watchlist/{player}                      {stage, owner, next_step, due, note, drop_reason}
    POST /api/watchlist/suggestions/{report}          {"action": "add" | "dismiss"}

Writes need a session + X-LOFC-Request (write_user). Remove is the card's
`POST /api/card/{p}/{c}/{s}/watchlist {"action": "remove"}`.
"""
from __future__ import annotations

import datetime
import types

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, Response

from lofc.core import webcache
from lofc.web.security import WebUser, current_user, write_user

router = APIRouter()
DASH = "—"


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


def _our_best() -> dict:
    """position group -> our best player there rated in League One this season (the Club vs
    League One page's level) -- shown for reference only, never compared."""
    try:
        from lofc.web.api import club_vs_league as cvapi
        return {g["group"]: g["level"] for g in cvapi._base()["gaps"] if g.get("level")}
    except Exception:                                           # noqa: BLE001 -- reference only
        return {}


def _sources():
    """The store and loaders (tests swap the whole namespace)."""
    from lofc.config import settings
    from lofc.core import squad
    from lofc.dashboard import loaders as L
    from lofc.store import users, watchlist

    class Openable:
        def __contains__(self, key):
            return key in _openable(int(key[2]))

    def reports():
        return pd.read_sql("SELECT id, player_id, verdict, scout, fixture_date, submitted_at, missing_since, "
                           "player_name, club_name FROM scout_reports", L.get_engine())

    def people():
        return [{"id": u.id, "name": u.full_name} for u in users.list_users(L.get_engine(), datetime.datetime.now())
                if u.is_active]
    return types.SimpleNamespace(
        engine=L.get_engine(), store=watchlist,
        live_season_id=settings.live_season_id, current_form=L.load_current_form,
        injuries_for=L.load_injuries_for_players, scorecards_for=_season_scorecards,
        names=L._competition_name_by_id(), openable=Openable(), now=None,
        live_rows=lambda: squad.rated_rows(settings.live_season_id),
        current_clubs=L.load_current_clubs, reports=reports, users=people, our_best=_our_best)


def _num(v):
    return None if v is None or (isinstance(v, float) and v != v) or pd.isna(v) else float(v)


def _txt(v):
    return v if isinstance(v, str) and v.strip() else None


def _abbr(league):
    from lofc.dashboard import compare_tables as ct
    return (ct._abbr(league) or None) if league else None


def build(sugg_all: bool = False) -> dict:
    """The whole page as plain data."""
    from lofc.core import watchlist_page as wp
    src = _sources()
    now = pd.Timestamp.now().normalize() if src.now is None else pd.Timestamp(src.now)
    users = src.users()
    names_by_id = {u["id"]: u["name"] for u in users}
    reports = src.reports()
    latest = wp.latest_reports(reports)
    dismissed = src.store.dismissed_report_ids(src.engine)
    df = src.store.load(src.engine)
    watched = {int(p) for p in df["player_id"]} if len(df) else set()
    live = src.live_rows()
    cur_club = dict(zip(src.current_clubs()["player_id"].astype(int), src.current_clubs()["current_club"]))

    # suggestions (both windows counted; the chosen one listed)
    s_all = wp.suggestions(latest, watched, dismissed, now, days=None)
    s_30 = [x for x in s_all if pd.notna(x["date"]) and x["date"] >= now - pd.Timedelta(days=wp.SUGGEST_DAYS)]
    shown = s_all if sugg_all else s_30
    sugg_rows = []
    for x in shown:
        pid = x["player_id"]
        lr = live.loc[pid] if pid in live.index else None
        league = src.names.get(int(lr["competition_id"])) if lr is not None else None
        sugg_rows.append({"report_id": x["report_id"], "player_id": pid, "name": x["name"],
                          "club": (lr["team_name"] if lr is not None else None) or x["club"],
                          "league_abbr": _abbr(league), "league": league,
                          "position": lr["position_group"] if lr is not None else None,
                          "overall": _num(lr["objective_composite"]) if lr is not None else None,
                          "verdict": x["verdict"], "report": x["report"],
                          "href": (f"/player/{pid}/{int(lr['competition_id'])}/{src.live_season_id}"
                                   if lr is not None and (pid, int(lr["competition_id"]), int(src.live_season_id))
                                   in src.openable else None)})
    out = {"empty": df.empty, "stages": list(src.store.STAGES), "active_stages": list(src.store.ACTIVE_STAGES),
           "users": users, "suggestions": {"rows": sugg_rows, "window": "all" if sugg_all else "30",
                                           "count_30": len(s_30), "count_all": len(s_all)}}
    if df.empty:
        out.update(text=wp.EMPTY_REDESIGN, tiles=wp.tiles([]), groups=[], closed=[], changes=[])
        return out

    _NO = pd.DataFrame(columns=["player_id", "competition_id", "season_id", "assessment_status"])
    df, _header = wp.enrich(df, assessment=_NO, live_season_id=src.live_season_id,
                            current_form=src.current_form, injuries_for=src.injuries_for,
                            scorecards_for=src.scorecards_for, now=src.now)
    df = wp.apply_pool_floor(df, wp.thin_sizes(df, src.scorecards_for))
    rows, now_rows = [], {}
    for r in df.to_dict("records"):
        pid = int(r["player_id"])
        lr = live.loc[pid] if pid in live.index else None
        if lr is not None:                      # his row this season: rating in his own league
            comp, season, pos = int(lr["competition_id"]), int(src.live_season_id), lr["position_group"]
            club, overall = lr["team_name"], _num(lr["objective_composite"])
        else:                                   # no minutes this season: the row he was added from
            comp, season, pos = int(r["competition_id"]), int(r["season_id"]), r["position_group"]
            club, overall = r["team_name"], _num(r["objective_composite"])
        league = src.names.get(comp)
        now_rows[pid] = {"rating": overall, "club": cur_club.get(pid) or club}
        rep = latest.loc[pid] if pid in latest.index else None
        due = pd.to_datetime(r.get("due_date"), errors="coerce")
        note_by = r.get("note_updated_by")
        note_at = pd.to_datetime(r.get("note_updated_at"), errors="coerce")
        owner = None if pd.isna(r.get("owner_user_id")) else int(r["owner_user_id"])
        rows.append({
            "player_id": pid, "name": r["player_name"], "club": cur_club.get(pid) or club,
            "league": league, "league_abbr": _abbr(league), "position": pos,
            "age": None if pd.isna(r.get("age")) else int(r["age"]), "overall": overall,
            "stage": r["status"] if r["status"] in src.store.STAGES else src.store.OLD_TO_NEW.get(r["status"], "Watching"),
            "verdict": None if rep is None else rep["verdict"],
            "next_step": _txt(r.get("next_step")), "owner_id": owner, "owner": names_by_id.get(owner),
            "due": None if pd.isna(due) else due.date().isoformat(),
            "due_text": None if pd.isna(due) else due.strftime("%-d %b"),
            "overdue": bool(pd.notna(due) and due.normalize() < now),
            "contract": None if pd.isna(r.get("contract_until_dt")) else pd.Timestamp(r["contract_until_dt"]).strftime("%b %Y"),
            "months_left": None if pd.isna(r.get("months_left")) else int(r["months_left"]),
            "note": _txt(r.get("note")) or "", "drop_reason": _txt(r.get("drop_reason")) or "",
            "note_meta": (f"{names_by_id.get(int(note_by), 'Someone')} · {note_at.strftime('%-d %b')}"
                          if pd.notna(note_at) and note_by is not None and not pd.isna(note_by) else None),
            "added": pd.to_datetime(r["created_at"]).strftime("%-d %b %Y"),
            "new_report": bool(rep is not None and pd.notna(rep["date"])
                               and rep["date"] >= now - pd.Timedelta(days=wp.NEW_REPORT_DAYS)),
            "href": f"/player/{pid}/{comp}/{season}" if (pid, comp, season) in src.openable else None,
        })
    groups, closed = wp.group_rows(rows, src.our_best())
    ch = wp.changes(df, now_rows, latest, reports, now)
    # dated items (scout reports) newest first, then the rest in list order
    ch.sort(key=lambda c: (0, -pd.Timestamp(c["date"]).value) if pd.notna(c.get("date")) else (1, 0))
    out.update(tiles=wp.tiles(rows), groups=groups, closed=closed, changes=ch[:wp.CHANGES_MAX])
    for c in out["changes"]:
        c.pop("date", None)
    return out


def page_json(sugg_all: bool = False) -> dict:
    return build(sugg_all)


@router.get("/api/watchlist")
async def watchlist_json(request: Request, user: WebUser = Depends(current_user)):
    data = await run_in_threadpool(page_json, request.query_params.get("sugg") == "all")
    return JSONResponse(data)


CSV_COLUMNS = ["Player", "Club", "League", "Position", "Age", "Overall", "Stage", "Scout verdict",
               "Next step", "Owner", "Due", "Contract", "Drop reason", "Note", "Added"]


@router.get("/api/watchlist/csv")
async def watchlist_csv(request: Request, user: WebUser = Depends(current_user)):
    def run():
        d = build()
        rows = [r for g in d.get("groups", []) for r in g["rows"]] + d.get("closed", [])
        if not rows:
            return None
        f = pd.DataFrame([[r["name"], r["club"], r["league"], r["position"], r["age"],
                           None if r["overall"] is None else f"{r['overall']:.2f}", r["stage"], r["verdict"],
                           r["next_step"], r["owner"], r["due"], r["contract"], r["drop_reason"] or None,
                           r["note"] or None, r["added"]] for r in rows], columns=CSV_COLUMNS)
        return f.fillna(DASH)
    frame = await run_in_threadpool(run)
    if frame is None:
        raise HTTPException(status_code=404, detail="nothing_to_download")
    from lofc.core.card import csv_disposition
    return Response(frame.to_csv(index=False).encode("utf-8"), media_type="text/csv",
                    headers={"Content-Disposition": csv_disposition("lofc_watchlist.csv")})


async def _body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="bad_request")
    return body


_FIELD = {"stage": "status", "owner": "owner_user_id", "next_step": "next_step", "due": "due_date",
          "note": "note", "drop_reason": "drop_reason"}


@router.post("/api/watchlist/{player_id}")
async def watchlist_save(player_id: int, request: Request, user: WebUser = Depends(write_user)):
    """Save any of: stage, owner (a user id or null), next_step, due ("YYYY-MM-DD" or ""), note,
    drop_reason (optional, owner 2026-11-23). Applies to the player's latest row."""
    body = await _body(request)
    fields = {}
    for k, v in body.items():
        if k not in _FIELD:
            raise HTTPException(status_code=400, detail=f"unknown field {k}")
        if k == "due":
            if v in (None, ""):
                v = None
            else:
                try:
                    v = datetime.date.fromisoformat(str(v))
                except ValueError:
                    raise HTTPException(status_code=400, detail="due must be YYYY-MM-DD")
        elif k == "owner":
            if v in (None, ""):
                v = None
            elif not isinstance(v, int) or isinstance(v, bool):
                raise HTTPException(status_code=400, detail="owner must be a user id")
        elif v is not None and not isinstance(v, str):
            raise HTTPException(status_code=400, detail=f"{k} must be text")
        fields[_FIELD[k]] = v

    def run():
        src = _sources()
        if "status" in fields and fields["status"] not in src.store.STAGES:
            return 400
        if fields.get("owner_user_id") is not None and fields["owner_user_id"] not in {u["id"] for u in src.users()}:
            return 400
        return 200 if src.store.update(src.engine, player_id, user_id=user.id, **fields) else 404
    code = await run_in_threadpool(run)
    from lofc.web.api.card import forget_prefetched
    forget_prefetched()
    if code == 400:
        raise HTTPException(status_code=400, detail="bad stage or owner")
    if code == 404:
        raise HTTPException(status_code=404, detail="not_on_the_watchlist")
    return {"ok": True}


@router.post("/api/watchlist/suggestions/{report_id}")
async def watchlist_suggestion(report_id: int, request: Request, user: WebUser = Depends(write_user)):
    """Add the suggested player (his row this season, else his latest) or dismiss the suggestion."""
    action = (await _body(request)).get("action")
    if action not in ("add", "dismiss"):
        raise HTTPException(status_code=400, detail="action must be add or dismiss")

    def run():
        src = _sources()
        rep = src.reports()
        hit = rep[(rep["id"] == report_id) & rep["player_id"].notna()]
        if hit.empty:
            return 404
        pid = int(hit.iloc[0]["player_id"])
        if action == "dismiss":
            src.store.dismiss(src.engine, report_id, pid, user.id)
            return 200
        live = src.live_rows()
        if pid in live.index:
            lr = live.loc[pid]
            comp, season = int(lr["competition_id"]), int(src.live_season_id)
            snap = {"rating": _num(lr["objective_composite"]), "club": lr["team_name"], "competition_id": comp}
        else:
            from lofc.dashboard import loaders as L
            last = pd.read_sql("SELECT competition_id, season_id, team_name FROM player_metrics_neutral "
                               "WHERE player_id = %(p)s ORDER BY season_id DESC, minutes DESC LIMIT 1",
                               L.get_engine(), params={"p": pid})
            if last.empty:
                return 404
            comp, season = int(last.iloc[0]["competition_id"]), int(last.iloc[0]["season_id"])
            snap = {"rating": None, "club": last.iloc[0]["team_name"], "competition_id": comp}
        src.store.add(src.engine, pid, comp, season, user_id=user.id, snapshot=snap)
        return 200
    code = await run_in_threadpool(run)
    from lofc.web.api.card import forget_prefetched
    forget_prefetched()
    if code == 404:
        raise HTTPException(status_code=404, detail="no_such_player")
    return {"ok": True}


def warm_watchlist() -> None:
    """The season frames the list reads (scorecards, candidates, current form, valuations):
    ~5 s cold. Never raises."""
    import logging
    import time
    log = logging.getLogger("lofc.web.warmup")
    t0 = time.perf_counter()
    try:
        page_json()
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
