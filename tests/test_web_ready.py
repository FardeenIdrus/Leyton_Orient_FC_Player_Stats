"""Production switch-over (owner 2026-11-09): a new web container takes traffic only once its
start-up warm-up is done. /healthz stays a cheap liveness check and also says whether the
warm-up is done; /readyz answers 503 until it is, then 200."""
import threading

from web_fakes import FakeStore, make


def test_not_ready_until_the_warmups_finish(monkeypatch):
    from lofc.web.api import players as players_api
    monkeypatch.setattr(players_api, "PLAYERS_WARM", threading.Event())
    c, *_ = make(FakeStore())
    assert c.get("/healthz").json() == {"status": "ok", "warm": False}
    r = c.get("/readyz")
    assert r.status_code == 503 and r.json() == {"ready": False}
    players_api.PLAYERS_WARM.set()
    assert c.get("/readyz").status_code == 200 and c.get("/healthz").json()["warm"] is True


def test_a_running_warmup_thread_means_not_ready(monkeypatch):
    from lofc.web.api import players as players_api
    ev = threading.Event(); ev.set()
    monkeypatch.setattr(players_api, "PLAYERS_WARM", ev)
    stop = threading.Event()
    t = threading.Thread(target=stop.wait, name="lofc-physical-warmup", daemon=True)
    t.start()
    try:
        c, *_ = make(FakeStore())
        assert c.get("/readyz").status_code == 503
    finally:
        stop.set(); t.join()
    assert c.get("/readyz").status_code == 200


def test_readiness_needs_no_login_and_reveals_nothing(monkeypatch):
    from lofc.web.api import players as players_api
    ev = threading.Event(); ev.set()
    monkeypatch.setattr(players_api, "PLAYERS_WARM", ev)
    c, *_ = make(FakeStore())
    r = c.get("/readyz")
    assert r.status_code == 200 and r.json() == {"ready": True}
