"""The Transfermarkt squad CSV -> Postgres, and reading it back.

WHY THIS EXISTS. `efl_values.csv` was the platform's one piece of DISPLAY data living on
a local disk rather than in Postgres. The dashboard read the file directly, so the Squads &
loans page only worked on a machine that had also run the scrape; anywhere else it fell back
to appearance data and showed 2,966 players instead of 3,783. The injury scrape has always
gone CSV -> loader -> `player_injuries` -> dashboard-reads-the-table; squads is the outlier
being brought into line.

The frame builder and the volume guard are pure. The load itself needs a database and uses
in-memory sqlite, same as `test_injury_load.py`.
"""

import datetime

import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from lofc.store.models import Base, TransfermarktSquad
from lofc.store.squads import load_squads, squad_frame_from_csv, volume_problem

ROWS = [
    {"league_code": "GB1", "competition_id": 3, "club_name": "Cardiff City",
     "tm_player_id": 111, "player_name": "A Player", "date_of_birth": "2000-01-31",
     "position": "Centre-Forward", "height_cm": 183.0, "foot": "left",
     "contract_until": "2027-06-30", "market_value_eur": 1500000.0},
    {"league_code": "GB2", "competition_id": 4, "club_name": "Leyton Orient",
     "tm_player_id": 222, "player_name": "B Player", "date_of_birth": "1998-05-02",
     "position": "Goalkeeper", "height_cm": None, "foot": None,
     "contract_until": None, "market_value_eur": None},
]


def _csv(tmp_path, rows=ROWS):
    path = tmp_path / "efl_values.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _engine():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[TransfermarktSquad.__table__])
    return engine


# --- the frame builder -----------------------------------------------------------------

def test_dates_are_parsed_not_left_as_text(tmp_path):
    frame = squad_frame_from_csv(_csv(tmp_path))
    assert frame.loc[0, "contract_until"] == datetime.date(2027, 6, 30)
    assert frame.loc[0, "date_of_birth"] == datetime.date(2000, 1, 31)


def test_missing_values_become_none_never_nan(tmp_path):
    """A NaN reaching the DB driver is an error on some backends and a silent 'nan'
    string on others. The B-row has no contract, height, foot or market value."""
    frame = squad_frame_from_csv(_csv(tmp_path))
    row = frame.loc[1]
    for field in ("contract_until", "height_cm", "foot", "market_value_eur"):
        assert row[field] is None, f"{field} should be None, got {row[field]!r}"


def test_every_column_the_table_declares_is_produced(tmp_path):
    frame = squad_frame_from_csv(_csv(tmp_path))
    declared = {c.name for c in TransfermarktSquad.__table__.columns} - {"id", "scraped_at"}
    assert declared <= set(frame.columns)


def test_a_missing_file_yields_an_empty_frame_not_an_exception(tmp_path):
    assert squad_frame_from_csv(tmp_path / "nope.csv").empty


# --- the volume guard ------------------------------------------------------------------
#
# The 11 Aug 2026 incident: a scrape against a stale season silently produced blanks and
# still reported success, destroying 1,381 contract dates. A squad snapshot is replaced
# wholesale (unlike injury history, stale squad data is WRONG, not valuable), so a
# truncated file would wipe the table.

def test_a_full_scrape_is_allowed():
    assert volume_problem(incoming=3783, existing=3783) is None


def test_a_truncated_scrape_is_refused():
    assert volume_problem(incoming=40, existing=3783) is not None


def test_the_first_load_is_always_allowed():
    """Nothing stored yet means nothing to lose."""
    assert volume_problem(incoming=5, existing=0) is None


def test_an_empty_scrape_over_real_data_is_refused():
    """Zero incoming is the worst case, not an exemption."""
    assert volume_problem(incoming=0, existing=3783) is not None


# --- the load --------------------------------------------------------------------------

def test_load_writes_every_row_and_reads_back(tmp_path):
    engine = _engine()
    assert load_squads(engine, squad_frame_from_csv(_csv(tmp_path))) == 2
    stored = pd.read_sql("SELECT * FROM transfermarkt_squads", engine)
    assert len(stored) == 2
    assert set(stored["tm_player_id"]) == {111, 222}


def test_load_replaces_rather_than_accumulates(tmp_path):
    """A squad list is a snapshot of NOW. Re-running must not double it."""
    engine = _engine()
    frame = squad_frame_from_csv(_csv(tmp_path))
    load_squads(engine, frame)
    load_squads(engine, frame)
    with engine.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM transfermarkt_squads")).scalar() == 2


def test_a_departed_player_is_gone_after_a_fresh_scrape(tmp_path):
    """Unlike injury history, a stale squad row is wrong -- he is not there any more.

    Sized so the departure is ordinary squad churn (10 rows -> 9), not a shrink big enough
    to trip the volume guard: this asserts the REPLACE, and the guard has its own tests.
    """
    engine = _engine()
    squad = [{**ROWS[0], "tm_player_id": 100 + n} for n in range(10)]
    load_squads(engine, squad_frame_from_csv(_csv(tmp_path, squad)))
    load_squads(engine, squad_frame_from_csv(_csv(tmp_path, squad[:9])))
    stored = pd.read_sql("SELECT tm_player_id FROM transfermarkt_squads", engine)
    assert len(stored) == 9
    assert 109 not in set(stored["tm_player_id"])


def test_a_truncated_load_aborts_before_deleting_anything(tmp_path):
    """The guard must fire BEFORE the delete, or it protects nothing."""
    engine = _engine()
    load_squads(engine, squad_frame_from_csv(_csv(tmp_path, ROWS * 30)))   # 60 rows
    before = pd.read_sql("SELECT * FROM transfermarkt_squads", engine)

    with pytest.raises(RuntimeError):
        load_squads(engine, squad_frame_from_csv(_csv(tmp_path, ROWS[:1])))   # 1 row

    after = pd.read_sql("SELECT * FROM transfermarkt_squads", engine)
    assert len(after) == len(before) == 60


def test_allow_shrink_is_the_deliberate_human_override(tmp_path):
    engine = _engine()
    load_squads(engine, squad_frame_from_csv(_csv(tmp_path, ROWS * 30)))
    load_squads(engine, squad_frame_from_csv(_csv(tmp_path, ROWS[:1])), allow_shrink=True)
    with engine.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM transfermarkt_squads")).scalar() == 1


def test_scraped_at_is_stamped_so_the_ui_can_show_the_snapshot_age(tmp_path):
    """`contract_data_date()` read the FILE's mtime -- a proxy that changes if anyone
    touches the file. MAX(scraped_at) is the real fact."""
    engine = _engine()
    load_squads(engine, squad_frame_from_csv(_csv(tmp_path)))
    stamp = pd.read_sql("SELECT scraped_at FROM transfermarkt_squads", engine)["scraped_at"]
    assert stamp.notna().all()
