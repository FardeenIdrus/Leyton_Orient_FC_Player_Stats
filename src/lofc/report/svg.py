"""The player report's charts, as inline SVG.

Hand-built rather than produced by a chart library, for three reasons the report depends on:
the file must be self-contained and print sharp (vector, no images), it must work offline
with no JavaScript, and the export path must add no dependency to the container.

Every function is pure -- values in, an SVG string out -- so the tests assert on the markup
and nothing has to be rendered to check it.

TWO RULES THESE ALL FOLLOW:

  * Colour never carries meaning alone. Every bar, point and strip prints its number, because
    the page is read in black and white and by people who cannot ask what a shade meant.
  * A missing value is never drawn as zero. An unmeasured metric says so; it does not appear
    at the origin, which would read as "the player did none of this".
"""

from __future__ import annotations

import html
import math

from lofc.dashboard.theme import RED

DARK = "#1A1A1A"
MID = "#6B6B6B"
LIGHT = "#D8D8D8"
PAPER = "#FFFFFF"

# Percentile bands. The colour reinforces the number; it never replaces it.
BAND_COLOURS: dict[str, str] = {
    "elite": "#1E6B32",
    "strong": "#4C9A5E",
    "average": "#C9D6CB",
    "weak": "#E8A33D",
    "poor": RED,
}


# Named percentile bands for the physical radar, modelled on the club's own reference
# report. Each carries its numeric range so the legend prints "Very Good (65-80)": a
# reader outside the recruitment room should never have to guess what a band name means.
#
# Listed OUTERMOST first, which is also paint order -- every ring is drawn at its own
# outer radius and the next paints over the middle of it, so the smallest must come last.
#
# The boundary between Above Average and Below Average is the 50th percentile, i.e. the
# league median for that position. That is why the radar carries no separate "league
# average" line: these rings already encode it, and a line at 50 on every axis draws the
# same perfect polygon for every player in every league, which is a gridline, not data.
PHYSICAL_BANDS = [
    ("Elite",          80, "#C9B37A"),
    ("Very Good",      65, "#7FAE72"),
    ("Good",           55, "#A8C89A"),
    ("Above Average",  50, "#E4EEDC"),
    ("Below Average",  25, "#F6DEDE"),
    ("Subpar",          0, "#E9A9A2"),
]


def band_ranges():
    """(name, low, high, colour) per band; `high` is the floor of the band above it."""
    out, upper = [], 100
    for name, low, colour in PHYSICAL_BANDS:
        out.append((name, low, upper, colour))
        upper = low
    return out


def _band(value: float) -> str:
    if value >= 80:
        return "elite"
    if value >= 60:
        return "strong"
    if value >= 40:
        return "average"
    if value >= 20:
        return "weak"
    return "poor"


def _e(text) -> str:
    """Escape any text bound for the SVG. Player and club names arrive here directly from
    the data, and one angle bracket would break a document that leaves the building."""
    return html.escape(str(text), quote=True)


def percentile_bars(labels: list[str], values: list[float | None],
                    width: int = 520, inverted: set[int] | None = None,
                    max_height: int = 300,
                    benchmark: list[float | None] | None = None) -> str:
    """Horizontal percentile bars, one per metric, each labelled with its own number.

    A None value draws no bar and says "not measured" -- see the module docstring.

    `inverted` holds the INDEXES of metrics where a high raw percentile is bad -- turnovers
    being the case that matters. Those bars are drawn on the flipped value and their label
    is suffixed "(fewer is better)", so a long green bar always means the player is good at
    the thing named. Without this a player in the 90th percentile for giving the ball away
    would get the same green bar as one in the 90th percentile for pass accuracy, and a
    reader who cannot query the data has no way to tell them apart.
    """
    inverted = inverted or set()
    # The row height ADAPTS to the metric count so the block always fits its share of the
    # page. A position's metric list ranges from 6 (Goalkeeper) to 24 (Centre Forward); a
    # fixed row height makes the report one page for a midfielder and two for a forward,
    # and a one-page report that sometimes prints as two is not a one-page report.
    pad_left, pad_right = 178, 46
    row_h = 17 if not labels else max(9, min(17, (max_height - 26) // max(1, len(labels))))
    track = width - pad_left - pad_right
    height = len(labels) * row_h + 26
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           f'viewBox="0 0 {width} {height}" font-family="Helvetica,Arial,sans-serif">']

    for i, (label, value) in enumerate(zip(labels, values)):
        y = i * row_h + 14
        if i in inverted:
            label = f"{label} (fewer is better)"
            if value is not None:
                value = 100.0 - float(value)
        out.append(f'<text x="{pad_left - 7}" y="{y + 9}" font-size="9.5" fill="{DARK}" '
                   f'text-anchor="end">{_e(label)}</text>')
        out.append(f'<rect x="{pad_left}" y="{y}" width="{track}" height="12" '
                   f'fill="#F2F2F2"/>')
        if value is None:
            out.append(f'<text x="{pad_left + 4}" y="{y + 9.5}" font-size="8.5" '
                       f'fill="{MID}" font-style="italic">not measured</text>')
            continue
        w = max(1.0, track * float(value) / 100.0)
        out.append(f'<rect x="{pad_left}" y="{y}" width="{w:.1f}" height="12" '
                   f'fill="{BAND_COLOURS[_band(value)]}"/>')
        mark = benchmark[i] if benchmark is not None and i < len(benchmark) else None
        if mark is not None:
            if i in inverted:
                mark = 100.0 - float(mark)
            mx = pad_left + track * float(mark) / 100.0
            out.append(f'<line class="benchmark" x1="{mx:.1f}" y1="{y - 1.5}" '
                       f'x2="{mx:.1f}" y2="{y + 13.5}" stroke="{DARK}" stroke-width="1.6"/>')
        out.append(f'<text x="{pad_left + w + 5:.1f}" y="{y + 9.5}" font-size="9" '
                   f'fill="{DARK}">{value:.1f}</text>')

    axis_y = len(labels) * row_h + 12
    out.append(f'<line x1="{pad_left}" y1="{axis_y}" x2="{pad_left + track}" '
               f'y2="{axis_y}" stroke="{LIGHT}"/>')
    for tick in (0, 25, 50, 75, 100):
        x = pad_left + track * tick / 100.0
        out.append(f'<text x="{x:.1f}" y="{axis_y + 11}" font-size="7.5" fill="{MID}" '
                   f'text-anchor="middle">{tick}</text>')
    out.append("</svg>")
    return "".join(out)


def radar(axes: list[str], series: list[tuple[str, list[float | None], str]],
          size: int = 340, league: str | None = None,
          value_series: int = 0) -> str:
    """A radar with one line per series, over NAMED percentile bands.

    A None on an axis breaks the line rather than plotting the centre: an unmeasured
    physical metric is not a player who covered no distance.

    `league` names the population the percentiles are drawn from. Supplying it swaps the
    plain grey rings for the named bands; without it no band claim is made, because a
    band name means nothing without the population behind it.

    `value_series` is the index of the series whose value is PRINTED at each vertex --
    the player's, normally. Reading a percentile off a polygon is guesswork; the club's
    own reference report prints the number at each point, and so does this.
    """
    cx = cy = size / 2
    r = size / 2 - 46
    n = max(1, len(axes))
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
           f'viewBox="0 0 {size} {size}" font-family="Helvetica,Arial,sans-serif">']

    labelled = (series[value_series][1]
                if series and 0 <= value_series < len(series) else None)

    def point(idx: int, value: float) -> tuple[float, float]:
        angle = -math.pi / 2 + 2 * math.pi * idx / n
        rad = r * max(0.0, min(100.0, value)) / 100.0
        return cx + rad * math.cos(angle), cy + rad * math.sin(angle)

    rings = ([(high, colour) for _n, _lo, high, colour in band_ranges()] if league
             else [(100, "#F7F7F7"), (80, "#EDEDED"), (60, "#E3E3E3"),
                   (40, "#D9D9D9"), (20, "#CFCFCF")])
    for ring, shade in rings:
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in
                       (point(i, ring) for i in range(n)))
        out.append(f'<polygon points="{pts}" fill="{shade}" stroke="{PAPER}" '
                   f'stroke-width="0.8"/>')

    for i, label in enumerate(axes):
        x, y = point(i, 100)
        out.append(f'<line x1="{cx}" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}" '
                   f'stroke="{LIGHT}" stroke-width="0.7"/>')
        lx, ly = point(i, 118)
        anchor = "middle" if abs(lx - cx) < 12 else ("start" if lx > cx else "end")
        out.append(f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="7.5" fill="{DARK}" '
                   f'text-anchor="{anchor}">{_e(label)}</text>')
        # The percentile sits DIRECTLY UNDER its own axis label, not out at the vertex.
        # At the vertex it collided with the neighbouring axis label on a radar this size
        # -- "PSV-99" and "93.2" printed on top of each other. Anchored to the label, the
        # number can never overlap anything, at any radius, for any value.
        if labelled is not None and i < len(labelled) and labelled[i] is not None:
            out.append(f'<text x="{lx:.1f}" y="{ly + 8.5:.1f}" font-size="8" '
                       f'font-weight="700" fill="{DARK}" text-anchor="{anchor}">'
                       f'{float(labelled[i]):.1f}</text>')

    for name, values, colour in series:
        pts = [f"{x:.1f},{y:.1f}" for i, v in enumerate(values) if v is not None
               for x, y in (point(i, float(v)),)]
        if len(pts) >= 2:
            out.append(f'<polyline points="{" ".join(pts)} {pts[0]}" fill="none" '
                       f'stroke="{colour}" stroke-width="1.8"/>')


    ly = size - 30
    for name, _values, colour in series:
        out.append(f'<rect x="10" y="{ly - 6}" width="9" height="3" fill="{colour}"/>')
        out.append(f'<text x="23" y="{ly}" font-size="8" fill="{DARK}">{_e(name)}</text>')
        ly += 11
    out.append("</svg>")
    return "".join(out)


def scatter(peers: list[tuple[str, float, float]], target_name: str,
            x_label: str, y_label: str, size: int = 380,
            label_peers: bool = True) -> str:
    """Every peer plotted and named on a percentile grid, the target ringed.

    BOTH AXES ARE PERCENTILES, 0-100, within the player's own league, season and position
    group -- so the grid reads the same way whichever position it is drawn for, and a
    point's position is directly interpretable: top-right is high on both, the midlines are
    the league median.

    Naming the peers is the chart's job, not decoration: "62nd percentile for pressing"
    means little alone, but "presses more than Smith and less than Jones" is a sentence a
    manager can act on.

    Labels are placed through an occupancy grid so a dense cluster drops labels rather than
    printing them on top of each other -- an unreadable pile of names is worse than a few
    unlabelled dots. The target is always labelled.
    """
    pad_l, pad_b, pad_t, pad_r = 34, 30, 16, 14
    inner = size - pad_l - pad_r
    height = size - pad_t - pad_b
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
           f'viewBox="0 0 {size} {size}" font-family="Helvetica,Arial,sans-serif">']
    out.append(f'<rect x="{pad_l}" y="{pad_t}" width="{inner}" height="{height}" '
               f'fill="{PAPER}" stroke="{LIGHT}"/>')

    def xy(x: float, y: float) -> tuple[float, float]:
        return pad_l + inner * x / 100.0, pad_t + height * (1 - y / 100.0)

    # Percentile gridlines every 25, with the axes labelled -- the reference report's own
    # convention, and what makes a point readable without counting pixels.
    for tick in (0, 25, 50, 75, 100):
        gx, _ = xy(tick, 0)
        _, gy = xy(0, tick)
        heavy = tick == 50
        stroke = "#B9BDC2" if heavy else "#EEF0F2"
        dash = ' stroke-dasharray="3 3"' if heavy else ""
        out.append(f'<line x1="{gx:.1f}" y1="{pad_t}" x2="{gx:.1f}" '
                   f'y2="{pad_t + height}" stroke="{stroke}"{dash}/>')
        out.append(f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{pad_l + inner}" '
                   f'y2="{gy:.1f}" stroke="{stroke}"{dash}/>')
        out.append(f'<text x="{gx:.1f}" y="{pad_t + height + 10}" font-size="6.5" '
                   f'fill="{MID}" text-anchor="middle">{tick}</text>')
        out.append(f'<text x="{pad_l - 5}" y="{gy + 2.2:.1f}" font-size="6.5" '
                   f'fill="{MID}" text-anchor="end">{tick}</text>')

    taken: set[tuple[int, int]] = set()
    cell = 16.0

    def surname(full: str) -> str:
        parts = str(full).split()
        return parts[-1] if parts else str(full)

    target = None
    for name, x, y in peers:
        px, py = xy(x, y)
        if name == target_name:
            target = (px, py, name)
            continue
        out.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="2.4" fill="#C4C6CA"/>')
        if not label_peers:
            continue
        key = (int(px // cell), int(py // cell))
        if key in taken:
            continue
        taken.add(key)
        out.append(f'<text x="{px + 3.6:.1f}" y="{py + 2.2:.1f}" font-size="5.4" '
                   f'fill="#7C8288">{_e(surname(name))}</text>')

    if target is not None:
        px, py, name = target
        out.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="5.2" fill="{RED}" '
                   f'stroke="{PAPER}" stroke-width="1.8"/>')
        anchor = "end" if px > pad_l + inner * 0.66 else "start"
        dx = -8.5 if anchor == "end" else 8.5
        out.append(f'<text x="{px + dx:.1f}" y="{py + 3:.1f}" font-size="8" '
                   f'font-weight="700" fill="{DARK}" text-anchor="{anchor}">'
                   f'{_e(name)}</text>')

    out.append(f'<text x="{pad_l + inner / 2:.1f}" y="{size - 6}" font-size="7.5" '
               f'font-weight="600" fill="{DARK}" text-anchor="middle">'
               f'{_e(x_label)} percentile \u2192</text>')
    out.append(f'<text x="10" y="{pad_t + height / 2:.1f}" font-size="7.5" '
               f'font-weight="600" fill="{DARK}" text-anchor="middle" '
               f'transform="rotate(-90 10 {pad_t + height / 2:.1f})">'
               f'{_e(y_label)} percentile \u2192</text>')
    out.append("</svg>")
    return "".join(out)


def category_strip(name: str, score: float, peers: list[float],
                   width: int = 200) -> str:
    """One category: the peer distribution as light marks, the player as a filled one.

    The score is printed, so the strip works without colour and without the reader
    estimating a position by eye.
    """
    height, pad = 44, 8
    track = width - 2 * pad
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           f'viewBox="0 0 {width} {height}" font-family="Helvetica,Arial,sans-serif">']
    out.append(f'<text x="{pad}" y="11" font-size="9" font-weight="700" '
               f'fill="{DARK}">{_e(name)}</text>')
    out.append(f'<text x="{width - pad}" y="11" font-size="9" fill="{DARK}" '
               f'text-anchor="end">{score:.0f}</text>')
    out.append(f'<line x1="{pad}" y1="26" x2="{pad + track}" y2="26" '
               f'stroke="{LIGHT}" stroke-width="3"/>')
    for peer in peers:
        x = pad + track * max(0.0, min(100.0, float(peer))) / 100.0
        out.append(f'<circle cx="{x:.1f}" cy="26" r="1.8" fill="#CFCFCF"/>')
    px = pad + track * max(0.0, min(100.0, float(score))) / 100.0
    out.append(f'<circle cx="{px:.1f}" cy="26" r="4.2" fill="{BAND_COLOURS[_band(score)]}" '
               f'stroke="{PAPER}" stroke-width="1.3"/>')
    out.append("</svg>")
    return "".join(out)


def physical_band_legend(league: str) -> str:
    """The band key as ONE inline run, for the footer.

    Six stacked rows beside the radar cost ~15mm in a 64mm column and pushed six of the
    eight positions onto a second page. The page is a fixed 194mm, so the key lives in
    the footer instead -- full width, one line, alongside the report's other provenance
    notes. The league is named once here rather than repeated on every row.

    Every band prints its RANGE in brackets: "Very Good" is a label, not a quantity, and
    a chairman reading this cannot ask what it covers.
    """
    parts = []
    for name, low, high, colour in band_ranges():
        parts.append(
            '<span class="bk"><span class="bk-sw" style="background:' + colour
            + '"></span>' + _e(name) + " (" + str(low) + "-" + str(high) + ")</span>")
    return ('<span class="bandkey">Physical bands, ' + _e(league) + " for this position: "
            + " ".join(parts) + "</span>")
