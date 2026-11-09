"""`lofc.core.watchlist_page`: the Watchlist page logic shared by Streamlit and the web page (no
database). Real-database parity: test_web_scout_watchlist_parity.py."""
import pandas as pd
import pytest

from lofc.core import watchlist_page as wp
from lofc.model import assessment_status as AS

NOW = pd.Timestamp("2026-11-09")


def _watch():
    return pd.DataFrame({
        "player_id": [1, 2], "competition_id": [5, 901], "season_id": [318, 319],
        "note": ["Watch his first touch", None], "status": ["Watching", "Scout sent"],
        "created_at": pd.to_datetime(["2026-09-14 11:05", "2026-10-12 15:14"]),
        "player_name": ["Al One", "Bo Two"], "contract_until": ["2027-03-01", None],
        "tm_player_id": [123.0, None], "team_name": ["Gills", "Celtic"],
        "position_group": ["Winger", "Attacking Mid"], "competition_name": [None, None],
        "performance_score": [None, None], "fit_score": [None, None],
        "market_value_eur": [None, None], "age": [24.04, None]})


def _scorecards(sid):
    return pd.DataFrame({
        "player_id": [1, 7, 2] if sid == 318 else [2, 8],
        "competition_id": [5, 5, 5] if sid == 318 else [901, 901],
        "season_id": [sid] * (3 if sid == 318 else 2),
        "position_group": ["Winger", "Winger", "Winger"] if sid == 318 else ["Attacking Mid"] * 2,
        "objective_composite": [3.41, 3.0, 2.0] if sid == 318 else [4.49, 3.1],
        "performance_band": [3.2, 3.0, 2.0] if sid == 318 else [4.6, 3.0],
        "physical_band": [3.7, 3.0, 2.0] if sid == 318 else [4.2, 3.0]})


def _enrich(df=None, live=319):
    live_rows = pd.DataFrame({"player_id": [1], "competition_id": [5], "season_id": [319],
                              "minutes": [455.5], "goals_p90": [0.4], "assists_p90": [0.2]})
    inj = pd.DataFrame({"player_id": [2], "date_from": ["2026-10-01"], "date_until": [None],
                        "injury_category": ["Hamstring"], "injury_type_raw": [None],
                        "days_out": [None], "games_missed": [None]})
    return wp.enrich(_watch() if df is None else df, assessment=pd.DataFrame(
        columns=["player_id", "competition_id", "season_id", "assessment_status"]),
        live_season_id=live, current_form=lambda: live_rows,
        injuries_for=lambda ids: inj, scorecards_for=_scorecards, now=NOW)


def test_enrich_adds_every_derived_column():
    df, header = _enrich()
    assert header == "This season (2026/27)"
    assert list(df["assessment_status"]) == [AS.NOT_ASSESSED] * 2
    assert df.loc[0, "current_form"].startswith("456 min") or df.loc[0, "current_form"].startswith("455 min")
    assert df.loc[1, "current_form"] == "Not featured yet"
    assert df.loc[1, "injury_status"].startswith("🔴 Currently out — Hamstring")
    assert df.loc[0, "injury_status"] == "No injury spells on record"
    assert df.loc[0, "objective_composite"] == 3.41 and df.loc[1, "objective_composite"] == 4.49
    assert df.loc[0, "months_left"] == 4


def test_enrich_without_a_live_season():
    df, header = _enrich(live=None)
    assert header == "This season" and set(df["current_form"]) == {"—"}


def test_filter_status_and_alerts():
    df, _ = _enrich()
    assert len(wp.filter_status(df, [AS.SIGNED_OFF])) == 0
    kept = wp.filter_status(df, list(AS.STATUSES))
    assert wp.alerts(kept) == {"total": 2, "expiring_soon": 1, "currently_injured": 1,
                               "not_assessed": 2}


def test_display_frame_columns_and_blanks():
    df, header = _enrich()
    names = {5: "League Two", 901: "Scottish Premiership"}
    frame = wp.display_frame(df, header, False, names)
    assert list(frame.columns) == [
        "Player", "Club", "League", "Position", "Age", "Composite", "Performance", "Physical",
        header, "Injury", "Contract", "Months left", "Status", "Assessed", "Note", "Added",
        "Transfermarkt"]
    assert frame.loc[0, "Age"] == "24.0" and frame.loc[1, "Age"] == "—"
    assert frame.loc[1, "Contract"] == "—" and frame.loc[1, "Months left"] == "—"
    assert frame.loc[0, "Transfermarkt"] == "https://www.transfermarkt.com/-/profil/spieler/123"
    assert frame.loc[1, "Note"] == ""


def test_display_frame_money_inserts_market_value_before_contract():
    df, header = _enrich()
    vals = pd.DataFrame({"player_id": [1], "season_id": [317], "market_value_eur": [1.5e6]})
    frame = wp.display_frame(df, header, True, {}, valuations=lambda ids: vals)
    cols = list(frame.columns)
    assert cols.index("Market value") == cols.index("Contract") - 1
    assert list(frame["Market value"]) == ["€1.5m", "—"]


def test_thin_sizes_and_pool_floor_blank_a_thin_rating():
    df, _ = _enrich()
    thin = wp.thin_sizes(df, _scorecards)
    # 318 Winger pool of 3, 319 Attacking Mid pool of 2: both thin
    assert list(thin) == [3.0, 2.0]
    out = wp.apply_pool_floor(df, thin)
    assert out[["objective_composite", "performance_band", "physical_band"]].isna().all().all()
    assert df.loc[0, "objective_composite"] == 3.41          # the input is not changed


def test_thin_sizes_nan_for_a_full_pool_and_no_scorecard():
    df, _ = _enrich()
    big = lambda sid: pd.concat([_scorecards(sid)] + [_scorecards(sid).assign(player_id=100 + i)
                                                       for i in range(10)])
    assert wp.thin_sizes(df, big).isna().all()
    df.loc[0, "objective_composite"] = float("nan")
    assert pd.isna(wp.thin_sizes(df, _scorecards).iloc[0])


def test_texts_are_streamlits():
    assert wp.EMPTY.startswith("No players on the watchlist yet.")
    assert wp.NONE_MATCH == "No watched players match the chosen assessment status."
    assert [t[0] for t in wp.TILES] == ["On the list", "Contract ≤ 6 months",
                                        "Currently injured", "Not yet assessed"]
