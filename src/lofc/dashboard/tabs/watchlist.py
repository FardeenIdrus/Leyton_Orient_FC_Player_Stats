"""The Watchlist tab: the recruiter's own tracked players, statuses and notes.

This is the one table in the platform that holds USER data rather than pipeline output, so
it is never rebuilt or swept by a pipeline run."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from lofc.dashboard.loaders import _competition_name_by_id, get_engine
from lofc.store import watchlist


@st.dialog("Watchlist entry")
def _watchlist_entry_dialog(pid: int, cid: int, sid: int, player_name: str,
                            club: str, note: str, status: str) -> None:
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

        st.markdown("**Players the club is tracking.** Click a row to read the full note, "
                    "edit it, change the status, or remove the player.")
        name_by_id = _competition_name_by_id()   # all leagues incl. Scottish/PL2 (901/902/903)
        frame = pd.DataFrame({
            "Player": df["player_name"], "Club": df["team_name"],
            "League": df["competition_id"].map(name_by_id).fillna(df["competition_name"]),
            "Position": df["position_group"],
            "Age": df["age"].round(1),
            "Quality": df["performance_score"],
            "Market value": (df["market_value_eur"] / 1e6).round(1),
            "Contract": pd.to_datetime(df["contract_until"], errors="coerce")
                        .dt.strftime("%m/%Y").fillna("—"),
            "Status": df["status"], "Note": df["note"].fillna(""),
            "Added": pd.to_datetime(df["created_at"]).dt.strftime("%d %b %Y"),
            "Transfermarkt": df["tm_player_id"].map(
                lambda t: f"https://www.transfermarkt.com/-/profil/spieler/{int(t)}"
                if pd.notna(t) else None),
        })

        # The key version bumps on every dialog exit, which clears the selection so
        # the dialog does not reopen on the next rerun.
        version = st.session_state.get("watchlist_table_ver", 0)
        selection = st.dataframe(
            frame, hide_index=True, width="stretch",
            on_select="rerun", selection_mode="single-row",
            key=f"watchlist_table_{version}",
            column_config={
                "Age": st.column_config.NumberColumn("Age", format="%.1f"),
                "Quality": st.column_config.ProgressColumn("Quality", min_value=0, max_value=100, format="%d"),
                "Style fit": st.column_config.ProgressColumn("Style fit", min_value=0, max_value=100, format="%d"),
                "Market value": st.column_config.NumberColumn("Market value", format="€%.1fm"),
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
                _watchlist_entry_dialog(
                    triple[0], triple[1], triple[2],
                    str(picked["player_name"]), str(picked["team_name"] or ""),
                    str(picked["note"] or ""), str(picked["status"]))
        else:
            # No selection: clear the marker so re-selecting the same row reopens.
            st.session_state["wl_dialog_handled"] = None

        st.caption("The watchlist is saved in the club database: it survives data refreshes and "
                   "restarts, and ignores the sidebar filters on purpose. A blank Quality or value "
                   "means that player sits outside the current data (e.g. not priced in his league).")
        st.download_button(
            "⬇ Download watchlist (CSV)",
            data=frame.to_csv(index=False).encode("utf-8"),
            file_name="lofc_watchlist.csv", mime="text/csv",
            help="The tracking list with statuses and full notes, for Excel or Sheets.")
