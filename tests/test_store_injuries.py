"""Reading a player's injury history. In-memory sqlite; no live Postgres."""

import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from lofc.store import injuries as store_injuries
from lofc.store.models import Base, Player, PlayerInjury


@pytest.fixture()
def engine():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Player(player_id=1, player_name="A Player"))
        session.add(PlayerInjury(player_id=1, season_label="25/26",
                                 injury_type_raw="Ankle injury", injury_category="ankle",
                                 date_from=dt.date(2025, 10, 1),
                                 date_until=dt.date(2025, 12, 1),
                                 days_out=61, games_missed=9, source="transfermarkt"))
        session.add(PlayerInjury(player_id=1, season_label="24/25",
                                 injury_type_raw="Knock", injury_category="other",
                                 date_from=dt.date(2024, 9, 1),
                                 date_until=dt.date(2024, 9, 8),
                                 days_out=7, games_missed=1, source="manual"))
        session.commit()
    return engine


def test_load_for_player_returns_every_spell(engine):
    frame = store_injuries.load_for_player(engine, 1)
    assert len(frame) == 2


def test_load_for_player_orders_newest_first(engine):
    frame = store_injuries.load_for_player(engine, 1)
    assert frame["date_from"].tolist()[0] == dt.date(2025, 10, 1)


def test_load_for_player_returns_an_empty_frame_with_columns_for_no_injuries(engine):
    """An empty frame must still carry its columns: availability_with_evidence and the panel
    both index into them, and a bare DataFrame() would raise KeyError instead of showing
    'not known'."""
    frame = store_injuries.load_for_player(engine, 99999)
    assert frame.empty
    for column in ("season_label", "injury_category", "games_missed", "source"):
        assert column in frame.columns
