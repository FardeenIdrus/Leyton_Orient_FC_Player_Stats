"""The player card's identity header: who he is, and what kind of season he had.

Replaces a single grey run-on caption ("Winger · age 20.7 · League Two · left-footed ·
183 cm · contract to Jun 2028") in which a scout scanning twenty players could not find
the contract date. Same facts, set as a register: label above value, in ruled cells, the
way the club's own report already sets a bio.

The one deliberate flourish is the MINUTES BAR. The platform assigns a player one position
and scores him against that group's peers; for roughly one player in ten that label covers
under half his season. The bar shows the split, and the segment drawn in club red is the
position he is SCORED as -- so the colour states which comparison the numbers below rest
on, rather than decorating. Every other segment is an ink grey. That is the whole palette:
one red, one family of greys.

Pure: every function returns an HTML string and touches nothing. `render` is the only
Streamlit call, so the markup can be tested without a browser or a session.

SECURITY: player and club names arrive straight from provider data and are interpolated
into markup that Streamlit renders with unsafe_allow_html. Everything user- or
provider-supplied goes through html.escape. A 2026-08-25 audit found a stored XSS in
exactly this pattern elsewhere in the app.
"""

from __future__ import annotations

import datetime
import html

import pandas as pd
import streamlit as st

from lofc.dashboard.theme import RED

INK = "#14161A"
INK_SOFT = "#5A6068"
RULE = "#D9DCE0"
PANEL = "#F7F8F9"

# Greys for the positions a player is NOT scored as, darkest first so the second-biggest
# share reads as the next most important thing on the bar.
_OTHER_TONES = ["#6E747C", "#8B9199", "#A8ADB4", "#C3C7CC"]

_CSS = f"""
<style>
.lofc-ph {{ margin: .1rem 0 .9rem; }}
.lofc-ph-top {{ display: flex; align-items: baseline; justify-content: space-between;
  gap: 1rem; flex-wrap: wrap; }}
.lofc-ph-name {{ font-size: 1.55rem; font-weight: 800; letter-spacing: -.02em;
  color: {INK}; line-height: 1.1; }}
.lofc-ph-club {{ font-size: .95rem; color: {INK_SOFT}; }}
.lofc-ph-role {{ display: flex; align-items: center; gap: .5rem; margin: .3rem 0 .55rem; }}
.lofc-ph-flag {{ width: 4px; height: 15px; background: {RED}; flex: none; }}
.lofc-ph-pos {{ font-size: .82rem; font-weight: 700; color: {RED};
  text-transform: uppercase; letter-spacing: .07em; }}
.lofc-ph-league {{ font-size: .82rem; color: {INK_SOFT}; }}
.lofc-ph-cells {{ display: flex; flex-wrap: wrap; border-top: 1px solid {RULE};
  border-bottom: 1px solid {RULE}; }}
.lofc-ph-cell {{ flex: 1 1 0; min-width: 88px; padding: .45rem .8rem .45rem 0;
  border-right: 1px solid {RULE}; }}
.lofc-ph-cell:last-child {{ border-right: none; }}
.lofc-ph-k {{ font-size: .62rem; text-transform: uppercase; letter-spacing: .12em;
  color: {INK_SOFT}; display: block; margin-bottom: .12rem; }}
.lofc-ph-v {{ font-size: .95rem; font-weight: 600; color: {INK};
  font-variant-numeric: tabular-nums; }}
.lofc-ph-v.absent {{ font-weight: 400; color: {INK_SOFT}; font-style: italic; }}
.lofc-ph-mins {{ margin-top: .75rem; }}
.lofc-ph-k2 {{ font-size: .62rem; text-transform: uppercase; letter-spacing: .12em;
  color: {INK_SOFT}; }}
.lofc-ph-bar {{ display: flex; height: 9px; margin: .3rem 0 .35rem; overflow: hidden;
  background: {PANEL}; }}
.lofc-ph-seg {{ height: 9px; }}
.lofc-ph-legend {{ font-size: .74rem; color: {INK_SOFT}; line-height: 1.5; }}
.lofc-ph-legend b {{ color: {INK}; font-weight: 600; }}
.lofc-ph-goals {{ font-size: .74rem; color: {INK_SOFT}; margin-top: .1rem; }}
/* Contract runway and loan status. Both are RECRUITMENT facts rather than performance
   ones -- they decide whether a player is gettable at all -- so they sit on their own
   line, ahead of the minutes split, and the expiry is stated in months remaining as well
   as a date: "Jun 2027" does not read as urgent, "9 months" does. */
.lofc-ph-status {{ display: flex; flex-wrap: wrap; gap: .5rem; margin-top: .6rem; }}
.lofc-ph-chip {{
  font-size: .72rem; padding: .12rem .5rem; border: 1px solid {RULE};
  color: {INK}; background: {PANEL}; white-space: nowrap;
}}
.lofc-ph-chip b {{ font-weight: 700; }}
.lofc-ph-chip.expiring {{ border-color: {RED}; color: {RED}; background: #FCE8EB; }}
.lofc-ph-chip.loan {{ border-color: #1F6FB2; color: #14507F; background: #EAF2F9; }}
</style>
"""


def _cell(label: str, value: str | None) -> str:
    """One labelled cell. An absent value says so in words; it never renders as 0 or '-'."""
    if value:
        inner = f'<span class="lofc-ph-v">{html.escape(value)}</span>'
    else:
        inner = '<span class="lofc-ph-v absent">not recorded</span>'
    return (f'<div class="lofc-ph-cell"><span class="lofc-ph-k">{html.escape(label)}</span>'
            f"{inner}</div>")


def minutes_bar(shares: pd.DataFrame, assigned: str) -> str:
    """The stacked minutes-by-position bar, plus its legend and goals line.

    `assigned` is the position the player is scored as; its segment is club red and every
    other is an ink grey. Returns "" when there is nothing to say -- a player who filled
    one position all season has no split worth drawing, and an empty bar would imply one.
    """
    if shares is None or len(shares) < 2:
        return ""

    segs, legend = [], []
    other = iter(_OTHER_TONES)
    for r in shares.itertuples():
        is_assigned = r.position_group == assigned
        colour = RED if is_assigned else next(other, _OTHER_TONES[-1])
        pct = float(r.share) * 100.0
        segs.append(f'<div class="lofc-ph-seg" style="width:{pct:.2f}%;background:{colour}" '
                    f'title="{html.escape(r.position_group)} {pct:.0f}%"></div>')
        name = html.escape(r.position_group)
        legend.append(f"<b>{name}</b> {pct:.0f}%" if is_assigned else f"{name} {pct:.0f}%")

    goals = [(r.position_group, float(r.goals)) for r in shares.itertuples()
             if pd.notna(r.goals) and float(r.goals) >= 0.5]
    goals_line = ""
    if len(goals) > 1 or (goals and shares.iloc[0]["position_group"] != goals[0][0]):
        parts = " · ".join(f"{g:.0f} as {html.escape(p.lower())}" for p, g in goals)
        goals_line = f'<div class="lofc-ph-goals">Goals: {parts}</div>'

    return (f'<div class="lofc-ph-mins">'
            f'<span class="lofc-ph-k2">Minutes by position</span>'
            f'<div class="lofc-ph-bar">{"".join(segs)}</div>'
            f'<div class="lofc-ph-legend">{" · ".join(legend)}</div>'
            f"{goals_line}</div>")


def _months_to(when) -> int | None:
    """Whole months from today to `when`, or None. Negative means already expired.

    pd.isna FIRST and unconditionally. `pd.NaT` passes `isinstance(x, datetime.datetime)`
    -- it subclasses datetime -- so guarding on the type before the null check let NaT
    through, returned nan, and the caller then raised "NaTType does not support strftime",
    breaking the whole player card for anyone with no contract date.
    """
    if when is None:
        return None
    try:
        if pd.isna(when):
            return None
    except (TypeError, ValueError):
        return None
    end = pd.Timestamp(when).date()
    today = datetime.date.today()
    return (end.year - today.year) * 12 + (end.month - today.month)


def status_strip(row: pd.Series, loan: pd.Series | None = None) -> str:
    """Contract runway and loan status, as chips.

    These decide whether a player is GETTABLE, which is a different question from how good
    he is, so they are stated plainly rather than left in a bio table. The runway is given
    in months as well as a date: "Jun 2027" does not read as urgent to someone scanning a
    list, "9 months left" does. Under 12 months is marked, because that is the window in
    which a player can be approached.
    """
    chips = []
    contract = row.get("contract_until")
    months = _months_to(contract)
    if months is None:
        chips.append('<span class="lofc-ph-chip">Contract <b>not recorded</b></span>')
    else:
        when = pd.Timestamp(contract).strftime("%b %Y")
        if months < 0:
            chips.append(f'<span class="lofc-ph-chip expiring">Contract <b>expired</b> '
                         f'({html.escape(when)})</span>')
        else:
            years, rem = divmod(months, 12)
            length = (f"{years}y {rem}m" if years and rem else
                      f"{years}y" if years else f"{rem}m")
            cls = " expiring" if months < 12 else ""
            chips.append(f'<span class="lofc-ph-chip{cls}">Contract to '
                         f'<b>{html.escape(when)}</b> · {length} left</span>')

    if loan is not None and len(loan):
        parent = loan.get("parent_club")
        ends = loan.get("loan_ends")
        bits = "On loan"
        if parent and pd.notna(parent):
            bits += f" from <b>{html.escape(str(parent))}</b>"
        if ends is not None and pd.notna(ends):
            bits += f" · until {html.escape(pd.Timestamp(ends).strftime('%b %Y'))}"
        chips.append(f'<span class="lofc-ph-chip loan">{bits}</span>')

    return f'<div class="lofc-ph-status">{"".join(chips)}</div>'


def build(row: pd.Series, shares: pd.DataFrame | None = None,
          loan: pd.Series | None = None) -> str:
    """The whole header as one HTML string."""
    def text(key, fmt=None):
        v = row.get(key)
        if v is None or (not isinstance(v, str) and pd.isna(v)):
            return None
        return fmt(v) if fmt else str(v)

    cells = [
        _cell("Age", text("age", lambda v: f"{float(v):.1f}")),
        _cell("Foot", text("foot", lambda v: str(v).capitalize())),
        _cell("Height", text("height_cm", lambda v: f"{int(v)} cm")),
        # Contract deliberately NOT here: it is the chip below, which carries the same
        # date PLUS the time remaining and the urgency colour. Showing it in both places
        # printed "Contract to" twice on every card. Nationality takes the freed cell --
        # it reached ~100% coverage in the 2026-09-07 backfill and had nowhere to show.
        _cell("Nationality", text("nationality")),
        _cell("Minutes", text("minutes", lambda v: f"{float(v):,.0f}")),
    ]
    name = html.escape(str(row.get("player_name", "")))
    club = html.escape(str(row.get("team_name", "") or ""))
    position = html.escape(str(row.get("position_group", "") or ""))
    league = html.escape(str(row.get("league", "") or ""))

    return (
        f'{_CSS}<div class="lofc-ph">'
        f'<div class="lofc-ph-top"><div class="lofc-ph-name">{name}</div>'
        f'<div class="lofc-ph-club">{club}</div></div>'
        f'<div class="lofc-ph-role"><span class="lofc-ph-flag"></span>'
        f'<span class="lofc-ph-pos">{position}</span>'
        f'<span class="lofc-ph-league">{league}</span></div>'
        f'<div class="lofc-ph-cells">{"".join(cells)}</div>'
        f'{status_strip(row, loan)}'
        f'{minutes_bar(shares, str(row.get("position_group", "")))}'
        f"</div>")


def render(row: pd.Series, shares: pd.DataFrame | None = None,
           loan: pd.Series | None = None) -> None:
    st.markdown(build(row, shares, loan), unsafe_allow_html=True)
