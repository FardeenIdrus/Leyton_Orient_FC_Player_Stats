"""The Compare page: page shell + JSON endpoints. Every figure and word comes from
`lofc.core.compare` (the same `compare_view` the Streamlit page draws) over the same frames;
this module only turns the URL into a request and the result into JSON.

    GET /compare?season=&position=&leagues=&rank_as=&money=&a=&b=&c=    page shell
    GET /api/compare?(same)        the comparison (slots resolved; defaults filled)
    GET /api/compare/pool?(same)   the picker's list: the filtered pool, ranked
    GET /api/compare/search?season=&position=&q=   typed search, that position only (C5)

Slots are "<player_id>-<competition_id>" in the season of `season`. Filters are the Players
page's (`players.Query`), so Compare picks from the same pool (`core.players_pool.build_pool`).
"""
from __future__ import annotations

import collections
import logging
import threading
import time

import pandas as pd
from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, Response

from lofc.core import compare as C
from lofc.core import webcache
from lofc.web.security import WebUser, current_user

router = APIRouter()
log = logging.getLogger("lofc.web.compare")
SLOTS = ("a", "b", "c")
_RENAME = {"Overall": "Composite", "Overall trend": "Composite trend"}   # owner: "Composite"
_RATING_ROWS = {"Overall", "Performance", "Physical"}


def parse_key(v) -> tuple[int, int] | None:
    """"39154-5" -> (39154, 5); anything else -> None (a stale URL still opens)."""
    try:
        p, c = str(v).split("-")
        return (int(p), int(c)) if p.isdigit() and c.isdigit() else None
    except (TypeError, ValueError):
        return None


# --- version-keyed copies of the loaders Compare reads (webcache: kept until the data changes,
# never unpickled per hit; the Streamlit page keeps its own st.cache loaders) ----------------
@webcache.versioned(maxsize=8)
def _sc_pcts(season_id: int):
    from lofc.dashboard import loaders as L
    return L.load_scorecard_percentiles(season_id)


@webcache.versioned(maxsize=8)
def _metric_values(season_id: int):
    from lofc.dashboard import loaders as L
    return L.load_metric_values(season_id)


@webcache.versioned(maxsize=8)
def _prev(season_id: int):
    from lofc.dashboard import loaders as L
    return L.load_previous_ratings(season_id)


@webcache.versioned(maxsize=8)
def _styles(season_id: int):
    from lofc.dashboard import loaders as L
    return L.load_style_labels(season_id)


@webcache.versioned(maxsize=8)
def _history(season_id: int):
    from lofc.dashboard import compare_tables as ct
    return ct.load_rating_history(season_id)


@webcache.versioned(maxsize=8)
def _candidates(season_id: int):
    from lofc.dashboard import loaders as L
    return L.load_candidates(1.0, season_id)


@webcache.versioned(maxsize=2)
def _scout_rows() -> pd.DataFrame:
    """Every live scout verdict (the table is small): the same rows `compare_tables.
    load_scout_verdicts` reads, without its 60 s TTL (the version tracks scout_reports)."""
    from lofc.dashboard import loaders as L
    try:
        return pd.read_sql("SELECT player_id, verdict FROM scout_reports "
                           "WHERE missing_since IS NULL", L.get_engine())
    except Exception:                                     # noqa: BLE001
        return pd.DataFrame(columns=["player_id", "verdict"])


def _scouts(pids: tuple[int, ...]) -> pd.DataFrame:
    rows = _scout_rows()
    return rows[rows["player_id"].isin([int(p) for p in pids])]


def _index(season_id: int) -> pd.DataFrame:
    """The season-wide search index (every position and league), as the Players search."""
    from lofc.core import players_pool as pp
    from lofc.dashboard import loaders as L
    return pp._search_index_for(L.data_version(with_scorecards=True), int(season_id))


@webcache.versioned(maxsize=8)
def _lookup(season_id: int) -> dict:
    """`C.index_lookup` of the season's search index plus (player, competition) -> label, kept
    per season: rebuilding them took ~0.3 s of every uncached Compare answer."""
    look = C.index_lookup(_index(season_id))
    look["label_of"] = {(p, c): lbl for (p, c, _s), lbl in look["by_key"].items()}
    look["key_of"] = {v: k for k, v in look["label_of"].items()}
    return look


@webcache.versioned(maxsize=64)
def _orient(position: str, season_id: int, exclude: tuple[int, ...] = ()):
    """`squad.orient_median`, leaving out every compared player who is ours (owner C1,
    2026-11-09: as the card leaves out its own player). N counts the players actually used."""
    from lofc.core import squad
    if len(exclude) <= 1:
        return squad.orient_median(position, season_id,
                                   exclude_player_id=exclude[0] if exclude else None)
    from lofc.dashboard import loaders as L
    sq = squad.squad()
    ours = squad._ours(position, season_id,
                       sq_all=sq[~sq["player_id"].astype(int).isin(exclude)])
    return squad.median_pct(ours, squad._metric_cols(L.load_scorecard_percentiles(season_id)))


def _ours_among(pids) -> tuple[int, ...]:
    """The compared players who are current Leyton Orient players, sorted (the cache key)."""
    from lofc.core import squad
    ours = set(squad.squad()["player_id"].astype(int))
    return tuple(sorted({int(p) for p in pids} & ours))


def _zone_slice(row) -> pd.DataFrame:
    from lofc.core import detail_store
    return detail_store.player_rows(row, "zone.")


# --- payload ---------------------------------------------------------------------------------
def _slots_from(params) -> dict[str, tuple[int, int] | None]:
    return {s: parse_key(params.get(s)) for s in SLOTS}


class _Q:
    """The Players page's query, with the pool always built affordability-off: on Compare the
    money switch only adds the Market row, and the budget / wage gates only add flags to the
    pool (`constrain.filters.apply_gates`), never remove a player -- so the rows and defaults
    are the same, and the switch reuses the warm pool instead of building a new one."""
    def __init__(self, params):
        from lofc.web.api import players as players_api
        self._q = players_api.Query(params)
        self.money = self._q.money

    def filters(self):
        import dataclasses
        return dataclasses.replace(self._q.filters(), budget_eur=float("inf"), wage_multiplier=1.0)


def _filters(params):
    return _Q(params)


def _table(rows: list[dict]) -> list[dict]:
    """compare_tables.build_rows as JSON; the percentile text is Python's (as `table_html`)."""
    return [{"metric": r["metric"], "label": r["label"], "tier": r.get("tier"),
             "cells": [{"text": c["text"], "pct": c["pct"],
                        "pct_text": f'P{c["pct"]:.0f}' if c.get("pct") is not None else None,
                        "cls": c["cls"] if c.get("cls") in ("best", "worst") else None}
                       for c in r["cells"]]}
            for r in rows]


def _orient_line(orient, n: int, keys: list[str], position: str) -> dict | None:
    if not n:
        return None
    return {"values": [orient.get(m) for m in keys],
            "label": f"Leyton Orient median ({n}), {position}s"}


def compare_payload(params) -> dict:
    from lofc.core import players_pool as pp
    from lofc.core.card import clean, text_or, thin_pool_size
    from lofc.dashboard import compare_tables as ct
    from lofc.dashboard import detail_section as ds
    from lofc.dashboard import loaders as L
    from lofc.dashboard import seasons as S
    from lofc.dashboard.labels import LABELS
    from lofc.model import club_framework as cf
    from lofc.web.api import players as players_api

    t0 = time.perf_counter()
    q = _filters(params)
    f = q.filters()
    sid, pos = f.season_id, f.position
    season_name = S.season_name_for(sid)
    out: dict = {
        "season": sid, "season_name": season_name, "position": pos,
        "title": f"{pos}s · {season_name}", "rank_as": f.archetype,
        "lens": None if f.archetype == cf.DEFAULT_ARCHETYPE else f.archetype,
        "money": q.money, "notice": None, "message": None,
        "slots": {s: None for s in SLOTS}, "players": []}

    idx = _index(sid)
    if idx.empty:
        out["message"] = {"level": "warn", "text": C.NO_PLAYERS}
        return out
    look = _lookup(sid)
    same_pos = look["by_position"].get(pos, [])
    if len(same_pos) < 2:
        out["message"] = {"level": "warn", "text": C.NEED_TWO}
        return out
    res = players_api.cached_pool(f)
    notice = pp.season_notice(res, f)
    out["notice"] = None if notice is None else {"level": notice[0], "text": notice[1]}

    # Slots exactly as the Streamlit selectboxes: a URL slot of another position (or one not in
    # this season) falls back to its default; A and B default from the ranked pool.
    label_of, row_of = look["label_of"], look["row_of"]
    state: dict = {}
    for s, key in _slots_from(params).items():
        if key is not None and key in label_of:
            state[f"cmp_{s}"] = label_of[key]
    state.setdefault("cmp_c", C.NONE_OPTION)
    C.sanitize_slots(state, same_pos)
    C.fill_default_slots(state, C.default_candidates(res.pool, idx, pos, look))
    picks = [state["cmp_a"], state["cmp_b"], state["cmp_c"]]
    key_of = look["key_of"]
    for s, lbl in zip(SLOTS, picks):
        if lbl in key_of:
            p, c = key_of[lbl]
            out["slots"][s] = f"{p}-{c}"
    out["slot_labels"] = {s: (lbl if lbl in key_of else None) for s, lbl in zip(SLOTS, picks)}

    chosen = list(dict.fromkeys(x for x in picks if x and x != C.NONE_OPTION))
    if len(chosen) < 2:
        out["message"] = {"level": "info", "text": C.PICK_TWO}
        return out
    recs, reasons = [], []
    scorecards = lambda s: pp.scorecards(s, pos, cf.DEFAULT_ARCHETYPE)   # noqa: E731 (= load_scorecards)
    for lbl in chosen:
        t = idx.iloc[row_of[lbl]]
        row, reason = C.pick_row((int(t["player_id"]), int(t["competition_id"]), int(t["season_id"])),
                                 res.pool, _candidates, scorecards, blank_unrated=True)
        recs.append(row)
        reasons.append(reason)
    if any(r is None for r in recs):
        out["message"] = {"level": "info", "text": C.NO_DATA}
        return out
    if len({r["position_group"] for r in recs}) > 1:
        out["message"] = {"level": "error", "text": C.NOT_LIKE}
        return out

    ctx = C.extras_context(tuple(int(r["player_id"]) for r in recs), sid, _styles, _history,
                           _scouts, L.competition_name_by_id)
    v = C.compare_view(recs, pos, f.archetype, q.money, _metric_values(sid), _sc_pcts(sid),
                       _prev(sid), ctx)
    names = v["names"]

    players, named_vs = [], []
    for i, (r, reason) in enumerate(zip(recs, reasons)):
        league = text_or(r.get("league"), C.DASH)
        thin = thin_pool_size(reason, r.get("peer_count"), r.get("minutes"))
        vs = C.vs_text(pos, league, thin)
        named_vs.append((str(r["player_name"]), vs))
        pid, cid, rsid = int(r["player_id"]), int(r["competition_id"]), int(r["season_id"])
        club = text_or(r.get("team_name"), "")
        players.append({
            "player_id": pid, "competition_id": cid, "season_id": rsid, "key": f"{pid}-{cid}",
            "name": str(r["player_name"]), "header_name": names[i],
            "sub": " · ".join(x for x in (club, str(v["rows"][i].get("League") or "")) if x),
            "href": f"/player/{pid}/{cid}/{rsid}",
            "not_rated": C.not_rated_caption(reason, r.get("peer_count"), r.get("minutes")),
            "vs": vs})
    out["players"] = players
    vs_line = C.vs_sub(named_vs)

    rows = v["rows"]
    out["summary"] = {
        "rows": [{"attribute": _RENAME.get(k, k),
                  "kind": "text" if k in C.TEXT_ROWS else "value",
                  "rating": k in _RATING_ROWS,
                  "cells": [{"text": str(r.get(k, C.DASH))} if k in C.TEXT_ROWS
                            else C.change_parts(str(r.get(k, C.DASH))) for r in rows]}
                 for k in C.summary_attributes(rows)],
        "caption": C.SUMMARY_CAPTION, "note": v["note"]}

    orient, n_orient = _orient(pos, sid, C.safe(
        lambda: _ours_among(int(r["player_id"]) for r in recs), ()))
    rad = v["radar"]
    out["perf_radar"] = {
        "heading": "Performance profile" + (f" · {f.archetype}" if v["lens"] else ""),
        "sub": f"High- and Mid-weight metrics · percentile vs {vs_line}",
        "axes": rad["axes"], "labels": [LABELS.get(m, m) for m in rad["axes"]],
        "traces": [{"name": n, "values": vals} for n, vals in rad["traces"]],
        "no_data": ("No percentiles for " + ", ".join(rad["no_data"]) + ".") if rad["no_data"] else None,
        "leagues_note": C.LEAGUES_NOTE if v["different_leagues"] else None,
        "orient": _orient_line(orient, n_orient, rad["axes"], pos)}
    ph = v["phys_radar"]
    out["phys_radar"] = None if not v["has_physical"] else {
        "heading": "Physical profile",
        "sub": f"Rated physical metrics · percentile vs {vs_line}",
        "axes": ph["axes"],
        "labels": [LABELS.get(C.PHYS_RADAR_LABEL[m], C.PHYS_RADAR_LABEL[m]) for m in ph["axes"]],
        "traces": [{"name": n, "values": vals} for n, vals in ph["traces"]],
        "no_data": C.no_physical_caption(ph["no_data"]) if ph["no_data"] else None,
        "orient": _orient_line(orient, n_orient, ph["axes"], pos)}
    out["perf_table"] = {"heading": v["perf_heading"].replace("Performance", "Performance · in the rating", 1),
                         "sub": f"Value · percentile vs {vs_line} · best green, worst red",
                         "rows": _table(v["perf_rows"])}
    out["perf_other"] = {"rows": _table(v["other_rows"])}
    out["phys_table"] = None if not v["phys_rows"] else {
        "heading": "Physical · in the rating",
        "sub": f"SkillCorner · value · percentile vs {vs_line}",
        "rows": _table(v["phys_rows"])}
    out["phys_other"] = {"rows": _table(v["phys_more"])} if v["phys_rows"] else None

    zones = C.safe(lambda: C.zone_measures(recs, _zone_slice), {})
    out["zones"] = None if not zones else {
        "options": [{"key": fam, "label": ct.ZONE_FAMILY_LABELS[fam]} for fam in ct.ZONE_FAMILIES],
        "zones": [{"code": z, "name": ds.ZONE_NAMES[z]} for z in ct.ZONES],
        "measures": {fam: [None if cells is None else {
            code: {"text": text, "pct": None if pct is None or pd.isna(pct) else round(float(pct)),
                   "pct_text": None if pct is None or pd.isna(pct) else f"{ds.ordinal(pct)} percentile"}
            for code, (text, pct) in cells.items()} for cells in per]
            for fam, per in zones.items()},
        "any_missing": {fam: any(c is not None and ct.zone_missing(c) for c in per)
                        for fam, per in zones.items()},
        "caption": "Per 90 · colour = percentile vs his position in his own league"}
    out["ms"] = round((time.perf_counter() - t0) * 1000)
    return clean(out)


def pool_payload(params) -> dict:
    """The picker's list: the filtered pool in ranking order (what Streamlit defaults A/B from)."""
    from lofc.core.card import clean
    from lofc.web.api import players as players_api
    q = _filters(params)
    f = q.filters()
    label_of = _lookup(f.season_id)["label_of"]
    pool = players_api.cached_pool(f).pool
    out = []
    for r in pool.itertuples():
        key = (int(r.player_id), int(r.competition_id))
        if key not in label_of:
            continue
        comp = getattr(r, "objective_composite", None)
        out.append({"key": f"{key[0]}-{key[1]}", "label": label_of[key],
                    "composite": None if comp is None or pd.isna(comp) else f"{float(comp):.2f}"})
    return clean({"season": f.season_id, "position": f.position, "players": out})


def search_payload(params) -> dict:
    """Typed search in a slot (owner C5, 2026-11-09): players of the selected Position only,
    any league and outside the filters, as `players_pool.search` (same matching, same items)."""
    from lofc.core import players_pool as pp
    from lofc.web.api import players as players_api
    text = (params.get("q") or "").strip()
    if not text:
        return {"results": []}
    q = players_api.Query(params)
    idx, look = _index(q.season), _lookup(q.season)
    labels = pp.filter_labels(look["by_position"].get(q.position, []), text)[:30]
    out = []
    for label in labels:
        r = idx.iloc[look["row_of"][label]]
        out.append({"label": label, "player_id": int(r["player_id"]),
                    "competition_id": int(r["competition_id"]), "season_id": int(r["season_id"]),
                    "name": str(r["player_name"]), "position": str(r["position_group"]),
                    "league": None if pd.isna(r["league"]) else str(r["league"])})
    return {"results": out}


# Whole answers keyed by the exact query (back/forward and re-picks ask for the same one again),
# as the Players page: JSON bytes, keyed on web_data_version (scout reports included).
_answers: "collections.OrderedDict[tuple, bytes]" = collections.OrderedDict()
_lock = threading.Lock()
_CACHE_SIZE = 64


def _cached(kind: str, params, build) -> bytes:
    from lofc.dashboard import loaders as L
    key = (kind, L.web_data_version(), tuple(sorted(params.multi_items())))
    with _lock:
        hit = _answers.get(key)
        if hit is not None:
            _answers.move_to_end(key)
            return hit
    body = JSONResponse(build(params)).body
    with _lock:
        _answers[key] = body
        while len(_answers) > _CACHE_SIZE:
            _answers.popitem(last=False)
    return body


@router.get("/api/compare")
async def compare_json(request: Request, user: WebUser = Depends(current_user)):
    body = await run_in_threadpool(_cached, "compare", request.query_params, compare_payload)
    return Response(body, media_type="application/json")


@router.get("/api/compare/pool")
async def pool_json(request: Request, user: WebUser = Depends(current_user)):
    body = await run_in_threadpool(_cached, "pool", request.query_params, pool_payload)
    return Response(body, media_type="application/json")


@router.get("/api/compare/search")
async def search_json(request: Request, user: WebUser = Depends(current_user)):
    body = await run_in_threadpool(_cached, "search", request.query_params, search_payload)
    return Response(body, media_type="application/json")


def warm_compare() -> None:
    """Fill the loaders Compare reads for every season and draw the default comparison of
    each, so the first visit after a restart is warm. Never raises."""
    from starlette.datastructures import QueryParams
    from lofc.core import players_pool as pp
    from lofc.dashboard import loaders as L
    t0 = time.perf_counter()
    try:
        for sid in sorted(L.available_seasons(), reverse=True):
            for fn in (_sc_pcts, _metric_values, _prev, _styles, _history, _candidates):
                C.safe(lambda fn=fn: fn(sid), None)
            C.safe(lambda: _lookup(sid), None)
            for position in pp.POSITION_ORDER:
                C.safe(lambda p=position: _orient(p, sid), None)
            qp = QueryParams({"season": str(sid)})
            C.safe(lambda qp=qp: _cached("compare", qp, compare_payload), None)
            C.safe(lambda qp=qp: _cached("pool", qp, pool_payload), None)
        _scout_rows()
    except Exception:                                           # noqa: BLE001
        log.warning("compare warm-up failed", exc_info=True)
    import gc
    gc.collect()
    gc.freeze()
    logging.getLogger("lofc.web.warmup").warning("compare warm-up done in %.0f s",
                                                 time.perf_counter() - t0)


def mount(app, render, shell) -> None:
    """Register the API and the page shell. Called before the generic page loop."""
    app.include_router(router)
    from lofc.core import webcache
    # re-run after any data change (webcache.rewarm_on_change), not only at start-up
    webcache.register_warmup("compare", lambda: warm_compare())

    def warm() -> None:
        # After the Players and card warm-ups, never beside them (one heavy job at a time).
        def run() -> None:
            from lofc.web.api import players as players_api
            players_api.PLAYERS_WARM.wait(timeout=900)
            time.sleep(1)
            for _ in range(900):
                if not any(t.name == "lofc-card-warmup" and t.is_alive()
                           for t in threading.enumerate()):
                    break
                time.sleep(1)
            warm_compare()
        threading.Thread(target=run, name="lofc-compare-warmup", daemon=True).start()
    app.router.on_startup.append(warm)

    @app.get("/compare", response_class=HTMLResponse, name="page_compare")
    async def compare_page(request: Request, user: WebUser = Depends(current_user)):
        from lofc.web import pages
        return render(request, "compare.html", **shell(request, user, "compare",
                                                       page=pages.PAGES["compare"]))
