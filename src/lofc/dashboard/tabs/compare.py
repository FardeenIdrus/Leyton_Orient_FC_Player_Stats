"""The Compare tab: two or three players head-to-head.

Charts the club's own Performance metrics (archetype-aware, from the scorecard percentiles)
so the picture matches the composite, plus a RAW physical table -- raw because physical
output, unlike within-league percentiles, is directly comparable across divisions."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from lofc.dashboard.charts import PLOTLY_CONFIG, radar_chart
from lofc.dashboard.formatting import value_or_dash
from lofc.dashboard.labels import PHYS_COMPARE_LABEL, metric_label
from lofc.dashboard.loaders import _competition_name_by_id, load_scorecard_percentiles
from lofc.dashboard.tabs.players import _club_metrics_for, _player_options, _sc_pct_series
from lofc.dashboard.theme import NONE_OPTION
from lofc.model import club_framework as cf


def _compare(tab, pool: pd.DataFrame, position: str, archetype: str,
             season_id: int, show_money: bool = False,
             metric_values: pd.DataFrame | None = None) -> None:
    with tab:
        if len(pool) < 2:
            st.warning("Need at least two players for these filters.")
            return
        lens = archetype != cf.DEFAULT_ARCHETYPE
        st.caption("Compare players head-to-head on the club's **Performance metrics** — the same stats "
                   "that build the composite" + (f" (archetype: _{archetype}_)" if lens else "") +
                   ". The further out on each axis, the better. Percentiles are ranked within league.")

        labels, by_label = _player_options(pool)
        c1, c2, c3 = st.columns(3)
        a = c1.selectbox("Player A", labels, index=0, key="cmp_a")
        b = c2.selectbox("Player B", labels, index=1, key="cmp_b")
        c = c3.selectbox("Player C (optional)", [NONE_OPTION] + labels, index=0, key="cmp_c")

        chosen = [p for p in [a, b, (c if c != NONE_OPTION else None)] if p]
        chosen = list(dict.fromkeys(chosen))  # de-duplicate, keep order
        if len(chosen) < 2:
            st.info("Pick two different players to compare.")
            return

        # Chart the CLUB Performance metrics (position + archetype), from the scorecard
        # percentiles — the same source the player profile and the composite use, so Compare is
        # consistent with the rest of the platform (not the retired Quality/Fit role metrics).
        perf_metrics = _club_metrics_for(position, archetype)[0]
        sc_pcts = load_scorecard_percentiles(season_id)
        series_by_label, rows = {}, []
        for label in chosen:
            r = pool.loc[by_label[label]]
            series_by_label[label] = _sc_pct_series(
                sc_pcts, int(r["player_id"]), int(r["competition_id"]), int(r["season_id"]))
            # A bare st.dataframe below (no column_config -- this is a tiny 2-3 row table,
            # not worth one) still prints the literal text "None" for a missing cell rather
            # than leaving it blank (confirmed directly; see formatting.py's docstring), so
            # every value here is pre-formatted text with an em-dash fallback, not a raw
            # number-or-None.
            row = {"Player": r["player_name"], "Club": r["team_name"],
                   "Age": value_or_dash(r.get("age"), "{:.1f}"),
                   "Composite": value_or_dash(r.get("objective_composite"), "{:.2f}"),
                   "Performance": value_or_dash(r.get("performance_band"), "{:.2f}")}
            if show_money:
                market_eur = r.get("market_value_eur")
                row["Market (€m)"] = value_or_dash(
                    market_eur / 1e6 if pd.notna(market_eur) else market_eur, "{:.1f}")
            rows.append(row)

        # Shared axes = the club metrics present (non-null) for EVERY chosen player, so no axis
        # is a misleading zero-fill.
        shared = [m for m in perf_metrics
                  if all(s is not None and m in s.index and pd.notna(s[m])
                         for s in series_by_label.values())]

        chart_col, table_col = st.columns([3, 2])
        if len(shared) >= 3:
            traces = [(pool.loc[by_label[label], "player_name"],
                       [float(series_by_label[label][m]) for m in shared]) for label in chosen]
            chart_col.plotly_chart(radar_chart(traces, shared), width="stretch", config=PLOTLY_CONFIG)
        else:
            chart_col.info("Not enough shared measured metrics between these players for a radar.")
        table_col.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

        # Percentiles are ranked within a league, so a cross-league comparison needs a caveat.
        chosen_comps = {int(pool.loc[by_label[label], "competition_id"]) for label in chosen}
        if len(chosen_comps) > 1:
            name_by_id = _competition_name_by_id()   # all leagues incl. Scottish/PL2 (901/902/903)
            leagues_str = " and ".join(sorted({name_by_id.get(c, f"league {c}") for c in chosen_comps}))
            st.warning(f"These players play in different leagues ({leagues_str}). All percentiles are "
                       "ranked against each player's own league, so an 80 in a lower league does not "
                       "equal an 80 in a higher one. Use the radar for style, not as a like-for-like "
                       "quality comparison; the valuation model is what accounts for league level.")

        # Physical output — RAW values, which (unlike the within-league percentiles above) ARE
        # directly comparable across leagues: a metre and a sprint mean the same everywhere. Mixed
        # units, so a table (not a radar). SkillCorner, 2025/26 only; GK has no physical dimension.
        phys_metrics = _club_metrics_for(position, archetype)[1]
        if phys_metrics and metric_values is not None:
            recs = []
            for m in phys_metrics:
                label, unit = PHYS_COMPARE_LABEL.get(m, (metric_label(m), ""))
                rec, any_val = {"Metric": f"{label} ({unit})" if unit else label}, False
                for lbl in chosen:
                    r = pool.loc[by_label[lbl]]
                    mv = metric_values[(metric_values["player_id"] == int(r["player_id"]))
                                       & (metric_values["competition_id"] == int(r["competition_id"]))]
                    val = mv.iloc[0].get(m) if not mv.empty else None
                    rec[r["player_name"]] = value_or_dash(val, "{:.1f}")
                    any_val = any_val or pd.notna(val)
                if any_val:
                    recs.append(rec)
            st.markdown("##### Physical output (raw — directly comparable across leagues)")
            if recs:
                st.dataframe(pd.DataFrame(recs), hide_index=True, width="stretch")
                st.caption("Raw per-90 physical output from SkillCorner. A metre and a sprint mean the "
                           "same in every division, so — unlike the percentile radar above — these are "
                           "directly comparable across leagues. 2025/26 only; a blank means no tracking "
                           "data (2024/25, or the Scottish Championship, which SkillCorner does not track).")
            else:
                st.info("No SkillCorner physical data for these players (physical is 2025/26 only and "
                        "not every league is tracked).")
