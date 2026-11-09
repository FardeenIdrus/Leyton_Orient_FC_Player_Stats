"""Reference page "How playing styles work" (approved design, 2026-10-23).

Built FROM model/styles.py -- the styles, their signals and the thresholds -- so it can never
disagree with the labels, exactly as "What goes into each rating" is built from the scoring.
The worked example is picked from the data (League One, last complete season), so it never
goes stale.
"""

from __future__ import annotations

import html as _html

import pandas as pd
import streamlit as st_

from lofc.dashboard.rating_reference import _CSS
from lofc.model import styles as st

# One plain sentence per style, describing what its signals measure. Wording to be confirmed
# with the Head of Recruitment; the signals themselves are the definition.
STYLE_DESCRIPTIONS = {
    "Attacking": "Gets forward, crosses and creates chances",
    "Defending": "Stays in the full-back zone and engages in ground duels",
    "Inside": "Receives in central lanes and between the lines",
    "Aerial": "Contests a lot of headers, and wins them",
    "Ball-playing": "Passes forward and on the ground, and breaks lines",
    "Aggressive": "Steps out to press and to contest ground duels",
    "Destroyer": "Contests duels, makes defensive touches and presses",
    "Playmaker": "Receives, and passes forward on the ground and through lines",
    "Box-to-box": "Defends and also gets into the box",
    "Runner": "Makes deep runs and arrives in the box",
    "Pocket": "Receives between the lines",
    "Dribbler": "Carries the ball and beats players",
    "In behind": "Gets on the ball behind the defence",
    "Wide": "Holds the width and receives on the touchline",
    "1v1": "Takes defenders on",
    "Creator": "Crosses, supplies the box and creates chances",
    "Goalscorer": "Shoots often, gets into the box and scores",
    "Target man": "Contests aerial duels and holds the ball up",
    "Presser": "Presses the opponent's build-up and counter-presses",
    "Scorer": "Shoots often, gets into the box and scores",
}

_GROUP_LABELS = {"Where": "Where he plays", "What": "What he does"}
EXAMPLE_LEAGUE = 4   # League One
EXAMPLE_STYLE = {"Winger": "Wide"}   # the approved design's example


def example_style(group: str) -> str:
    """The style the worked example uses: two signals, so the averaging is visible."""
    if group in EXAMPLE_STYLE:
        return EXAMPLE_STYLE[group]
    styles = {s: v for g in st.STYLES[group].values() for s, v in g.items()}
    return next(s for s, sigs in styles.items() if len(sigs) >= 2)


def label_rules() -> dict[str, str]:
    return {
        "Strong": f"Clearly plays this way. Fit {st.STRONG:.0f}+ (top {100 - st.STRONG:.0f}% of his "
                  f"peers) and no signal below {st.FLOOR:.0f}.",
        "Leans": f"Tends to play this way. His best fit is {st.FLOOR:.0f}–{st.STRONG:.0f}: above "
                 f"average, but not clearly. Shown as \"Wide (leans)\" in the table.",
        st.NO_STYLE: f"Below average ({st.FLOOR:.0f}) at every style for his position. No label "
                     f"is forced on him; his card's Style fit bars show where he sits.",
    }


def style_table(group: str) -> pd.DataFrame:
    """Style · Label · Signals · In plain words, for one style group."""
    groups = st.STYLES[group]
    rows = []
    for gname, styles in groups.items():
        for style, sigs in styles.items():
            signals = " · ".join(st.SIGNAL_LABELS[s] + (" ⚑" if s in st.QUALITY_SIGNALS else "")
                                 for s in sigs)
            rows.append({"Style": style,
                         "Label": _GROUP_LABELS.get(gname, "") if len(groups) > 1 else "",
                         "Signals": signals, "In plain words": STYLE_DESCRIPTIONS[style]})
    return pd.DataFrame(rows)


def example_players(labels: pd.DataFrame, style: str) -> pd.DataFrame:
    """The clearest Strong player in `style` and the Leans player nearest the middle of the
    Leans band -- a real pair that shows the difference."""
    fit = f"fit.{style}"
    if labels.empty or fit not in labels.columns:
        return pd.DataFrame()
    strong = labels[[style in (s if isinstance(s, list) else []) for s in labels["strong_styles"]]]
    leans = labels[[style in (s if isinstance(s, list) else []) for s in labels["leans_styles"]]]
    out = []
    if not strong.empty:
        out.append(strong.sort_values(fit, ascending=False).iloc[[0]].assign(tier="Strong"))
    if not leans.empty:
        mid = (st.FLOOR + st.STRONG) / 2
        out.append(leans.iloc[[(leans[fit] - mid).abs().argmin()]].assign(tier="Leans"))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def _e(x) -> str:
    return _html.escape(str(x))


_PAGE_CSS = """<style>
.sr-steps,.sr-labels{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px;margin:6px 0 4px}
.sr-step{background:#FAFAFB;border-radius:12px;padding:14px 18px;font-size:.95rem;line-height:1.45}
.sr-step b.n{display:block;color:#C8102E;font-size:.85rem;margin-bottom:4px}
.sr-card{border:1px solid #E6E6E6;border-radius:12px;padding:14px 18px;font-size:.9rem;line-height:1.45;color:#4A4A4A}
.sr-card .t{display:block;font-size:1rem;font-weight:700;color:#1A1A1A;margin:8px 0 4px}
.sr-pill{display:inline-block;border-radius:999px;padding:3px 13px;font-size:.85rem;font-weight:600}
.sr-pill.s{background:#1A1A1A;color:#fff;border:1px solid #1A1A1A}
.sr-pill.l{background:#fff;color:#4A4A4A;border:1px dashed #8A8A8A}
.sr-pill.n{color:#6B6B6B;padding-left:0}
.sr-note{font-size:.82rem;color:#6B6B6B;margin:4px 0 10px}
</style>"""


# The three steps, with **bold** marked (the web page renders the same text).
STEPS = [("1 · Signals", "Mostly what he **attempts** and **where** he plays, e.g. his "
          "share of receptions out wide. ⚑ marks the ones that measure success."),
         ("2 · Compared with peers", "Each signal becomes a percentile (0–100) against the "
          "**same position, league and season**, 450+ minutes."),
         ("3 · Fit", "A style's **fit** is the average of its signals' percentiles. His "
          "label comes from his best fit.")]


def _bold(text: str) -> str:
    import re
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)


def _steps_html() -> str:
    return '<div class="sr-steps">' + "".join(
        f'<div class="sr-step"><b class="n">{t}</b>{_bold(body)}</div>' for t, body in STEPS) + "</div>"


def worked_example(frame: pd.DataFrame, group: str) -> dict | None:
    """The worked example for one style group, from the style inputs of a season (League One):
    the example style, its signals, and up to two real players (best Strong, mid-band Leans)
    with each signal's percentile and the fit -- formatted as the page shows them. None when
    League One has no data for it."""
    style = example_style(group)
    sigs = {s: v for g in st.STYLES[group].values() for s, v in g.items()}[style]
    pool = frame[frame["competition_id"] == EXAMPLE_LEAGUE]
    if pool.empty or not set(sigs) <= set(pool.columns):
        return None
    pcts = st.signal_percentiles(pool)
    labels = st.assign_styles(pcts).merge(
        pool[["player_id", "competition_id", "player_name", "team_name"]],
        on=["player_id", "competition_id"])
    labels = labels[labels["position_group"].map(st.style_group) == group]
    ex = example_players(labels, style)
    if ex.empty:
        return None
    p = pcts.set_index(["player_id", "competition_id"])
    rows = []
    for _, r in ex.iterrows():
        pr = p.loc[(r["player_id"], r["competition_id"])]
        rows.append({"name": str(r["player_name"]), "team": str(r["team_name"]),
                     "pcts": [f"{pr[s]:.0f}" for s in sigs],
                     "fit": f"{r[f'fit.{style}']:.0f}", "tier": str(r["tier"])})
    return {"style": style, "signal_keys": list(sigs),
            "signals": [st.SIGNAL_LABELS[s] for s in sigs], "rows": rows}


def _labels_html() -> str:
    rules = label_rules()
    cards = [("s", "Wide", "Strong", rules["Strong"]),
             ("l", "Wide", "Leans", rules["Leans"]),
             ("n", st.NO_STYLE, "None", rules[st.NO_STYLE])]
    return '<div class="sr-labels">' + "".join(
        f'<div class="sr-card"><span class="sr-pill {c}">{_e(p)}</span>'
        f'<span class="t">{_e(t)}</span>{_e(body)}</div>' for c, p, t, body in cards) + "</div>"


def _example_html(ex: dict) -> str:
    head = "".join(f"<th>{_e(lab)}</th>" for lab in ex["signals"])
    body = []
    for r in ex["rows"]:
        cells = "".join(f"<td>{p}th percentile</td>" for p in r["pcts"])
        pill = ('<span class="sr-pill s">' if r["tier"] == "Strong" else '<span class="sr-pill l">') \
            + _e(ex["style"]) + "</span>" + ("" if r["tier"] == "Strong" else " leans")
        body.append(f'<tr><td class="metric">{_e(r["name"])}<br><span style="font-weight:400;'
                    f'color:#6B6B6B;font-size:.8rem">{_e(r["team"])}</span></td>{cells}'
                    f'<td class="metric">{r["fit"]}</td><td>{pill}</td></tr>')
    return (_CSS + f'<table class="lofc-ref"><tr><th>Player</th>{head}<th>Fit</th><th>Label</th></tr>'
            + "".join(body) + "</table>")


def _table_html(table: pd.DataFrame) -> str:
    cols = [c for c in table.columns if not (c == "Label" and not table["Label"].any())]
    head = "".join(f"<th>{_e(c)}</th>" for c in cols)
    rows = "".join("<tr>" + "".join(
        f'<td class="{"metric" if c == "Style" else "group" if c == "Label" else ""}">{_e(r[c])}</td>'
        for c in cols) + "</tr>" for _, r in table.iterrows())
    return _CSS + f'<table class="lofc-ref"><tr>{head}</tr>{rows}</table>'


def render(season_id: int, season_label: str) -> None:
    from lofc.dashboard.loaders import load_style_inputs

    st_.markdown("### How playing styles work")
    st_.markdown("A style describes **how a player plays**. Styles never change a player's "
                 "rating.")
    st_.markdown(_PAGE_CSS + _steps_html(), unsafe_allow_html=True)

    st_.markdown("##### What the labels mean")
    st_.markdown(_labels_html(), unsafe_allow_html=True)
    st_.markdown('<div class="sr-note">A player can be Strong in more than one style. Wingers '
                 'get two labels: <b>where</b> they play and <b>what</b> they do.</div>',
                 unsafe_allow_html=True)

    group = st_.segmented_control("Position", list(st.STYLES), default="Winger",
                                  key="style_ref_group")
    if not group:
        return

    # Worked example: a two-signal style, League One, the season passed in.
    ex = worked_example(load_style_inputs(season_id), group)
    if ex is not None:
        st_.markdown(f'##### Example: "{ex["style"]}", League One, {season_label}')
        st_.markdown(_example_html(ex), unsafe_allow_html=True)
        fits = " · ".join(f"{r['name']}: fit {r['fit']} → {r['tier']}" for r in ex["rows"])
        st_.markdown(f'<div class="sr-note">Fit = the average of the percentiles. {_e(fits)}.</div>',
                     unsafe_allow_html=True)

    st_.markdown("##### Styles and their signals")
    st_.markdown(_table_html(style_table(group)), unsafe_allow_html=True)
    st_.markdown('<div class="sr-note">⚑ = measures success, not only what he attempts. Team style affects receptions: a winger in a direct side receives '
                 'more balls in behind. Defensive and central midfielders are compared together '
                 'for style.</div>', unsafe_allow_html=True)
