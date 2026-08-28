"""The injury and availability evidence panel (spec section 6).

Rendered in TWO places -- the player profile and the assessment form -- from this one
module, so the two can never disagree about a player. Every figure here is evidence for a
human to weigh; Decision 12 means none of it is summed, weighted, or mapped into a score.

Layout (frontend-design skill, spec section 16): the availability figure, its status
caption and the league-coverage caption sit together in one block at the top of the panel
-- never split across a metrics row and a page footer. The status caption is rendered with
a bold lead-in word ("Not known.", "Available.", the percentage) so the state is carried by
text, not by colour.

The injury record below it is GROUPED, not greyed: a "Scored window" table sits above an
"Earlier seasons" table, both at full weight and full contrast, with window membership
stated in the section heading -- words, never colour alone. Earlier design faded
out-of-window rows to a light grey via a pandas Styler; on a typical player, where the
injury history reaches back to 2019/20 against a two-season window, that faded roughly 70%
of the table, so the panel read as disabled rather than as "these rows don't count towards
the figure". A scout wants the full history even when the current figure ignores it (spec
section 6, point 3) -- "visible but greyed" and "visible and legible" are not the same
thing at that ratio, so grouping replaces fading rather than reinforcing it.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from lofc.dashboard import theme
from lofc.model.medical import (AVAILABILITY_SEASONS, AvailabilityEvidence,
                                AvailabilityStatus, availability_with_evidence,
                                games_missed_in_window, window_labels)
from lofc.store.injuries import COVERAGE, load_for_player

# How each injury record's provenance is named on screen. "transfermarkt" used to render as
# the internal-jargon "Scraped" -- accurate to how the data arrived, but not a source name a
# reader outside the building would recognise on a panel that appears in reports. Naming the
# actual source is both more professional and more informative (which league site, not just
# "some scrape").
SOURCE_LABELS = {"transfermarkt": "Transfermarkt", "manual": "Entered by hand"}

# The columns shown in every injury table, and how each is labelled on screen. One list so
# the "no window configured" table, the "in window" table and the "earlier seasons" table
# can never drift into three different column sets.
_TABLE_COLUMNS = ["season_label", "injury_type_raw", "injury_category", "date_from",
                  "date_until", "days_out", "games_missed", "Source"]
_TABLE_HEADERS = ["Season", "Injury", "Category", "From", "Until", "Days out",
                  "Matches missed", "Source"]

_STYLE_KEY = "lofc_injury_window"


def _inject_style() -> None:
    """Scoped CSS for the "in the scored window" table only, keyed via `st.container(key=...)`
    -- the same technique `theme.py` and `session.topbar_identity` already use for
    page-level CSS. A thin red rule on the left edge marks the currently-scored table as the
    one the figure above was computed from; the "earlier seasons" table below is left with
    the plain document border every other table on the platform gets, so the distinction
    reads as structure (this table is the active one) rather than as one table being faded
    out. No text colour is touched anywhere -- window membership is carried by the two
    section headings in words, never by colour alone.
    """
    st.markdown(
        f"""
        <style>
          .st-key-{_STYLE_KEY} [data-testid="stDataFrame"] {{
            border-left: 3px solid {theme.RED};
          }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _format_table(frame: pd.DataFrame) -> pd.DataFrame:
    """One injury table, columns named and ordered for display. Never touches colour or
    font weight -- every row this is called on renders at full legibility."""
    display = frame.assign(Source=frame["source"].map(SOURCE_LABELS).fillna(frame["source"]))
    display = display[_TABLE_COLUMNS]
    display.columns = _TABLE_HEADERS
    return display


def resolve_window(season_id: int, seasons: int = AVAILABILITY_SEASONS) -> tuple[str, ...] | None:
    """The availability window's season labels, or None if this season is not yet mapped.

    `window_labels` is deliberately loud (it raises) so a forgotten `_SEASON_LABELS` update
    is a maintenance error that surfaces immediately, not a silently shrunk window -- see its
    docstring. That is correct for the model layer, but a raise here would take down the
    whole player profile for every player once the sidebar offers a season one step ahead of
    `_SEASON_LABELS` (CRITICAL 1: `available_seasons()` already does this before the mapping
    catches up). This is the one place that ValueError is expected and handled: the panel
    degrades to 'no window configured' rather than crashing the page.
    """
    try:
        return window_labels(season_id, seasons)
    except ValueError:
        return None


def spell_rows(injuries: pd.DataFrame, window: tuple[str, ...]) -> pd.DataFrame:
    """Every spell with an `in_window` flag saying whether it counts towards the figure.

    Out-of-window spells are RETAINED, flagged False, and greyed by the caller -- never
    filtered out. A scout wants a player's history even where the current figure ignores it.
    """
    frame = injuries.copy()
    if frame.empty:
        frame["in_window"] = pd.Series(dtype=bool)
        return frame
    frame["in_window"] = frame["season_label"].isin(window)
    return frame


def availability_caption(ev: AvailabilityEvidence, window: tuple[str, ...]) -> str:
    """The one-line caption that must sit beside the availability figure.

    The UNKNOWN wording is the fix for defect R8 on screen: a player Transfermarkt never
    tracked must never read as a player who was never injured.
    """
    seasons = " and ".join(window)
    if ev.status is AvailabilityStatus.UNKNOWN:
        return ("**Not known.** No injury record for this player, and his minutes do not "
                "confirm availability either way. This is a gap in the data, not a clean "
                "record.")
    if ev.status is AvailabilityStatus.CONFIRMED_BY_MINUTES:
        return ("**Available.** No injury record, but his minutes played rule out a long "
                "absence — an independent check that does not depend on injury reporting.")
    if ev.value is None:
        return ("Injury record present, but availability is **not scored** for this "
                "competition — no fixture count is configured for it.")
    return (f"**{ev.value:.0%}** of matches available across {seasons}. "
            "Counts matches missed through injury only — a fit player who was not selected "
            "is not penalised.")


def coverage_caption(competition_id: int) -> str:
    """How much an empty injury record is worth in THIS player's league (spec section 10.3).

    Sits beside the availability figure, never in a footer: a blank record in the
    Championship and a blank record in the National League are different statements and
    must not look identical.
    """
    figures = COVERAGE.get(competition_id)
    if figures is None:
        return ("We hold **no coverage figure** for this competition, so an empty injury "
                "record here says nothing either way.")
    with_record = f"{figures['with_record']:.0%}"
    knowable = figures.get("knowable")
    line = (f"In this league **{with_record}** of players have any injury record at all, "
            "so an empty record often means we have nothing rather than that nothing "
            "happened.")
    if knowable is not None:
        line += (f" Counting minutes played as a cross-check, availability is establishable "
                 f"for about **{knowable:.0%}** of players here.")
    return line


def render(engine, player_id: int, competition_id: int, season_id: int,
           minutes_played: int | None) -> None:
    """Draw the panel. Read-only everywhere it appears."""
    injuries = load_for_player(engine, player_id)
    window = resolve_window(season_id)

    _inject_style()
    st.markdown("#### Availability and injury record")

    if window is None:
        # CRITICAL 1: this season is not yet in `_SEASON_LABELS` (a maintenance gap, not a
        # player-specific problem). Degrade -- no figure, no crash -- and still show whatever
        # injury history exists, since that is real evidence regardless of the window.
        st.warning("**No availability window is configured for this season yet**, so a "
                   "two-season availability figure cannot be computed. The injury record "
                   "below is shown on its own.")
        _render_injury_table(injuries, window=None)
        return

    missed = games_missed_in_window(injuries, season_id)
    ev = availability_with_evidence(injuries, missed, competition_id, minutes_played,
                                    seasons=AVAILABILITY_SEASONS, minutes_seasons=1)

    # The figure, then its caveat, then the league-coverage warning -- all in one block, in
    # that order, so nothing about what the figure means is left for a footer to explain.
    figure = "—" if ev.value is None else f"{ev.value:.0%}"
    left, mid, right = st.columns([1.2, 1, 1])
    left.metric("Availability", figure)
    mid.metric("Matches missed", missed if not injuries.empty else "—")
    # `is not None`, not truthiness: a player with genuinely zero minutes must show "0", not
    # "—" -- this panel exists precisely to stop "zero" and "unknown" being conflated.
    right.metric("Minutes played", f"{minutes_played:,}" if minutes_played is not None else "—")

    st.markdown(availability_caption(ev, window))
    st.caption(coverage_caption(competition_id))

    _render_injury_table(injuries, window=window)


def _render_injury_table(injuries: pd.DataFrame, window: tuple[str, ...] | None) -> None:
    """The 'Injury spells' record. `window=None` means no scored window is configured for
    this season (CRITICAL 1) -- every spell is shown in one plain table, with no
    in-window/out-of-window split, since we have no window to judge them against.

    Otherwise the record is GROUPED into two tables -- "In the scored window" and "Earlier
    seasons" -- rather than shown as one table with out-of-window rows faded. Both render at
    full weight and full contrast; window membership is stated once, in words, in the
    heading each table sits under, which is unambiguous for every row beneath it and (unlike
    colour) survives black-and-white printing. See the module and `_inject_style` docstrings
    for why this replaced the previous per-row grey.
    """
    st.markdown("**Injury spells**")
    if injuries.empty:
        st.info("No injury spells on record for this player. Given the league coverage "
                "above, treat this as an absence of evidence, not evidence of fitness.")
        return

    if window is None:
        st.dataframe(_format_table(injuries), width="stretch", hide_index=True)
        st.caption("No scored window is configured for this season, so spells are listed "
                   "without an in-window / out-of-window split.")
        return

    spells = spell_rows(injuries, window)
    in_window = spells[spells["in_window"]]
    earlier = spells[~spells["in_window"]]
    window_text = " and ".join(window)

    st.markdown(f"**In the scored window** ({window_text}) — "
                f"{len(in_window)} spell{'' if len(in_window) == 1 else 's'}")
    with st.container(key=_STYLE_KEY):
        if in_window.empty:
            st.caption("No spells recorded in the scored window.")
        else:
            st.dataframe(_format_table(in_window), width="stretch", hide_index=True)

    st.markdown(f"**Earlier seasons** — "
                f"{len(earlier)} spell{'' if len(earlier) == 1 else 's'}")
    if earlier.empty:
        st.caption("No earlier spells on record.")
    else:
        st.dataframe(_format_table(earlier), width="stretch", hide_index=True)
    st.caption("Earlier seasons are part of the player's history but do not count towards "
               "the availability figure above.")
