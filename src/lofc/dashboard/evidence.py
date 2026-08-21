"""The injury and availability evidence panel (spec section 6).

Rendered in TWO places -- the player profile and the assessment form -- from this one
module, so the two can never disagree about a player. Every figure here is evidence for a
human to weigh; Decision 12 means none of it is summed, weighted, or mapped into a score.

Layout (frontend-design skill, spec section 16): the availability figure, its status
caption and the league-coverage caption sit together in one block at the top of the panel
-- never split across a metrics row and a page footer. The status caption is rendered with
a bold lead-in word ("Not known.", "Available.", the percentage) so the state is carried by
text, not by colour; the injury table's greying of out-of-window rows is likewise backed by
an explicit "Window" column so the colour is a reinforcement, never the only signal.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

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
    """The 'Injury spells' table. `window=None` means no scored window is configured for
    this season (CRITICAL 1) -- every spell is shown, with no in-window/out-of-window split,
    since we have no window to judge them against."""
    st.markdown("**Injury spells**")
    if injuries.empty:
        st.info("No injury spells on record for this player. Given the league coverage "
                "above, treat this as an absence of evidence, not evidence of fitness.")
        return

    if window is None:
        display = injuries.assign(
            Source=injuries["source"].map(SOURCE_LABELS).fillna(injuries["source"]),
        )[["season_label", "injury_type_raw", "injury_category", "date_from", "date_until",
           "days_out", "games_missed", "Source"]]
        display.columns = ["Season", "Injury", "Category", "From", "Until", "Days out",
                           "Matches missed", "Source"]
        st.dataframe(display, width="stretch", hide_index=True)
        st.caption("No scored window is configured for this season, so spells are listed "
                   "without an in-window / out-of-window split.")
        return

    spells = spell_rows(injuries, window)
    display = spells.assign(
        Window=spells["in_window"].map({True: "In window", False: "Outside window"}),
        Source=spells["source"].map(SOURCE_LABELS).fillna(spells["source"]),
    )[["season_label", "injury_type_raw", "injury_category", "date_from", "date_until",
       "days_out", "games_missed", "Window", "Source"]]
    display.columns = ["Season", "Injury", "Category", "From", "Until", "Days out",
                       "Matches missed", "Window", "Source"]

    def _grey(row):
        # Words carry the meaning (the Window column, in plain text); the grey only
        # reinforces it for a scout scanning the table quickly -- it is never the only
        # signal that a spell falls outside the scored window.
        faded = "color:#9a9a9a;" if row["Window"] == "Outside window" else ""
        return [faded] * len(row)

    st.dataframe(display.style.apply(_grey, axis=1), width="stretch", hide_index=True)
    st.caption("Spells outside the two-season window are shown greyed — they are part of "
               "the player's history but do not count towards the figure above.")
