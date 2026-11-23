"""Watchlist persistence tests against sqlite in-memory. No Postgres needed."""

import pandas as pd
import pytest
from sqlalchemy import create_engine

from lofc.store import watchlist
from lofc.store.models import Base, PlayerMetricNeutral, PlayerScore, PlayerSeasonMetric, Valuation


def _full_row(table, partial: dict) -> dict:
    """Fill every other NOT NULL column with 0 so the fixture survives the schema."""
    row = dict(partial)
    for column in table.columns:
        if column.name not in row and not column.nullable and column.name != "id":
            row[column.name] = 0
    return row


@pytest.fixture
def engine():
    """A fresh schema with one seeded player and his season facts."""
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    pd.DataFrame([{"player_id": 1, "player_name": "Test Striker",
                   "contract_until": "2026-06-30"}]).to_sql(
        "players", eng, index=False, if_exists="append")
    pd.DataFrame([_full_row(PlayerSeasonMetric.__table__, {
        "player_id": 1, "competition_id": 4, "season_id": 318,
        "competition_name": "League One", "season_name": "2025/2026",
        "player_name": "Test Striker", "team_name": "Testville",
        "position_group": "Centre Forward", "minutes": 2000.0,
        "matches_played": 30, "rankable": True})]).to_sql(
        "player_season_metrics", eng, index=False, if_exists="append")
    pd.DataFrame([_full_row(PlayerScore.__table__, {
        "player_id": 1, "competition_id": 4, "season_id": 318,
        "position_group": "Centre Forward",
        "performance_score": 80.0, "fit_score": 75.0})]).to_sql(
        "player_scores", eng, index=False, if_exists="append")
    return eng


def test_add_is_idempotent(engine):
    assert watchlist.add(engine, 1, 4, 318) is True
    assert watchlist.add(engine, 1, 4, 318) is False
    loaded = watchlist.load(engine)
    assert len(loaded) == 1
    assert loaded.iloc[0]["status"] == "Watching"


def test_remove(engine):
    watchlist.add(engine, 1, 4, 318)
    assert watchlist.remove(engine, 1, 4, 318) is True
    assert watchlist.load(engine).empty
    assert watchlist.remove(engine, 1, 4, 318) is False


def test_is_watched(engine):
    assert watchlist.is_watched(engine, 1, 4, 318) is False
    watchlist.add(engine, 1, 4, 318)
    assert watchlist.is_watched(engine, 1, 4, 318) is True


def test_note_and_status_round_trip(engine):
    watchlist.add(engine, 1, 4, 318)
    watchlist.set_note(engine, 1, 4, 318, "send a scout to the next home game")
    watchlist.set_status(engine, 1, 4, 318, "Scout to watch")
    row = watchlist.load(engine).iloc[0]
    assert row["note"] == "send a scout to the next home game"
    assert row["status"] == "Scout to watch"


def test_set_status_rejects_unknown(engine):
    watchlist.add(engine, 1, 4, 318)
    with pytest.raises(ValueError):
        watchlist.set_status(engine, 1, 4, 318, "Signed!!")


def test_load_joins_and_survives_missing_valuation(engine):
    # No valuations row was seeded: the watched player must still appear (left
    # join), with his name and scores attached and a blank market value.
    watchlist.add(engine, 1, 4, 318)
    row = watchlist.load(engine).iloc[0]
    assert row["player_name"] == "Test Striker"
    assert row["team_name"] == "Testville"
    assert row["performance_score"] == 80.0
    assert pd.isna(row["market_value_eur"])


def test_load_shows_club_position_for_non_efl_player(engine):
    # Bug: player_season_metrics only ever holds the four English leagues. A Scottish
    # Prem/Champ or PL2 player has no row there, so joining on it alone left the watchlist's
    # Club/Position blank for exactly those players even though their profile shows both
    # fine (the profile reads the combined 7-league player_metrics_neutral table).
    pd.DataFrame([{"player_id": 2, "player_name": "Test Winger",
                   "birth_date": "2000-01-01"}]).to_sql(
        "players", engine, index=False, if_exists="append")
    pd.DataFrame([_full_row(PlayerMetricNeutral.__table__, {
        "player_id": 2, "competition_id": 901, "season_id": 318,
        "player_name": "Test Winger", "team_name": "Glasgow Testers",
        "position_group": "Winger", "minutes": 1800.0, "rankable": True})]).to_sql(
        "player_metrics_neutral", engine, index=False, if_exists="append")
    watchlist.add(engine, 2, 901, 318)
    row = watchlist.load(engine).iloc[0]
    assert row["team_name"] == "Glasgow Testers"
    assert row["position_group"] == "Winger"
    # Age from birth_date at the 2025/26 season midpoint (2026-01-01) -- no valuations row
    # exists for a non-EFL player, so this also proves the birth_date path works standalone.
    assert row["age"] == 26.0


def test_load_age_falls_back_to_valuation_when_birth_date_missing(engine):
    # Test Striker (player 1, seeded with no birth_date) must still get an age from
    # valuations.age, exactly as the profile falls back (dashboard/loaders.py).
    pd.DataFrame([_full_row(Valuation.__table__, {
        "player_id": 1, "competition_id": 4, "season_id": 318,
        "position_group": "Centre Forward", "age": 24.0,
        "market_value_eur": 500000.0, "fair_value_eur": 500000.0,
        "undervaluation_eur": 0.0, "undervaluation_pct": 0.0,
        "model_version": "test"})]).to_sql(
        "valuations", engine, index=False, if_exists="append")
    watchlist.add(engine, 1, 4, 318)
    row = watchlist.load(engine).iloc[0]
    assert row["age"] == 24.0


# --- owner 2026-11-23: one shared list, one entry per PLAYER (decision A) ----------------------
def _raw_insert(engine, **row):
    from lofc.store.models import WatchlistEntry
    with engine.begin() as conn:
        conn.execute(WatchlistEntry.__table__.insert().values(**row))


def test_a_player_is_on_the_list_once_whatever_the_league_or_season(engine):
    assert watchlist.add(engine, 1, 4, 318) is True
    assert watchlist.add(engine, 1, 65, 319) is False             # already watched
    assert watchlist.is_watched(engine, 1, 65, 319) is True
    assert len(watchlist.load(engine)) == 1


def test_old_duplicate_rows_show_once_latest_wins_and_are_not_deleted(engine):
    import datetime as dt
    _raw_insert(engine, player_id=1, competition_id=4, season_id=318, status="Watching",
                note="old", created_at=dt.datetime(2026, 1, 1))
    _raw_insert(engine, player_id=1, competition_id=4, season_id=319, status="Shortlisted",
                note="new", created_at=dt.datetime(2026, 9, 1))
    got = watchlist.load(engine)
    assert len(got) == 1 and got.iloc[0]["note"] == "new" and int(got.iloc[0]["season_id"]) == 319
    assert watchlist.row_count(engine) == 2                       # nothing deleted
    # an edit goes to the latest row
    watchlist.update(engine, 1, user_id=7, status="Agent contacted")
    assert watchlist.load(engine).iloc[0]["status"] == "Agent contacted"


def test_add_keeps_who_and_a_snapshot_for_what_changed(engine):
    watchlist.add(engine, 1, 4, 318, user_id=3,
                  snapshot={"rating": 3.41, "club": "Testville", "competition_id": 4})
    r = watchlist.load(engine).iloc[0]
    assert (r["added_by_user_id"], r["added_rating"], r["added_club"], r["added_competition_id"]) == (3, 3.41, "Testville", 4)
    assert r["status"] == "Watching" and pd.notna(r["stage_changed_at"])


def test_update_stage_owner_next_step_due_note_and_optional_drop_reason(engine):
    import datetime as dt
    watchlist.add(engine, 1, 4, 318)
    watchlist.update(engine, 1, user_id=5, status="Shortlisted", owner_user_id=5,
                     next_step="Watch vs Crewe", due_date=dt.date(2026, 12, 2), note="quick")
    r = watchlist.load(engine).iloc[0]
    assert (r["status"], r["owner_user_id"], r["next_step"], r["note"]) == ("Shortlisted", 5, "Watch vs Crewe", "quick")
    assert pd.Timestamp(r["due_date"]).date() == dt.date(2026, 12, 2)
    assert r["note_updated_by"] == 5 and pd.notna(r["note_updated_at"])
    # owner 2026-11-23: dropping needs no reason
    watchlist.update(engine, 1, user_id=5, status="Dropped")
    assert watchlist.load(engine).iloc[0]["status"] == "Dropped"
    watchlist.update(engine, 1, user_id=5, drop_reason="Level")
    assert watchlist.load(engine).iloc[0]["drop_reason"] == "Level"
    # blanks clear; unknown stage or field refused
    watchlist.update(engine, 1, user_id=5, next_step="", due_date=None, owner_user_id=None)
    r = watchlist.load(engine).iloc[0]
    assert r["next_step"] is None and pd.isna(r["due_date"]) and pd.isna(r["owner_user_id"])
    with pytest.raises(ValueError):
        watchlist.update(engine, 1, user_id=5, status="Signed!!")
    with pytest.raises(ValueError):
        watchlist.update(engine, 1, user_id=5, added_rating=9.0)
    assert watchlist.update(engine, 99, user_id=5, note="x") is False   # not on the list


def test_remove_takes_the_player_off_every_row(engine):
    watchlist.add(engine, 1, 4, 318)
    assert watchlist.remove(engine, 1, 65, 319) is True          # any league / season
    assert watchlist.load(engine).empty


def test_stages_and_the_old_names_map(engine):
    assert watchlist.STAGES == ["Watching", "Scout to watch", "Shortlisted", "Agent contacted",
                                "Signed", "Dropped"]
    assert watchlist.ACTIVE_STAGES == ["Watching", "Scout to watch", "Shortlisted", "Agent contacted"]
    assert watchlist.OLD_TO_NEW == {"Watching": "Watching", "Scout sent": "Scout to watch",
                                    "Contact agent": "Agent contacted", "Dropped": "Dropped"}


def test_dismissed_suggestions(engine):
    assert watchlist.dismissed_report_ids(engine) == set()
    watchlist.dismiss(engine, report_id=11, player_id=1, user_id=5)
    watchlist.dismiss(engine, report_id=11, player_id=1, user_id=5)    # twice: no error
    assert watchlist.dismissed_report_ids(engine) == {11}
