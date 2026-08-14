"""The Player types tab: data-driven playing-style clusters within a position.

A description of HOW a player plays, not how good he is -- distinct from the club
scorecard's archetype lens, which is a scoring choice."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from lofc.dashboard.charts import SCATTER_CONFIG, _cluster_axes, cluster_scatter
from lofc.dashboard.labels import LABELS
from lofc.dashboard.theme import NONE_OPTION


def _player_types(tab, pool: pd.DataFrame, percentiles: pd.DataFrame, metrics: list[str], position: str) -> None:
    """Show the playing-style groups for this position: summary cards plus a scatter."""
    with tab:
        if pool.empty:
            st.warning("No players for these filters.")
            return
        st.markdown("**Playing-style groups for this position.** These are found by clustering players on their "
                    "relative strengths (what they do more of than the rest of their own game), so the split is by "
                    "*style*, not quality. The labels are auto-generated from each group's standout stats.")

        # Keyed by player AND league: a mid-season mover has one row per league, and a
        # player_id-only pivot would average his two leagues' percentiles together.
        keys = ["player_id", "competition_id"]
        pairs = pool[keys].drop_duplicates()
        block = percentiles.merge(pairs, on=keys)
        block = block[block["metric"].isin(metrics)]
        wide = block.pivot_table(index=keys, columns="metric", values="percentile")
        info = pool.drop_duplicates(keys).set_index(keys)[
            ["cluster_label", "objective_composite", "player_name", "team_name", "qualifies"]]
        wide = wide.join(info, how="inner")
        metric_cols = [m for m in metrics if m in wide.columns]
        if wide.empty or len(metric_cols) < 2:
            st.info("Not enough data to show playing-style groups for this position.")
            return
        wide[metric_cols] = wide[metric_cols].fillna(50.0)

        labels = sorted(wide["cluster_label"].dropna().unique())
        st.markdown("##### The groups")
        columns = st.columns(min(len(labels), 3) or 1)
        for i, label in enumerate(labels):
            group = wide[wide["cluster_label"] == label]
            examples = group.sort_values("objective_composite", ascending=False)["player_name"].head(2).tolist()
            with columns[i % len(columns)]:
                with st.container(border=True):
                    st.markdown(f"**{label}**")
                    # No average-quality figure here: the groups are built style-not-quality,
                    # so group means hover near 50 and a "47 vs 50" read would be noise.
                    st.caption(f"{len(group)} players · top fits: {', '.join(examples)}")

        st.markdown("##### How the groups separate")
        # Let the user circle any player directly here, defaulting to whoever is selected elsewhere.
        names = sorted(wide["player_name"].dropna().unique().tolist())
        prior = st.session_state.get("shortlist_selected_player") or st.session_state.get("profile_player")
        options = [NONE_OPTION] + names
        highlight = st.selectbox("Find a player (circles their dot)", options,
                                 index=options.index(prior) if prior in options else 0, key="types_highlight")
        selected = highlight if highlight != NONE_OPTION else None
        x_metric, y_metric = _cluster_axes(wide, metric_cols)
        st.plotly_chart(cluster_scatter(wide, x_metric, y_metric, selected),
                        width="stretch", config=SCATTER_CONFIG, key="cluster_scatter")
        st.caption(f"Each dot is a {position}, placed by {LABELS.get(x_metric, x_metric)} vs "
                   f"{LABELS.get(y_metric, y_metric)} (percentile), coloured by group. The two axes are the stats "
                   "that separate the groups most; the dotted lines mark the 50th percentile (average). The ringed "
                   "dot is the player selected on the Shortlist or Profile tab. Scroll or use the toolbar to zoom; "
                   "double-click to reset.")


# --- physical (SkillCorner) -----------------------------------------------------------
