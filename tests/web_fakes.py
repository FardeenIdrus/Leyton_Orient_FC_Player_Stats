"""Fake user store + app factory for the web tests. No database, no real passwords."""

import datetime
from dataclasses import dataclass, field

from fastapi.testclient import TestClient

from lofc.dashboard import auth
from lofc.store.users import ActiveUserRow, AuthResult, UserRow
from lofc.web.app import create_app

SECRET = "test-secret-not-real"
NOW = datetime.datetime(2026, 11, 8, 12, 0, 0)


@dataclass
class Account:
    id: int
    username: str
    full_name: str
    role: str
    password: str
    is_active: bool = True
    must_change_password: bool = False
    failed: int = 0
    locked_until: datetime.datetime | None = None


@dataclass
class FakeStore:
    accounts: dict[int, Account] = field(default_factory=dict)
    changed: list = field(default_factory=list)

    def add(self, **kw) -> Account:
        acc = Account(id=len(self.accounts) + 1, **kw)
        self.accounts[acc.id] = acc
        return acc

    def authenticate(self, username, password, now):
        acc = next((a for a in self.accounts.values() if a.username == username), None)
        if acc is None:
            return AuthResult("bad_credentials")
        locked, remaining = auth.lockout_state(acc.failed, acc.locked_until, now)
        if locked:
            return AuthResult("locked", seconds_locked=remaining)
        if password != acc.password:
            acc.failed, acc.locked_until = auth.next_failure_state(acc.failed, now)
            return AuthResult("bad_credentials")
        if not acc.is_active:
            return AuthResult("inactive")
        acc.failed, acc.locked_until = 0, None
        return AuthResult("ok", user_id=acc.id, full_name=acc.full_name, role=acc.role,
                          must_change_password=acc.must_change_password)

    def get_user(self, user_id):
        a = self.accounts.get(user_id)
        return None if a is None else ActiveUserRow(
            a.id, a.full_name, a.role, a.is_active, a.must_change_password)

    def change_password(self, user_id, new_password):
        problems = auth.password_problems(new_password)
        if problems:
            raise ValueError("; ".join(problems))
        a = self.accounts[user_id]
        a.password, a.must_change_password = new_password, False
        self.changed.append(user_id)


    # --- the Users page's admin calls (same names and rules as lofc.store.users) -----------
    def list_users(self, now):
        out = []
        for a in sorted(self.accounts.values(), key=lambda x: x.username):
            locked, remaining = auth.lockout_state(a.failed, a.locked_until, now)
            out.append(UserRow(a.id, a.username, a.full_name, a.role, a.is_active, locked,
                               remaining, a.failed, NOW - datetime.timedelta(days=a.id)))
        return out

    def create_user(self, username, full_name, role, password):
        if role not in auth.ROLES:
            raise ValueError(f"unknown role {role!r}")
        problems = auth.password_problems(password)
        if problems:
            raise ValueError("password rejected: " + "; ".join(problems))
        if any(a.username == username for a in self.accounts.values()):
            raise ValueError(f"user {username!r} already exists")
        return self.add(username=username, full_name=full_name, role=role, password=password,
                        must_change_password=True).id

    def reset_password(self, user_id, new_password):
        problems = auth.password_problems(new_password)
        if problems:
            raise ValueError("password rejected: " + "; ".join(problems))
        a = self.accounts[user_id]
        a.password, a.must_change_password, a.failed, a.locked_until = new_password, True, 0, None

    def clear_lockout(self, user_id):
        a = self.accounts[user_id]
        a.failed, a.locked_until = 0, None

    def set_active(self, user_id, active):
        self.accounts[user_id].is_active = active


class Clock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now


def make(store=None, clock=None, base_url="http://testserver"):
    store = store or FakeStore()
    clock = clock or Clock()
    app = create_app(users=store, secret=SECRET, clock=clock,
                     info_items=lambda: ["<b>4,376</b> players", "<b>3,229</b> rated (450+ mins)",
                                         "<b>7</b> leagues"])
    return TestClient(app, base_url=base_url, follow_redirects=False), store, clock


def login(client, username, password):
    return client.post("/login", content=f"username={username}&password={password}",
                       headers={"Content-Type": "application/x-www-form-urlencoded"})
