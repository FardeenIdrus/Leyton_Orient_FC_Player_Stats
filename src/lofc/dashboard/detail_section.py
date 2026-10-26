"""Player-card detail sections: Impect scores, packing zones, receptions by
type, and physical output by possession phase. DISPLAY ONLY -- nothing here moves a score.

Reads `player_detail_metrics` (built by build_neutral). Percentiles use the scoring
convention exactly: within league + season + position, rated players only, mid-rank.

THE PITCH IS A DIAGRAM of Impect's packing zones, attacking upward. Impect defines its zones
relative to the opponent's players, not as fixed areas, so no fixed grid is exact. The layout
follows the borders in Impect's own zone definitions (kpi_definitions.json `context`): the
in-behind wide zones border AM and IB; the wide zones border DM and CM; the full-back zones
border CB. Impect supplies no per-zone values for its GK zone -- the GK cell says so.

Units: "Per match" is Impect's own (its "Absolute": season total / matches, a full match being
~100 minutes), so a cell can be checked against Impect's screen directly; "Per 90" is the
platform's convention and runs ~10% lower for that reason.
"""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from lofc.model import club_framework as cf

from lofc.ingest.impect_detail import (AVAILABILITY, FAMILY_LABELS, MAP_FAMILIES, SCORES,
                                       ZONE_LABELS, ZONES)

FAMILY_ORDER = MAP_FAMILIES
# The two scores the Head of Recruitment asked for. Others are stored, not shown.
SCORE_TILES = ["offensive", "defensive"]
MODES = ["Per match", "Per 90", "Season total"]

# Cell titles: Impect's zone names without the trailing " Zone".
ZONE_NAMES = {z: label.removesuffix(" Zone") for z, label in ZONE_LABELS.items()}

# x, y, width, height on a 300 x 420 pitch, attacking upward; rows are 70 high.
# Approved design (2026-10-15). viewBox 420 x 620, attacking upward. Three columns
# (x 30 / 140 / 280 / 390), five rows of ROW_H from y 40, goalkeeper strip below. Rows follow
# Impect's zone borders: in-behind wide zones beside AM and IB, wide zones beside CM and DM,
# full-back zones beside CB.
ROW_H = 96
_COLS = [30, 140, 280, 390]
_Y0 = 40
_GAP = 4
_GRID = {"IBWL": (0, 0, 1, 2), "IB": (1, 0, 1, 1), "IBWR": (2, 0, 1, 2), "AM": (1, 1, 1, 1),
         "WL": (0, 2, 1, 2), "CM": (1, 2, 1, 1), "WR": (2, 2, 1, 2), "DM": (1, 3, 1, 1),
         "FBL": (0, 4, 1, 1), "CB": (1, 4, 1, 1), "FBR": (2, 4, 1, 1)}
# (x, y, width, height) of each zone's cell, before the gap is applied.
_ZONE_RECTS = {z: (_COLS[c], _Y0 + r * ROW_H, _COLS[c + w] - _COLS[c], h * ROW_H)
               for z, (c, r, w, h) in _GRID.items()}

# Club thresholds: 70th percentile = Elite, below 30th = band 2.0 (the veto level).
HI_FILL, MID_FILL, LO_FILL = "#2F8A5B", "#E6E8EC", "#C9483F"
NEUTRAL_FILL = "#FFFFFF"          # no percentile (player under 450 minutes): dashed outline
_INK_LIGHT, _INK_DARK = "#FFFFFF", "#1C2128"
_LINE = "rgba(28,33,40,.16)"

# Card labels = the glossary's name (glossary_data.PHYSICAL) + unit, so one metric has one
# name on every page.
_UNITS = {"distance_p90": "m", "running_distance_p90": "m", "hsr_distance_p90": "m",
          "sprint_distance_p90": "m", "psv99_kmh": "km/h", "top5_psv99_kmh": "km/h",
          "time_to_hsr": "s", "time_to_sprint": "s", "time_to_hsr_post_cod": "s",
          "time_to_sprint_post_cod": "s", "agility_505_90": "s", "agility_505_180": "s"}


def _label(metric: str) -> str:
    from lofc.dashboard.glossary_data import PHYSICAL
    name = PHYSICAL[metric][0]
    if metric not in _UNITS:
        return name
    unit = _UNITS[metric]
    # "Top speed (PSV-99)" -> "Top speed (PSV-99, km/h)", never two sets of brackets.
    return f"{name[:-1]}, {unit})" if name.endswith(")") else f"{name} ({unit})"


PHASE_METRICS = [(m, _label(m)) for m in (
    "distance_p90", "running_distance_p90", "hsr_distance_p90", "sprint_distance_p90",
    "hsr_count_p90", "sprint_count_p90", "medium_accel_count_p90", "high_accel_count_p90",
    "medium_decel_count_p90", "high_decel_count_p90", "cod_count_p90", "meters_per_minute")]
SPEED_METRICS = [(m, _label(m), m.startswith(("time_", "agility_"))) for m in (
    "top5_psv99_kmh", "psv99_kmh", "time_to_hsr", "time_to_sprint", "time_to_hsr_post_cod",
    "time_to_sprint_post_cod", "agility_505_90", "agility_505_180")]


# --- pure -------------------------------------------------------------------------------

def pool_percentiles(pool: pd.DataFrame) -> pd.DataFrame:
    """`pool` (player_id, position_group, rankable, metric, value_p90, total) plus `pct`:
    mid-rank percentile within position and metric over rated players; NaN for the rest."""
    if pool.empty:
        return pd.DataFrame(columns=["player_id", "position_group", "rankable", "metric",
                                     "value_p90", "total", "pct"])
    out = pool.copy()
    rated = out[out["rankable"].astype(bool)]
    grp = rated.groupby(["position_group", "metric"])["value_p90"]
    pct = (grp.rank() - 0.5).div(grp.transform("count")) * 100.0
    out["pct"] = pct.reindex(out.index)
    return out


def cell_fill(pct: float | None) -> str:
    if pct is None or pd.isna(pct):
        return NEUTRAL_FILL
    if pct >= 70:
        return HI_FILL
    return MID_FILL if pct >= 30 else LO_FILL


def _text_fill(pct: float | None) -> str:
    return _INK_LIGHT if cell_fill(pct) in (HI_FILL, LO_FILL) else _INK_DARK


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def unit_value(total: float | None, per90: float | None, matches: float | None,
               mode: str) -> float | None:
    """A cell's value in the chosen unit. Per match = Impect's own: total / matches."""
    if mode == "Season total":
        return total
    if mode == "Per 90":
        return per90
    if total is None or matches is None or pd.isna(total) or pd.isna(matches) or matches <= 0:
        return None
    return total / matches


def fmt_value(value: float | None, mode: str, family: str) -> str:
    if value is None or pd.isna(value):
        return "—"
    if mode == "Season total":
        return f"{value:.1f}" if family == "xg" else f"{value:.0f}"
    return f"{value:.2f}" if family == "xg" else f"{value:.1f}"


CHAR_PX = 5.6   # average width of a 10px sans-serif character, for wrapping cell titles


def wrap_label(title: str, width: float) -> list[str]:
    """Split a zone name into lines that fit a cell `width` px wide (6 px padding each side)."""
    room = max(1, int((width - 12) // CHAR_PX))
    lines, line = [], ""
    for word in title.replace("-", "- ").split():
        candidate = f"{line}{word}" if line.endswith("-") else f"{line} {word}".strip()
        if line and len(candidate) > room:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines


def _cell(zone: str, value: str, pct: float | None) -> str:
    x0, y0, w0, h0 = _ZONE_RECTS[zone]
    x, y, w, h = x0 + _GAP / 2, y0 + _GAP / 2, w0 - _GAP, h0 - _GAP
    title = ZONE_NAMES[zone]
    fill, ink = cell_fill(pct), _text_fill(pct)
    has_pct = pct is not None and not pd.isna(pct)
    hover = f"{title}: {value} · " + (f"{_ordinal(round(pct))} percentile" if has_pct
                                      else "no percentile")
    outline = ('' if has_pct else f' stroke="#C9CDD3" stroke-dasharray="4 3"')
    spans = "".join(f'<tspan x="{x + 10}" dy="{0 if i == 0 else 14}">{html.escape(l)}</tspan>'
                    for i, l in enumerate(wrap_label(title, w)))
    return (f'<g data-zone="{zone}" class="zone" data-tip="{html.escape(hover)}">'
            f'<title>{html.escape(hover)}</title>'
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill}"{outline}/>'
            f'<text x="{x + 10}" y="{y + 18}" font-size="11.5" fill="{ink}" opacity="0.85">'
            f'{spans}</text>'
            f'<text x="{x + w / 2}" y="{y + h / 2 + 12}" font-size="26" font-weight="700" '
            f'text-anchor="middle" fill="{ink}">{html.escape(value)}</text></g>')


def pitch_svg(cells: dict[str, tuple[str, float | None]]) -> str:
    """cells: zone code -> (formatted value, percentile or None). A diagram of Impect's
    packing zones on a pitch outline; the percentile is shown on hover."""
    line = f'class="pitch-line" fill="none" stroke="{_LINE}" stroke-width="1.2"'
    parts = ['<svg viewBox="0 0 420 620" xmlns="http://www.w3.org/2000/svg" role="img" '
             'aria-label="Packing zones" style="width:100%;max-width:560px;display:block;'
             'margin:0 auto;font-family:\'Source Sans 3\',\'Source Sans Pro\',sans-serif">',
             '<style>.zone:hover rect{stroke:#1C2128;stroke-width:2}</style>',
             f'<rect x="20" y="30" width="380" height="560" rx="6" fill="#FBFBFC" '
             f'stroke="{_LINE}" stroke-width="1.5"/>',
             '<text x="210" y="20" text-anchor="middle" font-size="11" fill="#5F6773">'
             'Attacking ↑</text>']
    for zone in ZONES:
        value, pct = cells.get(zone, ("—", None))
        parts.append(_cell(zone, value, pct))
    # Faint markings over the zones, so the shape reads as a pitch.
    parts += [f'<line x1="20" y1="310" x2="400" y2="310" {line}/>',
              f'<circle cx="210" cy="310" r="42" {line}/>',
              f'<rect x="110" y="30" width="200" height="78" {line}/>',
              f'<rect x="165" y="30" width="90" height="28" {line}/>',
              f'<rect x="110" y="512" width="200" height="78" {line}/>',
              f'<rect x="165" y="562" width="90" height="28" {line}/>',
              '<rect x="150" y="522" width="120" height="56" rx="8" fill="none" '
              'stroke="#C9CDD3" stroke-dasharray="4 3"/>',
              '<text x="210" y="554" text-anchor="middle" font-size="11" fill="#5F6773">'
              'Goalkeeper zone · no data</text>', '</svg>']
    return "".join(parts)


PITCH_FRAME_HEIGHT = 820


def pitch_frame_html(cells: dict[str, tuple[str, float | None]], any_missing: bool) -> str:
    """The pitch + legend as a self-contained page for st.components.v1.html.

    Its own frame because st.markdown does not reliably keep SVG tooltips, and native
    tooltips appear only after a ~1 s pause and never on touch screens. A custom tooltip shows
    immediately on hover, and on tap."""
    return ('<!doctype html><html><head><meta charset="utf-8">'
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Source+Sans+3:'
            'wght@400;600;700&display=swap"><style>'
            "body{margin:0;font-family:'Source Sans 3','Source Sans Pro',sans-serif;"
            'background:#FFFFFF;}'
            '.zone{cursor:pointer}'
            '#tip{position:fixed;pointer-events:none;background:#1C2128;color:#FFFFFF;'
            'font-size:13px;padding:6px 9px;border-radius:6px;white-space:nowrap;'
            'box-shadow:0 2px 8px rgba(0,0,0,.18);opacity:0;transition:opacity .08s}'
            '</style></head><body>'
            + pitch_svg(cells) + legend_html(any_missing) +
            '<div id="tip"></div><script>'
            'const tip=document.getElementById("tip");'
            'function show(e,t){tip.textContent=t;tip.style.opacity=1;'
            'const x=Math.min(e.clientX+14,window.innerWidth-tip.offsetWidth-8);'
            'tip.style.left=x+"px";tip.style.top=(e.clientY+14)+"px";}'
            'document.querySelectorAll("[data-tip]").forEach(g=>{'
            'g.addEventListener("mousemove",e=>show(e,g.dataset.tip));'
            'g.addEventListener("mouseleave",()=>{tip.style.opacity=0;});'
            'g.addEventListener("click",e=>show(e,g.dataset.tip));});'
            '</script></body></html>')


def legend_html(any_missing: bool) -> str:
    """The pitch legend as chips; the 'No percentile' chip only when a zone has none."""
    chips = [(HI_FILL, "", "70th percentile and above"), (MID_FILL, "", "30th to 70th"),
             (LO_FILL, "", "Below 30th")]
    if any_missing:
        chips.append((NEUTRAL_FILL, "border:1px dashed #C9CDD3;", "No percentile (under 450 min)"))
    items = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:6px;margin-right:16px">'
        f'<i style="width:14px;height:14px;border-radius:3px;display:inline-block;'
        f'background:{c};{extra}"></i>{html.escape(t)}</span>' for c, extra, t in chips)
    return f'<div style="font-size:.88rem;color:#5F6773;margin-top:10px">{items}</div>'


# Impect position enums -> plain names for the per-position breakdown.
IMPECT_POSITIONS = {
    "GOALKEEPER": "Goalkeeper", "CENTRAL_DEFENDER": "Centre back",
    "LEFT_WINGBACK_DEFENDER": "Left back", "RIGHT_WINGBACK_DEFENDER": "Right back",
    "DEFENSE_MIDFIELD": "Defensive midfield", "CENTRAL_MIDFIELD": "Central midfield",
    "ATTACKING_MIDFIELD": "Attacking midfield", "LEFT_WINGER": "Left winger",
    "RIGHT_WINGER": "Right winger", "CENTER_FORWARD": "Centre forward",
}


def position_breakdown(rows: pd.DataFrame) -> pd.DataFrame:
    """Impect's per-position scores: Position | Minutes | Offensive IMPECT | Defensive IMPECT,
    most minutes first."""
    parts = rows["metric"].str.split(".", n=2, expand=True)
    frame = pd.DataFrame({"kind": parts[1], "position": parts[2], "value": rows["value_p90"]})
    wide = frame.pivot_table(index="position", columns="kind", values="value", aggfunc="first")
    out = pd.DataFrame({
        "Position": [IMPECT_POSITIONS.get(p, p) for p in wide.index],
        "Minutes": wide.get("minutes"),
        "Offensive IMPECT": wide.get("offensive"),
        "Defensive IMPECT": wide.get("defensive")}).reset_index(drop=True)
    return out.sort_values("Minutes", ascending=False).reset_index(drop=True)


def physical_table(detail: pd.DataFrame, neutral: pd.Series, pcts: pd.Series | None,
                   scored: list[str]) -> pd.DataFrame:
    """The card's ONE physical table: every physical metric once.

    Metric | In rating (✓ = one of the rating's physical metrics) | All phases | In possession |
    Out of possession | Percentile (the scorecard's, same as everywhere on the card) | Band
    (only for metrics in the rating). Per 90 minutes played; metres per minute is a rate.
    Speed and agility rows have no possession split -- SkillCorner does not provide one."""
    by_metric = dict(zip(detail["metric"], detail["value_p90"])) if not detail.empty else {}
    rows = []
    entries = [(m, label) for m, label in PHASE_METRICS] + \
              [(m, label) for m, label, _ in SPEED_METRICS]
    for name, label in entries:
        pct = pcts.get(name) if pcts is not None else None
        pct = None if pct is None or pd.isna(pct) else float(pct)
        rows.append({
            "Metric": label,
            "In rating": "✓" if name in scored else "",
            "All phases": neutral.get(name),
            "In possession": by_metric.get(f"phys_tip.{name}"),
            "Out of possession": by_metric.get(f"phys_otip.{name}"),
            "Percentile": None if pct is None else round(pct),
            "Band": round(cf.band(pct), 2) if (pct is not None and name in scored) else None,
        })
    out = pd.DataFrame(rows)
    return out[out[["All phases", "In possession", "Out of possession"]].notna().any(axis=1)] \
        .reset_index(drop=True)


# --- data -------------------------------------------------------------------------------

def split_physical(table: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(metrics in the rating, with band; every other physical metric, without band). The
    headings carry the meaning, so neither keeps the 'In rating' column."""
    if table.empty:
        return table, table
    rated = table[table["In rating"] == "✓"].drop(columns=["In rating"])
    other = table[table["In rating"] != "✓"].drop(columns=["In rating", "Band"])
    return rated.reset_index(drop=True), other.reset_index(drop=True)


def physical_gap(league_has_physical: bool, position: str) -> str | None:
    """The one line shown when a card has no physical data: whether the league or the player
    is missing it. Nothing for goalkeepers -- physical never counts in their rating."""
    if position == "Goalkeeper":
        return None
    return "no physical data for this " + ("player" if league_has_physical else "league")


@st.cache_data(ttl=600)
def _league_has_physical(competition_id: int, season_id: int) -> bool:
    from lofc.dashboard.loaders import get_engine
    return bool(pd.read_sql(
        "SELECT EXISTS (SELECT 1 FROM player_metrics_neutral WHERE competition_id = %(c)s "
        "AND season_id = %(s)s AND distance_p90 IS NOT NULL) AS has",
        get_engine(), params={"c": int(competition_id), "s": int(season_id)})["has"].iloc[0])


def like_prefix(prefix: str) -> str:
    """A SQL LIKE pattern matching `prefix` literally (`_` is a LIKE wildcard)."""
    return prefix.replace("\\", "\\\\").replace("_", "\\_").replace("%", "\\%") + "%"


@st.cache_data(ttl=600)
def _pool(competition_id: int, season_id: int, prefix: str) -> pd.DataFrame:
    from lofc.dashboard.loaders import get_engine
    return pd.read_sql(
        "SELECT d.player_id, n.position_group, n.rankable, d.metric, d.value_p90, d.total "
        "FROM player_detail_metrics d JOIN player_metrics_neutral n "
        "  ON n.player_id = d.player_id AND n.competition_id = d.competition_id "
        " AND n.season_id = d.season_id "
        "WHERE d.competition_id = %(c)s AND d.season_id = %(s)s AND d.metric LIKE %(p)s",
        get_engine(), params={"c": int(competition_id), "s": int(season_id), "p": like_prefix(prefix)})


def _player_rows(row: pd.Series, prefix: str) -> pd.DataFrame:
    pool = pool_percentiles(_pool(int(row["competition_id"]), int(row["season_id"]), prefix))
    mine = pool[pool["player_id"] == int(row["player_id"])]
    return mine


# --- render -----------------------------------------------------------------------------

def render(row: pd.Series, neutral: pd.Series | None, league: str, key_prefix: str,
           pcts: pd.Series | None = None, scored: list[str] | None = None) -> None:
    position = row["position_group"]

    scores = _player_rows(row, "score.")
    if not scores.empty:
        st.markdown("##### Impect scores")
        by = scores.set_index("metric")
        cols = st.columns(len(SCORE_TILES))
        for col, key in zip(cols, SCORE_TILES):
            name = f"score.{key}"
            if name in by.index:
                pct = by.at[name, "pct"]
                col.metric(SCORES[key][1], f"{by.at[name, 'value_p90']:.2f}", border=True,
                           delta=None if pd.isna(pct) else f"{pct:.0f}th percentile",
                           delta_color="off")
        per_pos = _player_rows(row, "score_pos.")
        if not per_pos.empty:
            table = position_breakdown(per_pos)
            st.caption("All positions, weighted by minutes. By position:")
            st.dataframe(table, hide_index=True, width="stretch",
                         column_config={
                             "Minutes": st.column_config.NumberColumn(format="%d"),
                             "Offensive IMPECT": st.column_config.NumberColumn(format="%.2f"),
                             "Defensive IMPECT": st.column_config.NumberColumn(format="%.2f")})

    zones = _player_rows(row, "zone.")
    meta = _player_rows(row, "meta.")
    matches = meta["total"].iloc[0] if not meta.empty else None
    if not zones.empty:
        st.markdown("##### Packing zones")
        c1, c2 = st.columns([2, 2])
        family = c1.selectbox("Metric", FAMILY_ORDER, format_func=lambda f: FAMILY_LABELS[f],
                              key=f"{key_prefix}_zone_family")
        mode = c2.radio("Values", MODES, horizontal=True, key=f"{key_prefix}_zone_mode")
        by = zones.set_index("metric")
        cells = {}
        for code in ZONES:
            name = f"zone.{family}.{code}"
            if name in by.index:
                value = unit_value(by.at[name, "total"], by.at[name, "value_p90"], matches, mode)
                cells[code] = (fmt_value(value, mode, family), by.at[name, "pct"])
        left, right = st.columns([3, 2])
        with left:
            # Our own generated HTML (every text value escaped), never user input.
            st.iframe(
                pitch_frame_html(cells, any(p is None or pd.isna(p) for _, p in cells.values())),
                height=PITCH_FRAME_HEIGHT)
            st.caption(f"All positions. Colour: percentile vs {position}s in {league}, per 90. "
                       "Hover a zone for its percentile.")
        with right:
            avail = _player_rows(row, "avail.")
            if not avail.empty:
                by_a = avail.set_index("metric")
                table = pd.DataFrame(
                    [(label, by_a.at[f"avail.receptions.{k}", "value_p90"],
                      by_a.at[f"avail.receptions.{k}", "pct"])
                     for k, (_, label) in AVAILABILITY.items()
                     if f"avail.receptions.{k}" in by_a.index],
                    columns=["Receptions", "Per 90", "Percentile"])
                st.dataframe(table, hide_index=True, width="stretch",
                             column_config={
                                 "Per 90": st.column_config.NumberColumn(format="%.2f"),
                                 "Percentile": st.column_config.ProgressColumn(
                                     min_value=0, max_value=100, format="%d")})

    phys = _player_rows(row, "phys_")
    if neutral is not None:
        table = physical_table(phys, neutral, pcts, scored or [])
        if not table.empty:
            rated, other = split_physical(table)
            cfg = {**{c: st.column_config.NumberColumn(format="%.1f")
                      for c in ("All phases", "In possession", "Out of possession")},
                   "Percentile": st.column_config.ProgressColumn(
                       min_value=0, max_value=100, format="%d",
                       help="Against the same position in his league."),
                   "Band": st.column_config.NumberColumn(format="%.2f", help="1-5.")}
            if not rated.empty:
                st.markdown("##### Physical — in the rating")
                st.dataframe(rated, hide_index=True, width="stretch", column_config=cfg,
                             key=f"{key_prefix}_phys_rated")
            if not other.empty:
                st.markdown("##### Other physical metrics")
                st.dataframe(other, hide_index=True, width="stretch", column_config=cfg,
                             key=f"{key_prefix}_phys_other")
            st.caption("Per 90 minutes played. Metres per minute is a rate.")
        else:
            gap = physical_gap(_league_has_physical(int(row["competition_id"]),
                                                    int(row["season_id"])), position)
            if gap:
                st.markdown(f"##### Physical — *{gap}*")
