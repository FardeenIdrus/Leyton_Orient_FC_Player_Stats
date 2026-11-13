"""The "Club vs League One" page (owner 2026-11-09): page shell + one JSON endpoint. Every rule
is in `lofc.core.club_vs_league`; every number is a stored rating, minutes or percentile.

    GET /club-vs-league?group=&age=&contract=&league=     page shell
    GET /api/club-vs-league?group=&age=&contract=&cols=&rank=&vs=
                                                           top 6, gap map, recommendations,
                                                           big picture
`group` = the gap-map position whose recommendations to list (default: the biggest gap).
`cols` = the chosen metric columns, comma-separated (default: the 3 biggest shortfalls);
`rank=gap` ranks each league's list by Gap closed instead of Overall.
`vs` = one of our rated players at `group` to measure it against (default: our best).
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

    def phase_detail():
        """SkillCorner's in / out of possession splits (player_detail_metrics "phys_tip." /
        "phys_otip." rows, value_p90) for League One this season and last, from the card's
        precomputed detail pools (core.detail_store, the same rows the card's physical table
        reads)."""
        from lofc.core import detail_store
        out = []
        for s in sorted(set(seasons())):
            f = detail_store.pools(cv.LEAGUE_ONE, s)["phys_"].frame
            f = f[f["metric"].astype(str).str.startswith(tuple(cv.PHASES.values()))]
            out.append(pd.DataFrame({"player_id": f["player_id"].to_numpy(), "competition_id": cv.LEAGUE_ONE,
                                     "season_id": s, "metric": f["metric"].astype(str).to_numpy(),
                                     "value_p90": f["value_p90"].to_numpy()}))
        return pd.concat(out, ignore_index=True) if out else pd.DataFrame(
            columns=["player_id", "competition_id", "season_id", "metric", "value_p90"])

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
        label=label, watched=watched, phase_detail=phase_detail)


def _pct_row(pcts, key):
    keys = ["player_id", "competition_id", "season_id", "position_group"]
    hit = pcts
    for k, v in zip(keys, key):
        hit = hit[hit[k] == v]
    return None if hit.empty else hit.iloc[0]


def _detail(src, pcts_cur, player: dict, theirs: list) -> dict:
    """One of our players' shortfalls against the named top-6 players (cv.gap_detail over his
    own percentiles, his own position's metrics) -- our best's in _base, a chosen player's in
    page_json (owner 2026-11-13)."""
    mine = _pct_row(pcts_cur, (player["player_id"], player["competition_id"], player["season_id"], player["position"]))
    return cv.gap_detail(mine, theirs, src.metrics(player["position"]), cv.weak_label(src.label))


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
    profiles, bar_rows = {}, {}
    for g in gaps:
        lvl, b = g["level"], g["bar"]
        g["shortfalls"], g["all_shortfalls"] = [], []
        profiles[g["group"]], bar_rows[g["group"]] = {}, []
        if lvl is None or not b["players"]:
            continue
        bar_rows[g["group"]] = [_pct_row(pc[b["season_id"]], (p["player_id"], p["competition_id"], p["season_id"], p["position"]))
                                for p in b["players"]]
        d = _detail(src, pc[cur], lvl, bar_rows[g["group"]])
        g["shortfalls"], g["all_shortfalls"], profiles[g["group"]] = d["shortfalls"], d["all_shortfalls"], d["profile"]
    return {"profiles": profiles, "bar_rows": bar_rows, "pcts_cur": pc[cur],
            "cur": cur, "prev": prev, "names": names, "rated": rated, "ours": ours,
            "squad_ids": {int(i) for i in squad["player_id"]},
            "top6": [_club_out(r) for r in clubs.head(cv.TOP_N).to_dict("records")],
            "us": _club_out(cv.orient_club(clubs), of=len(clubs)),
            "orient": cv._rank_text(table), "clubs": int(len(table)), "gaps": gaps,
            "big_picture": cv.big_picture(rated, neutral, cur, prev, getattr(src, "picture", src.physical),
                                          src.label, getattr(src, "sections", None), phases=_phases(src, neutral))}


def _phases(src, neutral) -> dict | None:
    """Big picture's in / out of possession frames (owner 2026-11-13), or None without the data."""
    get = getattr(src, "phase_detail", None)
    if get is None:
        return None
    detail = get()
    if detail is None or detail.empty:
        return None
    return {k: cv.phase_frame(detail, neutral, k, list(src.physical)) for k in cv.PHASES}


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


MAX_COLS = 5
NO_SHORTFALL = "None of these metrics is a shortfall, so no Gap closed."


def page_json(group=None, age=None, contract=None, strong=None, top6=None, cols=None,
              rank=None, vs=None) -> dict:
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
    rank = "gap" if rank == "gap" else ""
    # owner 2026-11-13: measure the selected position against any of our rated players there
    # (`vs`, a player_id; anything invalid -> our best). Every other position is unchanged.
    gaps = [cv.measure_against(g, None, None) for g in gaps]
    i = groups.index(sel)
    him = cv.compared_player(b["ours"], sel, vs)
    profile = b["profiles"].get(sel, {})
    if him is not None and gaps[i]["level"] is not None and him["player_id"] != gaps[i]["level"]["player_id"]:
        d = _detail(src, b["pcts_cur"], him, b["bar_rows"].get(sel, [])) if b["bar_rows"].get(sel) else None
        gaps[i] = cv.measure_against(gaps[i], him, d)
        profile = d["profile"] if d else {}
    row = gaps[i]
    level = row["level"]["rating"] if row["level"] else None
    # owner 2026-11-13: the metric columns -- the 3 biggest shortfalls, or the recruiter's own
    # pick (up to MAX_COLS of the position's rating metrics); Gap closed then counts only those
    position = row["level"]["position"] if row["level"] else cv.positions_in(sel)[0]
    wl = cv.weak_label(src.label)
    options = list(dict.fromkeys(src.metrics(position)))
    default = [s["metric"] for s in row["shortfalls"]]
    picked = []
    for m in str(cols or "").split(","):
        if m in options and m not in picked and len(picked) < MAX_COLS:
            picked.append(m)
    custom = bool(picked) and picked != default
    columns = picked if custom else default
    weights = cv.overall_weights(position)
    rec = cv.recommendations(b["rated"], src.candidates(b["cur"]), b["cur"], sel, level, b["squad_ids"],
                             src.league_names(), age=age, contract=contract, pcts=src.pcts(b["cur"]),
                             tag_metrics=columns, label=wl, strong2=strong, bar=row["bar"]["median"],
                             top6_only=top6, gap=profile, weights=weights,
                             score_metrics=columns if custom else None, strong_metrics=default, rank=rank)
    rec["metric_options"] = [{"metric": m, "label": wl(m)} for m in options]
    rec["gap_closed"] = {"custom": custom,
                         "note": NO_SHORTFALL if custom and not set(columns) & set(profile) else None}
    # owner 2026-11-13: "How this is worked out" -- Gap closed step by step, per league tab
    for lg in rec["leagues"]:
        lg["example"] = cv.gap_example(sel, row["level"], row["bar"]["median"], profile, lg.pop("top_gap", None),
                                       weights, lg["league"], label=wl, metrics=columns if custom else None)
    watched = src.watched()
    for lg in rec["leagues"]:
        for r in lg["rows"]:
            p, c, s = r["ids"]
            r["href"] = f"/player/{p}/{c}/{s}"
            r["watched"] = (p, c, s) in watched
            r["top6_level"] = row["bar"]["median"] is not None and r["overall"] >= row["bar"]["median"]
    for r in b["big_picture"]:
        r.setdefault("label", r["measure"])
    gaps_out = gaps
    compare = None
    if row.get("vs") is not None:
        compare = {"player_id": row["vs"], "name": row["level"]["name"], "rating": row["level"]["rating"],
                   "terms": cv.vs_terms(row["level"]["name"])}
    return {"compare": compare, "season": b["names"][b["cur"]], "prev_season": b["names"][b["prev"]],
            "top6": b["top6"], "us": b["us"], "orient": b["orient"], "clubs": b["clubs"],
            "gaps": gaps_out, "selected": sel, "recommendations": rec,
            "filters": {"age": age, "contract": contract, "strong": strong, "top6": top6,
                        "cols": picked if custom else [], "rank": rank, "vs": row.get("vs"),
                        "ages": [{"key": k, "label": l} for k, l in AGE_BANDS],
                        "contracts": [k for k in S.CONTRACT_HORIZONS if k != "Any"]},
            "big_picture": b["big_picture"], "terms": cv.TERMS}


@router.get("/api/club-vs-league")
async def club_vs_league_json(request: Request, user: WebUser = Depends(current_user)):
    q = request.query_params
    data = await run_in_threadpool(page_json, q.get("group"), q.get("age"), q.get("contract"),
                                   q.get("strong"), q.get("top6"), q.get("cols"), q.get("rank"), q.get("vs"))
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
