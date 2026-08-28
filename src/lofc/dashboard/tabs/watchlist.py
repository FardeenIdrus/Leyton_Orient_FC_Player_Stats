"""The Watchlist tab: the recruiter's own tracked players, statuses and notes.

This is the one table in the platform that holds USER data rather than pipeline output, so
it is never rebuilt or swept by a pipeline run.

Beyond the tracking list itself, this page now surfaces the signals that make a watched
player worth revisiting: whether he's actually playing this season, how long his contract
has left, his recorded injury history, and the club's real 1-5 composite (replacing the
retired `player_scores.performance_score` figure the table used to show under 'Quality' --
see `store/models.py::PlayerScorecard`'s docstring for why that number is no longer
connected to the ranking anywhere else on the platform). Every figure here is read off data
that already exists; nothing is invented, and nothing hides a watched player from the list.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from lofc.config import settings
from lofc.dashboard import badges
from lofc.dashboard.formatting import link_or_blank, numeric_or_dash
from lofc.dashboard.loaders import (
    _competition_name_by_id, get_engine, load_assessment_status, load_current_form,
    load_injuries_for_players, load_scorecards)
from lofc.dashboard.seasons import season_name_for
from lofc.dashboard.session import CarriedPlayer, go_to_assess
from lofc.dashboard.tabs.players import _current_form_summary
from lofc.model import assessment_status
from lofc.model import scout_scores
from lofc.store import watchlist

# The four-value assessment_status category maps onto the raw statuses badges.for_status
# already renders text for, so the watchlist's badge column is never a second source of
# wording (Rule/spec section 7.1) -- it just doesn't know a single author/approver, since
# the aggregate can span two dimensions entered by two different people.
_AGGREGATE_TO_RAW_STATUS = {
    assessment_status.NOT_ASSESSED: None,
    assessment_status.AWAITING: "submitted",
    assessment_status.CONFLICTED: scout_scores.CONFLICT,
    assessment_status.SIGNED_OFF: "signed_off",
}

_INJURY_PREFIX = "🔴"   # currently-out marker; the word "out" always carries it too


def _badge_text(aggregate_status: str) -> str:
    return badges.for_status(_AGGREGATE_TO_RAW_STATUS[aggregate_status]).text


def _current_form_text(live_rows: pd.DataFrame, player_id: int) -> str:
    """Plain-fact 'has he played this season' read for one watched player -- reuses the same
    pure aggregator the profile's Current form section uses (`tabs/players.py`), so the two
    surfaces can never disagree about a player's minutes. Never a rating: too little of a
    live season is played for a composite, exactly as the profile's version states."""
    summary = _current_form_summary(live_rows, player_id)
    if summary is None:
        return "Not featured yet"
    return f"{summary['minutes']:,} min · {summary['goals']}g {summary['assists']}a"


def _summarize_injuries(injuries: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """One row per player: a plain-fact injury status from his most recent recorded spell,
    dated so the reader judges recency themselves.

    Deliberately reports only the LATEST spell, not a rating or a running tally: this is a
    watchlist column, not the Medical dimension's availability score (`model/medical.py`),
    and must not imply a verdict the single most-recent record can't support. A player with
    no rows at all reads as 'no injury spells on record' -- stating what the data holds, not
    claiming he is verified fit (the same distinction `model/medical.py`'s
    `AvailabilityStatus` draws for the scoring side: no record can mean genuinely uninjured
    OR simply unscraped, and this does not pretend to know which).
    """
    if injuries.empty:
        return pd.DataFrame(columns=["player_id", "injury_status"])
    df = injuries.copy()
    df["date_from"] = pd.to_datetime(df["date_from"], errors="coerce")
    df["date_until"] = pd.to_datetime(df["date_until"], errors="coerce")
    latest = (df.sort_values("date_from", ascending=False, na_position="last")
                .groupby("player_id", as_index=False).first())

    def _text(row) -> str:
        category = row["injury_category"] or row["injury_type_raw"] or "Injury"
        ongoing = pd.isna(row["date_until"]) or row["date_until"] >= as_of
        if ongoing:
            since = (row["date_from"].strftime("%d %b %Y")
                    if pd.notna(row["date_from"]) else "an unknown date")
            return f"{_INJURY_PREFIX} Currently out — {category} (since {since})"
        returned = row["date_until"].strftime("%d %b %Y")
        return f"Last injury: {category} (returned {returned})"

    latest["injury_status"] = latest.apply(_text, axis=1)
    return latest[["player_id", "injury_status"]]


def _watchlist_alerts(months_left: pd.Series, injury_status_col: pd.Series,
                      assessment_status_col: pd.Series) -> dict[str, int]:
    """Counts for the 'what needs a look' strip above the table. Every figure is read
    straight off columns already on the frame -- pure and testable without Streamlit, so the
    threshold logic (what counts as 'expiring soon', 'currently injured') is verified
    directly rather than only by eye in the rendered page."""
    expiring = int(((months_left >= 0) & (months_left <= 6)).sum())
    injured = int(injury_status_col.fillna("").str.startswith(_INJURY_PREFIX).sum())
    unassessed = int((assessment_status_col == assessment_status.NOT_ASSESSED).sum())
    return {"total": int(len(months_left)), "expiring_soon": expiring,
           "currently_injured": injured, "not_assessed": unassessed}


@st.dialog("Watchlist entry")
def _watchlist_entry_dialog(pid: int, cid: int, sid: int, player_name: str,
                            club: str, note: str, status: str,
                            position_group: str | None = None) -> None:
    """Read and edit one watched player: full note, status, save or remove.

    Every exit path bumps the table key (clearing the row selection) before
    rerunning, so the dialog does not immediately reopen.
    """
    st.markdown(f"**{player_name}** · {club}")
    new_note = st.text_area("Scout note", value=note, height=160, key="wl_dialog_note",
                            placeholder="What to verify, who watched him, verdicts...")
    new_status = st.selectbox("Status", watchlist.WATCHLIST_STATUSES,
                              index=watchlist.WATCHLIST_STATUSES.index(status)
                              if status in watchlist.WATCHLIST_STATUSES else 0,
                              key="wl_dialog_status")
    st.caption("'Scout sent' above is a note you enter yourself — it records that you asked "
               "someone to look at this player. It is separate from the assessment status "
               "shown in the table, which records that someone actually did.")

    def _close():
        st.session_state["watchlist_table_ver"] = st.session_state.get("watchlist_table_ver", 0) + 1
        st.rerun()

    save_col, remove_col, close_col = st.columns(3)
    if save_col.button("Save", type="primary", key="wl_dialog_save"):
        watchlist.set_note(get_engine(), pid, cid, sid, new_note.strip() or None)
        watchlist.set_status(get_engine(), pid, cid, sid, new_status)
        _close()
    if remove_col.button("Remove from watchlist", key="wl_dialog_remove"):
        watchlist.remove(get_engine(), pid, cid, sid)
        _close()
    if close_col.button("Close", key="wl_dialog_close"):
        _close()

    if st.button("Assess this player", key="wl_dialog_assess"):
        # Same session-state handoff the profile's "Assess this player" button uses
        # (dashboard/tabs/players.py::_scout_section), so both entry points agree. The
        # watchlist has no `minutes` column (see store/watchlist.load's SELECT) -- the Assess
        # page's evidence panel shows that as "—", the same as any other unknown minutes.
        st.session_state["watchlist_table_ver"] = st.session_state.get("watchlist_table_ver", 0) + 1
        go_to_assess(CarriedPlayer(
            player_id=pid, player_name=player_name, competition_id=cid, season_id=sid,
            position_group=position_group, minutes=None))


def _watchlist(tab) -> None:
    """The tracking list: every watched player; click a row to read/edit its note.

    Reads its own fresh query (never the filtered pool, never cached): watched
    players must show regardless of the sidebar filters, and edits must be
    visible immediately after saving.
    """
    with tab:
        df = watchlist.load(get_engine())
        if df.empty:
            st.info("No players on the watchlist yet. Open any player's profile and click "
                    "“☆ Add to watchlist” — tracked players, statuses and scout notes live here.")
            return

        # Derived, never stored: joins on the same (player, competition, season) triple the
        # profile's scout section reads, so a watchlist row and a profile row can't disagree.
        df = assessment_status.attach(df, load_assessment_status())

        # Current-season form: matched on player_id alone -- a watchlist row is keyed to
        # whichever season he was SCORED in, but "is he playing right now" is about the live
        # season regardless of that, exactly as the profile's own current-form section reads.
        live = settings.live_season_id
        if live is None:
            df["current_form"] = "—"
            form_header = "This season"
        else:
            live_rows = load_current_form()
            df["current_form"] = df["player_id"].map(
                lambda pid: _current_form_text(live_rows, int(pid)))
            form_header = f"This season ({season_name_for(live)})"

        # Contract countdown -- identical arithmetic to the Players tab, so the two surfaces
        # never disagree about how long a deal has left. Stored back onto `df` itself (not
        # kept as a standalone Series): the assessment-status filter below re-indexes `df`
        # with `reset_index(drop=True)`, and a Series left outside that no longer lines up by
        # position -- only a column travels correctly with its row through the filter.
        df["contract_until_dt"] = pd.to_datetime(df["contract_until"], errors="coerce")
        df["months_left"] = (
            (df["contract_until_dt"] - pd.Timestamp.now().normalize()).dt.days / 30.44).round(0)

        # Injury record, bulk-loaded for exactly the players on this list (never the whole
        # 3,766-row table) -- recent absence is material to a recruiter revisiting a target.
        player_ids = tuple(sorted(df["player_id"].astype(int).unique().tolist()))
        injuries = _summarize_injuries(load_injuries_for_players(player_ids),
                                       pd.Timestamp.now().normalize())
        df = df.merge(injuries, on="player_id", how="left")
        df["injury_status"] = df["injury_status"].fillna("No injury spells on record")

        # The club's real 1-5 composite (replaces the old 'Quality' column, which read the
        # RETIRED player_scores.performance_score -- a 0-100 figure from a superseded scoring
        # model, no longer the platform's ranking anywhere else). A watched player can be
        # scored in more than one season, so pull scorecards for every season present here.
        season_ids = sorted(int(s) for s in df["season_id"].dropna().unique().tolist())
        sc_cols = ["player_id", "competition_id", "season_id", "objective_composite",
                  "performance_band", "physical_band"]
        scorecards = (pd.concat([load_scorecards(sid)[sc_cols] for sid in season_ids],
                                ignore_index=True) if season_ids else pd.DataFrame(columns=sc_cols))
        df = df.merge(scorecards, on=["player_id", "competition_id", "season_id"], how="left")

        st.markdown("**Players the club is tracking.** Click a row to read the full note, "
                    "edit it, change the status, or remove the player.")
        chosen = st.multiselect(
            "Assessment status", list(assessment_status.STATUSES),
            default=list(assessment_status.STATUSES),
            help="Which of your targets still need a scout?")
        df = df[df["assessment_status"].isin(chosen)].reset_index(drop=True)
        st.caption("'Scout sent' is a note you enter — it records that you asked someone to "
                   "look at a player. The assessment status records that someone did. They "
                   "are deliberately separate.")
        if df.empty:
            st.info("No watched players match the chosen assessment status.")
            return

        # --- What needs a look: a quiet, always-on read of the list, not a second filter --
        # every count here is derived from columns already computed above.
        alerts = _watchlist_alerts(df["months_left"], df["injury_status"], df["assessment_status"])
        a1, a2, a3, a4 = st.columns(4)
        a1.metric("On the list", alerts["total"], border=True)
        a2.metric("Contract ≤ 6 months", alerts["expiring_soon"], border=True,
                 help="Known contract dates only — free to sign a pre-contract deal elsewhere.")
        a3.metric("Currently injured", alerts["currently_injured"], border=True,
                 help="On record as out injured right now, per the Transfermarkt scrape.")
        a4.metric("Not yet assessed", alerts["not_assessed"], border=True,
                 help="No Psychological or Medical assessment recorded for this player yet.")

        name_by_id = _competition_name_by_id()   # all leagues incl. Scottish/PL2 (901/902/903)
        frame = pd.DataFrame({
            "Player": df["player_name"], "Club": df["team_name"],
            "League": df["competition_id"].map(name_by_id).fillna(df["competition_name"]),
            "Position": df["position_group"],
            # Age/Market value/Months left/Transfermarkt render as pre-formatted text
            # (numeric_or_dash/link_or_blank, dashboard/formatting.py), not raw numbers fed
            # to NumberColumn/LinkColumn: confirmed directly against the running app that a
            # missing NumberColumn/LinkColumn cell renders the literal text "None" here,
            # regardless of whether the missing marker is a numpy NaN, a Python None or
            # pandas' own pd.NA -- so the fix has to happen before the value ever reaches
            # that column type, not by trying a "cleaner" null. Text formatted this way
            # sorts as text, same known trade-off "Contract" already makes below.
            "Age": numeric_or_dash(df["age"], "{:.1f}"),
            "Composite": df["objective_composite"],
            "Performance": df["performance_band"],
            "Physical": df["physical_band"],
            form_header: df["current_form"],
            "Injury": df["injury_status"],
            "Market value": numeric_or_dash(df["market_value_eur"] / 1e6, "€{:.1f}m"),
            "Contract": df["contract_until_dt"].dt.strftime("%m/%Y").fillna("—"),
            "Months left": numeric_or_dash(df["months_left"], "{:.0f}"),
            "Status": df["status"],
            "Assessed": df["assessment_status"].map(_badge_text),
            "Note": df["note"].fillna(""),
            "Added": pd.to_datetime(df["created_at"]).dt.strftime("%d %b %Y"),
            "Transfermarkt": link_or_blank(
                df["tm_player_id"], "https://www.transfermarkt.com/-/profil/spieler/{:.0f}"),
        })

        # The key version bumps on every dialog exit, which clears the selection so
        # the dialog does not reopen on the next rerun.
        version = st.session_state.get("watchlist_table_ver", 0)
        selection = st.dataframe(
            frame, hide_index=True, width="stretch",
            on_select="rerun", selection_mode="single-row",
            key=f"watchlist_table_{version}",
            column_config={
                "Age": st.column_config.TextColumn("Age"),
                "Composite": st.column_config.ProgressColumn(
                    "Composite", help="The club's objective composite (1-5) — Performance + "
                                     "Physical, the same number the Players ranking uses.",
                    min_value=1, max_value=5, format="%.2f"),
                "Performance": st.column_config.ProgressColumn(
                    "Performance", help="Performance dimension (1-5).", min_value=1, max_value=5, format="%.2f"),
                "Physical": st.column_config.ProgressColumn(
                    "Physical", help="Physical dimension (1-5), where tracking data exists.",
                    min_value=1, max_value=5, format="%.2f"),
                form_header: st.column_config.TextColumn(
                    form_header, help="Minutes and output in the current live season — plain "
                                      "facts, not a rating (too little of the season has "
                                      "been played for a composite)."),
                "Injury": st.column_config.TextColumn(
                    "Injury", help="Most recent recorded spell (Transfermarkt). 'No injury "
                                   "spells on record' means none is on file — not a fitness "
                                   "guarantee, since coverage is incomplete outside the EFL."),
                "Market value": st.column_config.TextColumn(
                    "Market value", help="Transfermarkt. '—' = no known valuation."),
                "Months left": st.column_config.TextColumn(
                    "Months left", help="Months from today until the contract expires. Under "
                                        "6 = he can sign a pre-contract elsewhere. '—' = no "
                                        "known contract date."),
                "Assessed": st.column_config.TextColumn(
                    "Assessed", help="Whether a scout has completed the Psychological and "
                                     "Medical assessment (click the row to open the "
                                     "assessment form). Separate from the manual 'Status'."),
                "Note": st.column_config.TextColumn(
                    "Note", help="Preview — click the row to read or edit the full note."),
                "Transfermarkt": st.column_config.LinkColumn(
                    "Transfermarkt", display_text="Open profile ↗",
                    help="The player's Transfermarkt page, where scouts verify the basics."),
            },
        )

        # Open the dialog only when the selection CHANGES, never merely because a
        # selection exists: every tab re-runs on every interaction anywhere in the
        # app, and a persisted selection would otherwise re-open the dialog on each
        # click in the shortlist, compare or types tabs.
        rows = list(selection.selection.rows) if selection and selection.selection else []
        if rows and rows[0] < len(df):
            picked = df.iloc[rows[0]]
            triple = (int(picked["player_id"]), int(picked["competition_id"]),
                      int(picked["season_id"]), version)
            if st.session_state.get("wl_dialog_handled") != triple:
                st.session_state["wl_dialog_handled"] = triple
                position_group = (str(picked["position_group"])
                                  if pd.notna(picked["position_group"]) else None)
                _watchlist_entry_dialog(
                    triple[0], triple[1], triple[2],
                    str(picked["player_name"]), str(picked["team_name"] or ""),
                    str(picked["note"] or ""), str(picked["status"]), position_group)
        else:
            # No selection: clear the marker so re-selecting the same row reopens.
            st.session_state["wl_dialog_handled"] = None

        st.caption("The watchlist is saved in the club database: it survives data refreshes and "
                   "restarts, and ignores the sidebar filters on purpose. A blank Composite or "
                   "value means that player sits outside the current data (not yet scored, or "
                   "not priced in his league).")
        st.download_button(
            "⬇ Download watchlist (CSV)",
            data=frame.to_csv(index=False).encode("utf-8"),
            file_name="lofc_watchlist.csv", mime="text/csv",
            help="The tracking list with statuses and full notes, for Excel or Sheets.")
