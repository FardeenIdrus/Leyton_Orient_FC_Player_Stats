"""Leyton Orient recruitment dashboard (Streamlit) — the entry point.

This module owns only the page setup, the sidebar filters and the tab wiring; everything
else lives in a focused module beside it:

    theme      brand colours, page CSS, header
    labels     metric names, provenance, the glossary text
    charts     the Plotly figure builders
    seasons    season identity + contract-expiry horizons
    loaders    every cached database read
    controls   the synced sidebar widgets
    tabs/      one module per tab (players, compare, watchlist, player_types,
               physical, glossary, methodology)

Dependencies run one way — theme/labels -> charts -> loaders -> controls -> tabs -> app —
so the layers stay free of import cycles.

Run via docker compose (the `dashboard` service) at http://localhost:8501.
"""

from __future__ import annotations

import streamlit as st

from lofc.config import settings
from lofc.constrain.filters import apply_gates
from lofc.dashboard.controls import synced_budget, synced_min_minutes, synced_wage_budget
from lofc.dashboard.loaders import (
    available_seasons, league_names, load_candidates, load_metric_values, load_percentiles,
    load_scorecards, load_scorecards_archetype, load_wage_framework, max_minutes)
from lofc.dashboard.seasons import (
    CONTRACT_HORIZONS, DEFAULT_CONTRACT_HORIZON, contract_mask, season_name_for)
from lofc.dashboard.tabs.compare import _compare
from lofc.dashboard.tabs.glossary import _glossary
from lofc.dashboard.tabs.methodology import _methodology
from lofc.dashboard.tabs.physical import _physical
from lofc.dashboard.tabs.player_types import _player_types
from lofc.dashboard.tabs.players import _kpi_strip, _players
from lofc.dashboard.tabs.watchlist import _watchlist
from lofc.dashboard.theme import LOGO, header, style
from lofc.model import club_framework as cf
from lofc.model.score import POSITION_ROLE, ROLE_METRICS, _successor_metrics


def role_metrics_for(position: str) -> list[str]:
    """The chart/profile metric list for a position, mapped to Impect successors when the
    platform is in Impect-only mode (so the EFL charts don't reference now-blank StatsBomb
    metrics like tackles/interceptions)."""
    ms = list(ROLE_METRICS[POSITION_ROLE[position]])
    return _successor_metrics(ms) if settings.impect_only else ms

POSITION_ORDER = ["Goalkeeper", "Centre Back", "Full Back", "Defensive Mid",
                  "Central Mid", "Winger", "Attacking Mid", "Centre Forward"]

def main() -> None:
    st.set_page_config(page_title="LOFC Recruitment Intelligence",
                       page_icon=str(LOGO) if LOGO.exists() else None,
                       layout="wide", initial_sidebar_state="expanded")
    style()
    header()

    st.sidebar.header("Filters")
    seasons = available_seasons()
    season_id = st.sidebar.selectbox(
        "Season", seasons, format_func=season_name_for,
        help="Players are scored and ranked within one season. The latest season is the "
             "default; earlier seasons stay fully available here (and power the trajectory "
             "chart). SkillCorner physical data exists for 2025/26 only.")
    position = st.sidebar.selectbox("Position", POSITION_ORDER,
                                    index=POSITION_ORDER.index("Centre Forward"))
    # Archetype lens (Full Back / Winger only): rank players AS a specific type. Default
    # "All Metrics" leaves the all-round composite as the ranking; the all-round score stays
    # visible alongside whichever archetype is chosen.
    archetype_options = cf.archetypes_for(position)
    archetype = cf.DEFAULT_ARCHETYPE
    if len(archetype_options) > 1:
        archetype = st.sidebar.selectbox(
            "Archetype", archetype_options,
            help="Rank players as a specific archetype for this position. The Performance "
                 "dimension is then scored on that archetype's metrics; the all-round composite "
                 "stays visible alongside. 'All Metrics' is the full-profile default.")
    min_minutes = synced_min_minutes(max(max_minutes(), 900))
    max_age = st.sidebar.slider(
        "Maximum age", 18, 40, 40,
        help="Veterans dominate raw bargain lists: the market floor-values older players regardless "
             "of current output (little resale value, short horizon), so their output looks underpriced. "
             "Cap the age to match the signing horizon — e.g. 28 if resale value matters.")
    league_options = league_names()
    chosen_leagues = st.sidebar.multiselect("Leagues", league_options, default=league_options)
    contract_horizon = st.sidebar.selectbox(
        "Contract expiry", list(CONTRACT_HORIZONS),
        index=list(CONTRACT_HORIZONS).index(DEFAULT_CONTRACT_HORIZON),
        help="The free-transfer / cut-price market. A 'summer' horizon keeps players still under "
             "contract today whose deal ends by that 30 June — English contracts effectively all "
             "expire in June, so there is no separate January option: a player expiring in summer "
             "is inside his final six months from that January, which the 'Months left' column "
             "shows (6 or fewer). Contract dates come from the Transfermarkt scrape and are largely "
             "EFL-only; the number of players hidden for having no known date is shown on the "
             "Players tab.")
    foot_choice = st.sidebar.selectbox(
        "Preferred foot", ["Any", "Left", "Right"],
        help="Left/Right includes two-footed players. Only known feet are shown when set.")
    # Money is an opt-in secondary layer: the default view is 100% real football data
    # (composite + minutes + age). The market value/wage/affordability estimates are modelled
    # (soft) and only appear — as columns, tiles and a 'signable' filter — when this is on.
    show_money = st.sidebar.checkbox(
        "Show affordability (modelled)", value=False,
        help="Adds market value, modelled wages, undervaluation and a 'signable' filter. These "
             "are modelled estimates; they never affect the ranking, which stays on real football "
             "data (Performance + Physical).")
    # Option A: the transfer-budget and wage-ceiling controls belong to the money layer, so they
    # appear ONLY when affordability is on. With money off they'd be inert (they gate nothing in
    # the default view), so showing them would be misleading. Off = permissive defaults (no fee
    # cap, base wage ceiling), used only to compute flags nobody sees.
    if show_money:
        budget_eur = synced_budget()
        framework = load_wage_framework()
        position_ceilings = framework.query("position_group == @position")["weekly_wage_ceiling_gbp"]
        prime_ceiling = float(position_ceilings.max()) if not position_ceilings.empty else 6500.0
        wage_multiplier = synced_wage_budget(prime_ceiling)
        # Show the £/week cap this implies across the position's age bands, so it stays concrete.
        applied = position_ceilings * wage_multiplier
        if not applied.empty:
            st.sidebar.caption(f"≈ £{int(applied.min()):,}–£{int(applied.max()):,}/week across age bands for a "
                               f"{position} (the typed value is the prime-age cap; younger players scale down; modelled).")
    else:
        budget_eur = float("inf")   # no fee cap when money is off
        wage_multiplier = 1.0

    candidates = load_candidates(wage_multiplier, season_id)
    percentiles = load_percentiles(season_id)
    metric_values = load_metric_values(season_id)

    # An unknown age is kept, not silently dropped; the cap only excludes known-older players.
    age_ok = (candidates["age"] <= max_age) | candidates["age"].isna()
    candidates = candidates[age_ok]
    if chosen_leagues:
        candidates = candidates[candidates["league"].isin(chosen_leagues)]
    # Contract-expiry horizon. A player with NO known contract date cannot be judged, so he is
    # excluded — but we count him rather than dropping him silently: contract data is largely
    # EFL-only, so switching this on would otherwise look like "no Scottish/PL2 player is
    # expiring" when the truth is "we don't know". The count is surfaced on the Players tab.
    contract_unknown = 0
    mask = contract_mask(candidates["contract_until"], contract_horizon)
    if mask is not None:
        in_position = candidates["position_group"] == position
        contract_unknown = int((candidates["contract_until"].isna() & in_position).sum())
        candidates = candidates[mask]
    if foot_choice != "Any":
        candidates = candidates[candidates["foot"].isin([foot_choice.lower(), "both"])]
    pool = apply_gates(candidates[(candidates["position_group"] == position) &
                                  (candidates["minutes"] >= min_minutes)], budget_eur)
    # Phase 2: the club's objective composite (Performance + Physical, real data) is the
    # primary ranking — the invented Style-fit is retired. Merge the live scorecard in.
    keys3 = ["player_id", "competition_id", "season_id"]
    sc_cols = keys3 + ["objective_composite", "full_composite", "objective_weight_covered",
                       "performance_band", "physical_band", "veto", "below_min_composite"]
    # When an archetype lens is selected, rank by that archetype's composite but keep the
    # all-round composite visible alongside (the guardrail). "All Metrics" -> they are equal.
    all_round = load_scorecards(season_id)[keys3 + ["objective_composite"]].rename(
        columns={"objective_composite": "allround_composite"})
    ranking = (load_scorecards(season_id) if archetype == cf.DEFAULT_ARCHETYPE
               else load_scorecards_archetype(position, archetype, season_id))
    pool = pool.merge(ranking[sc_cols], on=keys3, how="left").merge(all_round, on=keys3, how="left")
    # Signable = affordable (fee + wage). The old on-profile/Style-fit gate is dropped: the
    # platform ranks everyone on the club composite and never excludes on a quality threshold.
    pool["qualifies"] = pool["affordable_fee"] & pool["affordable_wage"]
    pool = pool.sort_values("objective_composite", ascending=False, na_position="last").reset_index(drop=True)
    metrics = role_metrics_for(position)

    _kpi_strip(pool, season_name_for(season_id), season_id, show_money)
    (players_tab, compare_tab, watchlist_tab,
     types_tab, physical_tab, glossary_tab, method_tab) = st.tabs(
        ["Players", "Compare", "Watchlist", "Player types", "Physical", "Glossary", "Methodology"])
    _players(players_tab, pool, position, percentiles, metrics, metric_values, archetype, show_money,
             contract_horizon, contract_unknown)
    _compare(compare_tab, pool, position, archetype, season_id, show_money, metric_values)
    _watchlist(watchlist_tab)
    _player_types(types_tab, pool, percentiles, metrics, position)
    _physical(physical_tab)
    _glossary(glossary_tab)
    _methodology(method_tab, candidates, budget_eur, min_minutes)

    st.caption(f"Impect event data (+ SkillCorner physical), {season_name_for(season_id)} season. Player market values are "
               "real (Transfermarkt, EFL only — Scottish/PL2 have none, so those players are scouted on quality "
               "and style but can't be affordability-gated). Wages and the club identity profile are clearly-"
               "labelled modelled estimates, swappable for the club's real data with no code change.")


if __name__ == "__main__":
    main()
