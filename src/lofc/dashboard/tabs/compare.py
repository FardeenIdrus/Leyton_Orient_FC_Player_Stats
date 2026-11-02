"""The Compare tab: two or three players head-to-head.

A summary table, two radars (the High/Mid-weighted Performance metrics and the rating's
Physical metrics, as within-league percentiles, so the picture matches the composite), then a
Performance and a Physical table: every rating metric as a row with each player's value and
percentile, best green and worst red (`compare_tables`)."""

from __future__ import annotations

import html
import re

import pandas as pd
import streamlit as st

from lofc.dashboard.charts import PLOTLY_CONFIG, radar_chart
from lofc.dashboard.formatting import value_or_dash
from lofc.dashboard import compare_tables as ct
from lofc.dashboard.loaders import (
    competition_name_by_id, load_candidates, load_previous_ratings, load_scorecards,
    load_scorecard_percentiles, load_style_labels)
from lofc.dashboard.search import search_options
from lofc.dashboard.search_target import resolve_search_target
from lofc.dashboard.tabs.players import _sc_pct_series
from lofc.dashboard.theme import NONE_OPTION, RED
from lofc.model import club_framework as cf

# slot name -> session_state key of its selectbox
_SLOT_KEYS = {"Player A": "cmp_a", "Player B": "cmp_b", "Player C": "cmp_c"}


_KEYS = ["player_id", "competition_id", "season_id"]


def apply_compare_pick(state, search_index: pd.DataFrame, by_label: dict[str, int],
                       position: str, slot_key: str) -> None:
    """A slot's on_change logic (a plain function so it can be tested with a dict).

    Every slot lists every player of the season, but a comparison is strictly one position. If
    the player just picked into `slot_key` is of another position than the sidebar's, the
    sidebar switches to it (and his league is added if filtered out) and every OTHER slot is
    reset: they hold players of the old position, and keeping them would compare across
    positions. A and B then fall back to their defaults, C to "none". Must run as an on_change
    callback: the sidebar widgets are already instantiated by the time the page body runs, and
    Streamlit refuses writes to their keys then (same mechanism as the Players page search)."""
    picked = state.get(slot_key)
    if not picked or picked not in by_label:
        return
    trow = search_index.iloc[by_label[picked]]
    if str(trow["position_group"]) == position:
        return
    state["sidebar_position"] = str(trow["position_group"])
    current_leagues = list(state.get("sidebar_leagues", []))
    league = trow["league"]
    if pd.notna(league) and league != "—" and league not in current_leagues:
        state["sidebar_leagues"] = current_leagues + [league]
    for key in _SLOT_KEYS.values():
        if key != slot_key:
            if key == "cmp_c":
                state[key] = NONE_OPTION
            else:
                state.pop(key, None)


def default_candidates(pool: pd.DataFrame, search_index: pd.DataFrame, position: str) -> list[str]:
    """Search labels to default A/B from: the pool in its (rating) order, then the rest of the
    position, so two defaults exist even when the sidebar filters leave fewer than two."""
    by_key = {(int(r.player_id), int(r.competition_id), int(r.season_id)): r.label
              for r in search_index.itertuples()}
    out = [by_key[k] for k in zip(pool["player_id"].astype(int), pool["competition_id"].astype(int),
                                  pool["season_id"].astype(int)) if k in by_key]
    rest = search_index.loc[search_index["position_group"] == position, "label"]
    return list(dict.fromkeys(out + rest.tolist()))


def fill_default_slots(state, labels: list[str]) -> None:
    """Give A and B a default when unset, never the same player as each other or as C
    (verifier, 2026-11-02: picking the player at index 1 into A left B defaulting to index 1)."""
    def taken(*keys):
        return {state.get(k) for k in keys if state.get(k) not in (None, NONE_OPTION)}
    if "cmp_a" not in state:
        skip = taken("cmp_b", "cmp_c")
        state["cmp_a"] = next((x for x in labels if x not in skip), labels[0])
    if "cmp_b" not in state:
        skip = taken("cmp_a", "cmp_c")
        state["cmp_b"] = next((x for x in labels if x not in skip), labels[0])


def row_for_label(label: str, search_index: pd.DataFrame, by_label: dict[str, int],
                  pool: pd.DataFrame) -> pd.Series | None:
    """The player's row for a slot label: from the filtered pool when he is in it, otherwise
    resolved from the season-wide data so a pick hidden by age / league / contract / minutes
    filters still shows. None when he cannot be found."""
    t = search_index.iloc[by_label[label]]
    key = tuple(int(t[k]) for k in _KEYS)
    hit = pool[(pool["player_id"] == key[0]) & (pool["competition_id"] == key[1])
               & (pool["season_id"] == key[2])]
    if not hit.empty:
        return hit.iloc[0]
    # Default wage multiplier: money columns are only shown when the sidebar money layer is on,
    # and the row is used for display, never for ranking.
    row, _ = resolve_search_target(load_candidates(1.0, key[2]), load_scorecards(key[2]), key)
    return row


def sanitize_slots(state, labels: list[str]) -> None:
    """Drop slot values that are not of the sidebar's position (`labels` = that position's
    search labels), e.g. after the sidebar position changed, so they fall back to their default."""
    for key in _SLOT_KEYS.values():
        if key in state and state[key] not in labels and state[key] != NONE_OPTION:
            if key == "cmp_c":
                state[key] = NONE_OPTION
            else:
                state.pop(key)


def same_position(frame: pd.DataFrame) -> bool:
    """True when every row is one position -- comparisons are strictly like-for-like."""
    return frame["position_group"].nunique(dropna=False) <= 1


# Colours for the season-change cells (readable on both light and dark themes).
UP_STYLE = "color: #1a9850; font-weight: 600"
DOWN_STYLE = "color: #d73027; font-weight: 600"
NEUTRAL_STYLE = "color: #888888"

# Physical axes of the radar: the rating's physical metrics, minus "Average match top speed"
# (psv99_kmh), which the Head of Recruitment does not want shown; top5 is labelled "Top speed".
_PHYS_RADAR_LABEL = {
    "distance_p90": "Distance", "meters_per_minute": "Metres per minute",
    "hsr_count_p90": "High-speed runs", "hsr_distance_p90": "High-speed distance",
    "sprint_count_p90": "Sprints", "sprint_distance_p90": "Sprint distance",
    "top5_psv99_kmh": "Top speed",
}


def season_change(prev, now, fmt: str = "{:.2f}") -> str:
    """"3.41 → 3.68 (+0.27)". The change is taken from the displayed (rounded) numbers so the
    three figures always add up on screen. No previous season: this season's value alone."""
    now_txt = value_or_dash(now, fmt)
    if pd.isna(prev):
        return now_txt
    prev_txt = value_or_dash(prev, fmt)
    if pd.isna(now):
        return f"{prev_txt} → —"
    delta = float(fmt.format(now)) - float(fmt.format(prev))
    delta_txt = "0.00" if abs(delta) < 0.005 else f"{delta:+.2f}"
    return f"{prev_txt} → {now_txt} ({delta_txt})"


def change_style(cell) -> str:
    """CSS for a season-change cell: green if it rose, red if it fell, grey otherwise (equal,
    no previous season, blank). Reads the sign the text itself carries."""
    text = str(cell)
    if text.endswith("(0.00)") or not text.endswith(")"):
        return NEUTRAL_STYLE
    if "(+" in text:
        return UP_STYLE
    return DOWN_STYLE if "(-" in text else NEUTRAL_STYLE


# "3.41 (League Two) → 3.68 (+0.27)" -> prev, previous league, now, change. The text format is
# owned by `season_change`/`compare_row` above, so this is the one place that reads it back.
_CHANGE_RE = re.compile(r"^(?:(?P<prev>\S+?)(?: \((?P<lg>.+?)\))? → )?(?P<now>\S+?)"
                        r"(?: \((?P<delta>[+-]?\d+\.\d+)\))?$")

_CSS = f"""
<style>
.lofc-cmp {{ width: 100%; table-layout: fixed; border-collapse: collapse; margin: .2rem 0 .6rem; }}
.lofc-cmp th, .lofc-cmp td {{ padding: .5rem .7rem; text-align: left; vertical-align: top;
  border-bottom: 1px solid #D9DCE0; overflow-wrap: anywhere; }}
.lofc-cmp thead th {{ border-bottom: 2px solid {RED}; font-weight: 400; }}
.lofc-cmp .k {{ width: 16%; font-size: .85rem; font-weight: 600; color: #3C4048;
  vertical-align: middle; }}
.lofc-cmp .nm {{ display: block; font-size: 1.15rem; font-weight: 800; letter-spacing: -.02em;
  color: #14161A; line-height: 1.15; }}
.lofc-cmp .sm {{ display: block; font-size: .8rem; color: #5A6068; margin-top: .1rem; }}
.lofc-cmp .v {{ font-size: 1.15rem; font-weight: 600; color: #14161A;
  font-variant-numeric: tabular-nums; }}
.lofc-cmp .t {{ font-size: .9rem; color: #14161A; }}
.lofc-cmp .t.warn {{ color: #b3261e; }}
.lofc-cmp .ch {{ display: block; font-size: .78rem; margin-top: .1rem;
  font-variant-numeric: tabular-nums; }}
</style>
"""


def _value_cell(text: str) -> str:
    """One body cell: this season's value large, the change from last season small beneath it
    (green up, red down, grey otherwise -- `change_style` reads the sign)."""
    m = _CHANGE_RE.match(text)
    if not m:
        return f'<td><span class="v">{html.escape(text)}</span></td>'
    now, prev, lg, delta = m["now"], m["prev"], m["lg"], m["delta"]
    sub = ""
    if prev is not None:
        was = html.escape(prev + (f" ({lg})" if lg else ""))
        if delta is None:
            sub = f"was {was}"
        else:
            sub = (f"no change vs {was}" if delta == "0.00" else f"{html.escape(delta)} vs {was}")
    style = f' style="{change_style(text)}"' if sub else ""
    return (f'<td><span class="v">{html.escape(now)}</span>'
            + (f'<span class="ch"{style}>{sub}</span>' if sub else "") + "</td>")


# Summary rows that are plain text (not "value + change vs last season"), in display order:
# status above the ratings, history / style / scouts below them.
_TEXT_ROWS_TOP = ()   # Club now / Contract to / Loan removed (owner, 2026-11-02)
_TEXT_ROWS_BOTTOM = ("Rating trend", "Playing style", "Scout verdicts")


def _text_cell(text: str, warn: bool = False) -> str:
    return f'<td><span class="t{" warn" if warn else ""}">{html.escape(text)}</span></td>'


def comparison_html(rows: list[dict]) -> str:
    """The head-to-head as an HTML table: players are COLUMNS, attributes are ROWS, so it fits
    the page width with no sideways scroll however many players (2-3). Every value is escaped.
    A row's `_warn` (set of attribute names) marks a text cell in red."""
    head = "".join(
        f'<th><span class="nm">{html.escape(str(r["Player"]))}</span>'
        f'<span class="sm">{html.escape(" · ".join(x for x in (str(r.get("Club") or ""), str(r.get("League") or "")) if x))}'
        "</span></th>" for r in rows)
    attrs = [k for k in ("Age", "Minutes", *_TEXT_ROWS_TOP, "Overall", "Performance", "Physical",
                         "Market (€m)", *_TEXT_ROWS_BOTTOM)
             if any(k in r for r in rows)]
    text_rows = _TEXT_ROWS_TOP + _TEXT_ROWS_BOTTOM

    def cell(k, r):
        if k in text_rows:
            return _text_cell(str(r.get(k, "—")), k in r.get("_warn", ()))
        return _value_cell(str(r.get(k, "—")))

    body = "".join(
        f'<tr><th class="k" scope="row">{html.escape(k)}</th>'
        + "".join(cell(k, r) for r in rows) + "</tr>" for k in attrs)
    return (f'{_CSS}<table class="lofc-cmp"><thead><tr><th class="k"></th>{head}</tr></thead>'
            f"<tbody>{body}</tbody></table>")


def physical_radar_inputs(pcts_by_label: dict, position: str):
    """(axes, traces, missing) for the physical radar.

    `pcts_by_label` maps a player name to his scorecard-percentile Series (or None). Axes are the
    rating's physical metrics (club_framework.PHYSICAL_METRICS) minus psv99_kmh, as display
    labels, present for EVERY player who has data. A player with fewer than three physical
    percentiles (SkillCorner does not cover everyone) is returned in `missing`, not plotted."""
    metrics = [m for m in cf.PHYSICAL_METRICS.get(position, []) if m in _PHYS_RADAR_LABEL]
    if not metrics:
        return [], [], []
    have, missing = {}, []
    for name, s in pcts_by_label.items():
        vals = {m: s[m] for m in metrics if s is not None and m in s.index and pd.notna(s[m])}
        if len(vals) >= 3:
            have[name] = vals
        else:
            missing.append(name)
    shared = [m for m in metrics if all(m in v for v in have.values())] if have else []
    if len(shared) < 3:
        return [], [], missing + ([] if not have else list(have))
    axes = [_PHYS_RADAR_LABEL[m] for m in shared]
    return axes, [(n, [float(v[m]) for m in shared]) for n, v in have.items()], missing


def no_physical_caption(names: list[str]) -> str:
    return "No physical data: " + ", ".join(names)


def compare_row(r: pd.Series, prev: pd.DataFrame | None, show_money: bool = False) -> dict:
    """One row of the head-to-head table. A bare st.dataframe prints the literal "None" for a
    missing cell, so every value is pre-formatted text with an em-dash fallback. Overall,
    Performance and Physical read "last season → this season (change)"."""
    prev_row = pd.Series(dtype=object)
    if prev is not None and not prev.empty:
        hit = prev[prev["player_id"] == int(r["player_id"])]
        if not hit.empty:
            prev_row = hit.iloc[0]
    league_now = r.get("league")

    def cell(prev_col, now_col, league_note=False):
        text = season_change(prev_row.get(prev_col), r.get(now_col))
        prev_league = prev_row.get("prev_league")
        # Only name the league when it differs: a move up or down a division changes what the
        # number means, so the reader needs to see it.
        if league_note and " → " in text and pd.notna(prev_league) and prev_league != league_now:
            head, tail = text.split(" → ", 1)
            text = f"{head} ({prev_league}) → {tail}"
        return text

    row = {"Player": r["player_name"], "Club": r["team_name"],
           "League": value_or_dash(r.get("league"), "{}"),
           "Age": value_or_dash(r.get("age"), "{:.1f}"),
           "Minutes": value_or_dash(r.get("minutes"), "{:,.0f}"),
           "Overall": cell("prev_composite", "objective_composite", True),
           "Performance": cell("prev_performance", "performance_band"),
           "Physical": cell("prev_physical", "physical_band")}
    if show_money:
        market_eur = r.get("market_value_eur")
        row["Market (€m)"] = value_or_dash(
            market_eur / 1e6 if pd.notna(market_eur) else market_eur, "{:.1f}")
    return row


def _safe(fn, default):
    """A display extra must never take the page down: any failure reads as "no data"."""
    try:
        return fn()
    except Exception:                                     # noqa: BLE001
        return default


def summary_extras(r: pd.Series, ctx: dict) -> dict:
    """The status / history / style / scout rows of one player's summary column.
    `ctx` holds the already-loaded (cached) frames, keyed by player id; every value is text and
    a missing source reads "—"."""
    pid, cid, sid = int(r["player_id"]), int(r["competition_id"]), int(r["season_id"])
    hist = ctx.get("history", {}).get(pid, [])
    points = [*hist, (sid, r.get("objective_composite"), r.get("league"))]
    out = {
        "Rating trend": ct.rating_trend_text(points, r.get("league")),
        "Playing style": ct.style_text(ctx.get("styles", {}).get((pid, cid))),
        "Scout verdicts": ct.scout_text(ctx.get("scouts", {}).get(pid)),
    }
    return out


def _extras_context(pids: tuple[int, ...], season_id: int) -> dict:
    """Load (all cached) what the extra summary rows read, narrowed to the compared players."""
    styles = _safe(lambda: load_style_labels(season_id), pd.DataFrame())
    hist = _safe(lambda: ct.load_rating_history(season_id), pd.DataFrame())
    scouts = _safe(lambda: ct.load_scout_verdicts(pids), pd.DataFrame())
    ctx: dict = {"styles": {}, "history": {}, "scouts": {}}
    if not styles.empty and "player_id" in styles.columns:
        st_rows = styles[styles["player_id"].isin(pids)]
        ctx["styles"] = {(int(x["player_id"]), int(x["competition_id"])): x
                         for _, x in st_rows.iterrows()}
    if not hist.empty:
        names = competition_name_by_id()
        for pid, grp in hist[hist["player_id"].isin(pids)].groupby("player_id"):
            ctx["history"][int(pid)] = [
                (int(x.season_id), x.objective_composite, names.get(int(x.competition_id)))
                for x in grp.sort_values("season_id").itertuples()]
    if not scouts.empty:
        for pid, grp in scouts.groupby("player_id"):
            ctx["scouts"][int(pid)] = list(grp["verdict"])
    return ctx


def _mv_series(metric_values: pd.DataFrame | None, r: pd.Series) -> pd.Series | None:
    """The player's per-90 / physical values in his league (None when not held)."""
    if metric_values is None or metric_values.empty:
        return None
    mv = metric_values[(metric_values["player_id"] == int(r["player_id"]))
                       & (metric_values["competition_id"] == int(r["competition_id"]))]
    return mv.iloc[0] if not mv.empty else None


def _compare(tab, pool: pd.DataFrame, position: str, archetype: str,
             season_id: int, show_money: bool = False,
             metric_values: pd.DataFrame | None = None,
             search_index: pd.DataFrame | None = None) -> None:
    with tab:
        if search_index is None or search_index.empty:
            st.warning("No players for this season.")
            return

        # Every slot lists every player of the season (all positions, accent-folded labels, as
        # on the Players page); comparisons stay one position, see `apply_compare_pick`.
        all_labels, by_label = search_options(search_index)
        same_pos = search_index.loc[search_index["position_group"] == position, "label"].tolist()
        if len(same_pos) < 2:
            st.warning("Need at least two players in this position.")
            return
        sanitize_slots(st.session_state, same_pos)
        fill_default_slots(st.session_state, default_candidates(pool, search_index, position))
        slot_args = (st.session_state, search_index, by_label, position)
        c1, c2, c3 = st.columns(3)
        a = c1.selectbox("Player A", all_labels, key="cmp_a", on_change=apply_compare_pick,
                         args=(*slot_args, "cmp_a"))
        b = c2.selectbox("Player B", all_labels, key="cmp_b", on_change=apply_compare_pick,
                         args=(*slot_args, "cmp_b"))
        c = c3.selectbox("Player C (optional)", [NONE_OPTION] + all_labels, key="cmp_c",
                         on_change=apply_compare_pick, args=(*slot_args, "cmp_c"))

        chosen = [p for p in [a, b, (c if c != NONE_OPTION else None)] if p]
        chosen = list(dict.fromkeys(chosen))  # de-duplicate, keep order
        if len(chosen) < 2:
            st.info("Pick two different players to compare.")
            return

        recs = [row_for_label(lbl, search_index, by_label, pool) for lbl in chosen]
        if any(r is None for r in recs):
            st.info("One of these players has no data for this season.")
            return
        if len({r["position_group"] for r in recs}) > 1:
            st.error("Compare like with like: these players are not all in one position.")
            return

        # Percentiles come from the scorecard (position + league + season), the same source the
        # player profile and the composite use, so Compare agrees with the rest of the platform.
        sc_pcts = load_scorecard_percentiles(season_id)
        prev = load_previous_ratings(season_id)
        # Column heads: the name, plus the club only when two players share a name.
        raw = [r["player_name"] for r in recs]
        names = [f'{n} ({r["team_name"]})' if raw.count(n) > 1 else n for n, r in zip(raw, recs)]
        pcts = {n: _sc_pct_series(sc_pcts, int(r["player_id"]), int(r["competition_id"]),
                                  int(r["season_id"])) for n, r in zip(names, recs)}
        values = {n: _mv_series(metric_values, r) for n, r in zip(names, recs)}
        ctx = _extras_context(tuple(int(r["player_id"]) for r in recs), season_id)
        rows = [{**compare_row(r, prev, show_money), **summary_extras(r, ctx)} for r in recs]

        st.markdown(comparison_html(rows), unsafe_allow_html=True)
        st.caption("Big number: this season. Small: change from last season (green up, red down).")

        lens = archetype != cf.DEFAULT_ARCHETYPE
        different_leagues = len({int(r["competition_id"]) for r in recs}) > 1
        has_physical = bool(cf.PHYSICAL_METRICS.get(position))

        # --- radars side by side (they stack on a narrow screen) -----------------------------
        left, right = st.columns(2)
        with left:
            st.markdown("##### Performance" + (f" · {archetype}" if lens else ""))
            axes, traces, no_data = ct.radar_inputs(pcts, ct.radar_metrics(position, archetype))
            if traces:
                st.plotly_chart(radar_chart(traces, axes), width="stretch", config=PLOTLY_CONFIG)
            if no_data:
                st.caption("No percentiles for " + ", ".join(no_data) + ".")
            if different_leagues:
                st.caption("Different leagues: percentiles are within each player's own league.")
        with right:
            if has_physical:
                st.markdown("##### Physical")
                phys_axes, phys_traces, no_phys = physical_radar_inputs(pcts, position)
                if phys_traces:
                    st.plotly_chart(radar_chart(phys_traces, phys_axes), width="stretch",
                                    config=PLOTLY_CONFIG)
                if no_phys:
                    st.caption(no_physical_caption(no_phys))

        # --- Packing zones: one pitch per player, side by side ---------------------------------
        _zones_section(recs, names)

        # --- Performance table: the rating's metrics (tier shown), the rest in an expander ----
        st.markdown("##### Performance")
        rated = ct.rating_metrics(position, archetype)
        tiers = dict(rated)
        st.markdown(ct.table_html(names, ct.build_rows(
            [m for m, _ in rated], tiers, names, values, pcts)), unsafe_allow_html=True)
        value_cols = metric_values.columns if metric_values is not None else []
        other = ct.other_performance_metrics(
            position, archetype, [m for m in sc_pcts.columns if m in value_cols])
        other_rows = ct.build_rows(other, {}, names, values, pcts, drop_empty=True)
        if other_rows:
            with st.expander("Other metrics"):
                st.markdown(ct.table_html(names, other_rows), unsafe_allow_html=True)

        # --- Physical table (SkillCorner; goalkeepers have none) --------------------------------
        # Nothing at all when no compared player has physical data: the radar's caption
        # already names them (one message, not two).
        phys_rows = (ct.build_rows(ct.physical_rating_metrics(position), {}, names, values,
                                   pcts, drop_empty=True) if has_physical else [])
        if phys_rows:
            st.markdown("##### Physical")
            st.markdown(ct.table_html(names, phys_rows), unsafe_allow_html=True)
            more = ct.build_rows(ct.other_physical_metrics(position), {}, names, values, pcts,
                                 drop_empty=True)
            if more:
                with st.expander("Other metrics"):
                    st.markdown(ct.table_html(names, more), unsafe_allow_html=True)


def _zones_section(recs: list, names: list[str]) -> None:
    """Impect's packing zones, one pitch per player (the player card's pitch), one measure
    selector for all. A failure here reads as "no zone data", never a broken page."""
    if not _safe(lambda: ct.zone_has_data(recs), False):
        return           # no zone data for any of them (e.g. a league without Impect detail)
    st.markdown("##### Packing zones")
    family = st.selectbox("Measure", ct.ZONE_FAMILIES, key="cmp_zone_family",
                          format_func=lambda f: ct.ZONE_FAMILY_LABELS[f])
    cells = _safe(lambda: ct.zone_panels(recs, family), [None] * len(recs))
    any_missing = any(c is not None and ct.zone_missing(c) for c in cells)
    for col, name, c in zip(st.columns(len(recs)), names, cells):
        with col:
            st.markdown(f'<div style="font-weight:700;margin-bottom:.3rem">'
                        f'{html.escape(name)}</div>', unsafe_allow_html=True)
            if c is None:
                st.caption("No zone data for this measure.")
            else:
                # Our own generated HTML (every text value escaped), never user input.
                st.iframe(ct.zone_pitch_html(c, any_missing,
                                             frame_height=ct.ZONE_FRAME_HEIGHT[len(recs)]),
                          height=ct.ZONE_FRAME_HEIGHT[len(recs)])
    st.markdown(ct.zone_legend_html(any_missing), unsafe_allow_html=True)
    st.caption("Per 90. Colour: percentile vs the same position in each player's own league. "
               "Hover a zone for its percentile.")
