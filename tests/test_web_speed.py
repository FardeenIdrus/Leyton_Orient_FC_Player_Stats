"""TASKS 2.36 speed items: gzip (S-A), versioned immutable static files (S-B), card prefetch
hand-off (S-C). No database: the app is built with fakes."""
import gzip
import re
import time
from pathlib import Path

import pytest

from web_fakes import FakeStore, login, make

STATIC = Path(__file__).resolve().parent.parent / "src" / "lofc" / "web" / "static"


def _client():
    s = FakeStore()
    s.add(username="u", full_name="Ann Scout", role="scout", password="correct-horse-1")
    c, *_ = make(s)
    login(c, "u", "correct-horse-1")
    return c


def _version(html: str) -> str:
    m = re.search(r'/static/v/([0-9a-f]{10,})/css/app\.css', html)
    assert m, "app.css is not linked through a versioned URL"
    return m.group(1)


# --- S-A gzip --------------------------------------------------------------------------------
def test_static_js_and_api_json_are_gzipped_and_keep_their_headers(monkeypatch):
    from lofc.web.api import physical as api
    import test_web_physical as twp
    c = _client()
    ver = _version(c.get("/players").text)
    r = c.get(f"/static/v/{ver}/js/common.js", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and r.headers["content-encoding"] == "gzip"
    assert "server-timing" in r.headers and "content-security-policy" in r.headers
    # an /api/ answer (the Physical page's, on fakes)
    twp.install_fake(monkeypatch)
    a = c.get("/api/physical", headers={"Accept-Encoding": "gzip"})
    assert a.status_code == 200 and a.headers["content-encoding"] == "gzip"
    assert a.json()["pool"] and "server-timing" in a.headers
    assert a.headers["cache-control"] == "no-store"
    api.clear()


def test_login_still_sets_the_session_cookie_with_gzip_on():
    s = FakeStore()
    s.add(username="u", full_name="Ann", role="scout", password="correct-horse-1")
    c, *_ = make(s)
    r = c.post("/login", content="username=u&password=correct-horse-1",
               headers={"Content-Type": "application/x-www-form-urlencoded",
                        "Accept-Encoding": "gzip"})
    assert r.status_code == 303 and "lofc_web=" in r.headers.get("set-cookie", "")
    assert "httponly" in r.headers["set-cookie"].lower()


# --- S-B versioned static files ------------------------------------------------------------------
def test_pages_link_only_versioned_static_urls_and_those_are_immutable():
    c = _client()
    html = c.get("/players").text
    ver = _version(html)
    assert not re.search(r'(src|href)="/static/(?!v/)', html), "an unversioned /static/ link"
    r = c.get(f"/static/v/{ver}/js/players.js")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert c.get("/players").headers["cache-control"] == "no-store"
    login_html = make(FakeStore())[0].get("/login").text
    assert _version(login_html) == ver


def test_an_old_version_is_never_served():
    """A page still holding an old version must not pair its modules with today's files."""
    c = _client()
    ver = _version(c.get("/players").text)
    old = "0" * len(ver)
    assert c.get(f"/static/v/{old}/js/common.js").status_code == 404


def test_path_traversal_is_refused():
    c = _client()
    ver = _version(c.get("/players").text)
    assert c.get(f"/static/v/{ver}/../app.py").status_code == 404
    assert c.get(f"/static/v/{ver}/%2e%2e/%2e%2e/app.py").status_code == 404


def test_a_code_change_gives_a_new_version(tmp_path):
    from lofc.web import static_version as sv
    (tmp_path / "js").mkdir()
    f = tmp_path / "js" / "a.js"
    f.write_text("export const a = 1;")
    v1 = sv.compute(tmp_path)
    f.write_text("export const a = 2;")
    v2 = sv.compute(tmp_path)
    assert v1 != v2 and len(v1) == len(v2) >= 10
    assert sv.compute(tmp_path) == v2                    # stable while nothing changes


def test_modules_import_each_other_relatively():
    """`import … from '/static/js/common.js'` would load a second, unversioned copy beside the
    versioned one: every import between modules is relative, so it stays in one version."""
    for js in (STATIC / "js").glob("*.js"):
        text = js.read_text()
        assert not re.search(r"""from\s+['"]/static/""", text), js.name
        assert not re.search(r"""import\(\s*['"]/static/""", text), js.name


# --- S-C card prefetch hand-off -------------------------------------------------------------------
def test_handoff_is_single_use_and_expires():
    from lofc.web.prefetch import Handoff
    h = Handoff(ttl=30.0, maxsize=4)
    calls = []
    assert h.produce("k", lambda: calls.append(1) or b"card") == b"card"
    assert h.produce("k", lambda: calls.append(1) or b"again") == b"card"   # not built twice
    assert h.consume("k") == b"card" and h.consume("k") is None             # used once
    h2 = Handoff(ttl=0.01, maxsize=4)
    h2.produce("k", lambda: b"x")
    time.sleep(0.03)
    assert h2.consume("k") is None


def test_handoff_waits_for_an_in_flight_prefetch():
    import threading
    from lofc.web.prefetch import Handoff
    h = Handoff(ttl=30.0, maxsize=4)
    gate = threading.Event()

    def slow():
        gate.wait(2)
        return b"built once"
    t = threading.Thread(target=lambda: h.produce("k", slow))
    t.start()
    time.sleep(0.05)
    got = []
    t2 = threading.Thread(target=lambda: got.append(h.consume("k")))
    t2.start()
    time.sleep(0.05)
    gate.set()
    t.join(); t2.join()
    assert got == [b"built once"]


def test_handoff_clear_and_size_cap():
    from lofc.web.prefetch import Handoff
    h = Handoff(ttl=30.0, maxsize=2)
    for k in "abc":
        h.produce(k, lambda k=k: k.encode())
    assert h.consume("a") is None and h.consume("c") == b"c"
    h.clear()
    assert h.consume("b") is None


def test_card_prefetch_then_open_builds_the_card_once(monkeypatch):
    from lofc.web.api import card as card_api
    calls = []

    class Core:
        @staticmethod
        def build_card(engine, p, c, s, rank_as=None, show_money=False):
            calls.append((p, c, s, rank_as, show_money))
            return {"ok": True, "p": p}
    monkeypatch.setattr(card_api, "_core", lambda: Core)
    monkeypatch.setattr(card_api, "get_engine", lambda: None)
    card_api.HANDOFF.clear()
    c = _client()
    pre = c.get("/api/card/1/2/3", headers={"X-LOFC-Prefetch": "1"})
    assert pre.status_code == 200 and pre.json() == {"ok": True, "p": 1}
    real = c.get("/api/card/1/2/3")
    assert real.json() == {"ok": True, "p": 1} and len(calls) == 1
    c.get("/api/card/1/2/3")                                  # the hand-off was used up
    assert len(calls) == 2
    c.get("/api/card/1/2/3?money=1", headers={"X-LOFC-Prefetch": "1"})
    c.get("/api/card/1/2/3")                                  # other params: not handed over
    assert len(calls) == 4


def test_a_watchlist_write_drops_prefetched_cards(monkeypatch):
    from lofc.web.api import card as card_api
    card_api.HANDOFF.clear()
    card_api.HANDOFF.produce(("x",), lambda: b"{}")
    card_api.forget_prefetched()
    assert card_api.HANDOFF.consume(("x",)) is None


def test_squad_section_prefetch_is_handed_over_too(monkeypatch):
    from lofc.web.api import card as card_api
    calls = []
    row = {"player_id": 1, "player_name": "A", "position_group": "Winger", "season_id": 3}

    class Core:
        @staticmethod
        def card_row(p, c, s, rank_as=None):
            calls.append(rank_as)
            return row, "All Metrics", None

        @staticmethod
        def clean(x):
            return x

    class Squad:
        @staticmethod
        def section(*a, **k):
            return {"title": "Against our Wingers"}
    monkeypatch.setattr(card_api, "_core", lambda: Core)
    monkeypatch.setattr(card_api, "_squad", lambda: Squad)
    card_api.HANDOFF.clear()
    c = _client()
    assert c.get("/api/card/1/2/3/squad?rank_as=X", headers={"X-LOFC-Prefetch": "1"}).status_code == 200
    r = c.get("/api/card/1/2/3/squad?rank_as=X")
    assert r.json() == {"title": "Against our Wingers"}
    assert calls == ["X"]                                # built once, handed over
