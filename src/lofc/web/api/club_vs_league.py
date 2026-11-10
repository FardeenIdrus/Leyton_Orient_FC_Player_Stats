"""The "Club vs League One" page (owner 2026-11-09): page shell + one JSON endpoint. Every rule
is in `lofc.core.club_vs_league`; every number is a stored rating, minutes or percentile.

    GET /club-vs-league?group=&age=&contract=&league=     page shell
    GET /api/club-vs-league?group=&age=&contract=          top 6, gap map, recommendations,
                                                           big picture
`group` = the gap-map position whose recommendations to list (default: the biggest gap).
"""
from __future__ import annotations

import types

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse

from lofc.core import club_vs_league as cv
from lofc.core import webcache
from lofc.web.security import WebUser, current_user

router = APIRouter()


def _sources():
    """The stored frames (tests swap the whole namespace)."""
    import pandas as pd
    from sqlalchemy import text
    from lofc.core import infobar, squad
    from lofc.dashboard import loaders as L
    from lofc.dashboard.glossary_data import PHYSICAL
    from lofc.dashboard.labels import metric_label
    from lofc.dashboard.seasons import season_name_for
    from lofc.leagues import league_names
    from lofc.model import club_framework as cf
    from lofc.web.api import compare as cmp

    phys = list(cf.PHYSICAL_METRICS["Winger"])
    # owner 2026-11-09: performance measures from players' season figures (same method)
    perf = {"Attack": ["np_xg_p90", "xa_p90", "touches_in_box_p90"],
            "Progression": ["packing_bypassed_opponents_p90", "deep_progressions_p90", "passes_into_box_p90"],
            "Without the ball": ["pressures_p90", "ball_wins_p90", "ground_duel_win_pct", "aerial_win_pct"]}
    sections = {m: "Physical" for m in phys} | {m: sec for sec, ms in perf.items() for m in ms}
    picture = phys + [m for ms in perf.values() for m in ms]

    def seasons():
        cur = infobar.latest_season_id(L.get_engine())
        older = [s for s in L.available_seasons() if s < cur]
        return cur, (max(older) if older else cur)

    def cards():
        cur, prev = seasons()
        return pd.read_sql(text(
            "SELECT player_id, competition_id, season_id, position_group, objective_composite, "
            "performance_band, physical_band FROM player_scorecards WHERE archetype = 'All Metrics' "
            "AND season_id IN (:a, :b)"), L.get_engine(), params={"a": cur, "b": prev})

    def neutral():
        cur, prev = seasons()
        cols = ", ".join(["player_id", "competition_id", "season_id", "minutes", "team_name",
                          "player_name"] + picture)
        return pd.read_sql(text(f"SELECT {cols} FROM player_metrics_neutral WHERE season_id IN (:a, :b)"),
                           L.get_engine(), params={"a": cur, "b": prev})

    def metrics(position):
        from lofc.dashboard.tabs import players as P
        return list(P._club_metrics_for(position, cf.DEFAULT_ARCHETYPE)[0]) + list(cf.PHYSICAL_METRICS.get(position, []))

    def label(m):
        return PHYSICAL[m][0] if m in PHYSICAL else metric_label(m)

    def watched():
        from lofc.store import watchlist
        w = watchlist.load(L.get_engine())
        return {(int(a), int(b), int(c)) for a, b, c in zip(w["player_id"], w["competition_id"], w["season_id"])} if len(w) else set()

    return types.SimpleNamespace(
        seasons=seasons, season_name=season_name_for, cards=cards, neutral=neutral,
        squad=squad.squad, pcts=L.load_scorecard_percentiles, candidates=cmp._candidates,
        league_names=league_names, metrics=metrics, physical=phys, picture=picture, sections=sections,
        label=label, watched=watched)


def _pct_row(pcts, key):
    keys = ["player_id", "competition_id", "season_id", "position_group"]
    hit = pcts
    for k, v in zip(keys, key):
        hit = hit[hit[k] == v]
    return None if hit.empty else hit.iloc[0]


@webcache.versioned(maxsize=2)
def _base() -> dict:
    """Everything that does not depend on the user's picks: rated rows, our players, the top 6,
    the gap map with each position's shortfalls, the big picture."""
    src = _sources()
    cur, prev = src.seasons()
    names = {cur: src.season_name(cur), prev: src.season_name(prev)}
    neutral = src.neutral()
    rated = cv.rated_frame(src.cards(), neutral)
    squad = src.squad()
    ours = cv.our_players(squad, rated, cur, prev, src.league_names())
    table = cv.club_table(rated, cur)
    clubs = cv.club_ratings(rated, cur)
    gaps = cv.gap_map(rated, ours, cur, prev, names)
    pc = {cur: src.pcts(cur), prev: src.pcts(prev)}
    for g in gaps:
        lvl, b = g["level"], g["bar"]
        g["shortfalls"], g["all_shortfalls"] = [], []
        if lvl is None or not b["players"]:
            continue
        mine = _pct_row(pc[cur], (lvl["player_id"], lvl["competition_id"], lvl["season_id"], lvl["position"]))
        theirs = [_pct_row(pc[b["season_id"]], (p["player_id"], p["competition_id"], p["season_id"], p["position"]))
                  for p in b["players"]]
        wl = cv.weak_label(src.label)
        g["shortfalls"] = cv.shortfalls(mine, theirs, src.metrics(lvl["position"]), wl)
        g["all_shortfalls"] = cv.all_shortfalls(mine, theirs, src.metrics(lvl["position"]), wl)
    return {"cur": cur, "prev": prev, "names": names, "rated": rated, "ours": ours,
            "squad_ids": {int(i) for i in squad["player_id"]},
            "top6": [_club_out(r) for r in clubs.head(cv.TOP_N).to_dict("records")],
            "us": _club_out(cv.orient_club(clubs), of=len(clubs)),
            "orient": cv._rank_text(table), "clubs": int(len(table)), "gaps": gaps,
            "big_picture": cv.big_picture(rated, neutral, cur, prev, getattr(src, "picture", src.physical),
                                          src.label, getattr(src, "sections", None))}


def _club_out(r: dict | None, of: int | None = None) -> dict | None:
    """A Top 6 card row: Overall ("avg"), Performance and Physical club averages to 2 dp."""
    if r is None:
        return None
    two = lambda v: None if v is None or v != v else round(float(v), 2)   # noqa: E731
    out = {"club": r["team_name"], "avg": two(r["overall"]), "performance": two(r["performance"]),
           "physical": two(r["physical"]), "players": int(r["n"]), "rank": int(r["rank"])}
    if of is not None:
        out["of"] = int(of)
    return out


def clear() -> None:
    _base.clear()


def page_json(group=None, age=None, contract=None, strong=None, top6=None) -> dict:
    from lofc.core.physical_page import AGE_BANDS
    from lofc.dashboard import seasons as S
    src = _sources()
    b = _base()
    gaps = b["gaps"]
    groups = [g["group"] for g in gaps]
    sel = group if group in groups else next((g["group"] for g in gaps if g["gap"] is not None), groups[0])
    age = age if age in {k for k, _ in AGE_BANDS} else ""
    contract = contract if contract in S.CONTRACT_HORIZONS and contract != "Any" else ""
    strong = str(strong or "").lower() in ("1", "true", "on", "yes")
    top6 = str(top6 or "").lower() in ("1", "true", "on", "yes")
    row = next(g for g in gaps if g["group"] == sel)
    level = row["level"]["rating"] if row["level"] else None
    rec = cv.recommendations(b["rated"], src.candidates(b["cur"]), b["cur"], sel, level, b["squad_ids"],
                             src.league_names(), age=age, contract=contract, pcts=src.pcts(b["cur"]),
                             tag_metrics=[s["metric"] for s in row["shortfalls"]], label=cv.weak_label(src.label),
                             strong2=strong, bar=row["bar"]["median"], top6_only=top6)
    watched = src.watched()
    for lg in rec["leagues"]:
        for r in lg["rows"]:
            p, c, s = r["ids"]
            r["href"] = f"/player/{p}/{c}/{s}"
            r["watched"] = (p, c, s) in watched
            r["top6_level"] = row["bar"]["median"] is not None and r["overall"] >= row["bar"]["median"]
    for r in b["big_picture"]:
        r.setdefault("label", r["measure"])
    gaps_out = [{k: v for k, v in g.items()} for g in gaps]
    return {"season": b["names"][b["cur"]], "prev_season": b["names"][b["prev"]],
            "top6": b["top6"], "us": b["us"], "orient": b["orient"], "clubs": b["clubs"],
            "gaps": gaps_out, "selected": sel, "recommendations": rec,
            "filters": {"age": age, "contract": contract, "strong": strong, "top6": top6,
                        "ages": [{"key": k, "label": l} for k, l in AGE_BANDS],
                        "contracts": [k for k in S.CONTRACT_HORIZONS if k != "Any"]},
            "big_picture": b["big_picture"], "terms": cv.TERMS}


@router.get("/api/club-vs-league")
async def club_vs_league_json(request: Request, user: WebUser = Depends(current_user)):
    q = request.query_params
    data = await run_in_threadpool(page_json, q.get("group"), q.get("age"), q.get("contract"),
                                   q.get("strong"), q.get("top6"))
    return JSONResponse(data)


def warm() -> None:
    try:
        page_json()
    except Exception:                                           # noqa: BLE001
        import logging
        logging.getLogger("lofc.web.warmup").warning("club vs league warm-up failed", exc_info=True)


def mount(app, render, shell) -> None:
    app.include_router(router)
    webcache.register_warmup("club-vs-league", lambda: warm())

    def start() -> None:
        # After every other page's warm-up (one heavy job at a time); named "-warmup" so
        # /readyz waits for it too.
        import threading

        def run() -> None:
            from lofc.web.api import players as players_api
            players_api.PLAYERS_WARM.wait(timeout=900)
            for t in threading.enumerate():
                if t.name.endswith("-warmup") and t is not threading.current_thread():
                    t.join(timeout=900)
            warm()
        threading.Thread(target=run, name="lofc-club-vs-league-warmup", daemon=True).start()
    app.router.on_startup.append(start)

    @app.get("/club-vs-league", response_class=HTMLResponse, name="page_club_vs_league")
    async def page(request: Request, user: WebUser = Depends(current_user)):
        from lofc.web import pages
        return render(request, "club_vs_league.html", terms=cv.TERMS,
                      **shell(request, user, "club-vs-league", page=pages.PAGES["club-vs-league"]))
