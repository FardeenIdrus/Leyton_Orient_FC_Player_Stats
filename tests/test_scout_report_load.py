"""Scout reports into Postgres: upsert, never delete, and refuse a truncated read.

THE WRITE MODE IS AN UPSERT, AND THAT IS THE WHOLE POINT. A scout can reopen a report
from the sheet and edit it -- 127 of the 437 live rows carry a `Last Update Date`. The
JotForm submission id is stable across those edits, so an edited report must OVERWRITE
its stored row rather than insert a second one. Keyed on anything less stable (name,
fixture, timestamp) and every edit would duplicate.

NOTHING IS EVER DELETED. A report that was filed is a fact about work a scout did. If a
row disappears from the sheet -- someone sorts, filters, or deletes it by accident -- the
stored row stays and is stamped `missing_since`. Same principle as the injury loader
(`store/injuries.py`), and the deliberate opposite of the squad snapshot, where a stale
row is simply wrong.

THE VOLUME GUARD. The sheet is one accidental Ctrl-A away from being emptied, and the
platform reads it once a minute. The 11 Aug 2026 incident -- a degraded scrape that
reported success and destroyed 1,381 contract dates -- is why every loader in this
codebase has one. Here it cannot cause data loss (we never delete), but it stops a
truncated read from flagging 400 live reports as missing.

The frame builders are pure and tested elsewhere; this needs a database and uses
in-memory sqlite, same as `test_injury_load.py` and `test_squad_load.py`.
"""

import datetime as dt

import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from lofc.store.models import Base, Player, ScoutPlayerLookup, ScoutReport, ScoutSync
from lofc.store.scout_reports import (
    last_digest,
    load_player_lookup,
    record_sync,
    stamp_missing,
    upsert_reports,
    volume_problem,
)

REPORT = {
    "submission_id": "6607479223932953217",
    "scout": "Gareth Mycock",
    "observation": "Video",
    "report_type": "Match Report",
    "player_name": "Ra'ess Bangura-Williams",
    "club_name": "Millwall",
    "foot": "Left",
    "home_team": "Gillingham",
    "away_team": "Millwall",
    "fixture_date": dt.date(2026, 7, 21),
    "comments": "Left footed, athletic.",
    "positions_played": ["LW"],
    "recommended_positions": ["LW"],
    "grade": "B",
    "squad_role": "Core (>70% of Minutes)",
    "verdict": "Sign",
    "edit_url": "https://eu.jotform.com/edit/6607479223932953217",
    "submitted_at": None,
    "updated_at": dt.date(2026, 7, 27),
    "linkable": True,
}


def _engine():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[
        Player.__table__, ScoutReport.__table__, ScoutPlayerLookup.__table__,
        ScoutSync.__table__])
    return engine


def _frame(*rows):
    return pd.DataFrame(list(rows) or [REPORT])


def _stored(engine):
    return pd.read_sql("SELECT * FROM scout_reports", engine)


# --- the upsert --------------------------------------------------------------------------

def test_a_new_report_is_inserted():
    engine = _engine()
    assert upsert_reports(engine, _frame()) == 1
    assert len(_stored(engine)) == 1


def test_re_running_an_unchanged_sync_does_not_duplicate():
    """Polled every 60 seconds. A loader that inserted blindly would add 1,440 copies
    of every report per day."""
    engine = _engine()
    upsert_reports(engine, _frame())
    upsert_reports(engine, _frame())
    assert len(_stored(engine)) == 1


def test_an_edited_report_overwrites_rather_than_duplicating():
    """THE CASE THE KEY EXISTS FOR. 127 of 437 live rows have been edited."""
    engine = _engine()
    upsert_reports(engine, _frame())
    upsert_reports(engine, _frame({**REPORT, "verdict": "Don't sign", "grade": "D"}))
    stored = _stored(engine)
    assert len(stored) == 1
    assert stored.iloc[0]["verdict"] == "Don't sign"
    assert stored.iloc[0]["grade"] == "D"


def test_two_different_reports_both_land():
    engine = _engine()
    upsert_reports(engine, _frame(REPORT, {**REPORT, "submission_id": "999"}))
    assert len(_stored(engine)) == 2


def test_the_multi_value_positions_survive_the_round_trip():
    """Stored as JSON so the same model runs on Postgres and the sqlite used here."""
    engine = _engine()
    upsert_reports(engine, _frame({**REPORT, "positions_played": ["RB", "RWB"]}))
    assert _stored(engine).iloc[0]["positions_played"] in (["RB", "RWB"], '["RB", "RWB"]')


def test_a_blank_submitted_at_stays_null():
    """22 of 437 rows have none. Absent is not now() and not the epoch."""
    engine = _engine()
    upsert_reports(engine, _frame())
    assert pd.isna(_stored(engine).iloc[0]["submitted_at"])


def test_an_empty_frame_writes_nothing_and_does_not_raise():
    engine = _engine()
    assert upsert_reports(engine, pd.DataFrame()) == 0


def test_the_player_link_is_not_clobbered_by_a_later_sync():
    """`player_id` is resolved by a SEPARATE stage after the load. A sync that reset it
    to NULL every minute would undo the linking work on every poll."""
    engine = _engine()
    upsert_reports(engine, _frame())
    with engine.begin() as conn:
        conn.execute(text("UPDATE scout_reports SET player_id = 4242"))
    upsert_reports(engine, _frame({**REPORT, "verdict": "Monitor"}))
    stored = _stored(engine)
    assert stored.iloc[0]["player_id"] == 4242
    assert stored.iloc[0]["verdict"] == "Monitor"


# --- nothing is ever deleted ---------------------------------------------------------------

def test_a_report_missing_from_the_sheet_is_kept_and_stamped():
    """Someone deleting a row in a spreadsheet must not erase the record that a scout
    watched that match."""
    engine = _engine()
    upsert_reports(engine, _frame(REPORT, {**REPORT, "submission_id": "999"}))
    stamp_missing(engine, seen_ids={"6607479223932953217"})
    stored = _stored(engine).set_index("submission_id")
    assert len(stored) == 2
    assert pd.isna(stored.loc["6607479223932953217", "missing_since"])
    assert pd.notna(stored.loc["999", "missing_since"])


def test_a_report_that_reappears_has_its_missing_stamp_cleared():
    """A filtered view, or a sort mid-read, can hide a row for one sync. Coming back is
    not a new report and must not stay flagged."""
    engine = _engine()
    upsert_reports(engine, _frame())
    stamp_missing(engine, seen_ids=set())
    assert pd.notna(_stored(engine).iloc[0]["missing_since"])
    upsert_reports(engine, _frame())
    assert pd.isna(_stored(engine).iloc[0]["missing_since"])


def test_stamping_missing_never_deletes_a_row():
    engine = _engine()
    upsert_reports(engine, _frame())
    stamp_missing(engine, seen_ids=set())
    assert len(_stored(engine)) == 1


# --- the volume guard -----------------------------------------------------------------------

def test_a_full_read_is_allowed():
    assert volume_problem(incoming=437, existing=437) is None


def test_a_truncated_read_is_refused():
    """What an interrupted fetch, a filtered view or a cleared sheet looks like."""
    assert volume_problem(incoming=12, existing=437) is not None


def test_an_empty_read_over_real_data_is_refused():
    assert volume_problem(incoming=0, existing=437) is not None


def test_the_first_load_is_always_allowed():
    assert volume_problem(incoming=437, existing=0) is None


def test_ordinary_growth_is_allowed():
    """Reports only accumulate; the count should rise week on week."""
    assert volume_problem(incoming=460, existing=437) is None


# --- the sync record --------------------------------------------------------------------

def test_the_digest_is_recorded_and_read_back():
    engine = _engine()
    record_sync(engine, digest="abc123", reports_seen=437, reports_written=437)
    assert last_digest(engine) == "abc123"


def test_no_sync_yet_reads_as_none_not_an_error():
    """First run on a fresh database."""
    assert last_digest(_engine()) is None


def test_the_latest_digest_wins():
    engine = _engine()
    record_sync(engine, digest="old", reports_seen=1, reports_written=1)
    record_sync(engine, digest="new", reports_seen=2, reports_written=2)
    assert last_digest(engine) == "new"


def test_an_unchanged_sync_is_recorded_as_unchanged():
    """The dashboard shows when the data was last CHECKED, not only when it last moved
    -- "nothing has changed for three hours" and "the sync died three hours ago" look
    identical otherwise, which is register P14 in miniature."""
    engine = _engine()
    record_sync(engine, digest="abc", reports_seen=437, reports_written=0, changed=False)
    stored = pd.read_sql("SELECT * FROM scout_sync", engine)
    assert bool(stored.iloc[0]["changed"]) is False
    assert pd.notna(stored.iloc[0]["synced_at"])


# --- the player lookup ---------------------------------------------------------------------

LOOKUP = {"player_name": "Aaron Bouwman", "date_of_birth": dt.date(2007, 8, 28),
          "source_ref": "Aaron Bouwman (39322)", "profile_url": None, "flagged": "No"}


def test_the_lookup_is_replaced_not_accumulated():
    """A dropdown list is a snapshot: a name no longer offered is simply gone."""
    engine = _engine()
    load_player_lookup(engine, pd.DataFrame([LOOKUP]))
    load_player_lookup(engine, pd.DataFrame([LOOKUP]))
    assert len(pd.read_sql("SELECT * FROM scout_player_lookup", engine)) == 1


def test_a_lookup_row_without_a_birth_date_is_still_stored():
    """1,695 of 4,598 rows have no parseable DOB -- some hold "19 yrs" instead. They
    cannot be matched, but they are still valid dropdown entries."""
    engine = _engine()
    load_player_lookup(engine, pd.DataFrame([{**LOOKUP, "date_of_birth": None}]))
    stored = pd.read_sql("SELECT * FROM scout_player_lookup", engine)
    assert len(stored) == 1 and pd.isna(stored.iloc[0]["date_of_birth"])


def test_a_truncated_lookup_aborts_before_deleting_anything():
    """The guard must fire BEFORE the delete, or it protects nothing."""
    engine = _engine()
    load_player_lookup(engine, pd.DataFrame(
        [{**LOOKUP, "source_ref": str(n)} for n in range(60)]))
    with pytest.raises(RuntimeError):
        load_player_lookup(engine, pd.DataFrame([LOOKUP]))
    assert len(pd.read_sql("SELECT * FROM scout_player_lookup", engine)) == 60
