"""The Players list, built from filters -- ONE source of truth for Streamlit and the web front end.

Lifted from `dashboard/app.py::main()` (the sidebar -> candidates -> pool steps) and
`dashboard/tabs/players.py::_players` (metric filters, assessed ranking, signable filter, the
ranked table). Streamlit's `main()` now calls `build_pool`; the web API calls `build_pool` and
`build_list`, so both show the same rows. Pure: inputs are a plain dataclass, outputs frames and
strings; the only I/O is the existing cached loaders (`lofc.dashboard.loaders`).

Rules kept from the Streamlit code (do not change one without the other):
  * `objective_composite` is the ranking; scout input never touches it.
  * A pool below MIN_PEERS_FOR_RANKING is withheld, never shown as a rating.
  * The step order matters (age -> leagues -> contract -> foot -> position/minutes -> scorecard
    -> loans -> loan filter -> peers -> styles -> current club -> thin pools -> sort).
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, field

import pandas as pd

from lofc.config import settings
from lofc.constrain.filters import RANK_COLUMN, apply_gates
from lofc.dashboard import loaders as L
from lofc.dashboard import metric_filters
from lofc.dashboard import seasons as S
from lofc.dashboard.search import build_search_index, filter_labels
from lofc.model import club_framework as cf
from lofc.model import styles as styles_mod
from lofc.model.scorecard import MIN_PEERS_FOR_RANKING, peer_pool_sizes, with_peer_counts

POSITION_ORDER = ["Goalkeeper", "Centre Back", "Full Back", "Defensive Mid",
                  "Central Mid", "Winger", "Attacking Mid", "Centre Forward"]
DEFAULT_POSITION = "Centre Forward"
FOOT_CHOICES = ["Any", "Left", "Right"]
ALL_STYLES = "All styles"
KEYS3 = ["player_id", "competition_id", "season_id"]
DEFAULT_PRIME_CEILING = 6500.0     # Streamlit's fallback when a position has no wage ceiling
RATING_COLUMNS = ("Composite", "All-round", "Performance", "Physical")


@dataclass(frozen=True)
class PoolFilters:
    """Every sidebar filter that shapes the pool (Streamlit's widgets, one field each)."""
    season_id: int
    position: str = DEFAULT_POSITION
    archetype: str = cf.DEFAULT_ARCHETYPE
    min_minutes: int = 450
    max_age: int = 40                 # 40 = no cap (unknown ages are always kept)
    leagues: tuple[str, ...] = ()     # empty = no league filter
    contract_horizon: str = S.DEFAULT_CONTRACT_HORIZON
    loan: str = S.LOAN_ANY
    foot: str = "Any"
    style: str = ALL_STYLES
    strong_only: bool = False
    budget_eur: float = float("inf")  # no fee cap when money is off
    wage_multiplier: float = 1.0


@dataclass
class PoolResult:
    pool: pd.DataFrame               # ranked, sorted by objective_composite, thin pools removed
    withheld: pd.DataFrame           # player_name, team_name, league of the withheld
    contract_unknown: int            # no known contract date (only counted under a contract filter)
    candidates: pd.DataFrame         # after age/league/contract/foot, before position/minutes
    search_index: pd.DataFrame       # season-wide, built BEFORE any filter
    ranking: pd.DataFrame            # the season's full scorecard set for the archetype


@functools.lru_cache(maxsize=32)
def _scorecards_for(version: str, season_id: int, position: str, archetype: str) -> pd.DataFrame:
    return (L.load_scorecards(season_id) if archetype == cf.DEFAULT_ARCHETYPE
            else L.load_scorecards_archetype(position, archetype, season_id))


def scorecards(season_id: int, position: str, archetype: str) -> pd.DataFrame:
    """The season's scorecards for an archetype (callers never mutate the frame). Kept per data
    version -- the scorecard table is part of the version, so a saved assessment still shows
    within ~30 s -- instead of recomputed whenever the loaders' 60 s TTL lapses: that rebuild
    is a 1-2 s stall for whoever clicks next."""
    # the all-metrics frame does not depend on the position: one cache entry per season
    position = "" if archetype == cf.DEFAULT_ARCHETYPE else position
    return _scorecards_for(L.data_version(with_scorecards=True), int(season_id), position, archetype)


def build_pool(f: PoolFilters, with_search_index: bool = True) -> PoolResult:
    """The sidebar's pool for one season/position -- the steps `app.py::main()` used to run
    inline, in the same order. `with_search_index=False` skips the season-wide search index
    (a third of the cost) for callers that never read it; the web API builds it separately."""
    # The wage multiplier only scales one column (`build_candidates`: wage_ceiling_gbp =
    # weekly_wage_ceiling_gbp * multiplier), but `load_candidates(m)` rebuilds the whole
    # all-season frame for every new m (about 7 s each time the wage slider moves). Take the
    # cached m=1 frame and apply the same multiplication; tests/test_core_players_pool.py
    # proves the result is identical to `load_candidates(m)`.
    candidates = L.load_candidates(1.0, f.season_id)
    if f.wage_multiplier != 1.0:
        candidates = candidates.assign(
            wage_ceiling_gbp=candidates["weekly_wage_ceiling_gbp"] * f.wage_multiplier)
    # The global player search's universe: every position, every league, for this season --
    # built BEFORE any filter narrows `candidates`, so the search never depends on the filters.
    search_index = build_search_index(candidates) if with_search_index else candidates.iloc[0:0]

    # An unknown age is kept, not silently dropped; the cap only excludes known-older players.
    age_ok = (candidates["age"] <= f.max_age) | candidates["age"].isna()
    candidates = candidates[age_ok]
    if f.leagues:
        candidates = candidates[candidates["league"].isin(f.leagues)]
    # A player with NO known contract date cannot be judged under a contract filter, so he is
    # excluded -- but counted, so "no Scottish player is expiring" is never confused with
    # "we do not know".
    contract_unknown = 0
    mask = S.contract_mask(candidates["contract_until"], f.contract_horizon)
    if mask is not None:
        in_position = candidates["position_group"] == f.position
        contract_unknown = int((candidates["contract_until"].isna() & in_position).sum())
        candidates = candidates[mask]
    if f.foot != "Any":
        candidates = candidates[candidates["foot"].isin([f.foot.lower(), "both"])]
    pool = apply_gates(candidates[(candidates["position_group"] == f.position) &
                                  (candidates["minutes"] >= f.min_minutes)], f.budget_eur)
    # The club's objective composite (Performance + Physical, real data) is the ranking. All
    # six dimension bands travel with the pool: the `veto` flag can trip on any of them and the
    # profile's advisory names which.
    sc_cols = KEYS3 + ["objective_composite", "full_composite", "objective_weight_covered",
                       "performance_band", "physical_band", "financial_band", "resale_band",
                       "psychological_band", "medical_band", "veto", "below_min_composite"]
    # With an archetype lens, rank by that archetype's composite but keep the all-round one
    # visible alongside (the guardrail). "All Metrics" -> they are equal.
    all_round = scorecards(f.season_id, f.position, cf.DEFAULT_ARCHETYPE)[
        KEYS3 + ["objective_composite"]].rename(columns={"objective_composite": "allround_composite"})
    ranking = scorecards(f.season_id, f.position, f.archetype)
    pool = pool.merge(ranking[sc_cols], on=KEYS3, how="left").merge(all_round, on=KEYS3, how="left")
    # Loan status joined on player_id only: a loan is a fact about the player TODAY, not about
    # the season being ranked.
    pool = pool.merge(L.load_loan_status(), on="player_id", how="left")
    pool["on_loan"] = pool["on_loan"].fillna(False)
    loan_filter = S.loan_mask(pool["on_loan"], pool["loan_ends"], f.loan)
    if loan_filter is not None:
        pool = pool[loan_filter]
    pool["qualifies"] = pool["affordable_fee"] & pool["affordable_wage"]
    # Peer counts come from the season's FULL scorecard set (`ranking`), never from `pool`: a
    # peer group is a property of the data and must not shrink when a filter narrows the list.
    pool = with_peer_counts(pool, peer_pool_sizes(ranking))
    # Style labels joined LEFT, so a player without one is never dropped from the list.
    style = L.load_style_labels(f.season_id)
    if not style.empty:
        style_cols = KEYS3 + ["style_label", "tier", "strong_styles", "leans_styles"] + \
            [c for c in style.columns if c.startswith("fit.")]
        pool = pool.merge(style[style_cols], on=KEYS3, how="left")
        if f.style != ALL_STYLES:
            pool = pool[[styles_mod.has_style(r, f.style, f.strong_only)
                         for r in pool.to_dict("records")]]
    # Where he is now (Impect), for "Dundalk FC · now FC Portsmouth". LEFT join, display only.
    current = L.load_current_clubs()
    if not current.empty:
        pool = pool.merge(current, on="player_id", how="left")
    # A composite is a rank within its pool: below the floor it is not a weak ranking, it is
    # not a ranking at all (a player alone in his pool scores 4.90 by construction). Withheld,
    # not placed. NaN (no scorecard) counts as thin.
    thin = pool["peer_count"].isna() | (pool["peer_count"] < MIN_PEERS_FOR_RANKING)
    withheld = pool.loc[thin, ["player_name", "team_name", "league"]].copy()
    pool = pool[~thin]
    pool = pool.sort_values("objective_composite", ascending=False,
                            na_position="last").reset_index(drop=True)
    return PoolResult(pool=pool, withheld=withheld, contract_unknown=contract_unknown,
                      candidates=candidates, search_index=search_index, ranking=ranking)


# ---- money controls ------------------------------------------------------------------------

def position_ceilings(position: str) -> pd.Series:
    framework = L.load_wage_framework()
    return framework.query("position_group == @position")["weekly_wage_ceiling_gbp"]


def prime_ceiling(position: str) -> float:
    """The position's prime-age weekly wage ceiling (£), Streamlit's fallback when unknown."""
    c = position_ceilings(position)
    return float(c.max()) if not c.empty else DEFAULT_PRIME_CEILING


def wage_pounds_from_slider(multiple: float, ceiling: float) -> int:
    """Slider moved: the £ box shows the wage that multiple implies for a prime-age player."""
    return int(round(multiple * ceiling))


def wage_slider_from_pounds(pounds: float, ceiling: float) -> float:
    """£ box typed: the slider follows, clamped to 0.5-25 and snapped to its 0.5 step."""
    implied = min(25.0, max(0.5, pounds / ceiling))
    return round(implied / 0.5) * 0.5


def money_caption(position: str, wage_multiplier: float) -> str | None:
    applied = position_ceilings(position) * wage_multiplier
    if applied.empty:
        return None
    return (f"≈ £{int(applied.min()):,}–£{int(applied.max()):,}/week across age bands for a "
            f"{position} (the typed value is the prime-age cap; younger players scale down; "
            "modelled).")


def resolve_money(show_money: bool, position: str, budget_m: float | None,
                  wage_pounds: float | None = None, wage_x: float | None = None) -> dict:
    """Budget in euros and the wage multiplier the gate applies, as the sidebar computes them.
    Money off = permissive defaults (no fee cap, base ceiling). The £ box wins over the slider
    (typed figures are used exactly); a slider move is converted to £ first."""
    if not show_money:
        return dict(budget_eur=float("inf"), wage_multiplier=1.0, wage_pounds=None,
                    wage_x=None, ceiling=None, caption=None)
    ceiling = prime_ceiling(position)
    budget = 5.0 if budget_m is None else float(budget_m)
    if wage_pounds is None:
        wage_pounds = (wage_pounds_from_slider(wage_x, ceiling) if wage_x is not None
                       else int(round(ceiling)))
    wage_pounds = int(min(200_000, max(0, wage_pounds)))
    multiplier = wage_pounds / ceiling
    return dict(budget_eur=budget * 1_000_000, wage_multiplier=multiplier,
                wage_pounds=wage_pounds, wage_x=wage_slider_from_pounds(wage_pounds, ceiling),
                ceiling=ceiling, caption=money_caption(position, multiplier))


# ---- filter options ------------------------------------------------------------------------

def styles_by_position() -> dict[str, list[str]]:
    return {p: styles_mod.style_options(p) for p in POSITION_ORDER}


def archetypes_by_position() -> dict[str, list[str]]:
    return {p: cf.archetypes_for(p) for p in POSITION_ORDER}


def default_season(seasons: list[int]) -> int:
    return S.default_season_id(seasons, settings.live_season_id)


def season_options() -> list[dict]:
    return [{"id": int(s), "name": S.season_name_for(s)} for s in L.available_seasons()]


def minutes_bounds() -> dict:
    return {"min": 450, "max": int(max(L.max_minutes(), 900)), "step": 10, "default": 450}


def loan_help() -> str:
    as_of = S.loan_data_date()
    return ("Loan status is current, not the selected season — the 'On loan at' column shows "
            "where he is now." + (f" Loan data as of {as_of}, updated manually." if as_of
                                  else " No loan data loaded."))


# ---- metric filters (Players body "Metric filters" fold-out) -----------------------------------

@functools.lru_cache(maxsize=32)
def _raw_for(version: str, season_id: int, position: str) -> pd.DataFrame:
    """Raw metric values for this season's players in this position -- the slider bounds come
    from the WHOLE season/position, not the filtered pool, so a slider never jumps when another
    filter changes. `version` keys the cache to the data version."""
    pcts = L.load_scorecard_percentiles(season_id)
    in_position = pcts.loc[pcts["position_group"] == position, ["player_id", "competition_id"]]
    return L.load_metric_values(season_id).merge(
        in_position, on=["player_id", "competition_id"], how="inner")


def _raw(season_id: int, position: str) -> pd.DataFrame:
    return _raw_for(L.data_version(with_scorecards=True), int(season_id), position)


def _physical_metrics(raw: pd.DataFrame, position: str) -> list[str]:
    return [m for m in metric_filters.PHYSICAL_SLIDERS.get(position, [])
            if m in raw.columns and raw[m].notna().any()]


def metric_filter_spec(season_id: int, position: str, archetype: str) -> dict:
    return _spec_for(L.data_version(with_scorecards=True), int(season_id), position, archetype)


@functools.lru_cache(maxsize=64)
def _spec_for(version: str, season_id: int, position: str, archetype: str) -> dict:
    """The sliders: physical raw values in tab groups (Min for higher-is-better, Max for the
    seconds metrics; range = season min-max for this position; resting value = the floor for
    Min, the ceiling for Max) and Performance minimum-percentile sliders."""
    raw = _raw(season_id, position)
    phys = _physical_metrics(raw, position)
    lower = set(metric_filters.LOWER_IS_BETTER_PHYSICAL)
    groups = []
    for group, metrics in metric_filters.PHYSICAL_GROUPS.items():
        sliders = []
        for m in metrics:
            if m not in phys:
                continue
            label, fmt = metric_filters.PHYSICAL_LABELS[m]
            lo, hi, step = metric_filters.slider_bounds(raw[m], fmt)
            is_max = m in lower
            sliders.append({"metric": m, "label": f"{'Max' if is_max else 'Min'} {label}",
                            "kind": "Max" if is_max else "Min", "min": lo, "max": hi,
                            "step": step, "rest": hi if is_max else lo,
                            "decimals": 2 if fmt.endswith("2f") else 1 if fmt.endswith("1f") else 0})
        if sliders:
            groups.append({"group": group, "sliders": sliders})
    from lofc.dashboard.labels import metric_label
    perf = [{"metric": m, "label": metric_label(m)}
            for m in metric_filters.performance_slider_metrics(position, archetype)]
    return {"physical": groups, "performance": perf}


def apply_metric_values(pool: pd.DataFrame, season_id: int, position: str, archetype: str,
                        pct: dict[str, float], raw_values: dict[str, float]
                        ) -> tuple[pd.DataFrame, int]:
    """Today's semantics: a Performance slider is active above 0; a physical slider is active
    only once it has moved off its resting value (floor for Min, ceiling for Max). Returns
    (filtered pool, how many were hidden for having no value on an active filter)."""
    if pool.empty:
        return pool, 0
    raw = _raw(season_id, position)
    phys = _physical_metrics(raw, position)
    lower = set(metric_filters.LOWER_IS_BETTER_PHYSICAL)
    perf = set(metric_filters.performance_slider_metrics(position, archetype))
    pct_mins = {m: float(v) for m, v in pct.items() if m in perf}
    raw_mins: dict[str, float] = {}
    raw_maxs: dict[str, float] = {}
    for m, v in raw_values.items():
        if m not in phys:
            continue
        lo, hi, _ = metric_filters.slider_bounds(raw[m], metric_filters.PHYSICAL_LABELS[m][1])
        is_max = m in lower
        if abs(float(v) - (hi if is_max else lo)) < 1e-9:
            continue                                  # resting value = inactive
        (raw_maxs if is_max else raw_mins)[m] = float(v)
    pcts = L.load_scorecard_percentiles(season_id)
    return metric_filters.apply_metric_filters(pool, pcts, raw, pct_mins, raw_mins, raw_maxs)


def hidden_text(unknown: int) -> str | None:
    return f"{unknown} hidden: no data for an active metric filter." if unknown else None


# ---- the ranked list --------------------------------------------------------------------------

@dataclass(frozen=True)
class ListRequest:
    filters: PoolFilters
    show_money: bool = False
    pct: dict = field(default_factory=dict)          # performance metric -> minimum percentile
    raw: dict = field(default_factory=dict)          # physical metric -> slider value
    assessed: bool = False                           # "Rank on scout-verified rating"
    signed_only: bool = False
    signable: bool | None = None                     # None = Streamlit's default (on if any qualify)
    sort: str | None = None                          # a column label; None = the ranking order
    descending: bool = True


@dataclass
class ListResult:
    pool: PoolResult
    table: pd.DataFrame              # one row per listed player, renamed like the Streamlit table
    columns: list[str]               # display order (Streamlit's `players_table_columns`)
    keys: pd.DataFrame               # ids per row (player_id, competition_id, season_id)
    meta: dict                       # captions and counts


def _contract_caption(f: PoolFilters, n: int, unknown: int) -> str | None:
    if not S.CONTRACT_HORIZONS.get(f.contract_horizon):
        return None
    if f.contract_horizon == S.CONTRACT_EXPIRED:
        line = (f"Contract filter: **{f.contract_horizon}** — {n} {f.position}s shown "
                "whose contract has already run out.")
    else:
        line = (f"Contract filter: **{f.contract_horizon}** — {n} {f.position}s shown, "
                f"still under contract today, expiring by {S.CONTRACT_HORIZONS[f.contract_horizon]}.")
    if unknown:
        line += f" **{unknown} hidden** (no known contract date)."
    return line


def season_notice(res: PoolResult, f: PoolFilters) -> tuple[str, str] | None:
    """The season banner (`seasons.ranking_notice`), from the pool BEFORE metric filters."""
    seasons = L.available_seasons()
    return S.ranking_notice(
        n_ranked=len(res.pool), withheld=res.withheld, season=S.season_name_for(f.season_id),
        complete_season=S.season_name_for(S.last_complete_season_id(seasons, settings.live_season_id)),
        position=f.position)


def build_list(req: ListRequest, res: PoolResult | None = None) -> ListResult:
    """Metric filters -> assessed ranking -> sort -> signable -> the displayed table, the steps
    `tabs/players.py::_players` ran inline. Formatting helpers are Streamlit's own."""
    from lofc.dashboard.tabs import players as pt
    from lofc.dashboard.formatting import numeric_or_dash
    from lofc.core import webcache
    from lofc.model import assessment_status

    f = req.filters
    res = res or build_pool(f)
    lens = f.archetype != cf.DEFAULT_ARCHETYPE
    position = f.position
    metric_values = L.load_metric_values(f.season_id)

    pool, unknown = apply_metric_values(res.pool, f.season_id, position, f.archetype,
                                        req.pct, req.raw)
    meta: dict = {"hidden": unknown, "hidden_text": hidden_text(unknown),
                  "contract_caption": _contract_caption(f, len(pool), res.contract_unknown),
                  "rank_caption": (f"Rank as **{f.archetype}** — the Composite is scored on this "
                                   "archetype's metrics; **All-round** shows the full-profile "
                                   "composite for context.") if lens else None,
                  "assessed_caption": None, "money_count": None}

    if req.assessed:
        # Match the loader the rest of the page uses: an archetype lens ranks on that
        # archetype's assessed composite.
        sc = scorecards(f.season_id, position, f.archetype)
        pool = pool.merge(sc[KEYS3 + ["assessed_composite"]], on=KEYS3, how="left")
        # the same frame as `load_assessment_status`, kept until an assessment changes
        pool = assessment_status.attach(pool, webcache.assessment_status(f.season_id))
        # Conflicted assessments have no composite; count them rather than hide them silently.
        conflicted = int((pool["assessment_status"] == assessment_status.CONFLICTED).sum())
        pool = pool[pool["assessed_composite"].notna()]
        rank_column = "assessed_composite"
        if req.signed_only:
            pool = pool[pool["assessment_status"] == assessment_status.SIGNED_OFF]
        if pool.empty:
            msg = ("No player has both dimensions assessed yet — the assessed ranking is empty "
                   "until a scout completes Psychological and Medical.")
        else:
            msg = (f"{len(pool)} players have both human dimensions assessed. This is a "
                   "different ranking from the default, not a filter on it.")
        if conflicted:
            msg += (f" **{conflicted} assessed player{'s' if conflicted != 1 else ''} not shown** "
                    "here — their assessments conflict, so nothing scores until someone signs "
                    "one off from the sign-off queue.")
        meta["assessed_caption"] = msg
    else:
        rank_column = RANK_COLUMN
    pool = pool.sort_values(rank_column, ascending=False, na_position="last").reset_index(drop=True)

    only_qualifying = False
    if req.show_money:
        qualifying = pool[pool["qualifies"]]
        fee_ok, wage_ok = int(pool["affordable_fee"].sum()), int(pool["affordable_wage"].sum())
        meta["count_caption"] = (f"**{len(pool)}** {position}s · **{fee_ok}** within the transfer "
                                 f"budget · **{wage_ok}** within the wage budget · "
                                 f"**{len(qualifying)}** affordable on both.")
        only_qualifying = (not qualifying.empty) if req.signable is None else bool(req.signable)
        meta["affordable_now"] = int(res.pool["qualifies"].sum())
        meta["money_count"] = {"total": len(pool), "fee": fee_ok, "wage": wage_ok,
                               "both": len(qualifying)}
        if only_qualifying and not qualifying.empty:
            pool = qualifying.reset_index(drop=True)
    else:
        meta["count_caption"] = f"**{len(pool)}** {position}s ranked."
    meta["signable"] = only_qualifying

    view = pool.copy().reset_index(drop=True)
    # "#" is the row's position in the list as currently filtered -- not a cross-league rank.
    view.insert(0, "#", range(1, len(view) + 1))
    view["Mins"] = view["minutes"].map(pt.whole_minutes)
    # Top speed = average of his 5 fastest matches (SkillCorner PSV-99 Top 5), raw km/h.
    speed = metric_values[["player_id", "competition_id", "top5_psv99_kmh"]].drop_duplicates(
        ["player_id", "competition_id"])
    view = view.merge(speed, on=["player_id", "competition_id"], how="left")
    view["Top speed"] = numeric_or_dash(view["top5_psv99_kmh"], "{:.1f}")
    view["Style"] = ([pt.style_pills(r) for r in view.to_dict("records")]
                     if "strong_styles" in view.columns else [[] for _ in range(len(view))])
    if {"loan_club", "parent_club"} <= set(view.columns):
        view["On loan at"] = pt.on_loan_at_column(view["loan_club"], view["parent_club"])
    # What the club's scouts concluded; blank = nobody watched him. Display only.
    consensus = webcache.scout_consensus()      # = consensus_by_player, kept per data version
    if not consensus.empty:
        view = view.merge(consensus[["player_id", "Scouts"]], on="player_id", how="left")
    else:
        view["Scouts"] = None
    view["Scouts"] = view["Scouts"].fillna("")
    if lens:
        view["All-round"] = view["allround_composite"].round(2)
    view["Age"] = numeric_or_dash(view["age"], "{:.1f}")
    if req.show_money:
        view["Market value"] = numeric_or_dash(view["market_value_eur"] / 1e6, "€{:.1f}m")
        view["Est. wage"] = numeric_or_dash(view["estimated_weekly_wage_gbp"] / 1000, "£{:.1f}k")
        view["Below fair value"] = numeric_or_dash(view["undervaluation_pct"] * 100, "{:.0f}%")

    table = view.assign(team_name=pt.club_column(view)).rename(columns={
        "player_name": "Player", "team_name": "Club", "league": "League",
        rank_column: "Composite", "performance_band": "Performance", "physical_band": "Physical",
        "affordable_fee": "Fee in budget", "affordable_wage": "Wages in budget"})
    loan_active = f.loan != S.LOAN_ANY
    columns = pt.players_table_columns(lens=lens, show_money=req.show_money,
                                       loan_column=loan_active and "On loan at" in view.columns)
    meta["composite_label"] = ("Scout-verified rating" if req.assessed
                               else f"Composite ({f.archetype})" if lens else "Composite")
    meta["composite_help"] = (
        "Performance + Physical + Psychological + Medical (1-5) — the assessed ranking, opt-in."
        if req.assessed else "The club's objective composite (1-5) — the ranking.")
    if req.sort and req.sort in columns and req.sort in table.columns and len(table):
        table = _sorted(table, req.sort, req.descending)
    return ListResult(pool=res, table=table, columns=columns,
                      keys=table[KEYS3].reset_index(drop=True), meta=meta)


# Columns whose displayed text is not what should order them (formatted strings, pill lists).
_SORT_SOURCE = {"Age": "age", "Mins": "minutes", "Top speed": "top5_psv99_kmh",
                "Market value": "market_value_eur", "Est. wage": "estimated_weekly_wage_gbp",
                "Below fair value": "undervaluation_pct"}


def _sorted(table: pd.DataFrame, column: str, descending: bool) -> pd.DataFrame:
    """Header-click sort. Orders by the underlying value (a "9.5" string would otherwise sort
    after "10.1"); blanks always go last; ties keep the ranking order. "#" is kept as it was
    (it is the ranking position, as when Streamlit's grid sorts a column)."""
    src = _SORT_SOURCE.get(column, column)
    key = table[src]
    if column == "Style":
        key = key.map(lambda v: ", ".join(v) if isinstance(v, list) else "")
    if pd.api.types.is_numeric_dtype(key) or pd.api.types.is_bool_dtype(key):
        key = pd.to_numeric(key, errors="coerce")
    else:
        key = key.map(lambda v: "" if v is None or (isinstance(v, float) and v != v)
                      else str(v).casefold())
        key = key.where(key != "", None)
    order = pd.DataFrame({"k": key, "i": range(len(table))})
    order = order.sort_values(["k", "i"], ascending=[not descending, True],
                              na_position="last", kind="stable")
    return table.iloc[order["i"].to_numpy()].reset_index(drop=True)


COLUMN_HELP = {
    "Age": "'—' = no known birth date or valuation.",
    "Style": ("How he plays, not how well: his best-fitting style, against players in the same "
              "position, league and season. \"(leans)\" = a weaker fit. \"No standout style\" = "
              "below average at every style for his position. Reference → How playing styles work."),
    "Mins": "Minutes played this season.",
    "All-round": "Full-profile composite (All Metrics), for context.",
    "Performance": "The club-framework Performance dimension (1-5).",
    "Physical": "The club-framework Physical dimension (1-5), where tracking exists.",
    "Top speed": "Average of his 5 fastest matches, km/h (SkillCorner PSV-99 Top 5).",
    "On loan at": ("Where he is playing THIS season, and who owns him. The Club column is the "
                   "season you are viewing."),
    "Market value": "Transfermarkt (modelled context). '—' = no known valuation.",
    "Est. wage": "Modelled weekly wage (£ thousands). '—' = no known valuation.",
    "Below fair value": "How far under fair value the market prices them. '—' = no known valuation.",
    "Fee in budget": "Transfer fee fits the budget.",
    "Wages in budget": "Modelled wage fits the ceiling.",
}


def column_defs(lr: ListResult) -> list[dict]:
    from lofc.dashboard.tabs.players import SCOUTS_HELP
    out = []
    for c in lr.columns:
        label, help_ = c, COLUMN_HELP.get(c)
        if c == "Composite":
            label, help_ = lr.meta["composite_label"], lr.meta["composite_help"]
        elif c == "Scouts":
            help_ = SCOUTS_HELP
        kind = ("rating" if c in RATING_COLUMNS else "style" if c == "Style"
                else "scouts" if c == "Scouts" else "bool" if c in ("Fee in budget", "Wages in budget")
                else "num" if c in ("#", "Age", "Mins", "Top speed", "Market value", "Est. wage",
                                    "Below fair value") else "text")
        out.append({"key": c, "label": label, "help": help_, "kind": kind})
    return out


def _clean(v):
    """JSON-safe cell: NaN/NA -> None, numpy scalars -> Python, lists kept."""
    if isinstance(v, (list, tuple)):
        return [str(i) for i in v]
    if v is None or v is pd.NA:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(v, "item"):
        v = v.item()
    return v


def _rating_text(v):
    v = _clean(v)
    if v is None:
        return None
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return None


def row_dicts(lr: ListResult) -> list[dict]:
    """Rows as the Streamlit table shows them: ratings as "x.xx" text (None = "—"), Age/Top
    speed/money already formatted, ids alongside for the link to the card. Built column by
    column: row-wise `.iloc` on this wide frame took 0.7 s for 1,200 rows."""
    t = lr.table
    cols = {c: [(_rating_text(v) if c in RATING_COLUMNS else _clean(v)) for v in t[c].tolist()]
            for c in lr.columns}
    ids = zip(t["player_id"].tolist(), t["competition_id"].tolist(), t["season_id"].tolist())
    return [{"id": [int(a), int(b), int(c)], "cells": {k: cols[k][i] for k in lr.columns}}
            for i, (a, b, c) in enumerate(ids)]


def csv_bytes(lr: ListResult) -> bytes:
    """"Saves exactly what is on screen": the displayed columns, "#" first, as Streamlit exports."""
    t = lr.table
    export = t[[c for c in lr.columns if c != "#"]].copy()
    export.insert(0, "#", t["#"])
    return export.to_csv(index=False).encode("utf-8")


def csv_filename(position: str) -> str:
    return f"lofc_players_{position.lower().replace(' ', '_')}.csv"


# ---- search ----------------------------------------------------------------------------------

@functools.lru_cache(maxsize=4)
def _search_index_for(version: str, season_id: int) -> pd.DataFrame:
    return build_search_index(L.load_candidates(1.0, season_id))


def search(season_id: int, query: str, limit: int = 30) -> list[dict]:
    """Players in this season matching `query` -- every position and league (the index is built
    before any filter), accent/case/punctuation-insensitive like the Streamlit box."""
    idx = _search_index_for(L.data_version(with_scorecards=True), int(season_id))
    labels = filter_labels(idx["label"].tolist(), query)[:limit]
    by_label = idx.drop_duplicates("label").set_index("label")
    out = []
    for label in labels:
        r = by_label.loc[label]
        out.append({"label": label, "player_id": int(r["player_id"]),
                    "competition_id": int(r["competition_id"]), "season_id": int(r["season_id"]),
                    "name": str(r["player_name"]), "position": str(r["position_group"]),
                    "league": None if pd.isna(r["league"]) else str(r["league"])})
    return out


def withheld_rows(res: PoolResult) -> list[dict]:
    w = res.withheld.assign(team_name=res.withheld["team_name"].fillna("Unknown club"),
                            league=res.withheld["league"].fillna("Unknown league"))
    w = w.sort_values(["player_name", "team_name"], kind="stable")
    return [{"name": r.player_name, "club": r.team_name, "league": r.league}
            for r in w.itertuples()]
