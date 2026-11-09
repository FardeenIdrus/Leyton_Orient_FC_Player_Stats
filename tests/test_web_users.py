"""The web Users page (admin only): list, create, reset a password, clear a lockout,
deactivate / reactivate -- through the same store calls and rules as the Streamlit page
(`lofc.store.users`, `lofc.model.user_admin`, `auth.password_problems`). Fakes only."""
import datetime

import pytest

from web_fakes import NOW, FakeStore, login, make

H = {"X-LOFC-Request": "1"}
PW = "correct-horse-battery"


def _store():
    s = FakeStore()
    s.add(username="admin", full_name="Ada Admin", role="admin", password=PW)
    s.add(username="scout", full_name="Sam Scout", role="scout", password=PW)
    locked = s.add(username="locky", full_name="Lou Locked", role="medical", password=PW)
    locked.failed, locked.locked_until = 5, NOW + datetime.timedelta(seconds=90)
    return s


def _client(who="admin"):
    s = _store()
    c, *_ = make(s)
    login(c, who, PW)
    return c, s


def test_page_renders_for_admin_with_the_script():
    c, _ = _client()
    r = c.get("/users")
    assert r.status_code == 200 and "/js/users.js" in r.text and "Currently building" not in r.text


@pytest.mark.parametrize("who", ["scout"])
def test_everything_is_admin_only(who):
    c, _ = _client(who)
    assert c.get("/users").status_code == 403
    assert c.get("/api/users").status_code == 403
    assert c.post("/api/users", json={}, headers=H).status_code == 403
    assert c.post("/api/users/1/unlock", headers=H).status_code == 403


def test_list_in_words_never_a_password():
    c, _ = _client()
    d = c.get("/api/users").json()
    assert [u["username"] for u in d["users"]] == ["admin", "locky", "scout"]
    lou = d["users"][1]
    assert lou["status"] == "Active" and lou["lockout"] == "Locked (2 minutes remaining)"
    assert lou["locked"] is True and lou["created"] == "05 Nov 2026"
    assert d["users"][0]["can_deactivate"] is False                  # yourself
    assert d["users"][0]["deactivate_reason"].startswith("You cannot deactivate your own account")
    assert d["roles"] == ["scout", "medical", "head_of_recruitment", "admin"]
    assert "password" not in str(d).lower().replace("password_hint", "")


def test_writes_need_the_request_header():
    c, _ = _client()
    assert c.post("/api/users/3/unlock").status_code == 403


def test_create_account():
    c, s = _client()
    r = c.post("/api/users", json={"username": " newbie ", "full_name": " New Bie ", "role": "scout",
                                   "password": PW, "confirm": PW}, headers=H)
    assert r.status_code == 200 and r.json()["message"].startswith("Created scout account 'newbie'")
    acc = next(a for a in s.accounts.values() if a.username == "newbie")
    assert acc.full_name == "New Bie" and acc.must_change_password


@pytest.mark.parametrize("body,err", [
    ({"username": "", "full_name": "X", "role": "scout", "password": PW, "confirm": PW},
     "Username and full name are both required."),
    ({"username": "x", "full_name": "X", "role": "scout", "password": PW, "confirm": PW + "!"},
     "The two passwords do not match."),
    ({"username": "x", "full_name": "X", "role": "scout", "password": "short", "confirm": "short"},
     "Password rejected:"),
    ({"username": "scout", "full_name": "X", "role": "scout", "password": PW, "confirm": PW},
     "already exists"),
    ({"username": "x", "full_name": "X", "role": "king", "password": PW, "confirm": PW},
     "unknown role"),
])
def test_create_refusals(body, err):
    c, _ = _client()
    r = c.post("/api/users", json=body, headers=H)
    assert r.status_code == 400 and err in r.json()["error"]


def test_reset_password_unlock_and_activation():
    c, s = _client()
    r = c.post("/api/users/2/reset", json={"password": PW + "x", "confirm": PW + "x"}, headers=H)
    assert r.status_code == 200 and s.accounts[2].must_change_password
    assert c.post("/api/users/2/reset", json={"password": "a", "confirm": "b"}, headers=H).status_code == 400
    assert c.post("/api/users/3/unlock", headers=H).status_code == 200 and s.accounts[3].failed == 0
    assert c.post("/api/users/2/active", json={"active": False}, headers=H).status_code == 200
    assert s.accounts[2].is_active is False
    assert c.post("/api/users/2/active", json={"active": True}, headers=H).status_code == 200
    assert s.accounts[2].is_active is True


def test_an_admin_cannot_deactivate_themselves():
    c, s = _client()
    r = c.post("/api/users/1/active", json={"active": False}, headers=H)
    assert r.status_code == 400 and "own account" in r.json()["error"]
    assert s.accounts[1].is_active is True


def test_unknown_user_is_404():
    c, _ = _client()
    assert c.post("/api/users/99/unlock", headers=H).status_code == 404


def test_real_accounts_list_like_the_streamlit_page():
    """Real database (skipped without one): the web list is store.users.list_users with the
    Streamlit page's own labels (model.user_admin)."""
    from sqlalchemy import create_engine
    from lofc.config import settings
    from lofc.model import user_admin
    from lofc.store import users as store_users
    from lofc.web.api import users as users_api
    try:
        e = create_engine(settings.database_url)
        e.connect().close()
    except Exception:
        pytest.skip("no database")
    now = datetime.datetime.now()
    rows = store_users.list_users(e, now)
    out = [users_api._row(r, -1) for r in rows]
    assert [o["username"] for o in out] == [r.username for r in rows]
    for o, r in zip(out, rows):
        assert o["status"] == user_admin.account_status_label(r.is_active)
        assert o["lockout"] == user_admin.lockout_label(r.locked, r.locked_seconds_remaining)
        assert o["created"] == r.created_at.strftime("%d %b %Y")
