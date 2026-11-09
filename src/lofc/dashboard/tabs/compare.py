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
from lofc.dashboard.seasons import season_name_for
from lofc.dashboard.tabs.players import _sc_pct_series
from lofc.dashboard.theme import NONE_OPTION, RED
from lofc.model import club_framework as cf

# The page's logic lives in lofc.core.compare (one implementation for Streamlit and the web);
# this module draws it. Names are re-exported so callers and tests keep working.
from lofc.core.compare import (  # noqa: E402,F401
    CHANGE_RE as _CHANGE_RE, DOWN_STYLE, NEUTRAL_STYLE, PHYS_RADAR_LABEL as _PHYS_RADAR_LABEL,
    SLOT_KEYS as _SLOT_KEYS, TEXT_ROWS_BOTTOM as _TEXT_ROWS_BOTTOM,
    TEXT_ROWS_TOP as _TEXT_ROWS_TOP, TONE_STYLE, UP_STYLE, change_parts, change_style,
    compare_row, compare_view, default_candidates, fill_default_slots, mv_series as _mv_series,
    no_physical_caption, physical_radar_inputs, safe as _safe, same_position, sanitize_slots,
    season_change, summary_attributes, summary_extras)
from lofc.core import compare as _core  # noqa: E402

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


def row_for_label(label: str, search_index: pd.DataFrame, by_label: dict[str, int],
                  pool: pd.DataFrame) -> pd.Series | None:
    """The player's row for a slot label: from the filtered pool when he is in it, otherwise
    resolved from the season-wide data so a pick hidden by age / league / contract / minutes
    filters still shows. None when he cannot be found."""
    t = search_index.iloc[by_label[label]]
    key = tuple(int(t[k]) for k in _KEYS)
    row, _reason = _core.pick_row(key, pool, lambda s: load_candidates(1.0, s), load_scorecards)
    return row


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
    (green up, red down, grey otherwise -- `core.compare.change_parts` reads the text)."""
    p = change_parts(text)
    sub = (f'<span class="ch" style="{TONE_STYLE[p["tone"]]}">{html.escape(p["sub"])}</span>'
           if p["sub"] else "")
    return f'<td><span class="v">{html.escape(p["now"])}</span>{sub}</td>'


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
    attrs = summary_attributes(rows)
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


def _extras_context(pids: tuple[int, ...], season_id: int) -> dict:
    """Load (all cached) what the extra summary rows read, narrowed to the compared players."""
    return _core.extras_context(pids, season_id, load_style_labels, ct.load_rating_history,
                                ct.load_scout_verdicts, competition_name_by_id)


def _compare(tab, pool: pd.DataFrame, position: str, archetype: str,
             season_id: int, show_money: bool = False,
             metric_values: pd.DataFrame | None = None,
             search_index: pd.DataFrame | None = None) -> None:
    with tab:
        if search_index is None or search_index.empty:
            st.warning(_core.NO_PLAYERS)
            return

        # Every slot lists every player of the season (all positions, accent-folded labels, as
        # on the Players page); comparisons stay one position, see `apply_compare_pick`.
        all_labels, by_label = search_options(search_index)
        same_pos = search_index.loc[search_index["position_group"] == position, "label"].tolist()
        if len(same_pos) < 2:
            st.warning(_core.NEED_TWO)
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
            st.info(_core.PICK_TWO)
            return

        recs = [row_for_label(lbl, search_index, by_label, pool) for lbl in chosen]
        if any(r is None for r in recs):
            st.info(_core.NO_DATA)
            return
        if len({r["position_group"] for r in recs}) > 1:
            st.error(_core.NOT_LIKE)
            return

        ctx = _extras_context(tuple(int(r["player_id"]) for r in recs), season_id)
        v = compare_view(recs, position, archetype, show_money, metric_values,
                         load_scorecard_percentiles(season_id), load_previous_ratings(season_id),
                         ctx)
        names = v["names"]

        st.markdown(comparison_html(v["rows"]), unsafe_allow_html=True)
        st.caption(_core.SUMMARY_CAPTION)
        st.caption(v["note"])

        # --- radars side by side (they stack on a narrow screen) -----------------------------
        left, right = st.columns(2)
        with left:
            st.markdown("##### " + v["perf_heading"])
            rad = v["radar"]
            if rad["traces"]:
                st.plotly_chart(radar_chart(rad["traces"], rad["axes"]), width="stretch",
                                config=PLOTLY_CONFIG)
            if rad["no_data"]:
                st.caption("No percentiles for " + ", ".join(rad["no_data"]) + ".")
            if v["different_leagues"]:
                st.caption(_core.LEAGUES_NOTE)
        with right:
            if v["has_physical"]:
                st.markdown("##### Physical")
                ph = v["phys_radar"]
                if ph["traces"]:
                    st.plotly_chart(radar_chart(ph["traces"], [_PHYS_RADAR_LABEL[m] for m in ph["axes"]]),
                                    width="stretch", config=PLOTLY_CONFIG)
                if ph["no_data"]:
                    st.caption(no_physical_caption(ph["no_data"]))

        # --- Packing zones: one pitch per player, side by side ---------------------------------
        _zones_section(recs, names)

        # --- Performance table: the rating's metrics (tier shown), the rest in an expander ----
        st.markdown("##### Performance")
        st.markdown(ct.table_html(names, v["perf_rows"]), unsafe_allow_html=True)
        if v["other_rows"]:
            with st.expander("Other metrics"):
                st.markdown(ct.table_html(names, v["other_rows"]), unsafe_allow_html=True)

        # --- Physical table (SkillCorner; goalkeepers have none) --------------------------------
        # Nothing at all when no compared player has physical data: the radar's caption
        # already names them (one message, not two).
        if v["phys_rows"]:
            st.markdown("##### Physical")
            st.markdown(ct.table_html(names, v["phys_rows"]), unsafe_allow_html=True)
            if v["phys_more"]:
                with st.expander("Other metrics"):
                    st.markdown(ct.table_html(names, v["phys_more"]), unsafe_allow_html=True)


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
