"""Squad view: who is at each club right now, on what contract, and on loan from whom.

The January window's page. It exists because the ranking cannot answer January's question.
A composite needs 450 minutes; two months into 2026/27 the average player has 69-119, so
NOBODY is rankable and a season filter set to 26/27 returned an empty screen. The 450 rule
is right -- a per-90 rate on 70 minutes is noise -- but "nothing to show" is the wrong
answer to "who is at this club and can I sign him".

So this page answers a different question from the ranking, using facts that ARE current:

  who is in the squad now      current-season appearances
  is he gettable               contract expiry, and how long is left
  is he even available         on loan from whom, until when
  how good is he               LAST season's composite, labelled as such

Nothing here is scored. The rating column is carried across from the last complete season
and says so, because inventing a 26/27 composite from 70 minutes would be worse than
showing none.
"""
# The page's logic lives in `lofc.core.squads` (shared with the web page, TASKS 2.36); this
# module keeps the widgets and the Streamlit caches of the loaders. Every name below is
# re-exported so callers and tests keep importing it from here.

from __future__ import annotations

import pandas as pd
import streamlit as st

from lofc.core import squads as _core
from lofc.core.squads import (  # noqa: F401  (re-exported)
    DISPLAY_COLUMNS, EXPORT_ROUNDING, FOOTER_CAPTION, LOAN_COLUMNS, MINUTES_HELP,
    SHOW_OPTIONS, TM_LEAGUES, TM_POSITION_GROUPS, _FALLBACK_SUFFIX, _REGISTERED_SUFFIX,
    _DISPLAY_FORMATS, _bare_position, _loan_lookup, attach_loans, best_profile_target,
    build_frame, build_view, by_club, by_league, club_options, ensure_display_columns,
    export_filename, filter_by_name, filter_by_position, for_export, league_options, loan_view,
    months_left, no_rating_message, no_record_message, position_options, prepare,
    prepare_loans, registered_position, resolve_loan_player_ids, sidebar_view,
    squad_display, squad_source_warning, summary_counts, this_season_score, tiles,
    transfermarkt_asof, with_last_season_position, with_registered_position)
from lofc.dashboard.seasons import contract_data_date, loan_data_date
from lofc.dashboard.session import go_to_player
from lofc.dashboard.sidebar_filters import SidebarFilters


# --- the loaders, cached for Streamlit (the SQL is in lofc.core.squads) -------------------
squad_frame = st.cache_data(ttl=300)(_core.squad_frame)
loans_frame = st.cache_data(ttl=300)(_core.loans_frame)
player_rated_rows = st.cache_data(ttl=300)(_core.player_rated_rows)
_season_scorecards = st.cache_data(ttl=300)(_core.season_scorecards)
scraped_squads = st.cache_data(ttl=300)(_core.scraped_squads)


@st.cache_data(ttl=300)
def registered_squad_frame(season_id: int, rating_season_id: int) -> pd.DataFrame:
    """`core.squads.registered_squad_frame` over the cached scrape."""
    return _core.registered_squad_frame(season_id, rating_season_id, squads=scraped_squads())


def render(season_id: int, rating_season_id: int, season_label: str,
           rating_label: str, filters: SidebarFilters | None = None) -> None:
    filters = filters or SidebarFilters()
    st.subheader("Squads, contracts and loans")
    st.caption(f"Every registered squad member, {season_label}. Click a row to open the "
               f"player.")

    asof = transfermarkt_asof(contract_data_date(), loan_data_date())
    if asof:
        st.caption(asof)

    # This season's rating where it is rankable -- gated by the same peer-pool floor the
    # Players page uses, so a pool-of-one 4.90 cannot appear here after being removed there.
    frame = build_frame(registered_squad_frame(season_id, rating_season_id),
                        _season_scorecards(season_id), season_id)
    # Before anything else on the page: is this the real squad list, or the appearance-based
    # fallback? `scraped_squads()` is @st.cache_data, so this second call is free.
    warning = squad_source_warning(len(scraped_squads()), len(frame))
    if warning:
        st.error(warning)
    if frame.empty:
        st.info("No squad data for this season yet.")
        return

    frame = sidebar_view(frame, filters)
    # Bottom-aligned so every control (and the radio, whose label sits above it) shares a baseline;
    # the radio gets the widest column so its three options do not wrap or squash.
    c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 2.4, 4.6], vertical_alignment="bottom")
    league = c1.selectbox("League", league_options(frame))
    view = by_league(frame, league)
    club = c2.selectbox("Club", club_options(view))
    position = c3.selectbox("Position", position_options(by_club(view, club)))
    query = c4.text_input("Player", placeholder="Search a player…")
    show = c5.radio("Show", SHOW_OPTIONS, horizontal=True, label_visibility="visible")

    # The rows: league -> club -> position -> name, then "On loan only" REPLACES them with
    # every loan (re-applying all of those filters and the sidebar), or "Contract expiring"
    # keeps months left < 12 -- see core.squads.build_view.
    built = build_view(frame, filters, league, club, position, query, show,
                       loans=lambda: prepare_loans(loans_frame(season_id, rating_season_id)))
    view = built.view
    m1, m2, m3, m4 = st.columns(4)
    for col, (label, value) in zip((m1, m2, m3, m4), tiles(built.counts)):
        col.metric(label, value)

    help_ = _core.COLUMN_HELP
    table = squad_display(view[DISPLAY_COLUMNS].reset_index(drop=True))
    selection = st.dataframe(
        table, hide_index=True, width="stretch", height=560,
        on_select="rerun", selection_mode="single-row", key="squads_table",
        column_config={
            "Age": st.column_config.TextColumn("Age", width="small"),
            "This season": st.column_config.TextColumn(
                "This season", help=help_["This season"]),
            "Position": st.column_config.TextColumn("Position", help=help_["Position"]),
            "Minutes": st.column_config.NumberColumn(
                "Minutes", format="%d", width="small", help=help_["Minutes"]),
            "Last season": st.column_config.TextColumn(
                f"{rating_label} rating", width="small", help=help_["Last season"]),
            "Also rated": st.column_config.TextColumn(
                "Also rated", width="small", help=help_["Also rated"]),
            "Contract to": st.column_config.DateColumn(
                "Contract to", format="MMM YYYY", help=help_["Contract to"]),
            "Loan ends": st.column_config.DateColumn("Loan ends", format="MMM YYYY"),
            "Months left": st.column_config.NumberColumn(
                "Months left", format="%d", width="small", help=help_["Months left"]),
        })

    # Row click -> that player's profile. The ID is carried, never the label.
    rows = list(selection.selection.rows) if selection and selection.selection else []
    if rows and rows[0] < len(view):
        picked = view.iloc[rows[0]]
        # A squad member we hold no record of has no player_id, and int(NaN) raised
        # "cannot convert float NaN to integer" -- clicking him crashed the whole page.
        # He is in the squad list because Transfermarkt registered him; we cannot open a
        # profile we do not have, so say which and why rather than navigate or crash.
        if pd.isna(picked.get("player_id")):
            st.info(no_record_message(picked["Player"], picked["Club"]))
        else:
            # Pick a league-season he actually HAS a rating in, rather than pairing this
            # season's league with last season's id -- see best_profile_target.
            target = best_profile_target(player_rated_rows(int(picked["player_id"])))
            if target is None:
                st.info(no_rating_message(picked["Player"]))
            else:
                go_to_player(int(picked["player_id"]), target[0], target[1])

    d1, d2 = st.columns([1, 4])
    d1.download_button(
        _core.DOWNLOAD_LABEL, data=for_export(table).to_csv(index=False).encode("utf-8"),
        file_name=export_filename(built.league, built.club),
        mime="text/csv", width="stretch", help=_core.DOWNLOAD_HELP)

    st.caption(FOOTER_CAPTION)
