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


def pool_notes(df: pd.DataFrame, scorecards_for, names: dict) -> pd.DataFrame:
    """Per watched row with a composite: `not_rated` -- the card's line when his pool is below
    MIN_PEERS_FOR_RANKING ("Not rated: only N <Position>s in <League> with 450+ minutes (needs
    10).") -- and `pool_tag` -- "Rated against all midfielders" when he was rated in the
    midfield fallback pool; None otherwise. Pools as `thin_sizes` (the pool he was rated in)."""
    from lofc.core.card import not_rated_line, pool_tag
    from lofc.model.scorecard import peer_pool_scopes, peer_pool_sizes, pool_is_thin
    out = pd.DataFrame({"not_rated": [None] * len(df), "pool_tag": [None] * len(df)},
                       index=df.index, dtype=object)
    for sid in sorted(int(s) for s in df["season_id"].dropna().unique().tolist()):
        sc = scorecards_for(sid)
        sizes, scopes = peer_pool_sizes(sc), peer_pool_scopes(sc)
        pos = {(int(p), int(c)): g for p, c, g in zip(sc["player_id"], sc["competition_id"],
                                                        sc["position_group"])}
        for i in df.index[df["season_id"] == sid]:
            if pd.isna(df.at[i, "objective_composite"]):
                continue
            comp = int(df.at[i, "competition_id"])
            group = pos.get((int(df.at[i, "player_id"]), comp))
            if group is None:
                continue
            n = sizes.get((comp, sid, group))
            if n is not None and pool_is_thin(n):
                out.at[i, "not_rated"] = not_rated_line(int(n), group,
                                                        names.get(comp, f"League {comp}"))
            else:
                out.at[i, "pool_tag"] = pool_tag(scopes.get((comp, sid, group)))
    return out


def apply_pool_floor(df: pd.DataFrame, thin: pd.Series) -> pd.DataFrame:
    """A copy with the three ratings blanked where `thin` holds a pool size."""
    out = df.copy()
    mask = thin.reindex(out.index).notna()
    for c in RATING_COLUMNS:
        out[c] = pd.to_numeric(out[c], errors="coerce").mask(mask)
    return out


# ================= Watchlist redesign (owner 2026-11-23) =========================================
# One shared list, one entry per player; grouped by position with our best (League One) shown
# for reference only -- a watched player's Overall is rated in his own league, never compared
# with ours. Pure functions over plain frames: the web API passes the data in.
SUGGEST_VERDICTS = ("Sign", "Monitor Priority")
CHANGES_MAX = 12
EMPTY_REDESIGN = "No players on the watchlist yet. Add one from his player page, or from the suggestions above."
SUGGEST_DAYS = 30
NEW_REPORT_DAYS = 14
RATING_STEP = 0.10                      # a rating move smaller than this is not a change
EXPIRING_MONTHS = 6
GROUP_ORDER = ["Goalkeeper", "Centre Back", "Full Back", "Midfield", "Winger", "Centre Forward", "Other"]
GROUP_LABEL = {"Midfield": "Midfielders", "Other": "Other"}
CLOSED = ("Signed", "Dropped")


def _report_date(r) -> pd.Timestamp:
    d = pd.to_datetime(r.get("fixture_date"), errors="coerce")
    return d if pd.notna(d) else pd.to_datetime(r.get("submitted_at"), errors="coerce")


def _short_date(d) -> str:
    return "" if d is None or pd.isna(d) else pd.Timestamp(d).strftime("%-d %b")


def latest_reports(reports: pd.DataFrame) -> pd.DataFrame:
    """Each matched player's latest live scout report (by match date, then when submitted),
    indexed by player_id. Reports gone from the sheet (`missing_since`) are left out."""
    if reports is None or reports.empty:
        return pd.DataFrame(columns=["id", "verdict", "scout", "date"]).rename_axis("player_id")
    f = reports[reports["player_id"].notna() & reports["missing_since"].isna()].copy()
    f["date"] = [_report_date(r) for r in f.to_dict("records")]
    f["_sub"] = pd.to_datetime(f["submitted_at"], errors="coerce")
    f = f.sort_values(["date", "_sub", "id"], kind="stable")
    f["player_id"] = f["player_id"].astype("int64")
    return f.groupby("player_id").tail(1).set_index("player_id").drop(columns="_sub")


def suggestions(latest: pd.DataFrame, watched: set, dismissed: set, now, days: int | None = SUGGEST_DAYS) -> list[dict]:
    """"Suggested from scout reports": players whose LATEST report is Sign or Monitor Priority,
    not on the list, report not dismissed; within `days` of `now` (None = all). Newest first."""
    now = pd.Timestamp(now)
    out = []
    for pid, r in latest.iterrows():
        if r["verdict"] not in SUGGEST_VERDICTS or int(pid) in watched or int(r["id"]) in dismissed:
            continue
        if days is not None and (pd.isna(r["date"]) or r["date"] < now - pd.Timedelta(days=days)):
            continue
        out.append({"report_id": int(r["id"]), "player_id": int(pid), "verdict": r["verdict"],
                    "date": r["date"], "report": f"{r['scout']} · {_short_date(r['date'])}",
                    "name": r.get("player_name"), "club": r.get("club_name")})
    out.sort(key=lambda x: (x["date"] if pd.notna(x["date"]) else pd.Timestamp.min), reverse=True)
    return out


def changes(rows: pd.DataFrame, now_rows: dict, latest: pd.DataFrame, reports: pd.DataFrame, now) -> list[dict]:
    """"What changed since added", per watched player (`rows`: player_id, player_name,
    created_at, added_rating, added_club, months_left, injury_status; `now_rows`: player_id ->
    {"rating", "club"} today). Kinds, in this order per player: a scout report after he was
    added (the latest), rating moved by RATING_STEP or more (vs when added), club moved,
    injured now, contract under EXPIRING_MONTHS. Unknown snapshots are skipped, never guessed."""
    out = []
    for r in rows.to_dict("records"):
        pid, name = int(r["player_id"]), r.get("player_name")
        added = pd.to_datetime(r.get("created_at"), errors="coerce")
        cur = now_rows.get(pid) or {}
        if pid in latest.index:
            rep = latest.loc[pid]
            if pd.notna(added) and pd.notna(rep["date"]) and rep["date"] >= added.normalize():
                out.append({"player_id": pid, "name": name, "kind": "report", "date": rep["date"],
                            "verdict": rep["verdict"],
                            "text": f"new scout report: {rep['verdict']} ({rep['scout']}, {_short_date(rep['date'])})"})
        a, b = r.get("added_rating"), cur.get("rating")
        if a is not None and b is not None and not pd.isna(a) and not pd.isna(b) \
                and abs(float(b) - float(a)) >= RATING_STEP - 1e-9:
            out.append({"player_id": pid, "name": name, "kind": "rating", "dir": "up" if b > a else "dn",
                        "text": f"rating {float(a):.2f} → {float(b):.2f}"})
        a, b = r.get("added_club"), cur.get("club")
        if isinstance(a, str) and isinstance(b, str) and a and b and a != b:
            out.append({"player_id": pid, "name": name, "kind": "club", "text": f"moved: {a} → {b}"})
        inj = r.get("injury_status")
        if isinstance(inj, str) and inj.lower().startswith("currently injured"):
            out.append({"player_id": pid, "name": name, "kind": "injury", "text": inj})
        m = r.get("months_left")
        if m is not None and not pd.isna(m) and 0 <= float(m) < EXPIRING_MONTHS:
            out.append({"player_id": pid, "name": name, "kind": "contract",
                        "text": f"contract ends in {int(m)} month{'s' if int(m) != 1 else ''}"})
    return out


def group_of(position) -> str:
    from lofc.core.club_vs_league import group_of as g
    return g(position) if isinstance(position, str) and position else "Other"


def group_rows(rows: list[dict], our_best: dict) -> tuple[list[dict], list[dict]]:
    """(groups, closed): active players by position group (GROUP_ORDER), each group with our
    best player there (League One) for reference only; Signed / Dropped apart."""
    closed = [r for r in rows if r.get("stage") in CLOSED]
    active = [r for r in rows if r.get("stage") not in CLOSED]
    groups = []
    for g in GROUP_ORDER:
        mine = [r for r in active if group_of(r.get("position")) == g]
        if not mine:
            continue
        best = our_best.get(g)
        groups.append({"group": g, "label": GROUP_LABEL.get(g, g + "s"), "rows": mine,
                       "our_best": None if not best else {"name": best["name"], "rating": best["rating"],
                                                          "league": "L1"}})
    return groups, closed


def tiles(rows: list[dict]) -> list[dict]:
    """On the list (active) · Shortlisted · In form (3+ Top in his last 5 games; owner 2026-11-23,
    phase 4 -- it replaced "Contract ≤ 6 months") · New scout report (14 days)."""
    active = [r for r in rows if r.get("stage") not in CLOSED]
    return [
        {"key": "active", "label": "On the list", "value": len(active)},
        {"key": "Shortlisted", "label": "Shortlisted", "value": sum(r.get("stage") == "Shortlisted" for r in active)},
        {"key": "inform", "label": "In form (3+ Top in last 5)", "value": sum(bool(r.get("in_form")) for r in active)},
        {"key": "newrep", "label": "New scout report (14 days)", "value": sum(bool(r.get("new_report")) for r in active)},
    ]
