"""Leyton Orient recruitment dashboard (Streamlit) — the entry point.

This module owns only the page setup, the sidebar filters and the page wiring; everything
else lives in a focused module beside it:

    theme      brand colours, page CSS, header
    labels     metric names, provenance, the glossary text
    charts     the Plotly figure builders
    seasons    season identity + contract-expiry horizons
    loaders    every cached database read
    controls   the synced sidebar widgets
    session    the login gate, current-user session, the assess-page player carry
    tabs/      one module per page (players, compare, watchlist, assess, signoff,
               player_types, physical, glossary, methodology)

Dependencies run one way — theme/labels -> charts -> loaders -> controls -> session ->
tabs -> app — so the layers stay free of import cycles. `st.switch_page` needs a live
`st.Page` object, which only `app.py` builds (it is the one module that imports every tabs/
module); `session.register_pages`/`session.switch_to` let a tabs/ module navigate to a named
page without importing `app.py` back, which would cycle.

NAVIGATION (Part A of task 10): nine `st.tabs()` panes became nine `st.Page`s under
`st.navigation`. The login gate is unchanged in effect -- `main()` still returns immediately
after `require_login` yields no user, and that `return` happens BEFORE the sidebar filters,
BEFORE the pool is built, and BEFORE `st.navigation(...)` is even constructed, so an
unauthenticated visitor sees the sign-in form and literally nothing else: no page list, no
filters, no data. The sidebar filters stay a single source of truth: they are computed once
here, in `main()`, above `st.navigation(...).run()` -- never duplicated inside a page.

Run via docker compose (the `dashboard` service) at http://localhost:8501.
"""

from __future__ import annotations

import datetime

import streamlit as st

from lofc.config import settings
from lofc.constrain.filters import apply_gates
from lofc.dashboard.auth import can
from lofc.dashboard.controls import synced_budget, synced_min_minutes, synced_wage_budget
from lofc.dashboard.loaders import (
    available_seasons, get_engine, league_names, load_candidates, load_metric_values,
    load_percentiles, load_scorecards, load_scorecards_archetype, load_wage_framework,
    max_minutes, player_context_lookup, player_names)
from lofc.dashboard.seasons import (
    CONTRACT_HORIZONS, DEFAULT_CONTRACT_HORIZON, contract_mask, season_name_for)
from lofc.dashboard.session import (
    force_reload_after_logout, register_pages, require_login, restore_user, topbar_identity)
from lofc.dashboard.tabs import assess as assess_page_mod
from lofc.dashboard.tabs.compare import _compare
from lofc.dashboard.tabs.glossary import _glossary
from lofc.dashboard.tabs.methodology import _methodology
from lofc.dashboard.tabs.physical import _physical
from lofc.dashboard.tabs.player_types import _player_types
from lofc.dashboard.tabs.players import _kpi_strip, _players
from lofc.dashboard.tabs.signoff import render as _signoff
from lofc.dashboard.tabs.users import render as _users_render
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
    if force_reload_after_logout():
        return          # a hard reload is already on its way; nothing else should render

    # Peek at the session to know whether to draw the top-right identity in this same header
    # row -- but this is only a peek: it does NOT gate anything. `require_login` below is
    # still the sole gate, and it is what actually decides whether the rest of the page (the
    # sidebar filters, the pool, `st.navigation`) renders at all. A user mid-forced-password-
    # change is deliberately treated as "not yet in": no name shown until that is done.
    peeked = restore_user(st.session_state, datetime.datetime.now())
    show_identity = peeked is not None and not st.session_state.get("must_change_password")
    header((lambda: topbar_identity(peeked)) if show_identity else None)

    user = require_login(get_engine())
    if user is None:
        return          # the gate renders the form; nothing else on the page exists yet

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

    # A season that has player data but no scorecards yet (e.g. the current season, freshly
    # under way) must not read as a blank/broken page -- `ranking` degrades to a well-formed
    # empty frame (see `loaders._attach_scorecard_meta`) rather than raising, so say why here,
    # above every page, rather than leaving the recruiter looking at blank composite columns.
    if ranking.empty:
        st.info(f"**{season_name_for(season_id)} is under way, but no player has yet reached "
                "the 450-minute minimum needed to be ranked.** Scores will appear here once "
                "enough of the season has been played — try an earlier season in the meantime.")

    _kpi_strip(pool, season_name_for(season_id), season_id, show_money)

    # Each page below is a thin closure over this run's already-computed filter state (pool,
    # position, season_id, ...) -- the SAME shared filters every page reads, none re-queried
    # or re-widgeted per page. A page function receives `st.container()` in place of the
    # `st.tabs()` pane the tab modules were written against; a container is a drop-in context
    # manager for `with tab:`, so no tab module's internals needed to change for this. Page
    # order matches the pre-existing tab order exactly (Part A.5).
    engine = get_engine()

    def _players_page():
        _players(st.container(), pool, position, percentiles, metrics, metric_values,
                 archetype, show_money, contract_horizon, contract_unknown)

    def _compare_page():
        _compare(st.container(), pool, position, archetype, season_id, show_money, metric_values)

    def _watchlist_page():
        _watchlist(st.container())

    def _assess_page():
        assess_page_mod.page(engine, user, pool)

    def _signoff_page():
        with st.container():
            _signoff(engine, user, player_names(), player_context_lookup())

    def _player_types_page():
        _player_types(st.container(), pool, percentiles, metrics, position)

    def _physical_page():
        _physical(st.container())

    def _glossary_page():
        _glossary(st.container())

    def _methodology_page():
        _methodology(st.container(), candidates, budget_eur, min_minutes)

    def _users_page():
        with st.container():
            _users_render(engine, user)

    pages = {
        "players": st.Page(_players_page, title="Players", url_path="players", default=True),
        "compare": st.Page(_compare_page, title="Compare", url_path="compare"),
        "watchlist": st.Page(_watchlist_page, title="Watchlist", url_path="watchlist"),
        "assess": st.Page(_assess_page, title="Assess", url_path="assess"),
        "signoff": st.Page(_signoff_page, title="Sign-off", url_path="sign-off"),
        "player_types": st.Page(_player_types_page, title="Player types", url_path="player-types"),
        "physical": st.Page(_physical_page, title="Physical", url_path="physical"),
        "glossary": st.Page(_glossary_page, title="Glossary", url_path="glossary"),
        "methodology": st.Page(_methodology_page, title="Methodology", url_path="methodology"),
    }
    # The Users page (admin account management -- create, reset a password, deactivate/
    # reactivate, clear a lockout) is added to `pages` ONLY for someone holding
    # `manage_users`. This is what actually keeps it out of a non-admin's sidebar: `pages`
    # feeds both `register_pages` (so `switch_to` can never navigate to it either) and
    # `st.navigation` below, so a role without the permission never sees the page exist,
    # never mind reach its actions. `tabs/users.py::render` re-checks the same permission on
    # its own as a second line of defence -- never trust registration alone.
    if can(user.role, "manage_users"):
        pages["users"] = st.Page(_users_page, title="Users", url_path="users")
    # Registered BEFORE .run(): a page's own render call (e.g. "Assess this player") can
    # trigger `session.switch_to`/`go_to_assess` while `.run()` is still executing below, so
    # the lookup must already be in place. `register_pages` keeps the flat name -> Page lookup
    # `switch_to` needs; it is indifferent to how the pages are grouped for display.
    register_pages(pages)
    # Nine pages read as one flat list; grouped into the four clusters staff actually use them
    # in, the current page reads as "where am I within this cluster" rather than "which of
    # nine". `st.navigation` renders each dict key as a section header above its pages, in the
    # order given -- so top-to-bottom order across the whole sidebar still matches the
    # unchanged page order (Players, Compare, Watchlist, Assess, Sign-off, Player types,
    # Physical, Glossary, Methodology); only the grouping and the section labels are new.
    nav_sections = {
        "Scouting": [pages["players"], pages["compare"], pages["watchlist"]],
        "Assessment": [pages["assess"], pages["signoff"]],
        "Analysis": [pages["player_types"], pages["physical"]],
        "Reference": [pages["glossary"], pages["methodology"]],
    }
    # A tenth page, but its own section: it is not scouting/assessment/analysis/reference
    # work, it is platform administration, and folding it into an existing group would bury
    # it (or misrepresent one of those groups as containing admin tooling for everyone). Only
    # added when the page itself was -- an admin-less `pages` dict never produces this key.
    if "users" in pages:
        nav_sections["Admin"] = [pages["users"]]
    st.navigation(nav_sections).run()

    st.caption(f"Impect event data (+ SkillCorner physical), {season_name_for(season_id)} season. Player market values are "
               "real (Transfermarkt, EFL only — Scottish/PL2 have none, so those players are scouted on quality "
               "and style but can't be affordability-gated). Wages and the club identity profile are clearly-"
               "labelled modelled estimates, swappable for the club's real data with no code change.")


if __name__ == "__main__":
    main()
