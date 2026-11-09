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

from lofc.core import card as card_core   # the card's facts, shared with the web front end
from lofc.dashboard.loaders import round_half_up
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



def with_current_club(row: pd.Series, clubs: pd.DataFrame) -> pd.Series:
    """A copy of `row` carrying his current club, looked up by player_id -- so the card shows
    it however he was opened (table, search, watchlist)."""
    out = row.copy()
    match = clubs.loc[clubs["player_id"] == row.get("player_id"), "current_club"] \
        if not clubs.empty else pd.Series(dtype=object)
    out["current_club"] = match.iloc[0] if not match.empty else None
    return out


def club_text(team: str, current) -> str:
    """The club his stats are from, plus where he is now when that differs (Impect's current
    club): "Dundalk FC · now FC Portsmouth". Both names are Impect's, so they compare as-is."""
    if isinstance(current, str) and current and current != team:
        return f"{team} · now {current}"
    return team

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
    split = card_core.minutes_split(shares, assigned)
    if split is None:
        return ""

    segs, legend = [], []
    for seg in split["segments"]:
        pct = seg["share_pct"]
        segs.append(f'<div class="lofc-ph-seg" style="width:{pct:.2f}%;background:{seg["colour"]}" '
                    f'title="{html.escape(seg["position"])} {pct:.0f}%"></div>')
        name = html.escape(seg["position"])
        legend.append(f"<b>{name}</b> {pct:.0f}%" if seg["assigned"] else f"{name} {pct:.0f}%")

    goals_line = ""
    if split["goals_line"]:
        # "Goals: 4 as centre forward" -- the position names are provider text: escape them
        goals_line = f'<div class="lofc-ph-goals">{html.escape(split["goals_line"])}</div>'

    return (f'<div class="lofc-ph-mins">'
            f'<span class="lofc-ph-k2">Minutes by position</span>'
            f'<div class="lofc-ph-bar">{"".join(segs)}</div>'
            f'<div class="lofc-ph-legend">{" · ".join(legend)}</div>'
            f"{goals_line}</div>")


def _months_to(when) -> int | None:
    """Whole months from today to `when` (see `core.card.months_to`)."""
    return card_core.months_to(when)


def _chip_html(chip: dict, cls: str) -> str:
    inner = "".join(f"<b>{html.escape(t)}</b>" if bold else html.escape(t) for t, bold in chip["parts"])
    return f'<span class="lofc-ph-chip{cls}">{inner}</span>'


def status_strip(row: pd.Series, loan: pd.Series | None = None) -> str:
    """Contract runway and loan status, as chips.

    These decide whether a player is GETTABLE, which is a different question from how good
    he is, so they are stated plainly rather than left in a bio table. The wording and the
    under-12-months rule are `core.card.contract_chip` / `loan_chip`, shared with the web card.
    """
    contract = card_core.contract_chip(row.get("contract_until"))
    chips = [_chip_html(contract, " expiring" if contract["expiring"] else "")]
    loan_chip = card_core.loan_chip(loan)
    if loan_chip is not None:
        chips.append(_chip_html(loan_chip, " loan"))
    return f'<div class="lofc-ph-status">{"".join(chips)}</div>'


def build(row: pd.Series, shares: pd.DataFrame | None = None,
          loan: pd.Series | None = None) -> str:
    """The whole header as one HTML string."""
    cells = [_cell(label, value) for label, value in card_core.register_cells(row)]
    name = html.escape(str(row.get("player_name", "")))
    club = html.escape(club_text(row.get("team_name", "") or "", row.get("current_club")))
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
