"""The test suite must never write run records into a real database.

Before this guard, a test that drove a league-by-league step left 23 fake
"Pull Impect · success" rows in the Mac's pipeline_runs on every suite run. Task 2.2 reads
that table to show when data was last refreshed, so fake rows would show a refresh that
never happened.
"""
import pytest

from lofc.store import runs


def test_run_records_cannot_reach_a_real_database():
    with pytest.raises(RuntimeError, match="tests"):
        runs._engine()


def test_recording_under_tests_writes_nothing_and_does_not_raise(capsys):
    runs.record(step="Pull Impect", status="success", league="League Two 2025/26")
    assert "could not record" in capsys.readouterr().out
