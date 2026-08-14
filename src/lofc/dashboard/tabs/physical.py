"""The Physical tab: SkillCorner tracking data -- league benchmarks and the LOFC squad.

Scope is enforced by the data itself: team-level rows cover every club, player-level rows
cover only our own squad, so no candidate can be given an invented physical score here."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from lofc.dashboard.charts import _sc_league_bar
from lofc.dashboard.labels import SC_METRIC_LABELS
from lofc.dashboard.loaders import load_sc_players, load_sc_teams


def _physical(tab) -> None:
    with tab:
        teams = load_sc_teams()
        players = load_sc_players()
        if teams.empty:
            st.info("SkillCorner tracking data is not loaded. Drop the club export in "
                    "data/reference/skillcorner/ and run: python -m lofc.ingest.skillcorner")
            return

        season = teams["season_label"].iloc[0]
        st.markdown(f"**Physical output from SkillCorner tracking data, League One {season}.** "
                    "Off-ball running and intensity, which on-ball event data cannot see.")
        st.caption("Scope, stated plainly: player-level tracking covers the Leyton Orient squad only; "
                   "other clubs appear as team totals. So this page measures our own physical identity and "
                   "where the team sits in the league. It never scores recruitment targets, because no "
                   "tracking data exists for them.")

        st.markdown("##### Where Leyton Orient sit in the league")
        label_by_col = {v: k for k, v in SC_METRIC_LABELS.items()}
        choice = st.selectbox("Physical metric", list(SC_METRIC_LABELS.values()), key="sc_metric")
        metric = label_by_col[choice]
        ranks = teams[metric].rank(ascending=False, method="min")
        lofc_mask = teams["team_name"].str.contains("Leyton", na=False)
        if lofc_mask.any() and pd.notna(teams.loc[lofc_mask, metric].iloc[0]):
            rank = int(ranks[lofc_mask].iloc[0])
            value = teams.loc[lofc_mask, metric].iloc[0]
            median = teams[metric].median()
            st.caption(f"Leyton Orient: {value:,.1f} — rank {rank} of {len(teams)} "
                       f"(league median {median:,.1f}).")
        st.plotly_chart(_sc_league_bar(teams, metric), width="stretch", key="sc_league_bar")

        st.markdown("##### The measured identity of the current squad")
        summary_rows = []
        for col, label in SC_METRIC_LABELS.items():
            if teams[col].notna().sum() == 0 or not lofc_mask.any():
                continue
            rank = int(teams[col].rank(ascending=False, method="min")[lofc_mask].iloc[0])
            summary_rows.append({"Metric": label,
                                 "Leyton Orient": round(float(teams.loc[lofc_mask, col].iloc[0]), 1),
                                 "League median": round(float(teams[col].median()), 1),
                                 "Rank of 24": rank})
        st.dataframe(pd.DataFrame(summary_rows), hide_index=True, width="stretch")
        st.caption("This describes how the team currently plays, not how it should: a draft physical identity "
                   "for the Director of Football to confirm or override. Once confirmed, it informs which "
                   "on-ball traits (e.g. pressing volume) the Fit score weights for every candidate — the "
                   "traits themselves come from event data that exists for all players.")

        if not players.empty:
            st.markdown("##### Player level: the Leyton Orient squad")
            cols = {"player_name": "Player", "position_group": "Position",
                    "matches_measured": "Matches tracked", "distance_p90": "Distance/90 (m)",
                    "hsr_distance_p90": "High-speed dist/90 (m)", "sprint_count_p90": "Sprints/90",
                    "high_accel_count_p90": "High accels/90", "psv99_kmh": "Peak speed (km/h)"}
            view = (players[list(cols)].rename(columns=cols)
                    .sort_values("Distance/90 (m)", ascending=False).round(1))
            st.dataframe(view, hide_index=True, width="stretch", height=420)
            st.caption("Players with enough tracked minutes for season averages. Use this to see who drives "
                       "the team's running and sprint output, and as physical benchmarks when scouts assess "
                       "a target for the same role in person.")


# --- methodology ----------------------------------------------------------------------
# The recruitment flow, one entry per step. Plain language first; the technical
# line lives in a footnote so the page reads cleanly for a non-technical audience.
