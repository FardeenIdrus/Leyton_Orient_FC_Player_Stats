"""Shared test settings."""
import pytest


@pytest.fixture(autouse=True)
def _no_real_run_records(monkeypatch):
    """Run records (pipeline_runs) must never be written to a real database from a test:
    task 2.2 shows "last refreshed" from that table. A test that wants to see what would be
    recorded replaces `runs.record` itself (see test_pipeline_runs.py)."""
    from lofc.store import runs

    def _blocked():
        raise RuntimeError("run records are not written during tests")

    monkeypatch.setattr(runs, "_engine", _blocked)
