"""The bio backfill must never replace a known value with a blank.

A degraded Transfermarkt scrape once wrote NULL over 1,381 contract dates because both
writers set every bio column unconditionally. Both statements are now COALESCE-guarded:
a missing incoming value leaves the stored one alone. Tested against sqlite in-memory,
the pattern tests/test_watchlist.py already uses -- no Postgres needed.
"""

import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from lofc.model.identity import bio_update_stmt as identity_bio_update_stmt
from lofc.model.valuation import bio_update_stmt as valuation_bio_update_stmt
from lofc.store.models import Base

STORED = {"player_id": 1, "player_name": "Test Striker", "birth_date": "1998-05-14",
          "foot": "right", "contract_until": "2027-06-30", "height_cm": 190,
          "tm_player_id": 111}


@pytest.fixture
def engine():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    pd.DataFrame([STORED]).to_sql("players", eng, index=False, if_exists="append")
    return eng


def player(engine) -> dict:
    with engine.begin() as conn:
        row = conn.execute(text(
            "SELECT foot, contract_until, height_cm, tm_player_id, birth_date "
            "FROM players WHERE player_id = 1")).mappings().one()
    return dict(row)


def run(engine, stmt, params):
    with engine.begin() as conn:
        conn.execute(stmt, [params])


# --------------------------------------------------------------------------
# identity.main() -- links a player to Transfermarkt and carries bio across.
# --------------------------------------------------------------------------

def test_identity_blanks_never_overwrite_stored_bio(engine):
    run(engine, identity_bio_update_stmt(),
        {"pid": 1, "tm": 222, "ft": None, "cu": None, "hc": None})
    after = player(engine)
    assert after["contract_until"] == "2027-06-30"
    assert after["foot"] == "right"
    assert after["height_cm"] == 190
    # The row is still updated -- only blank columns are left alone.
    assert after["tm_player_id"] == 222


def test_identity_real_values_do_overwrite(engine):
    run(engine, identity_bio_update_stmt(),
        {"pid": 1, "tm": 222, "ft": "left", "cu": "2029-06-30", "hc": 185})
    after = player(engine)
    assert after["contract_until"] == "2029-06-30"
    assert after["foot"] == "left"
    assert after["height_cm"] == 185


def test_identity_leaves_other_players_alone(engine):
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO players (player_id, player_name, contract_until) "
                          "VALUES (2, 'Other', '2028-06-30')"))
    run(engine, identity_bio_update_stmt(),
        {"pid": 1, "tm": 222, "ft": None, "cu": None, "hc": None})
    with engine.begin() as conn:
        other = conn.execute(text(
            "SELECT contract_until FROM players WHERE player_id = 2")).scalar_one()
    assert other == "2028-06-30"


# --------------------------------------------------------------------------
# valuation.main() -- the bio backfill after the valuation write.
# --------------------------------------------------------------------------

def test_valuation_blanks_never_overwrite_stored_bio(engine):
    run(engine, valuation_bio_update_stmt(),
        {"pid": 1, "bd": None, "tm": None, "ft": None, "cu": None, "hc": None})
    assert player(engine) == {"foot": "right", "contract_until": "2027-06-30",
                              "height_cm": 190, "tm_player_id": 111,
                              "birth_date": "1998-05-14"}


def test_valuation_real_values_do_overwrite(engine):
    run(engine, valuation_bio_update_stmt(),
        {"pid": 1, "bd": "1998-05-15", "tm": 333, "ft": "both",
         "cu": "2030-06-30", "hc": 191})
    assert player(engine) == {"foot": "both", "contract_until": "2030-06-30",
                              "height_cm": 191, "tm_player_id": 333,
                              "birth_date": "1998-05-15"}


def test_valuation_writes_bio_onto_a_player_who_has_none(engine):
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO players (player_id, player_name) "
                          "VALUES (3, 'Blank Slate')"))
    run(engine, valuation_bio_update_stmt(),
        {"pid": 3, "bd": "2001-01-01", "tm": 444, "ft": "left",
         "cu": "2028-06-30", "hc": 180})
    with engine.begin() as conn:
        row = conn.execute(text("SELECT foot, contract_until, height_cm FROM players "
                                "WHERE player_id = 3")).mappings().one()
    assert dict(row) == {"foot": "left", "contract_until": "2028-06-30", "height_cm": 180}
