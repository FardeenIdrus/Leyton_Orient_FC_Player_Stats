"""The Players page: JSON endpoints + the page shell. All numbers come from
`lofc.core.players_pool` (the same function Streamlit calls); this module only turns query
parameters into a request and the result into JSON.

    GET /players                    page shell (replaces the placeholder)
    GET /api/players/options        filter choices + defaults (+ help texts)
    GET /api/players/metrics        metric-filter sliders for a season/position/Rank as
    GET /api/players                the ranked list (rows, captions, not-ranked)
    GET /api/players.csv            the same list as CSV ("exactly what is on screen")
    GET /api/players/search?q=      every position and league this season
    GET /api/players/wage           wage slider <-> £ box conversion
"""

from __future__ import annotations

import collections
import dataclasses
import threading
import time

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, Response

from lofc.config import settings
from lofc.core import players_pool as pp
from lofc.core import webcache
from lofc.dashboard import loaders as L
from lofc.dashboard import seasons as S
from lofc.model import club_framework as cf
from lofc.model.scorecard import MIN_PEERS_FOR_RANKING
from lofc.web.security import WebUser, current_user

router = APIRouter()

_TRUE = {"1", "true", "on", "yes"}


def _flag(v: str | None) -> bool:
    return (v or "").strip().lower() in _TRUE


def _num(v: str | None, lo: float, hi: float, default: float | None) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if x != x:
        return default
    return min(hi, max(lo, x))


class Query:
    """Query parameters -> a validated list request. Anything unknown or out of range falls back
    to the default (a stale URL must still open a page, never a 422)."""

    def __init__(self, params) -> None:
        g = params.get
        seasons = L.available_seasons()
        try:
            season = int(g("season"))
        except (TypeError, ValueError):
            season = pp.default_season(seasons)
        self.season = season if season in seasons else pp.default_season(seasons)
        pos = g("position")
        self.position = pos if pos in pp.POSITION_ORDER else pp.DEFAULT_POSITION
        arche = g("rank_as") or cf.DEFAULT_ARCHETYPE
        self.archetype = arche if arche in cf.archetypes_for(self.position) else cf.DEFAULT_ARCHETYPE
        all_leagues = L.league_names()
        chosen = [x for x in params.getlist("leagues") if x in all_leagues]
        # Every league selected = no league filter (the shared-filters rule on Squads too).
        self.leagues = tuple(chosen) if chosen and set(chosen) < set(all_leagues) else ()
        top = pp.minutes_bounds()["max"]
        self.min_minutes = int(_num(g("min_minutes"), 450, top, 450))
        self.max_age = int(_num(g("max_age"), 18, 40, 40))
        foot = g("foot")
        self.foot = foot if foot in pp.FOOT_CHOICES else "Any"
        c = g("contract")
        self.contract = c if c in S.CONTRACT_HORIZONS else S.DEFAULT_CONTRACT_HORIZON
        loan = g("loan")
        self.loan = loan if loan in S.LOAN_FILTERS else S.LOAN_ANY
        st = g("style") or pp.ALL_STYLES
        self.style = st if st in pp.styles_by_position()[self.position] else pp.ALL_STYLES
        self.strong_only = _flag(g("strong_only")) and self.style != pp.ALL_STYLES
        self.money = _flag(g("money"))
        self.budget = _num(g("budget"), 0, 150, None)
        self.wage = _num(g("wage"), 0, 200_000, None)
        self.wage_x = _num(g("wage_x"), 0.5, 25, None)
        self.assessed = _flag(g("assessed"))
        self.signed_only = _flag(g("signed_only")) and self.assessed
        sg = g("signable")
        self.signable = None if sg in (None, "") else _flag(sg)
        self.sort = g("sort") or None
        self.descending = (g("dir") or "desc").lower() != "asc"
        self.pct = {k[4:]: float(v) for k, v in params.items()
                    if k.startswith("pct_") and _num(v, 0, 100, None) is not None}
        self.raw = {k[4:]: float(v) for k, v in params.items()
                    if k.startswith("raw_") and _num(v, -1e9, 1e9, None) is not None}
        self.money_inputs = pp.resolve_money(self.money, self.position, self.budget,
                                             self.wage, self.wage_x)

    def filters(self) -> pp.PoolFilters:
        m = self.money_inputs
        return pp.PoolFilters(
            season_id=self.season, position=self.position, archetype=self.archetype,
            min_minutes=self.min_minutes, max_age=self.max_age, leagues=self.leagues,
            contract_horizon=self.contract, loan=self.loan, foot=self.foot, style=self.style,
            strong_only=self.strong_only, budget_eur=m["budget_eur"],
            wage_multiplier=m["wage_multiplier"])

    def request(self) -> pp.ListRequest:
        return pp.ListRequest(filters=self.filters(), show_money=self.money, pct=self.pct,
                              raw=self.raw, assessed=self.assessed, signed_only=self.signed_only,
                              signable=self.signable, sort=self.sort, descending=self.descending)


# The pool only depends on the sidebar-style filters, so moving a metric slider, toggling the
# assessed ranking or sorting reuses it. Keyed on the data version so a pipeline write
# invalidates it; a few entries only (each holds one season's candidate frame).
_pool_cache: "collections.OrderedDict[tuple, pp.PoolResult]" = collections.OrderedDict()
_pool_lock = threading.Lock()
_POOL_CACHE_SIZE = 48


def _slim(res: pp.PoolResult) -> pp.PoolResult:
    """What the API keeps: the page never reads the season-wide candidate/search frames, so
    they are dropped from the cache entry (about 5 MB each otherwise)."""
    return dataclasses.replace(res, candidates=res.candidates.iloc[0:0],
                               search_index=res.search_index.iloc[0:0],
                               ranking=res.ranking.iloc[0:0])


def cached_pool(f: pp.PoolFilters) -> pp.PoolResult:
    key = (L.data_version(with_scorecards=True), f)
    with _pool_lock:
        hit = _pool_cache.get(key)
        if hit is not None:
            _pool_cache.move_to_end(key)
            return hit
    res = _slim(pp.build_pool(f, with_search_index=False))
    with _pool_lock:
        _pool_cache[key] = res
        while len(_pool_cache) > _POOL_CACHE_SIZE:
            _pool_cache.popitem(last=False)
    return res


PLAYERS_WARM = threading.Event()        # set when the Players warm-up has finished


def warm_players() -> None:
    """Fill the pool and slider caches for every season x position (and the Full Back / Winger
    archetypes), live season first -- the same order the loaders are warmed in."""
    options_payload()
    seasons = sorted(L.available_seasons(), reverse=True)
    for sid in seasons:
        for position in pp.POSITION_ORDER:
            for archetype in cf.archetypes_for(position):
                cached_pool(pp.PoolFilters(season_id=sid, position=position, archetype=archetype))
                pp.metric_filter_spec(sid, position, archetype)
            # the list itself once (its first build also pays one-off imports)
            from starlette.datastructures import QueryParams
            list_payload(Query(QueryParams({"season": str(sid), "position": position})))


def _plural(position: str) -> str:
    return f"{position}s"


def _scope(q: Query) -> str:
    n = len(q.leagues)
    return "All leagues" if not n else q.leagues[0] if n == 1 else f"{n} leagues"


def list_payload(q: Query) -> tuple[dict, pp.ListResult]:
    t0 = time.perf_counter()
    req = q.request()
    res = cached_pool(req.filters)
    lr = pp.build_list(req, res)
    f, m = req.filters, lr.meta
    notice = pp.season_notice(res, f)
    season_name = S.season_name_for(f.season_id)
    as_of = S.contract_data_date()
    about = []
    if as_of:
        about.append(f"Contract data as of **{as_of}** (Transfermarkt snapshot, original seven "
                     "leagues only).")
    about.append("**Rank as** (Full Back / Winger only) reranks on that archetype's Performance "
                 "metrics; the all-round composite stays alongside.")
    about.append(f"Ranked players need **450+ minutes** and at least **{MIN_PEERS_FOR_RANKING} "
                 "peers** in their league and position. The minutes floor never goes below 450.")
    withheld = pp.withheld_rows(res)
    mi = q.money_inputs
    payload = {
        "season": f.season_id, "season_name": season_name, "position": f.position,
        "title": _plural(f.position),
        "meta": f"{season_name} · {_scope(q)} · 450+ minutes",
        "notice": None if notice is None else {"level": notice[0], "text": notice[1]},
        "count_caption": m["count_caption"], "contract_caption": m["contract_caption"],
        "rank_caption": m["rank_caption"], "assessed_caption": m["assessed_caption"],
        "hidden": m["hidden"], "hidden_text": m["hidden_text"],
        "signable": m["signable"], "money_count": m["money_count"],
        "affordable_now": m.get("affordable_now"),
        "money": None if not q.money else {
            "budget": (5.0 if q.budget is None else q.budget), "wage": mi["wage_pounds"],
            "wage_x": mi["wage_x"], "ceiling": mi["ceiling"], "caption": mi["caption"],
            "note": "Affordable = both **Fee in budget** and **Wages in budget** are checked below."},
        "columns": pp.column_defs(lr), "rows": pp.row_dicts(lr),
        "sort": {"column": q.sort, "descending": q.descending} if q.sort else None,
        "not_ranked": {
            "sub": f"450+ minutes, but fewer than {MIN_PEERS_FOR_RANKING} rated in their league",
            "rows": withheld,
            "empty": f"No unranked {_plural(f.position)} in {season_name}."},
        "about": about,
        "ms": round((time.perf_counter() - t0) * 1000),
    }
    return payload, lr


def _query_of(request: Request) -> Query:
    return Query(request.query_params)


@router.get("/api/players/options")
async def options(user: WebUser = Depends(current_user)):
    def build():
        L.start_warmup_if_needed()
        return options_payload()
    return JSONResponse(await run_in_threadpool(build))


@webcache.versioned(maxsize=2)
def options_payload() -> dict:
    """Filter choices + help texts: the same for everyone until the data changes (it read a
    600 s scrape-date loader and the wage framework on every page load)."""
    seasons = pp.season_options()
    ceilings = {p: pp.prime_ceiling(p) for p in pp.POSITION_ORDER}
    return {
        "seasons": seasons, "default_season": pp.default_season([s["id"] for s in seasons]),
        "positions": pp.POSITION_ORDER, "default_position": pp.DEFAULT_POSITION,
        "leagues": L.league_names(), "archetypes": pp.archetypes_by_position(),
        "default_archetype": cf.DEFAULT_ARCHETYPE, "styles": pp.styles_by_position(),
        "contract": list(S.CONTRACT_HORIZONS), "loan": S.LOAN_FILTERS,
        "foot": pp.FOOT_CHOICES, "minutes": pp.minutes_bounds(),
        "max_age": {"min": 18, "max": 40, "default": 40},
        "budget": {"min": 0, "max": 150, "step": 0.5, "default": 5.0},
        "wage_x": {"min": 0.5, "max": 25, "step": 0.5, "default": 1.0},
        "wage_pounds": {"min": 0, "max": 200000, "step": 500},
        "ceilings": ceilings,
        "help": {
            "season": ("Players are scored and ranked within one season. Opens on the season "
                       "being played; earlier seasons stay available here."),
            "search": ("Not limited to the current Position filter. Choosing a result switches "
                       "the Position filter to his position and opens his profile."),
            "style": ("How he plays, not how well — measured from what he attempts and where "
                      "he plays, against the same position, league and season."),
            "strong_only": "Off: includes players who lean to the style.",
            "rank_as": ("Scores Performance on that type of player's metrics; the all-round "
                        "composite stays alongside."),
            "minutes": "450 = the minimum sample to be ranked; per-90 numbers below that are noise.",
            "max_age": "Cap the age to match the signing horizon, e.g. 28 if resale value matters.",
            "contract": ("A 'summer' horizon keeps players still under contract whose deal "
                         "ends by that 30 June. Transfermarkt dates, largely EFL-only; players "
                         "with no known date are hidden and counted on the list."),
            "loan": pp.loan_help(),
            "foot": "Left/Right includes two-footed players. Only known feet are shown when set.",
            "money": ("Adds market value, modelled wages, undervaluation and a 'signable' "
                      "filter. Modelled estimates; never in the ranking."),
            "wage_x": ("1× = Leyton Orient's modelled weekly-wage ceiling for each position "
                       "and age band (modelled estimates)."),
            "wage_pounds": "Weekly wage cap for a prime-age player in this position.",
            "assessed": ("Ranks on Performance + Physical + Psychological + Medical Risk (86% "
                         "of the framework's weight; the data-only rating is 64%). Only players "
                         "with BOTH human dimensions assessed."),
            "signed_only": "Only signed-off assessments (an unsigned one still scores).",
        },
    }


@router.get("/api/players/metrics")
async def metrics(request: Request, user: WebUser = Depends(current_user)):
    q = _query_of(request)
    spec = await run_in_threadpool(pp.metric_filter_spec, q.season, q.position, q.archetype)
    return JSONResponse(spec)


@router.get("/api/players/wage")
async def wage(request: Request, user: WebUser = Depends(current_user)):
    """Slider <-> £ box. `x` (slider multiple) -> pounds, or `gbp` -> slider position."""
    pos = request.query_params.get("position")
    pos = pos if pos in pp.POSITION_ORDER else pp.DEFAULT_POSITION
    ceiling = await run_in_threadpool(pp.prime_ceiling, pos)
    x = _num(request.query_params.get("x"), 0.5, 25, None)
    gbp = _num(request.query_params.get("gbp"), 0, 200_000, None)
    if gbp is None:
        gbp = pp.wage_pounds_from_slider(x if x is not None else 1.0, ceiling)
    return {"wage": int(gbp), "wage_x": pp.wage_slider_from_pounds(gbp, ceiling),
            "ceiling": ceiling, "caption": await run_in_threadpool(
                pp.money_caption, pos, gbp / ceiling)}


# Whole answers, keyed by the exact query: back/forward and toggling a sort or switch on and
# off ask for the same list again. Keyed on `web_data_version`, which also tracks the scout
# reports (Scouts column) and the scout assessments (scout-verified ranking), so a saved report
# or assessment shows within ~30 s, as the 60 s loaders it replaces did.
_answers: "collections.OrderedDict[tuple, bytes]" = collections.OrderedDict()
_ANSWER_CACHE_SIZE = 64


def answer_key(params) -> tuple:
    return (L.web_data_version(), tuple(sorted(params.multi_items())))


def _answer(q: Query, key: tuple) -> bytes:
    """The list as the JSON body, kept as ONE bytes object: a cached dict of ~1,700 rows is
    ~50,000 Python objects, which every full garbage collection then walks (measured
    2026-11-09: 0.3-0.7 s pauses on random requests with 64 answers cached)."""
    payload, _ = list_payload(q)
    body = JSONResponse(payload).body
    with _pool_lock:
        _answers[key] = body
        while len(_answers) > _ANSWER_CACHE_SIZE:
            _answers.popitem(last=False)
    return body


@router.get("/api/players")
async def players(request: Request, user: WebUser = Depends(current_user)):
    q = _query_of(request)
    key = answer_key(request.query_params)
    with _pool_lock:
        hit = _answers.get(key)
        if hit is not None:
            _answers.move_to_end(key)
    if hit is None:
        hit = await run_in_threadpool(_answer, q, key)
    return Response(hit, media_type="application/json")


@router.get("/api/players.csv")
async def players_csv(request: Request, user: WebUser = Depends(current_user)):
    q = _query_of(request)

    def build():
        _, lr = list_payload(q)
        return pp.csv_bytes(lr), pp.csv_filename(q.position)
    data, name = await run_in_threadpool(build)
    return Response(data, media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/api/players/search")
async def search(request: Request, user: WebUser = Depends(current_user)):
    q = _query_of(request)
    text = (request.query_params.get("q") or "").strip()
    if not text:
        return JSONResponse({"results": []})
    results = await run_in_threadpool(pp.search, q.season, text)
    return JSONResponse({"results": results})


def mount(app, render, shell) -> None:
    """Register the API and the page shell. Called before the generic page loop, so this
    route wins over the "Being rebuilt" placeholder for /players."""
    app.include_router(router)
    from lofc.core import webcache
    # re-run after any data change (webcache.rewarm_on_change), not only at start-up
    webcache.register_warmup("players", lambda: warm_players())

    def warm() -> None:
        # Same background warm-up Streamlit starts (the loaders), then this page's own: the
        # default pool for every season and position, and the metric-slider ranges. The first
        # user after a restart should not wait for the cold loads. Non-blocking; never raises.
        try:
            thread = L.start_warmup_if_needed()
        except Exception:                                   # noqa: BLE001
            PLAYERS_WARM.set()
            return

        def run() -> None:
            import logging
            t0 = time.perf_counter()
            try:
                if thread is not None:
                    thread.join()
                warm_players()
            except Exception:                               # noqa: BLE001
                pass
            finally:
                PLAYERS_WARM.set()
                logging.getLogger("lofc.web.warmup").warning(
                    "loaders + players warm-up done in %.0f s", time.perf_counter() - t0)
        threading.Thread(target=run, name="lofc-players-warm", daemon=True).start()
    app.router.on_startup.append(warm)

    @app.get("/players", response_class=HTMLResponse, name="page_players")
    async def players_page(request: Request, user: WebUser = Depends(current_user)):
        from lofc.web import pages
        return render(request, "players.html", **shell(request, user, "players",
                                                       page=pages.PAGES["players"]))
