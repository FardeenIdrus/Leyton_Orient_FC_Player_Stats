"""Bind a ReportData, its charts and the template into one self-contained HTML document.

SELF-CONTAINED IS A REQUIREMENT, not a preference. The report is emailed to a chairman and
a manager who do not log in; it is opened offline, forwarded, and printed. So the stylesheet
is inlined, the charts are inline SVG, and nothing is fetched from anywhere. A test asserts
nothing is fetched: a test asserts no link, script, remote src or url() appears.
"""

from __future__ import annotations

import html
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from lofc.model import club_framework as cf
from lofc.model import styles as st
from lofc.model.scorecard import _resolved_performance
from lofc.report import svg
from lofc.report.data import ASSIST_DEFINITION, ReportData

_TEMPLATES = Path(__file__).parent / "templates"

# The physical block, in the order it reads best around a radar: volume first, then
# intensity, then top speed.
_PHYSICAL_AXES: list[tuple[str, str]] = [
    ("distance_p90", "Distance"),
    ("meters_per_minute", "M/min"),
    ("hsr_distance_p90", "HSR distance"),
    ("hsr_count_p90", "HSR count"),
    ("sprint_distance_p90", "Sprint distance"),
    ("sprint_count_p90", "Sprint count"),
    ("psv99_kmh", "PSV-99"),
    ("top5_psv99_kmh", "Top 5 PSV-99"),
]


# Metrics where a HIGH percentile is BAD: the bar is drawn on the flipped value so a long
# green bar always means "good at the thing named". (Carried over from the retired category grouping.)
_LOWER_IS_BETTER = frozenset({"turnovers_p90"})

_GROUP_TITLES = {"Where": "Where he plays", "What": "What he does"}


def style_view(d: ReportData) -> dict | None:
    """The Playing style section as plain data, or None when the position has no styles
    (goalkeepers) or no style row could be computed. Mirrors dashboard/style_card.py."""
    groups = st.STYLES.get(st.style_group(d.position))
    row = d.style
    if not groups or not row:
        return None
    label = row.get("style_label")
    strong = list(row.get("strong_styles") or [])
    leans = list(row.get("leans_styles") or [])
    if strong or leans:
        label = " \u00b7 ".join(strong + [f"{s} (leans)" for s in leans])
    fits = {s: row.get(f"fit.{s}") for g in groups.values() for s in g}
    rated = {s: v for s, v in fits.items() if v is not None and v == v}
    cols = []
    for gname, styles in groups.items():
        rows = []
        for style, sigs in styles.items():
            v = rated.get(style)
            if v is None:
                continue
            rows.append({
                "name": style, "fit": v,
                "tag": f"{v:.0f} \u00b7 Strong" if v >= st.STRONG else
                       (f"{v:.0f} \u00b7 Leans" if v >= st.FLOOR else f"{v:.0f}"),
                "bar": svg.style_bar(v, st.STRONG, st.FLOOR),
                "signals": " \u00b7 ".join(
                    ("\u2691 " if s in st.QUALITY_SIGNALS else "") + st.SIGNAL_LABELS[s]
                    for s in sigs)})
        title = _GROUP_TITLES.get(gname, "") if len(groups) > 1 else ""
        if rows:
            cols.append({"title": title, "rows": rows})
    return {"label": label or st.NO_STYLE, "groups": cols}


def ordinal(n: int) -> str:
    """1 -> st, 2 -> nd, 3 -> rd, 11-13 -> th. Used for "4th of 13" on the report AND on
    the player profile, so the two surfaces phrase a rank identically."""
    if 11 <= (n % 100) <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def _environment() -> Environment:
    env = Environment(loader=FileSystemLoader(str(_TEMPLATES)),
                      autoescape=select_autoescape(["html", "j2"]),
                      trim_blocks=True, lstrip_blocks=True)
    env.filters["ordinal"] = ordinal
    return env


def to_html(d: ReportData) -> str:
    """One player's report as a complete HTML document."""
    metrics = (_resolved_performance(d.position, "All Metrics")
               if d.position in cf.PERFORMANCE_METRICS else [])
    from lofc.dashboard.labels import LABELS
    labels = [LABELS.get(m, m.replace("_p90", "").replace("_", " ").capitalize())
              for m in metrics]
    values = [d.percentiles.get(m) for m in metrics]
    # Indexes of metrics where a high raw percentile is bad, so the bar is drawn on the
    # flipped value: a long green bar must always mean the player is good at the thing named.
    inverted = {i for i, m in enumerate(metrics) if m in _LOWER_IS_BETTER}
    # The club's own squad median for this position, drawn as a tick on each bar. Only
    # when the club actually HAS players in the position -- otherwise there is no
    # benchmark to draw and a missing tick is the honest rendering.
    bench = ([d.benchmark.get(m) for m in metrics] if d.benchmark_n else None)
    bars = svg.percentile_bars(labels, values, width=520, inverted=inverted,
                               benchmark=bench,
                               # 250, measured across all eight positions against the most
                               # position-fragmented player in each (the worst case for
                               # page height). The bar block is column 1 of the evidence
                               # band and, since the scatter was cut to 280, is what sets
                               # that band's height. A metric list runs 8-24 entries and
                               # the row height adapts underneath this ceiling, so the
                               # value only binds on the long lists -- Centre Forward's 24
                               # is the case that sets it.
                               #
                               # .evidence is flex:1, so it EXPANDS to fill whatever the
                               # other bands leave: shrinking the bars does not shorten
                               # the page, it only buys slack inside a fixed box. What
                               # this ceiling must guarantee is that the bars still FIT
                               # that box -- .evidence > div is overflow:hidden, so a
                               # block taller than its column loses metrics off the bottom
                               # with no visible sign. 280 leaves ~11mm of clearance on
                               # the worst case; 300 does not.
                               max_height=250)

    axes = [label for _key, label in _PHYSICAL_AXES]
    player_line = [d.physical.get(key) for key, _label in _PHYSICAL_AXES]
    series = [("This player", player_line, svg.RED)]
    # There is deliberately NO "league average" ring here. It used to draw [50] * 8, which
    # is a perfect octagon for every player in every league by construction: these axes are
    # PERCENTILES, so the median is ~50 on each one by definition (measured on PL2 Full
    # Backs: 50.5 on all eight). It could never take another shape, so it carried no
    # information while looking like data. The Leyton Orient line below is a real
    # comparison and does the job the ring pretended to.
    # The club's own squad, on the same axes. Drawn only where the club has players in
    # this position AND at least one physical axis is covered for them -- an all-None
    # series would draw as nothing and still claim a legend entry.
    if d.benchmark_n:
        club_line = [d.benchmark.get(key) for key, _label in _PHYSICAL_AXES]
        if any(v is not None for v in club_line):
            series.append((f"Leyton Orient (n={d.benchmark_n})", club_line, "#1F6FB2"))
    # league= switches the plain rings for the club's named bands, and the player's
    # series (index 0) has its percentile printed at every vertex.
    radar = svg.radar(axes, series, size=202, league=d.league, value_series=0)
    band_key = svg.physical_band_legend(d.league) if any(
        v is not None for v in player_line) else ""

    whence = goals_by_position(d.position_shares)

    css = (_TEMPLATES / "report.css").read_text()
    body = _environment().get_template("report.html.j2").render(
        d=d, bars=bars, style=style_view(d), radar=radar, band_key=band_key,
        whence=whence,
        assist_definition=ASSIST_DEFINITION)

    # The name is escaped explicitly here: this f-string is OUTSIDE Jinja, so the
    # template's autoescaping does not reach it. A player named with an angle bracket would
    # otherwise break the document, and the document leaves the building.
    title = html.escape(f"{d.player_name} — Recruitment Report")
    return (f"<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            f"<title>{title}</title>"
            f"<style>{css}</style></head><body>{body}</body></html>")


def goals_by_position(shares) -> list[str]:
    """["2 goals as attacking mid", ...] for the positions where he actually scored.

    Computed here, not in the template: the shares are tuples, and Jinja's selectattr
    does not index them, so doing it in the template silently produced nothing.

    Returns [] when he scored only in the position the page already names -- there is no
    story to tell then, and the line would be noise on a page with no spare room.
    """
    scoring = [(group, goals) for group, _m, _s, goals, _a in shares if goals]
    if len(scoring) < 2 and not (len(scoring) == 1 and shares and shares[0][3] in (0, None)):
        return []
    return [f"{goals:.0f} {'goal' if goals == 1 else 'goals'} as {group.lower()}"
            for group, goals in scoring]
