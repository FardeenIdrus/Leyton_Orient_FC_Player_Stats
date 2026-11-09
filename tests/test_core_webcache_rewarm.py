"""I1: a data write changes web_data_version() and empties every page's cache; every page's
registered warm-up must then re-run in the background, one after another."""
import pytest

from lofc.core import webcache


@pytest.fixture
def clean_registry(monkeypatch):
    monkeypatch.setattr(webcache, "_WARMERS", type(webcache._WARMERS)())
    return webcache


def test_rewarm_all_runs_every_registered_warmup_in_order(clean_registry):
    ran = []
    clean_registry.register_warmup("players", lambda: ran.append("players"))
    clean_registry.register_warmup("card", lambda: ran.append("card"))
    clean_registry.register_warmup("squads", lambda: ran.append("squads"))
    assert clean_registry.rewarm_all() == ["players", "card", "squads"]
    assert ran == ["players", "card", "squads"]


def test_registering_a_name_twice_keeps_one_entry(clean_registry):
    ran = []
    clean_registry.register_warmup("card", lambda: ran.append(1))
    clean_registry.register_warmup("card", lambda: ran.append(2))
    clean_registry.rewarm_all()
    assert ran == [2]


def test_a_failing_warmup_does_not_stop_the_others(clean_registry):
    ran = []

    def boom():
        raise RuntimeError("db down")
    clean_registry.register_warmup("a", boom)
    clean_registry.register_warmup("b", lambda: ran.append("b"))
    clean_registry.rewarm_all()
    assert ran == ["b"]


def test_watcher_rewarms_every_page_each_time_the_version_moves(clean_registry, monkeypatch):
    from lofc.dashboard import loaders as L
    versions = iter(["v1", "v1", "v2", "v2", "v3"])
    monkeypatch.setattr(L, "web_data_version", lambda: next(versions))
    ran = []
    clean_registry.register_warmup("players", lambda: ran.append("players"))
    clean_registry.register_warmup("squads", lambda: ran.append("squads"))
    clean_registry.rewarm_on_change(poll_s=0, rounds=4)
    assert ran == ["players", "squads", "players", "squads"]


def test_watcher_survives_a_failing_version_query(clean_registry, monkeypatch):
    from lofc.dashboard import loaders as L
    seq = iter(["v1", RuntimeError("x"), "v2"])

    def version():
        v = next(seq)
        if isinstance(v, Exception):
            raise v
        return v
    monkeypatch.setattr(L, "web_data_version", version)
    ran = []
    clean_registry.register_warmup("p", lambda: ran.append(1))
    clean_registry.rewarm_on_change(poll_s=0, rounds=2)
    assert ran == [1]


def test_every_built_page_registers_its_warmup(monkeypatch):
    """Mounting the app registers one warm-up per built page (startup threads are not run)."""
    monkeypatch.setattr(webcache, "_WARMERS", type(webcache._WARMERS)())
    from lofc.web.app import create_app
    create_app(users=_NoUsers(), secret="x" * 40, info_items=lambda: [])
    assert webcache.registered_warmups() == [
        "players", "card", "compare", "report", "squads", "scout-reports", "watchlist", "physical",
        "club-vs-league"]


class _NoUsers:
    def authenticate(self, *a):
        raise AssertionError

    def get_user(self, *a):
        return None

    def change_password(self, *a):
        raise AssertionError
