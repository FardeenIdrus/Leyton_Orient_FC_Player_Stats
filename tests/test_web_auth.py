"""Web front end: login, session, cookie, write protection."""

import datetime

import pytest

from lofc.dashboard import login_throttle
from lofc.web.app import create_app
from web_fakes import NOW, SECRET, FakeStore, login, make


@pytest.fixture(autouse=True)
def _fresh_throttle(monkeypatch):
    monkeypatch.setattr(login_throttle, "_shared", login_throttle.SprayThrottle(delay_seconds=0))


def _store():
    s = FakeStore()
    s.add(username="ann", full_name="Ann Scout", role="scout", password="correct-horse-1")
    return s


def test_no_secret_refuses_to_start():
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        create_app(users=FakeStore(), secret="")


def test_healthz_needs_no_login():
    c, *_ = make()
    assert c.get("/healthz").json()["status"] == "ok"


def test_every_response_says_how_long_the_server_took():
    # Server-Timing: the browser harness and DevTools can tell server time from page time
    c, *_ = make()
    h = c.get("/healthz").headers.get("server-timing", "")
    assert h.startswith("app;dur=") and float(h.split("=")[1]) >= 0


def test_login_page_renders():
    c, *_ = make(_store())
    r = c.get("/login")
    assert r.status_code == 200 and 'name="username"' in r.text and 'name="password"' in r.text


def test_login_success_sets_hardened_cookie_and_redirects():
    c, *_ = make(_store())
    r = login(c, "ann", "correct-horse-1")
    assert r.status_code == 303 and r.headers["location"] == "/players"
    cookie = r.headers["set-cookie"].lower()
    assert "lofc_web=" in cookie and "httponly" in cookie and "samesite=strict" in cookie
    assert "secure" not in cookie                       # plain http: browser would drop it
    assert f"max-age={12 * 3600}" in cookie             # 12 h absolute
    assert c.get("/players").status_code == 200


def test_cookie_is_secure_over_https():
    c, *_ = make(_store(), base_url="https://testserver")
    assert "secure" in login(c, "ann", "correct-horse-1").headers["set-cookie"].lower()


def test_wrong_password_and_unknown_user_look_identical():
    c, *_ = make(_store())
    a = login(c, "ann", "nope")
    b = login(c, "nobody", "nope")
    assert a.status_code == b.status_code == 401
    assert "Incorrect username or password." in a.text and "Incorrect username or password." in b.text
    assert "set-cookie" not in a.headers


def test_lockout_after_five_failures_even_with_the_right_password():
    c, *_ = make(_store())
    for _ in range(5):
        login(c, "ann", "wrong")
    r = login(c, "ann", "correct-horse-1")
    assert r.status_code == 401 and "locked for 15 minutes" in r.text


def test_inactive_account_cannot_sign_in():
    s = _store()
    s.add(username="old", full_name="Old", role="scout", password="correct-horse-1", is_active=False)
    c, *_ = make(s)
    r = login(c, "old", "correct-horse-1")
    assert r.status_code == 401 and "deactivated" in r.text


def test_failed_logins_feed_the_spray_throttle():
    c, *_ = make(_store())
    login(c, "ann", "wrong")
    assert login_throttle._shared.distinct_recent_usernames(NOW) == {"ann"}


def test_spray_throttle_delays_failed_attempts(monkeypatch):
    slept = []
    monkeypatch.setattr(login_throttle, "_shared",
                        login_throttle.SprayThrottle(distinct_threshold=1, delay_seconds=3.0))

    async def fake_sleep(s):
        slept.append(s)
    monkeypatch.setattr("lofc.web.app.asyncio.sleep", fake_sleep)
    c, *_ = make(_store())
    login(c, "ann", "wrong")
    assert slept == [3.0]


def test_page_redirects_to_login_but_api_returns_401():
    c, *_ = make(_store())
    r = c.get("/players")
    assert r.status_code == 303 and r.headers["location"] == "/login"
    r = c.post("/api/change-password", json={}, headers={"X-LOFC-Request": "1"})
    assert r.status_code == 401 and r.json()["detail"] == "not_signed_in"


def test_tampered_cookie_is_rejected():
    c, *_ = make(_store())
    login(c, "ann", "correct-horse-1")
    c.cookies.set("lofc_web", c.cookies.get("lofc_web")[:-3] + "xxx")
    assert c.get("/players").status_code == 303


def test_session_expires_after_twelve_hours():
    c, _, clock = make(_store())
    login(c, "ann", "correct-horse-1")
    clock.now = NOW + datetime.timedelta(hours=11, minutes=59)
    assert c.get("/players").status_code == 200
    clock.now = NOW + datetime.timedelta(hours=12, minutes=1)
    assert c.get("/players").status_code == 303


def test_deactivation_takes_effect_on_the_next_request():
    c, store, _ = make(_store())
    login(c, "ann", "correct-horse-1")
    store.accounts[1].is_active = False
    assert c.get("/players").status_code == 303


def test_forced_password_change_blocks_pages_until_done():
    s = FakeStore()
    s.add(username="new", full_name="New", role="scout", password="temp-pass-12345",
          must_change_password=True)
    c, store, _ = make(s)
    r = login(c, "new", "temp-pass-12345")
    assert r.headers["location"] == "/change-password"
    assert c.get("/players").headers["location"] == "/change-password"
    api = c.post("/api/change-password", json={"password": "x", "confirm": "x"},
                 headers={"X-LOFC-Request": "1"})
    assert api.status_code == 400 and "at least 12" in api.json()["error"]
    mism = c.post("/api/change-password", json={"password": "a" * 12, "confirm": "b" * 12},
                  headers={"X-LOFC-Request": "1"})
    assert "do not match" in mism.json()["error"]
    ok = c.post("/api/change-password", json={"password": "a-long-new-pass", "confirm": "a-long-new-pass"},
                headers={"X-LOFC-Request": "1"})
    assert ok.status_code == 200 and store.changed == [1]
    assert c.get("/players").status_code == 200


def test_other_api_is_403_while_password_change_pending():
    s = FakeStore()
    s.add(username="new", full_name="New", role="scout", password="temp-pass-12345",
          must_change_password=True)
    c, *_ = make(s)
    login(c, "new", "temp-pass-12345")
    from fastapi import Depends
    from lofc.web.security import write_user

    @c.app.post("/api/_probe")
    async def probe(u=Depends(write_user)):
        return {"ok": True}
    r = c.post("/api/_probe", headers={"X-LOFC-Request": "1"})
    assert r.status_code == 403 and r.json()["detail"] == "password_change_required"


def test_writes_need_the_request_header():
    from fastapi import Depends
    from lofc.web.security import write_user
    c, *_ = make(_store())

    @c.app.post("/api/_probe")
    async def probe(u=Depends(write_user)):
        return {"ok": True}
    assert c.post("/api/_probe", headers={"X-LOFC-Request": "1"}).status_code == 401   # no session
    login(c, "ann", "correct-horse-1")
    assert c.post("/api/_probe").status_code == 403                                    # no header
    assert c.post("/api/_probe", headers={"X-LOFC-Request": "0"}).status_code == 403
    assert c.post("/api/_probe", headers={"X-LOFC-Request": "1"}).status_code == 200


def test_logout_needs_header_and_clears_session():
    c, *_ = make(_store())
    login(c, "ann", "correct-horse-1")
    assert c.post("/logout").status_code == 403
    r = c.post("/logout", headers={"X-LOFC-Request": "1"})
    assert r.status_code == 200
    c.cookies.clear()
    assert c.get("/players").status_code == 303


def test_root_is_the_home_page_and_needs_a_session():
    c, *_ = make(_store())
    r = c.get("/")
    assert r.status_code == 303 and r.headers["location"] == "/login"
    login(c, "ann", "correct-horse-1")
    r = c.get("/")
    assert r.status_code == 200
    assert "/img/logo.png" in r.text and 'href="/players"' in r.text


def test_security_headers():
    c, *_ = make(_store())
    h = c.get("/login").headers
    assert "script-src" not in h["content-security-policy"] or "'unsafe-inline'" not in h["content-security-policy"].split("script-src")[1].split(";")[0]
    assert h["x-frame-options"] == "DENY" and h["cache-control"] == "no-store"
