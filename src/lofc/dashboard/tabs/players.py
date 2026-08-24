"""The Players workspace: the platform's primary surface.

A master-detail view -- a composite-ranked list of players, and on click or search the full
player detail (bio, dimension scores, the club-framework grand table and charts). Merged
from the former Shortlist + Club scorecard + Player profile tabs so there is ONE ranked list
rather than three overlapping ones. Money is an opt-in layer that never reorders the default
ranking."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from lofc.constrain.filters import RANK_COLUMN
from lofc.dashboard import assessment_detail, badges, evidence
from lofc.dashboard.charts import PLOTLY_CONFIG, bar_chart, radar_chart
from lofc.dashboard.labels import LABELS, _metric_source, metric_label
from lofc.dashboard.loaders import (
    get_engine, headline, league_names, load_assessment_status, load_scorecard_percentiles,
    load_scorecards, load_scorecards_archetype, load_trajectory, season_label)
from lofc.dashboard.seasons import (
    CONTRACT_EXPIRED, CONTRACT_HORIZONS, DEFAULT_CONTRACT_HORIZON, contract_data_date)
from lofc.dashboard.session import CarriedPlayer, go_to_assess
from lofc.model import assessment_status
from lofc.model import club_framework as cf
from lofc.model.score import POSITION_ROLE
from lofc.model import scorecard as scorecard_mod
from lofc.model import scout_scores
from lofc.store import assessments as store_assess
from lofc.store import watchlist


def _trajectory(player_id: int, role: str, key_prefix: str) -> None:
    """Season-by-season output for one player, role-relevant columns only."""
    rows = load_trajectory()
    rows = rows[rows["player_id"] == player_id]
    if len(rows) < 2:
        return
    view = pd.DataFrame({
        "Season": rows["season_name"].str.replace("/20", "/", regex=False),
        "League": rows["competition_name"],
        "Club": rows["team_name"],
        "Minutes": rows["minutes"].round(0).astype(int),
    })
    if role == "goalkeeper":
        view["Save %"] = (rows["save_pct"] * 100).round(0)  # stored 0-1
        view["Saves/90"] = rows["gk_saves_p90"].round(2)
    elif role == "defender":
        view["Tackles/90"] = rows["tackles_p90"].round(2)
        view["Interceptions/90"] = rows["interceptions_p90"].round(2)
        view["Pass %"] = (rows["pass_completion_pct"] * 100).round(0)  # stored 0-1
    else:
        view["Goals"] = rows["goals"].fillna(0).astype(int)
        view["Assists"] = rows["assists"].fillna(0).astype(int)
        view["npxG/90"] = rows["np_xg_p90"].round(2)
        view["xA/90"] = rows["xa_p90"].round(2)
    st.markdown("**Season by season**")
    st.dataframe(view, hide_index=True, width="stretch", key=f"{key_prefix}_trajectory")
    st.caption("Direction matters as much as level: improving output across seasons is a different "
               "buy from a one-off year. Scores and prices on this page are for the latest season; "
               "a league change between rows means the rates are not like-for-like (per-90 numbers "
               "are relative to each league).")


def _strengths_weaknesses(percentiles: pd.DataFrame, player_id: int, comp_id: int,
                          metrics: list[str]) -> str:
    """A one-line plain-English read of a player: top-3 and bottom-3 percentiles."""
    series = percentiles[(percentiles["player_id"] == player_id)
                         & (percentiles["competition_id"] == comp_id)
                         ].set_index("metric")["percentile"]
    pairs = [(m, float(series[m])) for m in metrics if m in series.index and pd.notna(series[m])]
    if len(pairs) < 2:
        return ""
    high = sorted(pairs, key=lambda x: x[1], reverse=True)[:3]
    low = sorted(pairs, key=lambda x: x[1])[:3]
    fmt = lambda items: " · ".join(f"{LABELS.get(m, m)} ({v:.0f})" for m, v in items)
    return f":green[**Strengths**] {fmt(high)}  \n:red[**Watch-outs**] {fmt(low)}"


def _metrics_held_by_anyone(metric_values: pd.DataFrame, metric_names) -> set[str]:
    """Which of these metric columns are non-null for at least one player in the loaded
    population (one season, every league).

    Retired StatsBomb columns Impect has no successor for (`tackles_p90`, `save_pct`, ...)
    are NULL for every player once StatsBomb is out of scoring -- they still live in `LABELS`
    (the full club-framework name list) and in `metric_values`'s columns, but showing them as
    an empty row on every profile reads as the platform being broken. This decides membership
    from the data actually held, not a hard-coded list of retired names, so it stays correct
    as sources are added or retired. Pure (no Streamlit, no per-player state) so it is directly
    testable.
    """
    return {m for m in metric_names
           if m in metric_values.columns and metric_values[m].notna().any()}


def _full_stats_table(row: pd.Series, percentiles: pd.DataFrame, metric_values: pd.DataFrame) -> pd.DataFrame | None:
    """Every metric the platform actually holds data for, as real numbers for one player:
    season total, per-90 (or rate), and percentile. Metrics nobody in the population has a
    value for (see `_metrics_held_by_anyone`) are dropped, not shown as a blank row."""
    player_id, comp_id = int(row["player_id"]), int(row["competition_id"])
    pcts = percentiles[(percentiles["player_id"] == player_id)
                       & (percentiles["competition_id"] == comp_id)].set_index("metric")["percentile"]
    value_rows = metric_values[(metric_values["player_id"] == player_id)
                               & (metric_values["competition_id"] == comp_id)]
    if value_rows.empty:
        return None
    values = value_rows.iloc[0]
    minutes = float(row["minutes"]) if pd.notna(row.get("minutes")) else 0.0
    held = _metrics_held_by_anyone(metric_values, LABELS)

    records = []
    for metric in held:
        if metric not in pcts.index or metric not in values.index or pd.isna(values[metric]):
            continue
        value = float(values[metric])
        if metric.endswith("_pct"):  # a 0-1 rate, not a count: no season total
            season_total, per_90 = "—", f"{value * 100:.0f}%"
        else:
            season_total = f"{round(value * minutes / 90):,}" if minutes else "—"
            per_90 = f"{value:.2f}"
        records.append({"Metric": LABELS[metric], "Source": _metric_source(metric),
                        "Season total": season_total,
                        "Per 90 / rate": per_90, "Percentile": round(float(pcts[metric]))})
    if not records:
        return None
    return pd.DataFrame(records).sort_values("Percentile", ascending=False).reset_index(drop=True)


def _selectable_key(base_key: str) -> str:
    """Dataframe key that carries a clear-nonce, so a row selection can be reset on demand."""
    return f"{base_key}__{st.session_state.get(base_key + '__nonce', 0)}"


def _clear_selection_button(base_key: str, disabled: bool = False,
                            label: str = "✕ Clear selection") -> None:
    """Reset a clickable dataframe's row selection by bumping its clear-nonce."""
    st.button(label, key=base_key + "__clearbtn", disabled=disabled, width="stretch",
              on_click=lambda: st.session_state.update(
                  {base_key + "__nonce": st.session_state.get(base_key + "__nonce", 0) + 1}),
              help="Clear the selected player.")


def _kpi_strip(pool: pd.DataFrame, season_label_text: str | None = None,
               season_id: int | None = None, show_money: bool = False) -> None:
    """A quiet, single-line orientation strip: which dataset am I looking at. Shown above
    every page (chrome, not a headline) -- so it stays a slim bar rather than the large
    metric cards a dashboard's own landing page might earn."""
    players, _ = headline(season_id)
    leagues = league_names()
    items = [
        f"<b>{players:,}</b> players analysed",
        f"<b>{len(leagues)}</b> leagues",
        f"<b>{season_label_text or season_label()}</b> season",
    ]
    if show_money:
        items.append(f"<b>{int(pool['qualifies'].sum()):,}</b> affordable now")
    sep = "<span class='lofc-infobar-sep'>&middot;</span>"
    body = sep.join(f"<span class='lofc-infobar-item'>{item}</span>" for item in items)
    st.markdown(f"<div class='lofc-infobar'>{body}</div>", unsafe_allow_html=True)


def _sc_pct_series(sc_pcts: pd.DataFrame, pid: int, cid: int, sid: int) -> pd.Series | None:
    """The scorecard-percentile row (wide) for one player-season, or None."""
    m = sc_pcts[(sc_pcts["player_id"] == pid) & (sc_pcts["competition_id"] == cid)
                & (sc_pcts["season_id"] == sid)]
    return m.iloc[0] if not m.empty else None


def _club_metrics_for(position: str, archetype: str) -> tuple[list[str], list[str]]:
    """(Performance, Physical) live metric lists for a position + archetype."""
    perf = scorecard_mod._resolved_performance(position, archetype)
    phys = [m for m in cf.PHYSICAL_METRICS.get(position, [])]
    return perf, phys


def _grand_table(row: pd.Series, position: str, archetype: str,
                 sc_pcts: pd.DataFrame, metric_values: pd.DataFrame) -> pd.DataFrame:
    """The unified club-framework metric table for one player, grouped by dimension:
    Dimension · Metric · Source · Season total · Per-90/rate · Percentile · 1-5 Band."""
    pid, cid, sid = int(row["player_id"]), int(row["competition_id"]), int(row["season_id"])
    pr = _sc_pct_series(sc_pcts, pid, cid, sid)
    mvr = metric_values[(metric_values["player_id"] == pid)
                        & (metric_values["competition_id"] == cid)]
    mvr = mvr.iloc[0] if not mvr.empty else pd.Series(dtype=float)
    minutes = float(row["minutes"]) if pd.notna(row.get("minutes")) else 0.0
    perf, phys = _club_metrics_for(position, archetype)

    records = []
    for dim, metrics in (("Performance", perf), ("Physical", phys)):
        for m in metrics:
            if pr is None or m not in pr.index or pd.isna(pr[m]):
                continue
            pct = float(pr[m])
            val = mvr.get(m)
            if m.endswith("_pct"):
                total, per90 = "—", (f"{float(val) * 100:.0f}%" if pd.notna(val) else "—")
            else:
                per90 = f"{float(val):.2f}" if pd.notna(val) else "—"
                total = f"{round(float(val) * minutes / 90):,}" if pd.notna(val) and minutes else "—"
            records.append({"Dimension": dim, "Metric": metric_label(m), "Source": _metric_source(m),
                            "Season total": total, "Per 90 / rate": per90,
                            "Percentile": round(pct), "Band": round(cf.band(pct), 2)})
    return pd.DataFrame(records)


def _render_profile_body(row: pd.Series, percentiles: pd.DataFrame, metrics: list[str],
                         metric_values: pd.DataFrame, key_prefix: str,
                         archetype: str = cf.DEFAULT_ARCHETYPE, show_money: bool = True) -> None:
    """The unified player detail: header, output, dimension scores, a plain read, the
    club-framework grand table, charts on the club per-position (archetype) metrics, and an
    'all tracked metrics' expander. Shared by the Players list (click + search); key_prefix
    keeps the instances' widgets distinct. Money columns/tiles show only when show_money.
    """
    st.subheader(f"{row['player_name']}  ·  {row['team_name']}")
    bio_bits = [f"{row['position_group']}"]
    if pd.notna(row.get("age")):
        bio_bits.append(f"age {row['age']:.1f}")
    bio_bits.append(str(row.get("league", "")))
    if pd.notna(row.get("foot")):
        bio_bits.append(f"{row['foot']}-footed")
    if pd.notna(row.get("height_cm")):
        bio_bits.append(f"{int(row['height_cm'])} cm")
    if pd.notna(row.get("contract_until")):
        bio_bits.append(f"contract to {row['contract_until']:%b %Y}")
    bio_bits.append(f"playing style: {row.get('cluster_label', 'n/a')}")
    st.caption(" · ".join(b for b in bio_bits if b))

    # Watch toggle. Key carries the render site AND the row identity, so the two
    # render sites never collide and a click can't land on a different player
    # after the selection changes.
    pid, cid, sid = int(row["player_id"]), int(row["competition_id"]), int(row["season_id"])
    wkey = f"{key_prefix}_watch_{pid}_{cid}_{sid}"
    if watchlist.is_watched(get_engine(), pid, cid, sid):
        wc1, wc2 = st.columns([1, 5])
        wc1.markdown("**★ On watchlist**")
        if wc2.button("Remove from watchlist", key=f"{wkey}_rm"):
            watchlist.remove(get_engine(), pid, cid, sid)
            st.rerun()
    elif st.button("☆ Add to watchlist", key=f"{wkey}_add"):
        watchlist.add(get_engine(), pid, cid, sid)
        st.rerun()
    if pd.notna(row.get("tm_player_id")):
        st.markdown(f"[View on Transfermarkt ↗](https://www.transfermarkt.com/-/profil/spieler/"
                    f"{int(row['tm_player_id'])})")

    # Season output as tiles, chosen for the player's role: goals mean nothing on a
    # goalkeeper's card, save percentage means nothing on a striker's.
    role = POSITION_ROLE[row["position_group"]]
    mv = metric_values[(metric_values["player_id"] == int(row["player_id"]))
                       & (metric_values["competition_id"] == int(row["competition_id"]))]
    mv = mv.iloc[0] if not mv.empty else pd.Series(dtype=float)
    minutes = float(row["minutes"]) if pd.notna(row.get("minutes")) else 0.0

    def total(per90_col: str) -> str:
        value = mv.get(per90_col)
        return f"{round(float(value) * minutes / 90):,}" if pd.notna(value) and minutes else "—"

    o1, o2, o3 = st.columns(3)
    if role == "goalkeeper":
        save_pct = mv.get("save_pct")  # stored 0-1
        o1.metric("Save %", f"{float(save_pct) * 100:.0f}%" if pd.notna(save_pct) else "—", border=True)
        o2.metric("Saves", total("gk_saves_p90"), border=True)
    elif role == "defender":
        o1.metric("Tackles", total("tackles_p90"), border=True)
        o2.metric("Interceptions", total("interceptions_p90"), border=True)
    else:
        # EFL rows carry raw season totals; scouting rows (all leagues) don't, so fall back
        # to the per-90-derived total, which the combined table supplies for every league.
        def _season_total(raw_col: str, per90_col: str) -> int:
            if pd.notna(row.get(raw_col)):
                return int(row[raw_col])
            v = mv.get(per90_col)
            return round(float(v) * minutes / 90) if pd.notna(v) and minutes else 0
        o1.metric("Goals", f"{_season_total('goals', 'goals_p90'):,}", border=True)
        o2.metric("Assists", f"{_season_total('assists', 'assists_p90'):,}", border=True)
    o3.metric("Minutes", f"{int(row['minutes']):,}", border=True)

    npxg, xa = row.get("np_xg_p90"), row.get("xa_p90")
    if role in ("midfielder", "attacker") and pd.notna(npxg) and pd.notna(xa):
        st.caption(f"Underlying rates: {npxg:.2f} non-pen xG per 90 · {xa:.2f} xA per 90 — these (not raw "
                   "goals/assists) drive the scores, because they're steadier season to season.")

    _trajectory(int(row["player_id"]), role, key_prefix)

    # Dimension score tiles (1-5). Money tiles only when the affordability layer is on.
    composite, performance, physical = (row.get("objective_composite"), row.get("performance_band"),
                                        row.get("physical_band"))
    fmt = lambda v: f"{v:.2f}" if pd.notna(v) else "—"
    has_value = show_money and pd.notna(row.get("market_value_eur"))
    cols = st.columns(5 if has_value else 3)
    comp_label = f"Composite ({archetype})" if archetype != cf.DEFAULT_ARCHETYPE else "Composite"
    cols[0].metric(comp_label, fmt(composite), border=True,
                   help="The club's objective composite (1-5): Performance + Physical, from real data.")
    cols[1].metric("Performance", fmt(performance), border=True,
                   help="The club-framework Performance dimension (1-5).")
    cols[2].metric("Physical", fmt(physical), border=True,
                   help="The club-framework Physical dimension (1-5), where tracking data exists.")
    if has_value:
        cols[3].metric("Market value", f"€{row['market_value_eur'] / 1e6:.1f}m", border=True)
        cols[4].metric("Fair value",
                       f"€{row['fair_value_eur'] / 1e6:.1f}m" if pd.notna(row.get("fair_value_eur")) else "n/a",
                       border=True)
        if pd.notna(row.get("estimated_weekly_wage_gbp")) and pd.notna(row.get("wage_ceiling_gbp")):
            st.caption(f"Modelled weekly wage £{int(row['estimated_weekly_wage_gbp']):,} vs the wage cap "
                       f"£{int(row['wage_ceiling_gbp']):,} for this player — modelled estimate, not an actual salary.")
        if int(row["competition_id"]) == 65 and pd.notna(row.get("fair_value_eur")):
            st.caption("⚠️ Fair-value note: Transfermarkt prices very few National League players, so "
                       "fair values in this league carry extra uncertainty — trust the direction, not the figure.")
    elif show_money:
        st.caption("No market-value or wage data for this league (Scottish / PL2 aren't priced) — this "
                   "is a quality view.")
    # Advisory flags (never exclusions) — an amber callout, so it reads as guidance, not a block.
    flags = []
    if row.get("veto"):
        flags.append("below the club minimum (band &lt; 2.0) on a dimension")
    if row.get("below_min_composite"):
        flags.append("composite below the club's 3.0 minimum standard")
    if flags:
        items = "".join(f"<li style='margin:2px 0;'>{f}</li>" for f in flags)
        st.markdown(
            "<div style='background:#FFF6E5;border:1px solid #F1C40F;border-left:5px solid #F1C40F;"
            "border-radius:8px;padding:9px 13px;margin:.35rem 0 .5rem;color:#7A5B00;font-size:.9rem;'>"
            "<span style='font-weight:700;color:#B8860B;'>⚠️ Advisory</span> "
            "<span style='color:#8A6D00;'>— informational only, the player is <b>not</b> excluded.</span>"
            f"<ul style='margin:5px 0 0;padding-left:20px;'>{items}</ul></div>",
            unsafe_allow_html=True)

    summary = _strengths_weaknesses(percentiles, int(row["player_id"]), int(row["competition_id"]), metrics)
    if summary:
        st.markdown(summary)

    # THE GRAND TABLE — the club-framework metrics that build the composite, with real numbers.
    position, sid = row["position_group"], int(row["season_id"])
    sc_pcts = load_scorecard_percentiles(sid)
    grand = _grand_table(row, position, archetype, sc_pcts, metric_values)
    if not grand.empty:
        st.markdown("##### Scorecard metrics — the stats behind the composite")
        st.dataframe(
            grand, hide_index=True, width="stretch", key=f"{key_prefix}_grand",
            column_config={
                "Source": st.column_config.TextColumn("Source", help="Which provider supplies this metric."),
                "Percentile": st.column_config.ProgressColumn(
                    "Percentile", help="Rank vs peers in the same position, league and season (0-100).",
                    min_value=0, max_value=100, format="%d"),
                "Band": st.column_config.ProgressColumn(
                    "Band", help="The metric's 1-5 band (median→3, 70th→4).", min_value=1, max_value=5, format="%.2f")})
        st.caption("These are the metrics that build the **Performance** and **Physical** dimensions for "
                   f"this position{' / archetype' if archetype != cf.DEFAULT_ARCHETYPE else ''}. Definitions "
                   "are on the **Glossary** tab.")

    # The broader set, for general scouting, kept out of the way.
    stats_table = _full_stats_table(row, percentiles, metric_values)
    if stats_table is not None and not stats_table.empty:
        with st.expander("All tracked metrics (every stat the platform holds — season total, per 90, percentile)"):
            st.dataframe(
                stats_table, hide_index=True, width="stretch", key=f"{key_prefix}_fullstats",
                column_config={
                    "Source": st.column_config.TextColumn(
                        "Source", help="Which data provider supplies this metric."),
                    "Percentile": st.column_config.ProgressColumn(
                        "Percentile", help="Rank against peers in the same position and league (0-100).",
                        min_value=0, max_value=100, format="%d"),
                },
            )
            st.caption("What each metric means — and, for a substitute, the StatsBomb stat it stands "
                       "in for — is on the **Glossary** tab (searchable).")

    # Chart the CLUB Performance metrics (position + archetype) so the picture matches the
    # composite — one bar/axis per stat that builds the Performance dimension.
    prow = _sc_pct_series(sc_pcts, int(row["player_id"]), int(row["competition_id"]), sid)
    chart_metrics = ([m for m in _club_metrics_for(position, archetype)[0]
                      if prow is not None and m in prow.index and pd.notna(prow[m])]
                     if prow is not None else [])
    if len(chart_metrics) >= 3:
        st.markdown("##### Performance profile (percentile vs peers)")
        view = st.radio("View", ["Bars", "Radar"], horizontal=True, key=f"{key_prefix}_view")
        values = [float(prow[m]) for m in chart_metrics]
        chart = (bar_chart(chart_metrics, values) if view == "Bars"
                 else radar_chart([(row["player_name"], values)], chart_metrics))
        st.plotly_chart(chart, width="stretch", config=PLOTLY_CONFIG, key=f"{key_prefix}_chart")

    st.divider()
    _scout_section(get_engine(), row)


def _players(tab, pool: pd.DataFrame, position: str, percentiles: pd.DataFrame, metrics: list[str],
             metric_values: pd.DataFrame, archetype: str = cf.DEFAULT_ARCHETYPE,
             show_money: bool = False, contract_horizon: str = DEFAULT_CONTRACT_HORIZON,
             contract_unknown: int = 0) -> None:
    """The one workspace: a composite-ranked list of players (master) with a full player
    detail (detail) opened by clicking a row or searching. Money is an opt-in layer."""
    with tab:
        lens = archetype != cf.DEFAULT_ARCHETYPE
        st.caption("Ranked by the club's **objective composite** (Performance + Physical, real data), "
                   "within the selected season and position. Click a player — or search below — for their "
                   "full detail. Money is off by default; turn on **Affordability (modelled)** in the sidebar.")
        # The contract filter hides anyone with no known expiry date, so say so plainly: contract
        # data is largely EFL-only and silence would read as "nobody else is expiring".
        if CONTRACT_HORIZONS.get(contract_horizon):
            if contract_horizon == CONTRACT_EXPIRED:
                msg = (f"**Contract filter: {contract_horizon}.** Showing {len(pool)} {position}s "
                       f"whose contract has already run out.")
            else:
                msg = (f"**Contract filter: {contract_horizon}.** Showing {len(pool)} {position}s "
                       f"still under contract today whose deal ends by "
                       f"{CONTRACT_HORIZONS[contract_horizon]}.")
            if contract_unknown:
                msg += (f" **{contract_unknown} {position}s are hidden** because we hold no contract "
                        f"date for them — contract data comes from the Transfermarkt scrape and is "
                        f"largely EFL-only, so this is *unknown*, not *not expiring*.")
            as_of = contract_data_date()
            if as_of:
                msg += (f"\n\n_Contract data as of **{as_of}** — it is a scraped snapshot, not live, "
                        f"so recent extensions or new signings may not be reflected._")
            st.info(msg)
        if lens:
            st.info(f"**Archetype lens: ranking {position}s as _{archetype}_.** The Composite is scored on "
                    f"this archetype's metrics; the **All-round** column is the full-profile composite for "
                    f"context. Change the **Archetype** in the sidebar.")
        full_pool = pool.copy()   # keep the unfiltered pool so search can reach any player

        # Assessed ranking mode: opt-in, off by default. The `else` branch below leaves the
        # default ranking (RANK_COLUMN = objective_composite) byte-for-byte unchanged.
        mode_col, check_col = st.columns([2, 2])
        assessed_mode = mode_col.toggle(
            "Rank on assessed composite", value=False,
            help="Ranks on Performance + Physical + Psychological + Medical (86% of the "
                 "framework's weight), and shows only players where a person has completed "
                 "both human dimensions. Off by default — the standard ranking is unchanged.")
        if assessed_mode:
            # A single season is passed into _players via `pool` already scoped to it (app.py
            # scores/ranks within one season); read it back rather than adding a parameter.
            season_id = int(pool["season_id"].iloc[0]) if not pool.empty else None
            # IMPORTANT 5: match the loader the rest of the page uses -- `load_scorecards`
            # always returns the 'All Metrics' rows, so with an archetype lens selected
            # (e.g. Winger / Inverted Winger) this used to silently rank on the all-round
            # Performance band instead of the archetype's. player_scorecards already stores
            # a per-archetype assessed_composite; just read the matching row.
            scorecards = (load_scorecards(season_id) if archetype == cf.DEFAULT_ARCHETYPE
                         else load_scorecards_archetype(position, archetype, season_id))
            assessed_col = scorecards[
                ["player_id", "competition_id", "season_id", "assessed_composite"]]
            pool = pool.merge(assessed_col, on=["player_id", "competition_id", "season_id"],
                              how="left")
            # attach() must run BEFORE the signed-off filter reads the column -- the Players
            # pool does not carry assessment_status otherwise, and the filter would KeyError.
            pool = assessment_status.attach(pool, load_assessment_status(season_id))
            # IMPORTANT 4: nothing on this platform hides a player. A conflicted dimension
            # has no assessed_composite (Decision 9 -- a None band on either side blocks the
            # composite), so it drops out of the ranking table below just like an unassessed
            # player would -- but unlike an unassessed player, someone DID do the work, and a
            # conflicted player must not look identical to one nobody has touched. Count them
            # here, before they are filtered out, and say so in the caption rather than
            # silently dropping them: adding a conflict-badge column to this ranking table
            # would mean carrying a second visual language (colour + badge) into a table that
            # otherwise reads as a plain numeric ranking, for a state (no rank exists yet)
            # the caption already states in words -- so the count is the fix, not a new column.
            conflicted_count = int((pool["assessment_status"] == assessment_status.CONFLICTED).sum())
            pool = pool[pool["assessed_composite"].notna()]
            rank_column = "assessed_composite"
            signed_only = check_col.checkbox(
                "Signed-off assessments only", value=False,
                help="For presenting a shortlist formally. Off by default — an unsigned "
                     "assessment still scores and still ranks.")
            if signed_only:
                pool = pool[pool["assessment_status"] == assessment_status.SIGNED_OFF]
            # An empty list here is expected, not broken -- say so plainly rather than
            # showing zero rows with no explanation.
            if pool.empty:
                msg = ("No player has both dimensions assessed yet — the assessed "
                       "ranking is empty until a scout completes Psychological and Medical.")
            else:
                msg = (f"{len(pool)} players have both human dimensions assessed. "
                       "This is a different ranking from the default, not a filter on it.")
            if conflicted_count:
                msg += (f" **{conflicted_count} assessed player"
                        f"{'s' if conflicted_count != 1 else ''} not shown** here — their "
                        "assessments conflict, so nothing scores until someone signs one off "
                        "from the sign-off queue.")
            st.caption(msg)
        else:
            rank_column = RANK_COLUMN
            signed_only = False

        # Playing-style filter + grouping.
        types = sorted(pool["cluster_label"].dropna().unique().tolist())
        fc1, fc2 = st.columns([3, 1])
        chosen = fc1.multiselect("Player type", types, default=types,
                                 help="Filter to one or more playing-style groups. Players with no "
                                      "playing-style (leagues we don't cluster) are always kept.")
        group_by_type = fc2.toggle("Group by type", value=False,
                                   help="Order by playing-style group, then by composite within each group.")
        if chosen:
            pool = pool[pool["cluster_label"].isin(chosen) | pool["cluster_label"].isna()]
        sort_cols = (["cluster_label", rank_column] if group_by_type else [rank_column])
        pool = pool.sort_values(sort_cols, ascending=[True, False] if group_by_type else False,
                                na_position="last").reset_index(drop=True)

        # Money: optional signable filter.
        only_qualifying = False
        if show_money:
            qualifying = pool[pool["qualifies"]]
            fee_ok, wage_ok = int(pool["affordable_fee"].sum()), int(pool["affordable_wage"].sum())
            st.caption(f"**{len(pool)}** {position}s · **{fee_ok}** within the transfer budget · "
                       f"**{wage_ok}** within the wage budget · **{len(qualifying)}** affordable on both.")
            only_qualifying = st.toggle("Show only signable players (fee + wage within budget)",
                                        value=not qualifying.empty)
            if only_qualifying and not qualifying.empty:
                pool = qualifying.reset_index(drop=True)
        else:
            st.caption(f"**{len(pool)}** {position}s ranked.")

        view = pool.copy().reset_index(drop=True)
        view.insert(0, "Rank", range(1, len(view) + 1))
        view["Minutes"] = view["minutes"].round(0)
        view["Measured"] = (view["objective_weight_covered"] * 100).round(0)
        if lens:
            view["All-round"] = view["allround_composite"].round(2)
        # Contract expiry is REAL scraped data (not modelled), and the free-transfer market is a
        # first-class recruitment question — so it shows by default, not only under the money layer.
        view["Contract"] = view["contract_until"].dt.strftime("%m/%Y").fillna("—")
        months_left = (view["contract_until"] - pd.Timestamp.now().normalize()).dt.days / 30.44
        view["Months left"] = months_left.round(0)
        if show_money:
            view["Market value"] = (view["market_value_eur"] / 1e6).round(1)
            view["Est. wage"] = (view["estimated_weekly_wage_gbp"] / 1000).round(1)
            view["Below fair value"] = (view["undervaluation_pct"] * 100).round(0)

        table = view.rename(columns={
            "player_name": "Player", "team_name": "Club", "league": "League", "age": "Age",
            rank_column: "Composite", "performance_band": "Performance",
            "physical_band": "Physical", "cluster_label": "Player type",
            "affordable_fee": "Fee in budget", "affordable_wage": "Wages in budget"})
        composite_label = ("Assessed composite" if assessed_mode
                           else f"Composite ({archetype})" if lens else "Composite")
        display_cols = ["Rank", "Player", "Club", "League", "Age", "Minutes", "Composite"]
        if lens:
            display_cols.append("All-round")
        display_cols += ["Performance", "Physical", "Measured", "Player type",
                         "Contract", "Months left"]
        if show_money:
            display_cols += ["Market value", "Est. wage", "Below fair value",
                             "Fee in budget", "Wages in budget"]

        band = lambda lbl, hlp: st.column_config.ProgressColumn(lbl, help=hlp, min_value=1, max_value=5, format="%.2f")
        composite_help = ("Performance + Physical + Psychological + Medical (1-5) — the "
                          "assessed ranking, opt-in.") if assessed_mode else \
                         "The club's objective composite (1-5) — the ranking."
        col_cfg = {
            "Age": st.column_config.NumberColumn("Age", format="%.1f"),
            "Minutes": st.column_config.NumberColumn("Minutes", format="%d"),
            "Composite": band(composite_label, composite_help),
            "All-round": band("All-round", "Full-profile composite (All Metrics), for context."),
            "Performance": band("Performance", "The club-framework Performance dimension (1-5)."),
            "Physical": band("Physical", "The club-framework Physical dimension (1-5), where tracking exists."),
            "Measured": st.column_config.NumberColumn(
                "Measured %", help="Share of the composite that could be measured from data.", format="%d%%"),
            "Player type": st.column_config.TextColumn("Player type", help="Playing-style archetype."),
            "Contract": st.column_config.TextColumn(
                "Contract", help="Contract expiry (MM/YYYY) from Transfermarkt. '—' = not known "
                                 "(contract data is largely EFL-only)."),
            "Months left": st.column_config.NumberColumn(
                "Months left", help="Months from today until the contract expires. Under 6 = he can "
                                    "sign a pre-contract elsewhere. Negative = already expired.",
                format="%d"),
        }
        style = table
        if show_money:
            col_cfg |= {
                "Market value": st.column_config.NumberColumn("Market value", help="Transfermarkt (modelled context).", format="€%.1fm"),
                "Est. wage": st.column_config.NumberColumn("Est. wage", help="Modelled weekly wage (£ thousands).", format="£%.1fk"),
                "Contract": st.column_config.TextColumn("Contract", help="Contract end (Transfermarkt)."),
                "Below fair value": st.column_config.NumberColumn("Below fair value", help="How far under fair value the market prices them.", format="%d%%"),
                "Fee in budget": st.column_config.CheckboxColumn("Fee in budget", help="Transfer fee fits the budget."),
                "Wages in budget": st.column_config.CheckboxColumn("Wages in budget", help="Modelled wage fits the ceiling."),
            }
            def _tint(r):
                return [f"background-color: {'#E9F7EE' if r['qualifies'] else '#FFF6EA'}"] * len(r)
            style = table.style.apply(_tint, axis=1)
            st.caption("🟢 affordable (fee + wage in budget) · 🟠 outside budget.")

        # Byte-for-byte identical to the pre-existing key when assessed_mode is off (Rule A):
        # the suffix only appears once the opt-in ranking mode is engaged.
        mode_suffix = f"_{assessed_mode}_{signed_only}" if assessed_mode else ""
        base_key = (f"players_{position}_{archetype}_{show_money}_{only_qualifying}_"
                   f"{group_by_type}_{'|'.join(chosen)}{mode_suffix}")
        selection = st.dataframe(
            style, column_order=display_cols, hide_index=True, width="stretch", height=560,
            on_select="rerun", selection_mode="single-row", key=_selectable_key(base_key), column_config=col_cfg)

        export = table[[c for c in display_cols if c != "Rank"]].copy()
        export.insert(0, "Rank", table["Rank"])
        st.download_button("⬇ Download this list (CSV)", data=export.to_csv(index=False).encode("utf-8"),
                           file_name=f"lofc_players_{position.lower().replace(' ', '_')}.csv", mime="text/csv",
                           help="Saves exactly what is on screen.")

        # --- detail: a clicked row, else a searched player -----------------------------
        rows = list(selection.selection.rows) if selection and selection.selection else []
        labels, by_label = _player_options(full_pool)
        detail_row = None
        if rows and rows[0] < len(view):
            detail_row = view.iloc[rows[0]]
        else:
            sc1, sc2 = st.columns([6, 1], vertical_alignment="bottom")
            picked = sc1.selectbox("Or search any player for their full detail", labels, index=None,
                                   placeholder="Search for a player…", key=f"players_search_{position}")
            sc2.button("✕ Clear", key=f"players_search_clear_{position}", width="stretch",
                       on_click=lambda: st.session_state.update({f"players_search_{position}": None}),
                       disabled=not st.session_state.get(f"players_search_{position}"))
            if picked and picked in by_label:
                detail_row = full_pool.loc[by_label[picked]]

        if detail_row is not None:
            st.divider()
            pc1, pc2 = st.columns([5, 1], vertical_alignment="bottom")
            pc1.markdown("#### Player detail")
            with pc2:
                _clear_selection_button(base_key, label="✕ Close")
            _render_profile_body(detail_row, percentiles, metrics, metric_values, key_prefix="detail",
                                 archetype=archetype, show_money=show_money)
        else:
            st.caption("⬆️ Click a player in the table, or search above, to open their full detail.")


def _dimension_status(frame: pd.DataFrame, dimension: str) -> str | None:
    """See `assessment_detail.dimension_status` -- one shared implementation so the profile
    and the sign-off queue can never derive the Decision 17 verdict two different ways."""
    return assessment_detail.dimension_status(frame, dimension)


def _scout_section(engine, row) -> None:
    """The two human bands, who entered them, who approved them, and when.

    Shows EVERY assessment, not just the one that scores: two assessors who disagree must
    both be visible, because Decision 14 accepts an unsigned assessment moving the ranking
    only on the basis that the competing view is on the page. Rendered as one table per
    dimension (Problem 2) rather than a stack of cards -- tabular and scannable across
    however many scouts have weighed in, with the per-criterion breakdown one click away
    in an expander rather than always on screen.

    B5 (task 10): where a dimension is CONTESTED, this shows the conflict badge -- not a
    band, and not silently one of the competing assessments -- alongside every competing
    assessment, exactly as the non-conflicted branch already does. Nothing is hidden either
    way; only the badge and caption differ. A rejected assessment (Problem 3) stays in the
    table and its reason is surfaced by `assessment_detail.render_flags`, so the scout who
    entered it can see it was declined and why, and submit a fresh one.
    """
    st.markdown("#### Scout assessment")
    frame = store_assess.load_for_player(engine, int(row["player_id"]),
                                         int(row["competition_id"]), int(row["season_id"]))
    position = row.get("position_group")
    if frame.empty:
        badges.render(badges.for_status(None))
        st.caption("No psychological or medical assessment has been recorded for this "
                   "player-season.")
    else:
        for dimension in (scout_scores.PSYCHOLOGICAL, scout_scores.MEDICAL):
            dim_rows = frame[frame["dimension"] == dimension]
            st.markdown(f"**{dimension}**")
            if dim_rows.empty:
                badges.render(badges.for_status(None))
                continue
            entries = list(dim_rows.itertuples())
            status = _dimension_status(frame, dimension)
            scoring = [e for e in entries if e.status in ("submitted", "signed_off")]
            if status == scout_scores.CONFLICT:
                badges.render(badges.for_status(scout_scores.CONFLICT))
                st.caption(f"{len(scoring)} assessments disagree. Nobody has signed one off, "
                           "so none of them scores this dimension. Resolve it from the "
                           "sign-off queue.")
            elif len(entries) > 1:
                # Which one scores depends on `status` (Decision 17): a signed-off row always
                # wins regardless of how many others exist; short of that, exactly one
                # `submitted` row scores. Naming the true winner here, rather than always
                # saying "the signed-off one", matters once a rejection can leave a single
                # ordinary `submitted` row sitting beside others that no longer score.
                winner_desc = ("the signed-off one scores" if status == "signed_off"
                              else "the submitted one scores" if status == "submitted"
                              else "none of them currently scores")
                st.caption(f"{len(entries)} assessment{'s' if len(entries) != 1 else ''} "
                           f"exist for this dimension. {winner_desc[0].upper()}"
                           f"{winner_desc[1:]}; the others stay on the record, attributed.")
            st.dataframe(assessment_detail.entries_table(dim_rows), hide_index=True,
                        width="stretch", key=f"assess_table_{row['player_id']}_"
                        f"{row['competition_id']}_{row['season_id']}_{dimension}")
            assessment_detail.render_flags(entries)
            assessment_detail.render_criterion_detail(
                engine, str(position) if pd.notna(position) else None, dimension, entries)

    minutes = row.get("minutes")
    evidence.render(engine, int(row["player_id"]), int(row["competition_id"]),
                    int(row["season_id"]), int(minutes) if pd.notna(minutes) else None)

    if st.button("Assess this player", key=f"assess_{row['player_id']}"):
        # Any authenticated user may assess either dimension (Decision 16). Carry the whole
        # player-season, not just the id, so the Assess page opens the form directly rather
        # than making the assessor search for the player a second time.
        minutes = row.get("minutes")
        go_to_assess(CarriedPlayer(
            player_id=int(row["player_id"]), player_name=str(row["player_name"]),
            competition_id=int(row["competition_id"]), season_id=int(row["season_id"]),
            position_group=str(row["position_group"]),
            minutes=int(minutes) if pd.notna(minutes) else None))


def _player_options(pool: pd.DataFrame) -> tuple[list[str], dict[str, int]]:
    """Selectbox labels 'Name — Club' and a label -> pool-index map.

    The club in the label disambiguates genuine namesakes (two different players
    with the same name), which a bare-name lookup would silently conflate.
    """
    labels, by_label = [], {}
    for idx, r in pool.iterrows():
        label = f"{r['player_name']} — {r['team_name']}"
        labels.append(label)
        by_label[label] = idx
    return labels, by_label
