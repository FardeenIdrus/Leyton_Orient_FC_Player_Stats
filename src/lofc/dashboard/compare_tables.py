"""Compare page helpers: radar axes, the Performance / Physical tables, summary-table extras.

Kept out of tabs/compare.py so the logic is testable without a Streamlit runtime. Everything
here is a pure function except the three small loaders at the bottom, which follow the
caching rules in loaders.py (pipeline tables: version-keyed; scout reports: 60 s TTL)."""

from __future__ import annotations

import html
import math

import pandas as pd
import streamlit as st

from lofc.dashboard.labels import PHYS_COMPARE_LABEL, metric_label
from lofc.dashboard.metric_filters import LOWER_IS_BETTER_PHYSICAL, PHYSICAL_GROUPS
from lofc.dashboard.theme import RED
from lofc.model import club_framework as cf
from lofc.model.performance_weights import WEIGHTS

DASH = "—"
RADAR_TIERS = ("High", "Mid")          # Low-weighted metrics are in the table, not on the radar
_PSV99 = "psv99_kmh"                   # "Average match top speed": not shown (Head of Recruitment)

# Lower-is-better metrics whose percentile the scorecard does NOT invert (only
# cf.LOWER_IS_BETTER is). Colouring by that percentile would crown the worse player, so they
# are left out of the "Other metrics" table rather than coloured wrongly.
_UNINVERTED_LOWER = {"gk_conceded_p90"}

_NOT_METRICS = {"player_id", "competition_id", "season_id", "position_group", "minutes",
                "rankable", "name", "team_name", "player_name", "id"}


def _missing(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v)) or bool(pd.isna(v))


# --- which metrics ----------------------------------------------------------------------
def _weights_table(position: str, archetype: str) -> dict:
    return (WEIGHTS.get((position, archetype))
            or WEIGHTS.get((position, cf.DEFAULT_ARCHETYPE)) or {})


def rating_metrics(position: str, archetype: str) -> list[tuple[str, str]]:
    """[(metric, tier)] of the rating's Performance table, in `performance_weights` order."""
    return [(m, tier) for m, (tier, _w) in _weights_table(position, archetype).items()]


def radar_metrics(position: str, archetype: str) -> list[str]:
    """The Performance radar's axes: High- and Mid-weighted metrics only."""
    return [m for m, tier in rating_metrics(position, archetype) if tier in RADAR_TIERS]


def physical_rating_metrics(position: str) -> list[str]:
    return [m for m in cf.PHYSICAL_METRICS.get(position, []) if m != _PSV99]


def other_physical_metrics(position: str) -> list[str]:
    if not cf.PHYSICAL_METRICS.get(position):
        return []
    rating = set(physical_rating_metrics(position))
    return [m for ms in PHYSICAL_GROUPS.values() for m in ms if m not in rating and m != _PSV99]


def other_performance_metrics(position: str, archetype: str, columns) -> list[str]:
    """Impect metrics held for the position that the rating does not use and the app can name
    (LABELS), from the percentile/value columns present. Physical ones live in the Physical table."""
    from lofc.dashboard.labels import LABELS
    rated = {m for m, _ in rating_metrics(position, archetype)}
    physical = {m for ms in PHYSICAL_GROUPS.values() for m in ms} | {_PSV99}
    return [c for c in columns
            if c in LABELS and c not in rated and c not in physical
            and c not in _NOT_METRICS and c not in _UNINVERTED_LOWER]


# --- radar ------------------------------------------------------------------------------
def radar_inputs(pcts_by_name: dict, metrics: list[str]):
    """(axes, traces, no_data) for a percentile radar.

    A metric one player lacks is still an axis: his value is None (the chart draws it at 0 and
    says "no value" on hover). The radar was previously dropped whenever fewer than three
    metrics were non-null for EVERY player. Only a player with no percentile at all is left
    off and returned in `no_data`; an axis nobody has a value for is dropped."""
    have, no_data = {}, []
    for name, s in pcts_by_name.items():
        vals = {m: float(s[m]) for m in metrics
                if s is not None and m in s.index and not _missing(s[m])}
        if vals:
            have[name] = vals
        else:
            no_data.append(name)
    axes = [m for m in metrics if any(m in v for v in have.values())]
    if len(axes) < 3:
        return [], [], list(pcts_by_name)
    return axes, [(n, [v.get(m) for m in axes]) for n, v in have.items()], no_data


# --- colouring --------------------------------------------------------------------------
def colour_classes(pcts: list) -> list[str | None]:
    """"best" / "worst" / None per player, from his PERCENTILE in this row.

    The percentile is already direction-aware (scorecard.metric_percentiles inverts the
    lower-is-better metrics), so a higher percentile is always better. Compared as displayed
    (rounded), so no colour is given for a difference the reader cannot see. Tied cells and
    missing ones stay uncoloured; with three players the middle one stays neutral."""
    vals = [None if _missing(p) else round(float(p)) for p in pcts]
    present = [v for v in vals if v is not None]
    if len(present) < 2 or max(present) == min(present):
        return [None] * len(vals)
    hi, lo = max(present), min(present)
    out = []
    for v in vals:
        if v is None:
            out.append(None)
        elif v == hi and present.count(hi) == 1:
            out.append("best")
        elif v == lo and present.count(lo) == 1:
            out.append("worst")
        else:
            out.append(None)
    return out


# --- values -----------------------------------------------------------------------------
_M_UNIT = {"distance_p90", "running_distance_p90", "hsr_distance_p90", "sprint_distance_p90",
           "hi_distance_p90"}


def format_value(metric: str, v) -> str:
    """A value in the metric's own unit; "—" when missing."""
    if _missing(v):
        return DASH
    v = float(v)
    if metric in LOWER_IS_BETTER_PHYSICAL:
        return f"{v:.2f} s"
    if metric in PHYSICAL_GROUPS["Speed"] or metric == _PSV99:
        return f"{v:.1f} km/h"
    if metric in _M_UNIT:
        return f"{v:,.0f} m"
    if metric == "meters_per_minute":
        return f"{v:.0f} m/min"
    # gk_shot_stopping_pct is a ratio around 0 that can go far below -1 (not a 0-100% rate)
    if metric.endswith("_pct") and metric != "gk_shot_stopping_pct" and 0 <= v <= 1:
        return f"{v:.0%}"
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    if abs(v) >= 100:
        return f"{v:.1f}"
    return f"{0.0 if abs(v) < 0.005 else v:.2f}"                  # no "-0.00"


def row_label(metric: str) -> str:
    if metric in PHYS_COMPARE_LABEL:
        return PHYS_COMPARE_LABEL[metric][0]
    try:
        from lofc.dashboard.glossary_data import PHYSICAL
        if metric in PHYSICAL:
            return PHYSICAL[metric][0]
    except Exception:                                     # noqa: BLE001 -- label only
        pass
    return metric_label(metric)


def build_rows(metrics: list[str], tiers: dict, names: list[str], values_by_name: dict,
               pcts_by_name: dict, drop_empty: bool = False) -> list[dict]:
    """Table rows: one per metric, one cell per player ({text, pct, cls}). A missing value is a
    dash with no percentile and no colour. `drop_empty` removes a row nobody has a value for."""
    rows = []
    for m in metrics:
        cells, pcts = [], []
        for n in names:
            vs, ps = values_by_name.get(n), pcts_by_name.get(n)
            v = vs[m] if vs is not None and m in vs.index else None
            p = ps[m] if ps is not None and m in ps.index else None
            has_v = not _missing(v)
            has_p = has_v and not _missing(p)
            cells.append({"text": format_value(m, v), "pct": float(p) if has_p else None, "cls": None})
            pcts.append(cells[-1]["pct"])
        if drop_empty and all(c["text"] == DASH for c in cells):
            continue
        for cell, cls in zip(cells, colour_classes(pcts)):
            cell["cls"] = cls
        rows.append({"metric": m, "label": row_label(m), "tier": tiers.get(m), "cells": cells})
    return rows


# --- table html -------------------------------------------------------------------------
CSS = f"""
<style>
.lofc-mt {{ width: 100%; table-layout: fixed; border-collapse: collapse; margin: .2rem 0 .6rem; }}
.lofc-mt th, .lofc-mt td {{ padding: .4rem .6rem; text-align: left; vertical-align: middle;
  border-bottom: 1px solid #D9DCE0; overflow-wrap: anywhere; }}
.lofc-mt thead th {{ border-bottom: 2px solid {RED}; font-weight: 800; font-size: .95rem;
  color: #14161A; letter-spacing: -.01em; }}
.lofc-mt .k {{ width: 30%; font-weight: 500; font-size: .85rem; color: #14161A; }}
.lofc-mt .tier {{ display: inline-block; margin-left: .4rem; font-size: .68rem; font-weight: 600;
  text-transform: uppercase; letter-spacing: .08em; color: #5A6068; }}
.lofc-mt .v {{ font-size: .95rem; font-weight: 600; color: #14161A;
  font-variant-numeric: tabular-nums; }}
.lofc-mt .pc {{ margin-left: .45rem; font-size: .72rem; color: #5A6068;
  font-variant-numeric: tabular-nums; }}
.lofc-mt td.best {{ background: rgba(26,152,80,.14); }}
.lofc-mt td.best .v {{ color: #137a3c; }}
.lofc-mt td.worst {{ background: rgba(215,48,39,.12); }}
.lofc-mt td.worst .v {{ color: #b3261e; }}
</style>
"""


def table_html(names: list[str], rows: list[dict]) -> str:
    """Metrics as ROWS, players as COLUMNS: fits the width at 2-3 players, no sideways scroll.
    Every name, label and value is escaped."""
    head = "".join(f"<th>{html.escape(str(n))}</th>" for n in names)
    body = []
    for r in rows:
        tier = f'<span class="tier">{html.escape(str(r["tier"]))}</span>' if r.get("tier") else ""
        cells = []
        for c in r["cells"]:
            pc = f'<span class="pc">P{c["pct"]:.0f}</span>' if c.get("pct") is not None else ""
            cls = f' class="{c["cls"]}"' if c.get("cls") in ("best", "worst") else ""
            cells.append(f'<td{cls}><span class="v">{html.escape(str(c["text"]))}</span>{pc}</td>')
        body.append(f'<tr><th class="k" scope="row">{html.escape(str(r["label"]))}{tier}</th>'
                    + "".join(cells) + "</tr>")
    return (f'{CSS}<table class="lofc-mt"><thead><tr><th class="k"></th>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table>')


# --- summary-table extras ---------------------------------------------------------------
_ABBR = {"Championship": "Ch", "League One": "L1", "League Two": "L2", "National League": "NL",
         "Scottish Premiership": "SPL", "Scottish Championship": "SC", "Premier League 2": "PL2"}


def _abbr(league) -> str:
    if not isinstance(league, str) or not league:
        return ""
    return _ABBR.get(league) or "".join(w[0] for w in league.split() if w[0].isalpha()).upper()


def rating_trend_text(points: list, current_league) -> str:
    """"3.21 (L2) → 3.48 → 4.06": Overall per season, oldest first; a league is added only
    where it differs from the current one. Seasons without a rating are skipped."""
    parts = []
    for _season, value, league in points:
        if _missing(value):
            continue
        tag = f" ({_abbr(league)})" if league and league != current_league and _abbr(league) else ""
        parts.append(f"{float(value):.2f}{tag}")
    return " → ".join(parts) if parts else DASH


def _short_season(season_id: int) -> str:
    """317 -> "24/25"."""
    from lofc.dashboard.seasons import season_name_for
    name = season_name_for(int(season_id))
    return f"{name[2:4]}/{name[5:]}" if len(name) == 7 else name


def rating_trend_rows(by_season: dict, season_ids: list, no_physical_seasons=(),
                      current_league=None) -> dict:
    """Three short rows -- Overall / Performance / Physical trend -- one value per season,
    oldest first, "—" where a season has none: "24/25 — · 25/26 3.41 · 26/27 —".

    `by_season` maps season_id -> (overall, performance, physical[, league]). Overall is
    Performance + Physical, so in a season where NOBODY has a physical band
    (`no_physical_seasons`, from `seasons_without_physical`) Overall would be a
    Performance-only number beside full ones and reads "—". That is season-level on purpose:
    a player without tracking in a season that has it still shows his Overall, as the
    Players table does. A league is appended, abbreviated, where it differs from
    `current_league` ("24/25 3.20 (L2)"), as the old single-line trend did."""
    def one(i, season_id):
        label = _short_season(season_id)
        got = by_season.get(season_id)
        if got is None or _missing(got[i]) or (i == 0 and season_id in set(no_physical_seasons)):
            return f"{label} {DASH}"
        league = got[3] if len(got) > 3 else None
        tag = f" ({_abbr(league)})" if league and league != current_league and _abbr(league) else ""
        return f"{label} {float(got[i]):.2f}{tag}"
    return {label: " · ".join(one(i, sid) for sid in season_ids)
            for i, label in enumerate(("Overall trend", "Performance trend", "Physical trend"))}


def seasons_without_physical(history: pd.DataFrame) -> list:
    """Season ids that hold ratings but no physical band at all, from the loaded history."""
    if history is None or history.empty or "physical_band" not in history.columns:
        return []
    per = history.groupby("season_id").agg(rated=("objective_composite", "count"),
                                           phys=("physical_band", "count"))
    return sorted(int(s) for s in per[(per.rated > 0) & (per.phys == 0)].index)


def comparison_note(season_names: list) -> str:
    """The one note per page for a "—" change."""
    base = f"{DASH} = no comparison possible."
    if not season_names:
        return base
    return f"{base} {' and '.join(season_names)} {'has' if len(season_names) == 1 else 'have'} no physical data."


def style_text(row) -> str:
    """The Players page's pills as compact text: "Wide · 1v1 (leans)"."""
    if row is None:
        return DASH
    from lofc.model.styles import style_pills
    pills = style_pills(row)
    return " · ".join(pills) if pills else DASH


def scout_text(verdicts) -> str:
    """"2 Sign · 1 Monitor", counted like the player card; "—" if no reports."""
    from lofc.dashboard.tabs.scout_reports import verdict_counts
    counts = verdict_counts(verdicts)
    return " · ".join(f"{n} {v}" for v, n in counts) if counts else DASH


# --- loaders (follow loaders.py: pipeline tables version-keyed, user-written short TTL) ----
from lofc.dashboard.loaders import _versioned, get_engine  # noqa: E402

@_versioned(with_scorecards=True)
def load_rating_history(season_id: int) -> pd.DataFrame:
    """Overall ('All Metrics') for the two seasons before `season_id`: one row per player and
    season, the league with the most minutes."""
    df = pd.read_sql(
        "SELECT s.player_id, s.season_id, s.competition_id, s.objective_composite, "
        "s.performance_band, s.physical_band, n.minutes "
        "FROM player_scorecards s JOIN player_metrics_neutral n ON n.player_id = s.player_id "
        " AND n.competition_id = s.competition_id AND n.season_id = s.season_id "
        "WHERE s.season_id BETWEEN %(lo)s AND %(hi)s AND s.archetype = 'All Metrics'",
        get_engine(), params={"lo": int(season_id) - 2, "hi": int(season_id) - 1})
    df = (df.sort_values("minutes", ascending=False, na_position="last", kind="stable")
          .drop_duplicates(subset=["player_id", "season_id"], keep="first"))
    return df.drop(columns="minutes").reset_index(drop=True)


@st.cache_data(ttl=60, show_spinner=False)   # scout_reports is user-written: reports sync every minute
def load_scout_verdicts(player_ids: tuple[int, ...]) -> pd.DataFrame:
    ids = ",".join(str(int(p)) for p in player_ids) or "NULL"
    try:
        return pd.read_sql(f"SELECT player_id, verdict FROM scout_reports "
                           f"WHERE player_id IN ({ids}) AND missing_since IS NULL", get_engine())
    except Exception:                                     # noqa: BLE001
        return pd.DataFrame(columns=["player_id", "verdict"])


# --- packing zones: the player card's pitch, one per compared player ------------------------
from lofc.dashboard import detail_section as _ds   # noqa: E402  (pitch, legend, cell maths)
from lofc.ingest.impect_detail import FAMILY_LABELS as ZONE_FAMILY_LABELS   # noqa: E402,F401
from lofc.ingest.impect_detail import MAP_FAMILIES, ZONES   # noqa: E402,F401

ZONE_FAMILIES = list(MAP_FAMILIES)      # the card's selector, in the card's order (first = default)
ZONE_MODE = "Per 90"                    # one unit for every pitch, so the players are like-for-like
# Heights of the pitch frame (no legend) for 2 / 3 columns; the SVG is 420:620 and scales to the
# column, so a wider column needs a taller frame.
ZONE_FRAME_HEIGHT = {2: 640, 3: 560}


def zone_cells(rows: pd.DataFrame, family: str, mode: str = ZONE_MODE) -> dict | None:
    """zone code -> (formatted value, percentile) for one player and measure, exactly as the
    card builds them; None when he has no zone values for it (the caller shows a caption).
    `rows` is his slice of the percentile pool (metric, value_p90, total, pct)."""
    if rows.empty:
        return None
    by = rows.drop_duplicates("metric").set_index("metric")
    cells = {}
    for code in ZONES:
        name = f"zone.{family}.{code}"
        if name in by.index:
            # matches is only needed for "Per match"; Compare always shows per 90.
            value = _ds.unit_value(by.at[name, "total"], by.at[name, "value_p90"], None, mode)
            cells[code] = (_ds.fmt_value(value, mode, family), by.at[name, "pct"])
    return cells or None


def zone_missing(cells: dict) -> bool:
    return any(p is None or pd.isna(p) for _, p in cells.values())


def zone_pitch_html(cells: dict, any_missing: bool, frame_height: int | None = None) -> str:
    """The card's pitch page (same SVG, tooltips, fonts) minus its legend: Compare shows ONE
    legend under all the pitches. With `frame_height` the pitch scales to fit the frame
    (aspect kept), so it is never clipped however wide the column is (manager check,
    2026-11-02: the goalkeeper zone was cut off)."""
    page = _ds.pitch_frame_html(cells, any_missing).replace(_ds.legend_html(any_missing), "", 1)
    if frame_height:
        fit = (f"<style>svg{{max-height:{frame_height - 16}px !important;"
               "width:100% !important;height:auto;margin:0 auto}</style>")
        page = fit + page
    return page


def zone_legend_html(any_missing: bool) -> str:
    return _ds.legend_html(any_missing)


@st.cache_data(ttl=600)
def _zone_pool(competition_id: int, season_id: int) -> pd.DataFrame:
    """Zone rows of one league + season with within-position percentiles. Same cached query
    the player card reads (`_pool`), so a card opened first makes this free."""
    return _ds.pool_percentiles(_ds._pool(int(competition_id), int(season_id), "zone."))


def _zone_slice(r) -> pd.DataFrame:
    pool = _zone_pool(int(r["competition_id"]), int(r["season_id"]))
    return pool[pool["player_id"] == int(r["player_id"])] if not pool.empty else pool


def zone_has_data(recs: list) -> bool:
    """True when at least one compared player has any zone values (else the section is hidden)."""
    return any(not _zone_slice(r).empty for r in recs)


def zone_panels(recs: list, family: str) -> list:
    """One entry per player: his pitch cells, or None when he has no zone data. Each player is
    ranked against his own league + season + position (same as the card)."""
    return [zone_cells(_zone_slice(r), family) for r in recs]
