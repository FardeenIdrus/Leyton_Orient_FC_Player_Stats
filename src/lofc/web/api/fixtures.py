"""The Fixtures page (owner 2026-11-27, phase 5): which games to watch, which players in them,
and why. Every fact comes from `lofc.core.fixtures`; nothing here feeds the ranking (P11).

    GET  /fixtures                                    page shell
    GET  /api/fixtures?win=7|14|past                  games, their players and why, assignments
    GET  /api/fixtures/xlsx?win=..&keys=m:1,x:2       the games shown, as Excel
    POST /api/fixtures/assign      {key, user_id}     head of recruitment / admin (null clears)
    POST /api/fixtures/games       {date, time, competition, home, away}   any user adds a game
    POST /api/fixtures/games/{id}/remove              whoever added it, or head of recruitment / admin
    POST /api/fixtures/link        {submission_id, player_id}   head of recruitment / admin

Writes need a session + X-LOFC-Request (write_user).
"""
from __future__ import annotations

import datetime

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, Response

from lofc.core import webcache
from lofc.web.security import WebUser, current_user, write_user

router = APIRouter()
WINDOWS = {"7": 7, "14": 14, "past": 21}
LONDON = "Europe/London"
CUP_NAMES = {10040: "EFL Cup"}


def _engine():
    from lofc.dashboard import loaders as L
    return L.get_engine()


def _comps():
    from lofc.ingest.impect_matches import CUPS, UK_IRELAND
    return sorted(UK_IRELAND), sorted(set(CUPS.values()))


def _league_names() -> dict:
    from lofc.dashboard import loaders as L
    return {**L._competition_name_by_id(), **CUP_NAMES}


@webcache.versioned(maxsize=4)
def _base(season_id: int, day: str) -> tuple:
    """Every UK and Irish club's players this season with their signals (core.fixtures.players),
    kept until the data changes. `day` keys the cache to today (ages, windows)."""
    from sqlalchemy import text
    from lofc.core import fixtures as fx
    leagues, _ = _comps()
    e, s = _engine(), {"s": season_id}
    inl = ",".join(str(c) for c in leagues)
    q = lambda sql: pd.read_sql(text(sql), e, params=s)                       # noqa: E731
    F = {
        "matches": q(f"SELECT match_id, competition_id, scheduled_at, home_squad_id, away_squad_id, home_name, "
                     f"away_name, available FROM impect_matches WHERE season_id = :s AND competition_id IN ({inl})"),
        "rows": q(f"SELECT player_id, match_id, squad_id, competition_id, minutes, position_group FROM player_match_scores "
                  f"WHERE season_id = :s AND player_id IS NOT NULL AND competition_id IN ({inl})"),
        "club": q(f"SELECT player_id, match_id, minutes, overall_pct FROM player_match_club "
                  f"WHERE season_id = :s AND player_id IS NOT NULL AND competition_id IN ({inl})"),
        "squadmin": q(f"SELECT player_id, impect_squad_id, team_name, position_group, minutes, competition_id "
                      f"FROM impect_squad_minutes WHERE season_id = :s AND minutes > 0 AND competition_id IN ({inl})"),
        "cards": q(f"SELECT player_id, competition_id, position_group, objective_composite FROM player_scorecards "
                   f"WHERE season_id = :s AND competition_id IN ({inl})"),
    }
    ids = set(F["rows"]["player_id"].dropna().astype(int)) | set(F["squadmin"]["player_id"].dropna().astype(int))
    F["people"] = pd.read_sql(text("SELECT player_id, player_name, birth_date FROM players"), e)
    F["people"] = F["people"][F["people"]["player_id"].isin(ids)]
    P, squads = fx.players(F, today=pd.Timestamp(day))
    regions = fx.load_regions()
    for sid, sq in squads.items():
        sq["region"] = fx.region(sq["name"], sq["comp"], regions)
    return P, squads


def _games(season_id: int, start, end) -> pd.DataFrame:
    from sqlalchemy import text
    leagues, cups = _comps()
    inl = ",".join(str(c) for c in leagues + cups)
    return pd.read_sql(text(f"SELECT match_id, competition_id, scheduled_at, home_squad_id, away_squad_id, home_name, "
                            f"away_name, available FROM impect_matches WHERE season_id = :s AND competition_id IN ({inl}) "
                            f"AND scheduled_at >= :a AND scheduled_at < :b ORDER BY scheduled_at"),
                       _engine(), params={"s": season_id, "a": start, "b": end})


def _reports() -> pd.DataFrame:
    return pd.read_sql("SELECT submission_id, player_id, verdict, submitted_at, scout, home_team, away_team, "
                       "fixture_date, player_name, club_name, linkable FROM scout_reports WHERE missing_since IS NULL",
                       _engine())


def _watch() -> dict:
    from lofc.store import watchlist
    df = watchlist.load(_engine())
    if df.empty:
        return {}
    df = df[df["status"].isin(watchlist.ACTIVE_STAGES)]
    return {int(p): s for p, s in zip(df["player_id"], df["status"])}


def _people() -> list:
    from lofc.store import users
    return [{"id": u.id, "name": u.full_name, "role": u.role}
            for u in users.list_users(_engine(), datetime.datetime.now()) if u.is_active]


def _int(v):
    return None if v is None or pd.isna(v) else int(v)


def window(win: str, now: pd.Timestamp):
    """[start, end) in UTC (naive, as stored) for "7", "14" or "past" (the last 3 weeks)."""
    days = WINDOWS.get(win, 7)
    today = now.normalize()
    return (today - pd.Timedelta(days=days), now) if win == "past" else (now - pd.Timedelta(hours=3), today + pd.Timedelta(days=days + 1))


def build(win: str, user: WebUser, now: pd.Timestamp | None = None) -> dict:
    """The page as plain data. Players are sent for the clubs in the listed games only."""
    from lofc.config import settings
    from lofc.core import fixtures as fx
    from lofc.dashboard import auth
    from lofc.store import fixtures as st
    now = pd.Timestamp.utcnow().tz_localize(None) if now is None else pd.Timestamp(now)
    season = settings.live_season_id
    start, end = window(win, now)
    P, squads = _base(season, str(now.date()))
    names = _league_names()
    assigned = st.assignments(_engine())
    reports = _reports()
    games = []
    for r in _games(season, start, end).to_dict("records"):
        games.append({"key": f"m:{int(r['match_id'])}", "at": pd.Timestamp(r["scheduled_at"]).isoformat(),
                      "lg": names.get(int(r["competition_id"]), ""), "cup": int(r["competition_id"]) in CUP_NAMES,
                      "home": r["home_name"], "away": r["away_name"],
                      "hs": _int(r["home_squad_id"]), "as": _int(r["away_squad_id"]), "manual": False})
    for r in st.manual_between(_engine(), start.to_pydatetime(), end.to_pydatetime()).to_dict("records"):
        games.append({"key": f"x:{int(r['id'])}", "at": pd.Timestamp(r["scheduled_at"]).isoformat(),
                      "lg": r.get("competition") or "Added by hand", "cup": False,
                      "home": r["home_name"], "away": r["away_name"],
                      "hs": _int(r.get("home_squad_id")), "as": _int(r.get("away_squad_id")), "manual": True,
                      "added_by": _int(r.get("added_by"))})
    games.sort(key=lambda g: g["at"])
    sq_in = {g[k] for g in games for k in ("hs", "as") if g[k] is not None}
    mine = {pid: p for pid, p in P.items() if p["sq"] in sq_in}
    out_players = fx.attach(mine, reports, _watch())

    # reports not attached to anyone, that may be about a player in these games (G2: suggested only)
    links = st.report_links(_engine())
    unl = reports[reports["player_id"].isna() & reports["linkable"].fillna(False).astype(bool)
                  & ~reports["submission_id"].isin(list(links))]
    roster = pd.DataFrame([{"player_id": pid, "player_name": p["n"], "team_name": squads.get(p["sq"], {}).get("name")}
                           for pid, p in out_players.items()])
    sugg = fx.suggest_links(unl, roster)
    by_sid = {x["submission_id"]: x for x in unl.to_dict("records")}
    for pid, sids in sugg.items():
        out_players[pid]["sug"] = [{"sid": s, "name": by_sid[s]["player_name"], "club": by_sid[s]["club_name"],
                                    "v": by_sid[s]["verdict"],
                                    "d": None if pd.isna(by_sid[s]["submitted_at"]) else str(pd.Timestamp(by_sid[s]["submitted_at"]).date())}
                                   for s in sids]
        out_players[pid]["ns"] = False      # a report may be about him: not "Not seen yet"
    stand = {}
    if win == "past":
        ids = [int(g["key"][2:]) for g in games if g["key"].startswith("m:")]
        if ids:
            from sqlalchemy import text
            club = pd.read_sql(text(f"SELECT match_id, player_id, minutes, overall_pct FROM player_match_club "
                                    f"WHERE match_id IN ({','.join(str(i) for i in ids)})"), _engine())
            stand = fx.standouts(club)
    people = _people()
    names_by_id = {u["id"]: u["name"] for u in people}
    for g in games:
        a = assigned.get(g["key"]) or {}
        g["assigned"] = a.get("user_id")                       # "Assigned to me"
        g["scout"] = names_by_id.get(a.get("user_id")) or a.get("name")
        g["region"] = [squads.get(g[k], {}).get("region") for k in ("hs", "as")]
        if win == "past":
            g["reports"] = fx.reports_at(reports, g["at"], g["home"], g["away"])
            g["covered"] = fx.covered_by(g["reports"])
            g["stand"] = stand.get(int(g["key"][2:]), []) if g["key"].startswith("m:") else []
    return {"window": win, "now": now.isoformat(), "season": season, "games": games, "players": {str(k): v for k, v in out_players.items()},
            "squads": {str(k): v for k, v in squads.items() if k in sq_in},
            "users": [{"id": u["id"], "name": u["name"]} for u in people],
            "typed_scouts": st.typed_names(_engine()),
            "me": user.id, "can_assign": auth.can(user.role, "assign_scouts"), "regions": fx.REGIONS,
            "clubs": sorted(({"id": k, "name": v["name"], "lg": names.get(v["comp"], "")} for k, v in squads.items()),
                            key=lambda c: c["name"] or "")}


def why(p: dict) -> list[str]:
    """A player's reasons in words, strongest first (the page and the Excel say the same)."""
    w = []
    if p.get("watch"):
        w.append(f"Watchlist: {p['watch']}")
    pr = next((r for r in p.get("rep", []) if r["v"] in ("Sign", "Monitor Priority")), None)
    if pr:
        w.append(f"{pr['v']} ({pd.Timestamp(pr['d']).strftime('%-d %b %Y')})" if pr["d"] else pr["v"])
    if p.get("dis"):
        w.append("Scouts disagree")
    if p.get("f5"):
        w.append(f"Top 20% in {p['t5']} of last 5 games")
    elif p.get("f10"):
        w.append(f"Top 20% in {p['t10']} of last 10 games")
    if p.get("rise"):
        w.append(f"Rising: {p['rise_from']}% → {p['rise_to']}% (last 5 games vs 5 before)")
    br = p.get("br") or {}
    if br.get("on"):
        w.append(f"U23, minutes {br['before']} → {br['after']} (last 5 club games vs 5 before)")
    elif br.get("up"):
        w.append(f"Minutes up: {br['before']} → {br['after']} (last 5 club games vs 5 before)")
    if p.get("ns"):
        w.append("Never scouted, rated 3.5+")
    return w


def _order(p: dict) -> tuple:
    """Players in a game, as on the page: watchlist, Sign / Monitor Priority, scouts disagree,
    most reasons to watch, then season Overall."""
    return (not p.get("watch"), not p.get("pri"), not p.get("dis"), -len(why(p)), -(p.get("ov") or 0))


def workbook(data: dict, keys: list[str], pids: set | None = None, filters: str = "") -> bytes:
    """The games shown, as the head of recruitment sends them to scouts (owner 2026-11-27):
    a Games sheet (with the filters used), then one sheet per region -- where the game is
    played, the home club -- each game a shaded row with one row per player under it. With
    filters on (`pids`), only the players they kept, plus scout priorities and watchlist
    players marked "outside your filters", as on the page."""
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    games = [data["games_by_key"][k] if "games_by_key" in data else next((g for g in data["games"] if g["key"] == k), None)
             for k in keys]
    games = [g for g in games if g is not None]
    squads = data.get("squads", {})
    bold, head_fill = Font(bold=True), PatternFill("solid", fgColor="E6EEF8")
    game_fill, wrap = PatternFill("solid", fgColor="F1F2F4"), Alignment(wrap_text=True, vertical="top")

    def venue(g):
        reg = g.get("region") or [None, None]
        return reg[0] or reg[1] or "Region unknown"

    def players(g):
        inside, outside = [], []
        for pid, p in data["players"].items():
            if p["sq"] not in (g["hs"], g["as"]):
                continue
            if pids is None:
                if why(p):
                    inside.append((pid, p))
            elif pid in pids:
                inside.append((pid, p))
            elif p.get("pri") or p.get("watch"):
                outside.append((pid, p))
        return sorted(inside, key=lambda x: _order(x[1])), sorted(outside, key=lambda x: _order(x[1]))

    def when(g):
        return pd.Timestamp(g["at"]).tz_localize("UTC").tz_convert(LONDON)

    wb = Workbook()
    ws = wb.active
    ws.title = "Games"
    ws.append([f"Filters: {filters}" if filters else "Filters: none (every game)"])
    ws["A1"].font = bold
    ws.append([])
    ws.append(["Date", "Kick-off (UK)", "Home", "Away", "Competition", "Region", "Assigned", "Players to watch"])
    for c in ws[3]:
        c.font, c.fill = bold, head_fill
    for g in games:
        at = when(g)
        ins, outs = players(g)
        ws.append([at.strftime("%a %d %b"), at.strftime("%H:%M"), g["home"], g["away"], g["lg"], venue(g),
                   g.get("scout") or "", len(ins) + len(outs)])
    for col, w in zip("ABCDEFGH", (14, 13, 26, 26, 24, 22, 20, 16)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A4"

    from lofc.core.fixtures import REGIONS
    order = REGIONS + ["Region unknown"]
    for region in [r for r in order if any(venue(g) == r for g in games)]:
        rs = wb.create_sheet(region[:31])
        rs.append(["Player", "Club", "Position", "Age", "Why watch", "Last 5 games", "Season Overall",
                   "Rank at position", "Scout reports"])
        for c in rs[1]:
            c.font, c.fill = bold, head_fill
        for g in (g for g in games if venue(g) == region):
            at = when(g)
            who = g.get("scout")
            rs.append([f"{at.strftime('%a %d %b %H:%M')} · {g['home']} v {g['away']} · {g['lg']}"
                       + (f" · Assigned: {who}" if who else "")])
            rs.merge_cells(start_row=rs.max_row, start_column=1, end_row=rs.max_row, end_column=9)
            cell = rs.cell(rs.max_row, 1)
            cell.font, cell.fill = bold, game_fill
            ins, outs = players(g)
            if not ins and not outs:
                rs.append(["No one flagged in this game"])
            for (pid, p), out in [(x, False) for x in ins] + [(x, True) for x in outs]:
                reasons = "\n".join(why(p)) + ("\n(outside your filters)" if out else "")
                last5 = " ".join("—" if x is None else f"{x}%" for x in (p.get("f") or [])[-5:])
                reps = "\n".join(f"{r['v'] or '—'} {pd.Timestamp(r['d']).strftime('%d %b %Y') if r['d'] else ''} "
                                 f"({r['s'] or '?'})".replace("  ", " ") for r in p.get("rep", []))
                rs.append([p["n"], squads.get(str(p["sq"]), {}).get("name") or "", p.get("pos"), p.get("age"), reasons,
                           last5 or "no game data", p.get("ov"), f"{p['rk']} of {p['of']}" if p.get("rk") else "not rated",
                           reps or "Never scouted"])
                for c in rs[rs.max_row]:
                    c.alignment = wrap
            rs.append([])
        for col, w in zip("ABCDEFGHI", (24, 20, 16, 6, 40, 22, 14, 16, 40)):
            rs.column_dimensions[col].width = w
        rs.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _need_assign(user: WebUser) -> None:
    from lofc.dashboard import auth
    if not auth.can(user.role, "assign_scouts"):
        raise HTTPException(status_code=403, detail="Only the head of recruitment or an admin can do this.")


@router.get("/api/fixtures")
async def fixtures_json(win: str = "7", user: WebUser = Depends(current_user)):
    if win not in WINDOWS:
        raise HTTPException(status_code=400, detail="win must be 7, 14 or past")
    return JSONResponse(await run_in_threadpool(build, win, user))


@router.get("/api/fixtures/xlsx")
async def fixtures_xlsx(win: str = "7", keys: str = "", pids: str = "", f: str = "",
                        user: WebUser = Depends(current_user)):
    """The games shown (`keys`, in the page's order); `pids` = the players the filters kept
    (empty: no player filter on); `f` = the filters in words, printed on the Games sheet."""
    from lofc.core.card import csv_disposition
    data = await run_in_threadpool(build, win if win in WINDOWS else "7", user)
    order = [k for k in keys.split(",") if k] or [g["key"] for g in data["games"]]
    chosen = {p for p in pids.split(",") if p} if pids else None
    body = await run_in_threadpool(workbook, data, order, chosen, f[:300])
    return Response(body, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": csv_disposition(f"Fixtures {pd.Timestamp.now().date()}.xlsx")})


@router.post("/api/fixtures/assign")
async def assign(request: Request, user: WebUser = Depends(write_user)):
    from lofc.store import fixtures as st
    _need_assign(user)
    body = await request.json()
    key, uid, name = str(body.get("key") or ""), body.get("user_id"), str(body.get("name") or "").strip()[:80]
    if not (key.startswith("m:") or key.startswith("x:")):
        raise HTTPException(status_code=400, detail="bad game")
    if uid in (None, "") and name:
        # a typed name that is a platform user's name is that user ("Assigned to me" then works)
        uid = next((u["id"] for u in _people() if u["name"].strip().lower() == name.lower()), None)
    await run_in_threadpool(st.assign, _engine(), key, None if uid in (None, "") else int(uid), user.id,
                            None if uid not in (None, "") else name)
    return {"ok": True}


@router.post("/api/fixtures/games")
async def add_game(request: Request, user: WebUser = Depends(write_user)):
    """A game Impect does not list for us (EFL Trophy, FA Cup, a friendly). Date and kick-off
    are UK time; a club picked from the list brings its players."""
    from zoneinfo import ZoneInfo
    from lofc.store import fixtures as st
    b = await request.json()
    try:
        local = datetime.datetime.fromisoformat(f"{b['date']}T{b.get('time') or '15:00'}")
    except (KeyError, ValueError):
        raise HTTPException(status_code=400, detail="Give a date and a kick-off time.")
    utc = local.replace(tzinfo=ZoneInfo(LONDON)).astimezone(datetime.timezone.utc).replace(tzinfo=None)
    home, away = b.get("home") or {}, b.get("away") or {}
    hn, an = str(home.get("name") or "").strip(), str(away.get("name") or "").strip()
    if not hn or not an:
        raise HTTPException(status_code=400, detail="Give both clubs.")
    i = await run_in_threadpool(st.add_manual, _engine(), utc, str(b.get("competition") or "").strip(), hn, an,
                                home.get("id"), away.get("id"), user.id)
    return {"ok": True, "key": f"x:{i}"}


@router.post("/api/fixtures/games/{fixture_id}/remove")
async def remove_game(fixture_id: int, user: WebUser = Depends(write_user)):
    from sqlalchemy import text
    from lofc.dashboard import auth
    from lofc.store import fixtures as st
    row = pd.read_sql(text("SELECT added_by FROM manual_fixtures WHERE id = :i"), _engine(), params={"i": fixture_id})
    if row.empty:
        raise HTTPException(status_code=404, detail="No such game")
    if _int(row.iloc[0]["added_by"]) != user.id and not auth.can(user.role, "assign_scouts"):
        raise HTTPException(status_code=403, detail="Only whoever added it, the head of recruitment or an admin can remove it.")
    await run_in_threadpool(st.remove_manual, _engine(), fixture_id)
    return {"ok": True}


@router.post("/api/fixtures/link")
async def link(request: Request, user: WebUser = Depends(write_user)):
    from lofc.store import fixtures as st
    _need_assign(user)
    b = await request.json()
    try:
        sid, pid = str(b["submission_id"]), int(b["player_id"])
    except (KeyError, ValueError, TypeError):
        raise HTTPException(status_code=400, detail="bad request")
    await run_in_threadpool(st.link_report, _engine(), sid, pid, user.id)
    return {"ok": True}


def warm() -> None:
    """Build the players' signals before anyone asks (owner 2026-11-27: the first open was slow).
    Runs at start-up and again after every data change (webcache.rewarm_on_change)."""
    from lofc.config import settings
    now = pd.Timestamp.utcnow().tz_localize(None)
    _base(settings.live_season_id, str(now.date()))


def mount(app, render, shell) -> None:
    app.include_router(router)
    webcache.register_warmup("fixtures", warm)

    def start() -> None:
        import threading

        def run() -> None:
            # after the Players warm-up, one at a time (as the other pages do)
            from lofc.web.api import players as players_api
            players_api.PLAYERS_WARM.wait(timeout=900)
            try:
                warm()
            except Exception:                           # noqa: BLE001 -- the page builds on demand
                pass
        threading.Thread(target=run, name="lofc-fixtures-warmup", daemon=True).start()
    app.router.on_startup.append(start)

    @app.get("/fixtures", response_class=HTMLResponse, name="page_fixtures")
    async def fixtures_page(request: Request, user: WebUser = Depends(current_user)):
        from lofc.web import pages
        return render(request, "fixtures.html", **shell(request, user, "fixtures", page=pages.PAGES["fixtures"]))
