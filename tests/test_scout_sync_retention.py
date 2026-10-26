"""The scout_sync history is pruned, and the rows the platform reads are never pruned away.

scout_sync gets one row a minute from the cron (`record_sync` runs even when nothing
changed), so without retention it grew without bound -- 32,686 rows before this was added.

Readers of the table, all of which must keep working:
  * `last_digest`                       -- the most recent row's digest (change detector)
  * dashboard `last_sync()`             -- the most recent row (the "last checked" time)
  * tests/test_scout_report_load.py     -- reads the latest rows

So the rule is: keep the newest row, and the newest CHANGED row, whatever their age.
Everything else older than SYNC_HISTORY_DAYS goes.

Same in-memory sqlite pattern as test_scout_report_load.py: throwaway, no real data.
"""

import datetime as dt

import pandas as pd
from sqlalchemy import create_engine, insert

from lofc.store.models import Base, ScoutSync
from lofc.store.scout_reports import (
    SYNC_HISTORY_DAYS,
    last_digest,
    prune_sync_history,
    record_sync,
)


def _engine():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[ScoutSync.__table__])
    return engine


def _insert(engine, digest, days_old, changed):
    """Insert a row directly with a chosen age, bypassing record_sync's clock."""
    with engine.begin() as conn:
        conn.execute(insert(ScoutSync.__table__).values(
            digest=digest,
            synced_at=dt.datetime.now() - dt.timedelta(days=days_old),
            reports_seen=1, reports_written=1 if changed else 0, changed=changed))


def _digests(engine):
    stored = pd.read_sql("SELECT digest FROM scout_sync ORDER BY id", engine)
    return list(stored["digest"])


def test_the_retention_period_is_seven_days():
    assert SYNC_HISTORY_DAYS == 7


def test_old_unchanged_rows_are_removed_and_recent_rows_kept():
    engine = _engine()
    _insert(engine, "old-a", days_old=30, changed=False)
    _insert(engine, "old-b", days_old=10, changed=False)
    _insert(engine, "recent-a", days_old=2, changed=False)
    _insert(engine, "recent-b", days_old=1, changed=True)

    prune_sync_history(engine)

    assert _digests(engine) == ["recent-a", "recent-b"]


def test_record_sync_prunes_old_history_as_it_writes():
    """The cron path: every run ends in record_sync, so pruning has to happen there."""
    engine = _engine()
    _insert(engine, "ancient", days_old=60, changed=False)
    _insert(engine, "recent", days_old=1, changed=False)

    record_sync(engine, digest="now", reports_seen=437, reports_written=0, changed=False)

    assert _digests(engine) == ["recent", "now"]
    assert last_digest(engine) == "now"


def test_the_latest_row_is_kept_even_when_it_is_old():
    """A clock skew or a restored table can leave the newest row older than the window.
    Readers take the newest row, so deleting it would blank the dashboard's last-sync time."""
    engine = _engine()
    _insert(engine, "only-old-a", days_old=40, changed=False)
    _insert(engine, "only-old-b", days_old=20, changed=False)

    prune_sync_history(engine)

    assert _digests(engine) == ["only-old-b"]
    assert last_digest(engine) == "only-old-b"


def test_the_latest_changed_row_is_kept_even_when_it_is_old():
    """The newest real change can be months old while the sheet is quiet. Pruning it would
    make "when did the scout data last actually change" unanswerable."""
    engine = _engine()
    _insert(engine, "last-real-change", days_old=90, changed=True)
    _insert(engine, "quiet-a", days_old=50, changed=False)
    _insert(engine, "quiet-b", days_old=40, changed=False)

    prune_sync_history(engine)

    assert _digests(engine) == ["last-real-change", "quiet-b"]


def test_an_empty_table_is_left_alone():
    engine = _engine()
    assert prune_sync_history(engine) == 0
    assert last_digest(engine) is None
