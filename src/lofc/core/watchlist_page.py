"""Watchlist page logic, shared by the Streamlit page (`dashboard/tabs/watchlist.py::_watchlist`,
which now calls these) and the web page (`web/api/watchlist.py`).

What `_watchlist` used to do inline: attach the assessment status, this season's form, the
contract countdown, the latest injury spell and the club's 1-5 scorecard to the watched rows
(`enrich`); the assessment-status filter; the four counts; the table as shown
(`display_frame`, also the CSV). The per-column helpers stay in the Streamlit module and are
called unchanged. Loaders are passed in, so each surface keeps its own caches.

Web only (owner decision D1, 2026-11-09): `thin_sizes` + `apply_pool_floor` blank a rating whose
league-position pool is below MIN_PEERS_FOR_RANKING. Nothing here touches a score.
"""
from __future__ import annotations

import pandas as pd

EMPTY = ("No players on the watchlist yet. Open any player's profile and click "
         "“☆ Add to watchlist” — tracked players, statuses and scout notes live here.")
NONE_MATCH = "No watched players match the chosen assessment status."
STATUS_HELP = "Which of your targets still need a scout?"
# (label, alerts key, help)
TILES = [
    ("On the list", "total", None),
    ("Contract ≤ 6 months", "expiring_soon",
     "Known contract dates only — free to sign a pre-contract deal elsewhere."),
    ("Currently injured", "currently_injured",
     "On record as out injured right now, per the Transfermarkt scrape."),
    ("Not yet assessed", "not_assessed",
     "No Psychological or Medical assessment recorded for this player yet."),
]
RATING_COLUMNS = ["objective_composite", "performance_band", "physical_band"]
SC_COLUMNS = ["player_id", "competition_id", "season_id", "objective_composite",
              "performance_band", "physical_band"]
TM_URL = "https://www.transfermarkt.com/-/profil/spieler/{:.0f}"


def _wl():
    from lofc.dashboard.tabs import watchlist as wl
    return wl


def enrich(df: pd.DataFrame, *, assessment: pd.DataFrame, live_season_id, current_form,
           injuries_for, scorecards_for, now: pd.Timestamp | None = None
           ) -> tuple[pd.DataFrame, str]:
    """(watched rows + every derived column, the "This season" column header).

    `current_form()` -> the live season's rows; `injuries_for(ids)` -> raw injury spells;
    `scorecards_for(season_id)` -> that season's scorecards. `now` None = today (Streamlit)."""
    from lofc.dashboard.seasons import season_name_for
    from lofc.model import assessment_status
    wl = _wl()
    # Derived, never stored: joins on the same (player, competition, season) triple the
    # profile's scout section reads, so a watchlist row and a profile row can't disagree.
    df = assessment_status.attach(df, assessment)

    # Current-season form: matched on player_id alone -- "is he playing right now" is about
    # the live season whichever season the row was scored in.
    if live_season_id is None:
        df["current_form"] = "—"
        form_header = "This season"
    else:
        live_rows = current_form()
        df["current_form"] = df["player_id"].map(
            lambda pid: wl._current_form_text(live_rows, int(pid)))
        form_header = f"This season ({season_name_for(live_season_id)})"

    # Contract countdown, stored on `df` so it travels with its row through the status filter.
    df["contract_until_dt"] = pd.to_datetime(df["contract_until"], errors="coerce")
    today = None if now is None else pd.Timestamp(now).date()
    df["months_left"] = wl.months_left_column(df["contract_until_dt"], today)

    # Injury record, bulk-loaded for exactly the players on this list.
    player_ids = tuple(sorted(df["player_id"].astype(int).unique().tolist()))
    as_of = (pd.Timestamp.now() if now is None else pd.Timestamp(now)).normalize()
    injuries = wl._summarize_injuries(injuries_for(player_ids), as_of)
    df = df.merge(injuries, on="player_id", how="left")
    df["injury_status"] = df["injury_status"].fillna("No injury spells on record")

    # The club's 1-5 composite, from every season present on the list.
    season_ids = sorted(int(s) for s in df["season_id"].dropna().unique().tolist())
    scorecards = (pd.concat([scorecards_for(sid)[SC_COLUMNS] for sid in season_ids],
                            ignore_index=True) if season_ids else pd.DataFrame(columns=SC_COLUMNS))
    df = df.merge(scorecards, on=["player_id", "competition_id", "season_id"], how="left")
    return df, form_header


def filter_status(df: pd.DataFrame, chosen) -> pd.DataFrame:
    return df[df["assessment_status"].isin(list(chosen))].reset_index(drop=True)


def alerts(df: pd.DataFrame) -> dict[str, int]:
    return _wl()._watchlist_alerts(df["months_left"], df["injury_status"],
                                   df["assessment_status"])


def display_frame(df: pd.DataFrame, form_header: str, show_money: bool, name_by_id: dict,
                  valuations=None) -> pd.DataFrame:
    """The table as shown, "—" for blanks (also the CSV). Market value only when `show_money`
    (`valuations(ids)` -> every valuation row; default the Streamlit loader)."""
    from lofc.dashboard.formatting import dash_blanks, link_or_blank, numeric_or_dash
    wl = _wl()
    frame = pd.DataFrame({
        "Player": df["player_name"], "Club": df["team_name"],
        "League": df["competition_id"].map(name_by_id).fillna(df["competition_name"]),
        "Position": df["position_group"],
        "Age": numeric_or_dash(df["age"], "{:.1f}"),
        "Composite": df["objective_composite"],
        "Performance": df["performance_band"],
        "Physical": df["physical_band"],
        form_header: df["current_form"],
        "Injury": df["injury_status"],
        "Contract": df["contract_until_dt"].dt.strftime("%m/%Y").fillna("—"),
        "Months left": numeric_or_dash(df["months_left"], "{:.0f}"),
        "Status": df["status"],
        "Assessed": df["assessment_status"].map(wl._badge_text),
        "Note": df["note"].fillna(""),
        "Added": pd.to_datetime(df["created_at"]).dt.strftime("%d %b %Y"),
        "Transfermarkt": link_or_blank(df["tm_player_id"], TM_URL),
    })
    market_value = wl.market_value_text(df, show_money, loader=valuations)
    if market_value is not None:
        frame.insert(frame.columns.get_loc("Contract"), "Market value", market_value)
    # Any remaining missing text cell (Position, Status, Injury...) would draw "None".
    return dash_blanks(frame)


def thin_sizes(df: pd.DataFrame, scorecards_for) -> pd.Series:
    """Per watched row: his league-position pool size when it is below MIN_PEERS_FOR_RANKING
    and he has a composite; NaN otherwise. Counted over the season's full scorecard set
    (`scorecard.peer_pool_sizes`), keyed by the scorecard's own position."""
    from lofc.model.scorecard import peer_pool_sizes, pool_is_thin
    out = pd.Series(float("nan"), index=df.index, dtype="float64")
    for sid in sorted(int(s) for s in df["season_id"].dropna().unique().tolist()):
        sc = scorecards_for(sid)
        sizes = peer_pool_sizes(sc)
        pos = {(int(p), int(c)): g for p, c, g in zip(sc["player_id"], sc["competition_id"],
                                                        sc["position_group"])}
        for i in df.index[df["season_id"] == sid]:
            if pd.isna(df.at[i, "objective_composite"]):
                continue
            group = pos.get((int(df.at[i, "player_id"]), int(df.at[i, "competition_id"])))
            n = sizes.get((int(df.at[i, "competition_id"]), sid, group)) if group else None
            if n is not None and pool_is_thin(n):
                out.at[i] = float(n)
    return out


def apply_pool_floor(df: pd.DataFrame, thin: pd.Series) -> pd.DataFrame:
    """A copy with the three ratings blanked where `thin` holds a pool size."""
    out = df.copy()
    mask = thin.reindex(out.index).notna()
    for c in RATING_COLUMNS:
        out[c] = pd.to_numeric(out[c], errors="coerce").mask(mask)
    return out
