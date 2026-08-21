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
    watchlist.set_status(engine, 1, 4, 318, "Scout sent")
    row = watchlist.load(engine).iloc[0]
    assert row["note"] == "send a scout to the next home game"
    assert row["status"] == "Scout sent"


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


def test_same_player_in_two_leagues_coexists(engine):
    # A mid-season mover is watched per league row, independently.
    assert watchlist.add(engine, 1, 4, 318) is True
    assert watchlist.add(engine, 1, 65, 318) is True
    assert len(watchlist.load(engine)) == 2
    watchlist.remove(engine, 1, 4, 318)
    remaining = watchlist.load(engine)
    assert len(remaining) == 1
    assert int(remaining.iloc[0]["competition_id"]) == 65
