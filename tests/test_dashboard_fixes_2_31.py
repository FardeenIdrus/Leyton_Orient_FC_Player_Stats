"""Watchlist/Squads fixes (TASKS 2.28c, 2.31a-c): market value fallback, one months-left
rule, the Squads wording, and the empty "On loan only" view."""

import datetime as dt
import inspect

import pandas as pd

from lofc.dashboard.seasons import calendar_months_left
from lofc.dashboard.tabs import squads, watchlist
from lofc.dashboard.tabs.squads import DISPLAY_COLUMNS, prepare, squad_display

TODAY = dt.date(2026, 11, 6)


# --- 2.31a: market value from the latest known valuation -------------------------------

def test_market_value_falls_back_to_the_latest_known_season():
    wl = pd.DataFrame({"player_id": [1, 2, 3], "season_id": [319] * 3,
                       "market_value_eur": [float("nan")] * 3})
    vals = pd.DataFrame({"player_id": [1, 1, 2], "season_id": [317, 318, 318],
                         "market_value_eur": [500_000.0, 800_000.0, 1_200_000.0]})
    out = watchlist.with_latest_market_value(wl, vals)
    assert out["market_value_eur"].tolist()[:2] == [800_000.0, 1_200_000.0]
    assert pd.isna(out["market_value_eur"].iloc[2])      # no valuation: stays blank, not 0


def test_an_exact_season_valuation_is_kept():
    wl = pd.DataFrame({"player_id": [1], "market_value_eur": [900_000.0]})
    vals = pd.DataFrame({"player_id": [1], "season_id": [318], "market_value_eur": [1.0]})
    assert watchlist.with_latest_market_value(wl, vals)["market_value_eur"].iloc[0] == 900_000.0


def test_no_valuations_at_all_is_safe():
    wl = pd.DataFrame({"player_id": [1], "market_value_eur": [float("nan")]})
    empty = pd.DataFrame(columns=["player_id", "season_id", "market_value_eur"])
    assert pd.isna(watchlist.with_latest_market_value(wl, empty)["market_value_eur"].iloc[0])


# --- 2.31b: one calendar-month rule ----------------------------------------------------

def test_calendar_months_left_matches_squads_example():
    # Nils Ramming, contract 31 May 2027: 6 calendar months (days/30.44 gave 7).
    assert calendar_months_left(dt.date(2027, 5, 31), TODAY) == 6


def test_squads_and_watchlist_give_the_same_months_for_the_same_dates():
    dates = ["2027-05-31", "2026-11-30", "2026-05-31", "2028-01-01"]
    wl = watchlist.months_left_column(pd.Series(dates), TODAY).tolist()
    sq = [squads.months_left(d, TODAY) for d in dates]
    assert wl == sq == [calendar_months_left(d, TODAY) for d in dates] == [6, 0, -6, 14]


def test_default_today_path_uses_the_current_date(monkeypatch):
    class Frozen(dt.date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 6)
    monkeypatch.setattr("lofc.dashboard.seasons.datetime.date", Frozen)
    assert calendar_months_left(dt.date(2027, 5, 31)) == 6
    assert squads.months_left(dt.date(2027, 5, 31)) == 6


def test_watchlist_months_column_is_calendar_months():
    out = watchlist.months_left_column(pd.Series(["2027-05-31", None, "2026-05-31"]), TODAY)
    assert out.iloc[0] == 6 and pd.isna(out.iloc[1]) and out.iloc[2] == -6


# --- 2.31c: wording --------------------------------------------------------------------

def test_squads_wording_names_the_transfermarkt_leagues_not_our_seven():
    texts = [squads.MINUTES_HELP, squads.FOOTER_CAPTION,
             squads.no_record_message("A B", "Club"), squads.no_rating_message("A B")]
    for text in texts:
        assert "7 leagues with Transfermarkt squad data" in text
        assert "seven" not in text
    assert squads.MINUTES_HELP == "This season, in the 7 leagues with Transfermarkt squad data."
    assert squads.FOOTER_CAPTION.endswith(
        "loaned out beyond the 7 leagues with Transfermarkt squad data will not appear.")
    assert "**A B** is in Club's squad" in squads.no_record_message("A B", "Club")


# --- 2.28c: "On loan only" with no loans -----------------------------------------------

def test_empty_loans_gives_the_normal_empty_view_with_zero_tiles():
    empty_loans = pd.DataFrame(columns=["competition_id", "team_name", "player_id",
                                        "tm_player_id", "player_name", "parent_club",
                                        "loan_ends"])
    view = squads.ensure_display_columns(prepare(empty_loans))
    assert squads.summary_counts(view) == {"players": 0, "on_loan": 0, "contract_known": 0,
                                           "expiring": 0}
    assert squad_display(view[DISPLAY_COLUMNS].reset_index(drop=True)).empty


# --- Market value follows "Show affordability (modelled)" ------------------------------

def _wl():
    return pd.DataFrame({"player_id": [1, 2], "market_value_eur": [float("nan")] * 2})


def test_market_value_column_absent_and_no_query_when_switch_off():
    calls = []
    def loader(ids):
        calls.append(ids)
        return pd.DataFrame(columns=["player_id", "season_id", "market_value_eur"])
    assert watchlist.market_value_text(_wl(), False, loader) is None
    assert calls == []


def test_market_value_column_present_when_switch_on():
    def loader(ids):
        return pd.DataFrame({"player_id": [1], "season_id": [318],
                             "market_value_eur": [1_500_000.0]})
    out = watchlist.market_value_text(_wl(), True, loader)
    assert out.tolist() == ["€1.5m", "—"]


def test_watchlist_page_takes_show_money_and_valuation_lookup_is_versioned():
    assert "show_money" in inspect.signature(watchlist._watchlist).parameters
    assert getattr(watchlist.load_valuations_for_players, "_is_versioned", False)
