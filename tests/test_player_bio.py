"""Filling foot and nationality from the best source for each field.

Only two fields have two sources: height and contract exist ONLY in Transfermarkt (Impect
ships neither, verified across 1,482 parquet columns and 25 API endpoints). So what is
tested here is the DECLARED ORDER, not machinery.

  foot        Transfermarkt -> Impect
  nationality Impect        -> Transfermarkt

and, above both, the stored value always wins.
"""

import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from lofc.model.player_bio import bio_fill_stmt, combine_sources
from lofc.store.models import Base


def _src(rows):
    """Rows are [player_id, foot, nationality] with an optional contract_until."""
    padded = [list(r) + [None] * (4 - len(r)) for r in rows]
    return pd.DataFrame(padded, columns=["player_id", "foot", "nationality",
                                         "contract_until"])


def test_foot_prefers_transfermarkt():
    """A squad-page fact about a registered player beats one inferred from play."""
    out = combine_sources(_src([[1, "left", None]]), _src([[1, "right", "Wales"]]))
    assert out.loc[0, "foot"] == "left"


def test_nationality_prefers_impect():
    """Impect carries it at ~100% in every league; nothing has ever written the column."""
    out = combine_sources(_src([[1, "left", "England"]]), _src([[1, "right", "Wales"]]))
    assert out.loc[0, "nationality"] == "Wales"


def test_impect_fills_foot_where_transfermarkt_is_silent():
    """The Scottish and PL2 case: nothing scraped them, so TM has nothing to say."""
    out = combine_sources(_src([[1, None, None]]), _src([[1, "right", "Wales"]]))
    assert out.loc[0, "foot"] == "right"


def test_transfermarkt_fills_nationality_where_impect_is_silent():
    out = combine_sources(_src([[1, None, "England"]]), _src([[1, "right", None]]))
    assert out.loc[0, "nationality"] == "England"


def test_a_player_in_only_one_source_still_appears():
    out = combine_sources(_src([[1, "left", None]]), _src([[2, "right", "Wales"]]))
    assert set(out.player_id) == {1, 2}


def test_a_player_with_nothing_to_say_is_dropped():
    """A row carrying neither field is not worth an UPDATE."""
    assert combine_sources(_src([[1, None, None]]), _src([[1, None, None]])).empty


def test_no_sources_returns_the_empty_shape():
    out = combine_sources(None, None)
    assert out.empty
    assert list(out.columns) == ["player_id", "foot", "nationality", "contract_until"]


@pytest.fixture
def engine():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    pd.DataFrame([{"player_id": 1, "player_name": "Stored Both",
                   "foot": "right", "nationality": "England"},
                  {"player_id": 2, "player_name": "Stored Neither",
                   "foot": None, "nationality": None}]
                 ).to_sql("players", eng, index=False, if_exists="append")
    return eng


def _row(engine, pid):
    with engine.begin() as c:
        return dict(c.execute(text("SELECT foot, nationality FROM players "
                                   "WHERE player_id = :p"), {"p": pid}).mappings().one())


def test_a_stored_value_is_never_overwritten(engine):
    with engine.begin() as c:
        c.execute(bio_fill_stmt(), [{"pid": 1, "ft": "left", "nat": "Brazil",
                                    "con": None}])
    assert _row(engine, 1) == {"foot": "right", "nationality": "England"}


def test_a_gap_is_filled(engine):
    with engine.begin() as c:
        c.execute(bio_fill_stmt(), [{"pid": 2, "ft": "left", "nat": "Brazil",
                                    "con": None}])
    assert _row(engine, 2) == {"foot": "left", "nationality": "Brazil"}


def test_an_incoming_null_never_blanks_a_stored_value(engine):
    """The 11 Aug 2026 failure mode: one degraded source nulled 1,381 contract dates."""
    with engine.begin() as c:
        c.execute(bio_fill_stmt(), [{"pid": 1, "ft": None, "nat": None,
                                    "con": None}])
    assert _row(engine, 1) == {"foot": "right", "nationality": "England"}


# --- contract: Transfermarkt only, live scrape leads, expired discarded ----------------

def test_contract_comes_from_transfermarkt_only():
    """Impect ships no contract data at all -- 25 endpoints, none of them registration."""
    import datetime as dt
    out = combine_sources(_src([[1, None, None, dt.date(2027, 5, 31)]]),
                          _src([[1, "right", "Wales"]]))
    assert out.loc[0, "contract_until"] == dt.date(2027, 5, 31)


def test_a_stored_contract_is_never_overwritten(engine):
    """The live squad scrape is current; the static dump is roughly a year old. The
    fallback fills gaps and must never correct."""
    import datetime as dt
    from sqlalchemy import text
    with engine.begin() as c:
        c.execute(text("UPDATE players SET contract_until = '2028-06-30' "
                       "WHERE player_id = 1"))
        c.execute(bio_fill_stmt(), [{"pid": 1, "ft": None, "nat": None,
                                     "con": dt.date(2027, 1, 1)}])
        got = c.execute(text("SELECT contract_until FROM players "
                             "WHERE player_id = 1")).scalar()
    assert str(got).startswith("2028-06-30")


def test_a_missing_contract_is_filled(engine):
    import datetime as dt
    from sqlalchemy import text
    with engine.begin() as c:
        c.execute(bio_fill_stmt(), [{"pid": 2, "ft": None, "nat": None,
                                     "con": dt.date(2027, 5, 31)}])
        got = c.execute(text("SELECT contract_until FROM players "
                             "WHERE player_id = 2")).scalar()
    assert str(got).startswith("2027-05-31")
