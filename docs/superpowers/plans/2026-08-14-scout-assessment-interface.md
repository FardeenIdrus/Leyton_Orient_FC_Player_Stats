# R3a-2 — Scout Assessment Interface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the interface through which recruitment staff log in, read the injury evidence, record the club's Psychological and Medical assessments, sign them off, and rank on the resulting `assessed_composite` — the R3a-1 foundation has all of this in the database and none of it on a screen.

**Architecture:** All logic lives in **pure, importable functions** (`model/assessment_rules.py`, `store/assessments.py`, `dashboard/badges.py`) that are unit-tested without Streamlit; the Streamlit modules are thin render layers over them. This matches the existing suite, which has no `AppTest` anywhere and tests dashboard behaviour through `dashboard/labels.py`-style pure functions. The evidence panel is written **once** and called from two places (player profile, assessment form) so the two can never disagree.

**Tech Stack:** Python 3.11 (in Docker), Streamlit, SQLAlchemy 2.0 Core, pandas, pytest, `hashlib.scrypt`. **No new dependencies.**

## Global Constraints

- **Everything runs in Docker**: `docker compose exec app …`. The host is Python 3.14; the container is 3.11. Never run `pytest` on the host.
- **No new dependencies.** Not for auth, not for tables, not for charts.
- **NEVER run `git push`.** Commit locally only. Committing is authorised on this branch; pushing is not.
- **No StatsBomb.** Scoring is Impect + SkillCorner only.
- **Nothing in this plan changes a score.** `objective_composite` remains `RANK_COLUMN` and the default ranking. `full_composite` and the `shortlists` ordering are untouched. Any diff that alters an existing scoring number is a defect.
- **All 365 existing tests must still pass.**
- **Decision 16 governs over spec §15's superseded text**: every role may assess **both** dimensions; `sign_off` is the only gated assessment action. Use `auth.can(role, action)` — never hard-code a role name in a page.
- **Decision 13**: a failed screening criterion **warns**. It never caps, clamps or overwrites the band the assessor entered.
- **Decision 14**: `submitted` scores and ranks immediately. Sign-off never hides a player, never changes a number, and gates only what may be exported as final.
- **Decision 12**: no formula produces a Medical band. Injury data is evidence shown to a person and is never summed, weighted or mapped into a score.
- **Colour never carries meaning alone** (spec §16). Every badge states its status in words.
- **Caveats sit beside the number they qualify**, never in a page footer (spec §16).
- **No staff names** in code, UI copy or docs.
- **Confidential data stays local**: never commit `docs/*.xlsx`, `docs/*.docx`, or any scraped feed.
- Schema changes go through **Alembic**. (This plan needs exactly one migration, in Task 0.)
- **Presentation is a spec requirement, not a preference** (spec §16). Tasks 3, 4 and 5 must invoke the frontend design skill before writing page code.

---

## File Structure

**New — pure logic (fully unit-tested, no Streamlit import):**

| File | Responsibility |
|---|---|
| `src/lofc/model/assessment_rules.py` | Psychological mean, completeness → `draft`/`submitted`, screening flag, Medical ceiling note. No I/O. |
| `src/lofc/store/assessments.py` | Every read/write of `scout_assessments` + `scout_criterion_scores`. Mirrors `store/watchlist.py`: plain SQLAlchemy Core, runs on sqlite in tests. |
| `src/lofc/store/injuries.py` | Reads `player_injuries` for one player, and the per-league coverage figures. |
| `src/lofc/dashboard/badges.py` | Status → badge text/colour. Pure string functions, so the words-not-colour rule is testable. |

**New — Streamlit render layers (thin):**

| File | Responsibility |
|---|---|
| `src/lofc/dashboard/session.py` | Login gate, session state, throttle wiring, `current_user()`. |
| `src/lofc/dashboard/evidence.py` | The §6 evidence panel. Rendered identically in both callers. |
| `src/lofc/dashboard/tabs/assess.py` | The assessment form. |
| `src/lofc/dashboard/tabs/signoff.py` | The sign-off queue. |

**Modified:**

| File | Change |
|---|---|
| `src/lofc/dashboard/auth.py` | Password strength rules; throttle; session expiry. |
| `src/lofc/admin.py` | `set-password` and `list-users` subcommands. |
| `src/lofc/dashboard/app.py` | Login gate before `main()`'s body; sidebar identity; two new tabs. |
| `src/lofc/dashboard/tabs/players.py` | Evidence panel + scout section on the profile; Assess button; Assessed ranking mode. |
| `src/lofc/dashboard/tabs/watchlist.py` | Status badge column, Assess action, status filter. |
| `src/lofc/store/models.py` | `User.failed_logins`, `User.locked_until`, `User.must_change_password`. |
| `alembic/versions/` | One migration for those three columns. |

**Dependency direction** (unchanged from `app.py`'s stated rule): `theme/labels → badges → charts → store/* → loaders → evidence → controls → tabs → app`. No cycles.

---

## Task 0: Auth hardening — reset, strength, throttle, expiry

Four gaps that do not matter on a laptop and all matter the day this is on a server. Done first because Task 1's login flow consumes every function here; doing it after would mean writing the login page twice.

**Files:**
- Modify: `src/lofc/dashboard/auth.py`
- Modify: `src/lofc/admin.py`
- Modify: `src/lofc/store/models.py:435-450` (the `User` model)
- Create: `alembic/versions/<hash>_user_login_security.py`
- Test: `tests/test_auth.py` (exists — extend it)

**Interfaces:**
- Consumes: `auth.hash_password`, `auth.verify_password`, `auth.ROLES` (all exist).
- Produces:
  - `auth.PASSWORD_MIN_LENGTH: int` = 12
  - `auth.password_problems(password: str) -> list[str]` — empty list means acceptable
  - `auth.MAX_FAILED_LOGINS: int` = 5, `auth.LOCKOUT_MINUTES: int` = 15
  - `auth.lockout_state(failed_logins: int, locked_until: datetime | None, now: datetime) -> tuple[bool, int]` — `(is_locked, seconds_remaining)`
  - `auth.next_failure_state(failed_logins: int, now: datetime) -> tuple[int, datetime | None]` — `(new_count, new_locked_until)`
  - `auth.SESSION_TTL_MINUTES: int` = 720
  - `auth.session_expired(logged_in_at: datetime | None, now: datetime) -> bool`
  - `User.failed_logins: int`, `User.locked_until: datetime | None`, `User.must_change_password: bool`

- [ ] **Step 1: Write the failing tests for password strength**

Add to `tests/test_auth.py`:

```python
def test_password_problems_rejects_short_password():
    problems = auth.password_problems("short")
    assert problems
    assert any("12" in p for p in problems)


def test_password_problems_rejects_empty():
    assert auth.password_problems("")


def test_password_problems_accepts_a_long_passphrase():
    assert auth.password_problems("correct horse battery staple") == []


def test_password_problems_does_not_require_symbols_or_digits():
    """Length is the rule. Composition rules push people towards Passw0rd! and a sticky note;
    a long passphrase is stronger and easier to remember. Documented so nobody 'improves' it."""
    assert auth.password_problems("a" * 12) == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `docker compose exec app pytest tests/test_auth.py -k password_problems -v`
Expected: FAIL — `AttributeError: module 'lofc.dashboard.auth' has no attribute 'password_problems'`

- [ ] **Step 3: Implement password strength in `auth.py`**

Append to `src/lofc/dashboard/auth.py`:

```python
# Length is deliberately the ONLY rule. Composition requirements (a digit, a symbol, mixed
# case) measurably push users towards predictable mutations -- Passw0rd! -- and towards
# writing the result down, while a long passphrase is both stronger and easier to recall.
# NIST SP 800-63B says the same. Do not "strengthen" this by adding character classes.
PASSWORD_MIN_LENGTH = 12


def password_problems(password: str) -> list[str]:
    """Every reason `password` is unacceptable. An empty list means it is acceptable.

    Returns a list rather than a bool so a caller can show the user all of the problems at
    once instead of making them fix one, resubmit, and discover the next.
    """
    problems: list[str] = []
    if len(password) < PASSWORD_MIN_LENGTH:
        problems.append(f"must be at least {PASSWORD_MIN_LENGTH} characters")
    return problems
```

- [ ] **Step 4: Run to verify they pass**

Run: `docker compose exec app pytest tests/test_auth.py -k password_problems -v`
Expected: 4 passed

- [ ] **Step 5: Write the failing tests for the login throttle**

```python
import datetime as dt


def test_lockout_state_unlocked_when_never_failed():
    locked, remaining = auth.lockout_state(0, None, dt.datetime(2026, 8, 14, 12, 0))
    assert locked is False
    assert remaining == 0


def test_lockout_state_locked_while_locked_until_is_in_the_future():
    now = dt.datetime(2026, 8, 14, 12, 0)
    locked, remaining = auth.lockout_state(5, now + dt.timedelta(minutes=10), now)
    assert locked is True
    assert remaining == 600


def test_lockout_state_unlocked_once_locked_until_has_passed():
    now = dt.datetime(2026, 8, 14, 12, 0)
    locked, remaining = auth.lockout_state(5, now - dt.timedelta(seconds=1), now)
    assert locked is False
    assert remaining == 0


def test_next_failure_state_counts_up_without_locking_below_the_limit():
    count, until = auth.next_failure_state(3, dt.datetime(2026, 8, 14, 12, 0))
    assert count == 4
    assert until is None


def test_next_failure_state_locks_on_reaching_the_limit():
    now = dt.datetime(2026, 8, 14, 12, 0)
    count, until = auth.next_failure_state(auth.MAX_FAILED_LOGINS - 1, now)
    assert count == auth.MAX_FAILED_LOGINS
    assert until == now + dt.timedelta(minutes=auth.LOCKOUT_MINUTES)
```

- [ ] **Step 6: Run to verify they fail**

Run: `docker compose exec app pytest tests/test_auth.py -k "lockout or failure_state" -v`
Expected: FAIL — `AttributeError: ... has no attribute 'lockout_state'`

- [ ] **Step 7: Implement the throttle**

Append to `src/lofc/dashboard/auth.py`:

```python
# scrypt already makes each guess cost ~50ms, which blunts online guessing but does not stop
# it: 5 attempts/second sustained overnight is still ~150k guesses. These bound it. The state
# lives on the users row rather than in process memory so it survives a Streamlit restart and
# is shared if the app is ever run with more than one worker.
MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15


def lockout_state(failed_logins: int, locked_until: "datetime.datetime | None",
                  now: "datetime.datetime") -> tuple[bool, int]:
    """Whether this account is currently locked, and for how many more seconds.

    `failed_logins` is accepted but deliberately not consulted: `locked_until` is the single
    source of truth for whether a lock is active, so a stale counter left behind by a partial
    write can never lock an account on its own.
    """
    if locked_until is None or locked_until <= now:
        return False, 0
    return True, int((locked_until - now).total_seconds())


def next_failure_state(failed_logins: int,
                       now: "datetime.datetime") -> tuple[int, "datetime.datetime | None"]:
    """The (count, locked_until) to store after one more failed attempt."""
    count = failed_logins + 1
    if count >= MAX_FAILED_LOGINS:
        return count, now + datetime.timedelta(minutes=LOCKOUT_MINUTES)
    return count, None
```

Add `import datetime` to the imports at the top of `auth.py`, beside `import hashlib`.

- [ ] **Step 8: Run to verify they pass**

Run: `docker compose exec app pytest tests/test_auth.py -k "lockout or failure_state" -v`
Expected: 5 passed

- [ ] **Step 9: Write the failing tests for session expiry**

```python
def test_session_expired_is_true_when_never_logged_in():
    assert auth.session_expired(None, dt.datetime(2026, 8, 14, 12, 0)) is True


def test_session_expired_is_false_inside_the_window():
    now = dt.datetime(2026, 8, 14, 12, 0)
    assert auth.session_expired(now - dt.timedelta(minutes=5), now) is False


def test_session_expired_is_true_past_the_window():
    now = dt.datetime(2026, 8, 14, 12, 0)
    stale = now - dt.timedelta(minutes=auth.SESSION_TTL_MINUTES + 1)
    assert auth.session_expired(stale, now) is True
```

- [ ] **Step 10: Run to verify they fail**

Run: `docker compose exec app pytest tests/test_auth.py -k session_expired -v`
Expected: FAIL — `AttributeError: ... has no attribute 'session_expired'`

- [ ] **Step 11: Implement session expiry**

```python
# 12 hours: long enough that nobody is re-authenticating during a working day, short enough
# that a browser left open on a shared training-ground machine does not stay logged in all week.
SESSION_TTL_MINUTES = 720


def session_expired(logged_in_at: "datetime.datetime | None",
                    now: "datetime.datetime") -> bool:
    """True if a session started at `logged_in_at` should no longer be trusted.

    A missing timestamp expires: an absent value means the session was never properly
    established, and defaulting that to 'still valid' would be the wrong direction to fail.
    """
    if logged_in_at is None:
        return True
    return now - logged_in_at > datetime.timedelta(minutes=SESSION_TTL_MINUTES)
```

- [ ] **Step 12: Run to verify they pass**

Run: `docker compose exec app pytest tests/test_auth.py -k session_expired -v`
Expected: 3 passed

- [ ] **Step 13: Add the three columns to the `User` model**

In `src/lofc/store/models.py`, inside `class User`, after the `is_active` line:

```python
    # Login throttling state (dashboard/auth.py). Stored on the row rather than in process
    # memory so a lockout survives a Streamlit restart.
    failed_logins: Mapped[int] = mapped_column(Integer, server_default="0")
    locked_until: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    # True after an admin sets a password on the user's behalf; the login page then forces a
    # change before anything else is shown, so an admin-chosen password is never a standing one.
    must_change_password: Mapped[bool] = mapped_column(Boolean, server_default="false")
```

- [ ] **Step 14: Generate and apply the migration**

```bash
docker compose exec app alembic revision --autogenerate -m "user login security"
docker compose exec app alembic upgrade head
```

Open the generated file and confirm it contains exactly three `op.add_column` calls on `users` and nothing else. If autogenerate has swept in unrelated drift, delete those lines — this migration adds three columns and does nothing more.

- [ ] **Step 15: Verify the migration against the live database**

Run: `docker compose exec db psql -U lofc lofc -c "\d users"`
Expected: `failed_logins`, `locked_until` and `must_change_password` are present, and the existing rows are intact.

- [ ] **Step 16: Write the failing test for `set-password`**

Add to `tests/test_admin.py` (create the file if it does not exist):

```python
"""Tests for the user-administration CLI. Uses an in-memory sqlite database, so no live
Postgres and no network."""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from lofc import admin
from lofc.dashboard import auth
from lofc.store.models import Base, User


@pytest.fixture()
def engine():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine


def test_set_password_replaces_the_hash_and_forces_a_change(engine):
    with Session(engine) as session:
        session.add(User(username="jsmith", full_name="J. Smith", role="scout",
                         password_hash=auth.hash_password("original passphrase")))
        session.commit()

    admin.set_password(engine, "jsmith", "a replacement passphrase")

    with Session(engine) as session:
        user = session.scalar(select(User).where(User.username == "jsmith"))
        assert auth.verify_password("a replacement passphrase", user.password_hash)
        assert not auth.verify_password("original passphrase", user.password_hash)
        assert user.must_change_password is True


def test_set_password_clears_an_existing_lockout(engine):
    """An admin resetting a password is the documented way out of a lockout. If the reset
    left the lock in place, the user would still be locked out with a working password."""
    import datetime as dt
    with Session(engine) as session:
        session.add(User(username="jsmith", full_name="J. Smith", role="scout",
                         password_hash=auth.hash_password("original passphrase"),
                         failed_logins=5,
                         locked_until=dt.datetime(2099, 1, 1)))
        session.commit()

    admin.set_password(engine, "jsmith", "a replacement passphrase")

    with Session(engine) as session:
        user = session.scalar(select(User).where(User.username == "jsmith"))
        assert user.failed_logins == 0
        assert user.locked_until is None


def test_set_password_rejects_a_weak_password(engine):
    with Session(engine) as session:
        session.add(User(username="jsmith", full_name="J. Smith", role="scout",
                         password_hash=auth.hash_password("original passphrase")))
        session.commit()

    with pytest.raises(SystemExit):
        admin.set_password(engine, "jsmith", "short")


def test_set_password_rejects_an_unknown_user(engine):
    with pytest.raises(SystemExit):
        admin.set_password(engine, "nobody", "a perfectly fine passphrase")
```

- [ ] **Step 17: Run to verify they fail**

Run: `docker compose exec app pytest tests/test_admin.py -v`
Expected: FAIL — `AttributeError: module 'lofc.admin' has no attribute 'set_password'`

- [ ] **Step 18: Implement `set_password` and refactor `create_user` to take an engine**

In `src/lofc/admin.py`, change `create_user` to accept an engine (so it is testable on sqlite exactly as `set_password` is), and add `set_password`:

```python
def _engine():
    # hide_parameters: an IntegrityError from an insert would otherwise print the failing
    # statement's bound parameters -- including the salt and password hash -- to stderr.
    # Not plaintext, but there is no reason for either to appear in a terminal or log.
    return create_engine(settings.database_url, hide_parameters=True)


def create_user(engine, username: str, full_name: str, role: str, password: str) -> None:
    if role not in ROLES:
        raise SystemExit(f"unknown role {role!r}; expected one of {', '.join(ROLES)}")
    problems = password_problems(password)
    if problems:
        raise SystemExit("password rejected: " + "; ".join(problems))
    with Session(engine) as session:
        if session.scalar(select(User).where(User.username == username)):
            raise SystemExit(f"user {username!r} already exists")
        session.add(User(username=username, full_name=full_name, role=role,
                         password_hash=hash_password(password)))
        session.commit()
    print(f"created {role} {username!r}")


def set_password(engine, username: str, password: str) -> None:
    """Replace a user's password, clear any lockout, and require a change at next login.

    This is the ONLY password-reset route: the users table holds no email address, so there
    is no self-service reset and no token to send anywhere. An admin does this in person.
    """
    problems = password_problems(password)
    if problems:
        raise SystemExit("password rejected: " + "; ".join(problems))
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.username == username))
        if user is None:
            raise SystemExit(f"no such user {username!r}")
        user.password_hash = hash_password(password)
        user.failed_logins = 0
        user.locked_until = None
        user.must_change_password = True
        session.commit()
    print(f"password set for {username!r}; they must change it at next login")


def list_users(engine) -> None:
    """Print every account and its state. No hashes are printed."""
    with Session(engine) as session:
        users = session.scalars(select(User).order_by(User.username)).all()
    if not users:
        print("no users")
        return
    print(f"{'username':<16} {'name':<24} {'role':<20} {'active':<7} locked")
    for u in users:
        locked = u.locked_until.strftime("%Y-%m-%d %H:%M") if u.locked_until else "-"
        print(f"{u.username:<16} {u.full_name:<24} {u.role:<20} {str(u.is_active):<7} {locked}")
```

Update `main()` to wire the two new subcommands and pass `_engine()` into all three:

```python
def main() -> None:
    parser = argparse.ArgumentParser(description="Manage platform users")
    sub = parser.add_subparsers(dest="command", required=True)

    new = sub.add_parser("create-user")
    new.add_argument("--username", required=True)
    new.add_argument("--name", required=True)
    new.add_argument("--role", required=True, choices=ROLES)

    reset = sub.add_parser("set-password")
    reset.add_argument("--username", required=True)

    sub.add_parser("list-users")
    args = parser.parse_args()

    if args.command == "list-users":
        list_users(_engine())
        return

    if not sys.stdin.isatty():
        # Without a TTY, getpass degrades to echoing the password to the terminal (with a
        # warning) instead of hiding it -- refuse rather than display it.
        raise SystemExit("refusing to prompt for a password on a non-interactive stdin")
    password = getpass.getpass("password: ")
    if not password:
        raise SystemExit("empty password")

    if args.command == "create-user":
        create_user(_engine(), args.username, args.name, args.role, password)
    elif args.command == "set-password":
        set_password(_engine(), args.username, password)
```

Add `password_problems` to the existing `from lofc.dashboard.auth import ...` line.

- [ ] **Step 19: Run the admin tests**

Run: `docker compose exec app pytest tests/test_admin.py -v`
Expected: 4 passed

- [ ] **Step 20: Run the full suite**

Run: `docker compose exec app pytest -q`
Expected: 365 existing + 16 new = **381 passed**

- [ ] **Step 21: Commit**

```bash
git add src/lofc/dashboard/auth.py src/lofc/admin.py src/lofc/store/models.py \
        alembic/versions/ tests/test_auth.py tests/test_admin.py
git commit -m "auth: password strength, login throttle, session expiry, set-password CLI"
```

---

## Task 1: Login gate and session

**Files:**
- Create: `src/lofc/dashboard/session.py`
- Create: `src/lofc/store/users.py`
- Modify: `src/lofc/dashboard/app.py:55-70` (inside `main()`, immediately after `header()`)
- Test: `tests/test_session.py`, `tests/test_store_users.py`

**Interfaces:**
- Consumes: `auth.verify_password`, `auth.needs_rehash`, `auth.hash_password`, `auth.lockout_state`, `auth.next_failure_state`, `auth.session_expired`, `auth.password_problems`, `auth.can`.
- Produces:
  - `store.users.authenticate(engine, username: str, password: str, now: datetime) -> AuthResult`
  - `store.users.AuthResult` — frozen dataclass `(outcome: str, user_id: int | None, full_name: str | None, role: str | None, must_change_password: bool, seconds_locked: int)`; `outcome` ∈ `{"ok", "bad_credentials", "locked", "inactive"}`
  - `store.users.change_password(engine, user_id: int, new_password: str) -> None`
  - `session.CurrentUser` — frozen dataclass `(id: int, full_name: str, role: str)`
  - `session.require_login() -> CurrentUser | None` — renders the gate and returns `None` until authenticated
  - `session.current_user() -> CurrentUser | None`
  - `session.logout() -> None`

- [ ] **Step 1: Write the failing tests for `authenticate`**

Create `tests/test_store_users.py`:

```python
"""Authentication against the users table. In-memory sqlite; no live Postgres, no network."""

import datetime as dt

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from lofc.dashboard import auth
from lofc.store import users as store_users
from lofc.store.models import Base, User

NOW = dt.datetime(2026, 8, 14, 12, 0)
GOOD = "a perfectly fine passphrase"


@pytest.fixture()
def engine():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(User(username="jsmith", full_name="J. Smith", role="scout",
                         password_hash=auth.hash_password(GOOD)))
        session.commit()
    return engine


def test_authenticate_accepts_the_right_password(engine):
    result = store_users.authenticate(engine, "jsmith", GOOD, NOW)
    assert result.outcome == "ok"
    assert result.full_name == "J. Smith"
    assert result.role == "scout"


def test_authenticate_rejects_the_wrong_password(engine):
    result = store_users.authenticate(engine, "jsmith", "the wrong passphrase", NOW)
    assert result.outcome == "bad_credentials"
    assert result.user_id is None


def test_unknown_user_is_indistinguishable_from_a_wrong_password(engine):
    """Both must return the same outcome, or the login page becomes a way to enumerate who
    has an account."""
    unknown = store_users.authenticate(engine, "nobody", GOOD, NOW)
    wrong = store_users.authenticate(engine, "jsmith", "the wrong passphrase", NOW)
    assert unknown.outcome == wrong.outcome == "bad_credentials"


def test_failed_attempts_accumulate_on_the_row(engine):
    store_users.authenticate(engine, "jsmith", "wrong one", NOW)
    store_users.authenticate(engine, "jsmith", "wrong two", NOW)
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.username == "jsmith"))
        assert user.failed_logins == 2


def test_account_locks_after_the_limit_and_reports_locked(engine):
    for _ in range(auth.MAX_FAILED_LOGINS):
        store_users.authenticate(engine, "jsmith", "wrong", NOW)
    result = store_users.authenticate(engine, "jsmith", GOOD, NOW)
    assert result.outcome == "locked"
    assert result.seconds_locked > 0


def test_a_locked_account_rejects_even_the_correct_password(engine):
    """The whole point of the lock. If the right password still worked, an attacker who
    guessed it on attempt 6 would be let in regardless."""
    for _ in range(auth.MAX_FAILED_LOGINS):
        store_users.authenticate(engine, "jsmith", "wrong", NOW)
    assert store_users.authenticate(engine, "jsmith", GOOD, NOW).outcome == "locked"


def test_lock_expires_and_the_correct_password_then_works(engine):
    for _ in range(auth.MAX_FAILED_LOGINS):
        store_users.authenticate(engine, "jsmith", "wrong", NOW)
    later = NOW + dt.timedelta(minutes=auth.LOCKOUT_MINUTES + 1)
    assert store_users.authenticate(engine, "jsmith", GOOD, later).outcome == "ok"


def test_a_successful_login_clears_the_failure_counter(engine):
    store_users.authenticate(engine, "jsmith", "wrong", NOW)
    store_users.authenticate(engine, "jsmith", GOOD, NOW)
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.username == "jsmith"))
        assert user.failed_logins == 0
        assert user.locked_until is None


def test_an_inactive_user_cannot_log_in(engine):
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.username == "jsmith"))
        user.is_active = False
        session.commit()
    assert store_users.authenticate(engine, "jsmith", GOOD, NOW).outcome == "inactive"


def test_change_password_stores_a_new_hash_and_clears_the_must_change_flag(engine):
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.username == "jsmith"))
        user.must_change_password = True
        session.commit()
        user_id = user.id

    store_users.change_password(engine, user_id, "another fine passphrase")

    with Session(engine) as session:
        user = session.scalar(select(User).where(User.id == user_id))
        assert auth.verify_password("another fine passphrase", user.password_hash)
        assert user.must_change_password is False


def test_change_password_rejects_a_weak_password(engine):
    with Session(engine) as session:
        user_id = session.scalar(select(User).where(User.username == "jsmith")).id
    with pytest.raises(ValueError):
        store_users.change_password(engine, user_id, "short")
```

- [ ] **Step 2: Run to verify they fail**

Run: `docker compose exec app pytest tests/test_store_users.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lofc.store.users'`

- [ ] **Step 3: Implement `store/users.py`**

```python
"""Authentication against the users table.

USER DATA: nothing here is ever written or cleared by the pipeline.

Kept separate from `dashboard/auth.py` on purpose: `auth.py` holds pure cryptography and
permission rules with no database import, so it can be reasoned about and tested in
isolation. This module is the only place those rules meet a live row.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from lofc.dashboard.auth import (hash_password, lockout_state, needs_rehash,
                                 next_failure_state, password_problems, verify_password)
from lofc.store.models import User


@dataclass(frozen=True)
class AuthResult:
    """The outcome of one login attempt.

    `outcome` is one of:
      ok               -- authenticated; the identity fields are populated
      bad_credentials  -- wrong password OR no such user. Deliberately the SAME outcome for
                          both, so the login page cannot be used to discover who has an
                          account. Do not split these apart for a friendlier message.
      locked           -- too many recent failures; `seconds_locked` says for how long
      inactive         -- the account exists but has been deactivated
    """

    outcome: str
    user_id: int | None = None
    full_name: str | None = None
    role: str | None = None
    must_change_password: bool = False
    seconds_locked: int = 0


def authenticate(engine, username: str, password: str,
                 now: datetime.datetime) -> AuthResult:
    """Verify a username and password, maintaining the lockout counters on the row.

    `now` is passed in rather than read from the clock so the lockout behaviour is testable
    without sleeping.
    """
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.username == username))
        if user is None:
            # No row to update, but return the same outcome as a wrong password.
            return AuthResult("bad_credentials")

        locked, remaining = lockout_state(user.failed_logins, user.locked_until, now)
        if locked:
            # Checked BEFORE verifying, so a locked account rejects even a correct password
            # -- otherwise an attacker who guesses correctly on the attempt after the lock
            # is simply let in and the lock has achieved nothing.
            return AuthResult("locked", seconds_locked=remaining)

        if not verify_password(password, user.password_hash):
            user.failed_logins, user.locked_until = next_failure_state(user.failed_logins, now)
            session.commit()
            return AuthResult("bad_credentials")

        if not user.is_active:
            # Checked AFTER the password, so the message cannot tell an attacker holding a
            # wrong password that the account exists.
            return AuthResult("inactive")

        if needs_rehash(user.password_hash):
            # The plaintext is known-correct exactly here and nowhere else, so this is the
            # only point at which an old-parameter hash can be upgraded.
            user.password_hash = hash_password(password)
        user.failed_logins = 0
        user.locked_until = None
        session.commit()
        return AuthResult("ok", user_id=user.id, full_name=user.full_name, role=user.role,
                          must_change_password=user.must_change_password)


def change_password(engine, user_id: int, new_password: str) -> None:
    """Set a user's own password. Raises ValueError if it fails the strength rules."""
    problems = password_problems(new_password)
    if problems:
        raise ValueError("; ".join(problems))
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.id == user_id))
        if user is None:
            raise ValueError(f"no such user id {user_id}")
        user.password_hash = hash_password(new_password)
        user.must_change_password = False
        session.commit()
```

- [ ] **Step 4: Run to verify they pass**

Run: `docker compose exec app pytest tests/test_store_users.py -v`
Expected: 11 passed

- [ ] **Step 5: Write the failing tests for the session helpers**

Create `tests/test_session.py`:

```python
"""Session-state logic for the login gate. The Streamlit rendering is not tested -- these
cover the decisions the gate makes, which is where the behaviour actually lives."""

import datetime as dt

from lofc.dashboard import session as sess

NOW = dt.datetime(2026, 8, 14, 12, 0)


def test_restore_returns_none_for_an_empty_state():
    assert sess.restore_user({}, NOW) is None


def test_restore_returns_the_user_for_a_fresh_session():
    state = {"user_id": 3, "full_name": "J. Smith", "role": "scout", "logged_in_at": NOW}
    user = sess.restore_user(state, NOW)
    assert user == sess.CurrentUser(id=3, full_name="J. Smith", role="scout")


def test_restore_returns_none_for_an_expired_session():
    stale = NOW - dt.timedelta(minutes=sess.auth.SESSION_TTL_MINUTES + 1)
    state = {"user_id": 3, "full_name": "J. Smith", "role": "scout", "logged_in_at": stale}
    assert sess.restore_user(state, NOW) is None


def test_restore_returns_none_when_the_timestamp_is_missing():
    """A state carrying an identity but no timestamp is malformed, not a valid session."""
    state = {"user_id": 3, "full_name": "J. Smith", "role": "scout"}
    assert sess.restore_user(state, NOW) is None


def test_lockout_message_states_the_wait_in_whole_minutes():
    assert "15 minutes" in sess.lockout_message(15 * 60)


def test_lockout_message_rounds_a_part_minute_up():
    """Rounding down would tell a user to try again in 0 minutes and have it fail."""
    assert "1 minute" in sess.lockout_message(30)
```

- [ ] **Step 6: Run to verify they fail**

Run: `docker compose exec app pytest tests/test_session.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lofc.dashboard.session'`

- [ ] **Step 7: Implement `dashboard/session.py`**

```python
"""The login gate and the current-user session.

The decisions this module makes -- is a stored session still valid, what does a lockout say
-- are pure functions taking a plain dict and a clock, so they are unit-tested without
Streamlit. `require_login` is the only Streamlit-aware function here, and it is a thin
render layer over them.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

import streamlit as st

from lofc.dashboard import auth
from lofc.store import users as store_users


@dataclass(frozen=True)
class CurrentUser:
    """Who is logged in. `role` is a RECORD of who acted, not a restriction on assessing --
    every role may assess both dimensions (Decision 16). Ask `auth.can()` before any gated
    action; never compare `role` to a literal in page code."""

    id: int
    full_name: str
    role: str


def restore_user(state, now: datetime.datetime) -> CurrentUser | None:
    """The logged-in user held in `state`, or None if there is none or it has expired.

    `state` is any mapping (Streamlit's session_state, or a plain dict in tests).
    """
    user_id = state.get("user_id")
    if user_id is None:
        return None
    if auth.session_expired(state.get("logged_in_at"), now):
        return None
    return CurrentUser(id=user_id, full_name=state["full_name"], role=state["role"])


def lockout_message(seconds: int) -> str:
    """The user-facing wait. Rounded UP: telling someone to wait 0 minutes and having the
    next attempt fail is worse than overstating by 30 seconds."""
    minutes = max(1, -(-seconds // 60))
    unit = "minute" if minutes == 1 else "minutes"
    return (f"Too many failed attempts. This account is locked for {minutes} {unit}. "
            "An administrator can reset it sooner.")


def logout() -> None:
    for key in ("user_id", "full_name", "role", "logged_in_at"):
        st.session_state.pop(key, None)


def _password_change_form(user_id: int, engine) -> None:
    st.warning("Your password was set by an administrator. Choose a new one to continue.")
    with st.form("change_password"):
        first = st.text_input("New password", type="password")
        second = st.text_input("Confirm new password", type="password")
        submitted = st.form_submit_button("Set password", type="primary")
    if not submitted:
        return
    if first != second:
        st.error("The two passwords do not match.")
        return
    try:
        store_users.change_password(engine, user_id, first)
    except ValueError as exc:
        st.error(f"Password rejected: {exc}")
        return
    st.session_state["must_change_password"] = False
    st.rerun()


def require_login(engine) -> CurrentUser | None:
    """Render the login gate. Returns the user once authenticated, None until then.

    The caller renders nothing else while this returns None -- that is what makes it a gate
    rather than a banner.
    """
    now = datetime.datetime.now()
    user = restore_user(st.session_state, now)

    if user is not None and st.session_state.get("must_change_password"):
        _password_change_form(user.id, engine)
        return None
    if user is not None:
        return user
    if st.session_state.get("user_id") is not None:
        # Had a session, and restore_user rejected it -- it expired. Clear it so the stale
        # identity cannot linger in state behind the login form.
        logout()
        st.info("Your session has expired. Please sign in again.")

    left, _ = st.columns([1, 1])
    with left:
        st.subheader("Sign in")
        with st.form("login"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", type="primary")
        if submitted:
            result = store_users.authenticate(engine, username, password, now)
            if result.outcome == "ok":
                st.session_state.update({
                    "user_id": result.user_id, "full_name": result.full_name,
                    "role": result.role, "logged_in_at": now,
                    "must_change_password": result.must_change_password})
                st.rerun()
            elif result.outcome == "locked":
                st.error(lockout_message(result.seconds_locked))
            elif result.outcome == "inactive":
                st.error("This account has been deactivated. Contact an administrator.")
            else:
                st.error("Incorrect username or password.")
        st.caption("Accounts are created by an administrator. There is no self-service "
                   "sign-up and no email reset — ask an administrator to reset a "
                   "forgotten password.")
    return None


def sidebar_identity(user: CurrentUser) -> None:
    """Show who is signed in, and the logout control."""
    st.sidebar.markdown(f"**{user.full_name}**  \n`{user.role}`")
    st.sidebar.button("Sign out", on_click=logout, use_container_width=True)
    st.sidebar.divider()
```

- [ ] **Step 8: Run to verify they pass**

Run: `docker compose exec app pytest tests/test_session.py -v`
Expected: 6 passed

- [ ] **Step 9: Wire the gate into `app.py`**

In `src/lofc/dashboard/app.py`, inside `main()`, immediately after the existing `header()` call, insert:

```python
    user = require_login(get_engine())
    if user is None:
        return          # the gate renders the form; nothing else on the page exists yet
    sidebar_identity(user)
```

Add to the imports:

```python
from lofc.dashboard.loaders import get_engine
from lofc.dashboard.session import require_login, sidebar_identity
```

(`get_engine` may already be imported via another name in that block — check before adding a duplicate.)

- [ ] **Step 10: Create a test account and confirm the gate works end to end**

```bash
docker compose exec app python -m lofc.admin create-user \
    --username testscout --name "Test Scout" --role scout
docker compose restart dashboard
```

Open http://localhost:8501. Expected: the login form and nothing else — no tabs, no sidebar filters, no player data. Sign in with the test account. Expected: the dashboard renders as before, with the name and role in the sidebar. Click **Sign out**. Expected: back to the login form.

- [ ] **Step 11: Run the full suite**

Run: `docker compose exec app pytest -q`
Expected: **398 passed** (381 + 17)

- [ ] **Step 12: Commit**

```bash
git add src/lofc/store/users.py src/lofc/dashboard/session.py src/lofc/dashboard/app.py \
        tests/test_store_users.py tests/test_session.py
git commit -m "dashboard: login gate, session expiry and sidebar identity"
```

---

## Task 2: The evidence panel

The §6 panel. Written **once** and called from the player profile and the assessment form, so the two can never show different numbers for the same player.

**Files:**
- Create: `src/lofc/store/injuries.py`
- Create: `src/lofc/dashboard/evidence.py`
- Test: `tests/test_store_injuries.py`, `tests/test_evidence.py`

**Interfaces:**
- Consumes: `medical.games_missed_in_window`, `medical.availability_with_evidence`, `medical.window_labels`, `medical.AvailabilityStatus`, `medical.SCHEDULED_GAMES`, `medical.AVAILABILITY_SEASONS`.
- Produces:
  - `store.injuries.load_for_player(engine, player_id: int) -> pd.DataFrame`
  - `store.injuries.COVERAGE: dict[int, dict[str, float]]` — per `competition_id`, `{"linked": float, "with_record": float, "knowable": float | None}`
  - `evidence.coverage_caption(competition_id: int) -> str`
  - `evidence.availability_caption(ev: AvailabilityEvidence, window: tuple[str, ...]) -> str`
  - `evidence.spell_rows(injuries: pd.DataFrame, window: tuple[str, ...]) -> pd.DataFrame` — adds an `in_window` bool column
  - `evidence.render(engine, player_id, competition_id, season_id, minutes_played) -> None`

- [ ] **Step 1: Write the failing tests for the spell table**

Create `tests/test_evidence.py`:

```python
"""The evidence panel's pure logic: which spells count, what each caption says. The Streamlit
rendering is not tested; every decision the panel makes lives in these functions."""

import pandas as pd
import pytest

from lofc.dashboard import evidence
from lofc.model.medical import AvailabilityEvidence, AvailabilityStatus

WINDOW = ("24/25", "25/26")


def _spells(*rows) -> pd.DataFrame:
    return pd.DataFrame(list(rows), columns=["season_label", "injury_type_raw",
                                             "injury_category", "date_from", "date_until",
                                             "days_out", "games_missed", "source"])


def test_spell_rows_marks_in_window_spells():
    frame = evidence.spell_rows(
        _spells(("25/26", "Ankle injury", "ankle", "2025-10-01", "2025-12-01", 61, 9,
                 "transfermarkt")), WINDOW)
    assert frame["in_window"].tolist() == [True]


def test_spell_rows_keeps_out_of_window_spells_and_marks_them():
    """Shown greyed, never hidden -- a scout wants the history even when the figure does not
    count it (spec section 6, point 3)."""
    frame = evidence.spell_rows(
        _spells(("22/23", "Broken leg", "leg", "2022-09-01", "2023-02-01", 153, 22,
                 "transfermarkt")), WINDOW)
    assert len(frame) == 1
    assert frame["in_window"].tolist() == [False]


def test_spell_rows_handles_an_empty_history():
    frame = evidence.spell_rows(_spells(), WINDOW)
    assert frame.empty
    assert "in_window" in frame.columns


def test_spell_rows_preserves_provenance():
    frame = evidence.spell_rows(
        _spells(("25/26", "Knock", "other", "2025-10-01", "2025-10-08", 7, 1, "manual")),
        WINDOW)
    assert frame["source"].tolist() == ["manual"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `docker compose exec app pytest tests/test_evidence.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lofc.dashboard.evidence'`

- [ ] **Step 3: Write the failing tests for the captions**

Append to `tests/test_evidence.py`:

```python
def test_availability_caption_says_measured_with_the_window():
    ev = AvailabilityEvidence(status=AvailabilityStatus.MEASURED, value=0.87)
    caption = evidence.availability_caption(ev, WINDOW)
    assert "87%" in caption
    assert "24/25" in caption and "25/26" in caption


def test_availability_caption_for_unknown_never_says_clean():
    """The single most important line on the panel. A blank record must never read as a
    perfect one -- that is defect R8, and this caption is what closes it on screen."""
    ev = AvailabilityEvidence(status=AvailabilityStatus.UNKNOWN, value=None)
    caption = evidence.availability_caption(ev, WINDOW)
    assert "Not known" in caption
    assert "100%" not in caption
    assert "1.0" not in caption


def test_availability_caption_for_confirmed_by_minutes_says_why():
    ev = AvailabilityEvidence(status=AvailabilityStatus.CONFIRMED_BY_MINUTES, value=1.0)
    caption = evidence.availability_caption(ev, WINDOW)
    assert "minutes" in caption.lower()


def test_availability_caption_for_measured_but_unscored_league_explains_itself():
    """MEASURED with value None means the league has no scheduled-games constant -- there IS
    injury evidence, but no denominator. Distinct from UNKNOWN, and must not read as it."""
    ev = AvailabilityEvidence(status=AvailabilityStatus.MEASURED, value=None)
    caption = evidence.availability_caption(ev, WINDOW)
    assert "not scored" in caption.lower()
    assert "Not known" not in caption


def test_coverage_caption_names_the_league_share():
    caption = evidence.coverage_caption(4)          # League One
    assert "39%" in caption


def test_coverage_caption_for_a_thin_league_is_blunt():
    caption = evidence.coverage_caption(65)         # National League
    assert "18%" in caption


def test_coverage_caption_handles_an_unmapped_competition():
    caption = evidence.coverage_caption(999999)
    assert caption
    assert "no coverage figure" in caption.lower()
```

- [ ] **Step 4: Run to verify they fail**

Run: `docker compose exec app pytest tests/test_evidence.py -k caption -v`
Expected: FAIL — module still missing

- [ ] **Step 5: Write the failing test for the injury loader**

Create `tests/test_store_injuries.py`:

```python
"""Reading a player's injury history. In-memory sqlite; no live Postgres."""

import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from lofc.store import injuries as store_injuries
from lofc.store.models import Base, Player, PlayerInjury


@pytest.fixture()
def engine():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Player(player_id=1, player_name="A Player"))
        session.add(PlayerInjury(player_id=1, season_label="25/26",
                                 injury_type_raw="Ankle injury", injury_category="ankle",
                                 date_from=dt.date(2025, 10, 1),
                                 date_until=dt.date(2025, 12, 1),
                                 days_out=61, games_missed=9, source="transfermarkt"))
        session.add(PlayerInjury(player_id=1, season_label="24/25",
                                 injury_type_raw="Knock", injury_category="other",
                                 date_from=dt.date(2024, 9, 1),
                                 date_until=dt.date(2024, 9, 8),
                                 days_out=7, games_missed=1, source="manual"))
        session.commit()
    return engine


def test_load_for_player_returns_every_spell(engine):
    frame = store_injuries.load_for_player(engine, 1)
    assert len(frame) == 2


def test_load_for_player_orders_newest_first(engine):
    frame = store_injuries.load_for_player(engine, 1)
    assert frame["date_from"].tolist()[0] == dt.date(2025, 10, 1)


def test_load_for_player_returns_an_empty_frame_with_columns_for_no_injuries(engine):
    """An empty frame must still carry its columns: availability_with_evidence and the panel
    both index into them, and a bare DataFrame() would raise KeyError instead of showing
    'not known'."""
    frame = store_injuries.load_for_player(engine, 99999)
    assert frame.empty
    for column in ("season_label", "injury_category", "games_missed", "source"):
        assert column in frame.columns
```

- [ ] **Step 6: Run to verify it fails**

Run: `docker compose exec app pytest tests/test_store_injuries.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lofc.store.injuries'`

- [ ] **Step 7: Implement `store/injuries.py`**

```python
"""Reading injury spells for the evidence panel, and the per-league coverage figures that
say how much a blank record is worth.

Plain SQLAlchemy Core so this runs identically on production Postgres and the sqlite used
in tests, matching `store/watchlist.py`.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import select

from lofc.store.models import PlayerInjury

_TABLE = PlayerInjury.__table__

_COLUMNS = ["id", "player_id", "season_label", "injury_type_raw", "injury_category",
            "date_from", "date_until", "days_out", "games_missed", "source", "entered_by"]

# Decision 12 / spec section 10, point 3. Measured on live data 2026-08-14.
#   linked       -- share of the league's players matched to a Transfermarkt profile at all
#   with_record  -- share that have at least one injury row
#   knowable     -- share whose availability can be established either way, once minutes
#                   played is used as the independent cross-check. None where it was not
#                   measured for that league.
# These are DISPLAY figures. Nothing in scoring reads them -- Decision 12 removed the
# automatic Medical band precisely because these numbers make it unsound.
COVERAGE: dict[int, dict[str, float | None]] = {
    3:  {"linked": 0.98, "with_record": 0.74, "knowable": 0.84},   # Championship
    4:  {"linked": 0.95, "with_record": 0.39, "knowable": 0.64},   # League One
    5:  {"linked": 0.96, "with_record": 0.32, "knowable": 0.58},   # League Two
    65: {"linked": 0.92, "with_record": 0.18, "knowable": 0.49},   # National League
}


def load_for_player(engine, player_id: int) -> pd.DataFrame:
    """Every recorded spell for one player, newest first.

    Returns an empty frame WITH the full column set when there are none: the caller indexes
    into these columns to decide between "no injuries" and "not known", and a bare empty
    frame would raise KeyError instead of rendering that distinction.
    """
    query = (select(*[_TABLE.c[name] for name in _COLUMNS])
             .where(_TABLE.c.player_id == player_id)
             .order_by(_TABLE.c.date_from.desc(), _TABLE.c.id.desc()))
    with engine.connect() as conn:
        frame = pd.DataFrame(conn.execute(query).fetchall(), columns=_COLUMNS)
    return frame
```

- [ ] **Step 8: Run to verify it passes**

Run: `docker compose exec app pytest tests/test_store_injuries.py -v`
Expected: 3 passed

- [ ] **Step 9: INVOKE THE FRONTEND DESIGN SKILL**

Before writing any of `evidence.py`'s rendering, invoke the frontend design skill and follow it for this panel's layout. Spec §16 makes this a requirement of the spec, not a preference. The panel must satisfy:

- the availability figure first, its caveat **immediately beside it**, never in a footer
- the coverage warning adjacent to the availability figure, not at the bottom of the page
- the injury table dense but scannable; out-of-window spells greyed, present, not hidden
- provenance (scraped vs hand-entered) visible per row
- no status conveyed by colour alone

- [ ] **Step 10: Implement `dashboard/evidence.py`**

```python
"""The injury and availability evidence panel (spec section 6).

Rendered in TWO places -- the player profile and the assessment form -- from this one
module, so the two can never disagree about a player. Every figure here is evidence for a
human to weigh; Decision 12 means none of it is summed, weighted, or mapped into a score.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from lofc.model.medical import (AVAILABILITY_SEASONS, AvailabilityEvidence,
                                AvailabilityStatus, availability_with_evidence,
                                games_missed_in_window, window_labels)
from lofc.store.injuries import COVERAGE, load_for_player


def spell_rows(injuries: pd.DataFrame, window: tuple[str, ...]) -> pd.DataFrame:
    """Every spell with an `in_window` flag saying whether it counts towards the figure.

    Out-of-window spells are RETAINED, flagged False, and greyed by the caller -- never
    filtered out. A scout wants a player's history even where the current figure ignores it.
    """
    frame = injuries.copy()
    if frame.empty:
        frame["in_window"] = pd.Series(dtype=bool)
        return frame
    frame["in_window"] = frame["season_label"].isin(window)
    return frame


def availability_caption(ev: AvailabilityEvidence, window: tuple[str, ...]) -> str:
    """The one-line caption that must sit beside the availability figure.

    The UNKNOWN wording is the fix for defect R8 on screen: a player Transfermarkt never
    tracked must never read as a player who was never injured.
    """
    seasons = " and ".join(window)
    if ev.status is AvailabilityStatus.UNKNOWN:
        return ("**Not known.** No injury record for this player, and his minutes do not "
                "confirm availability either way. This is a gap in the data, not a clean "
                "record.")
    if ev.status is AvailabilityStatus.CONFIRMED_BY_MINUTES:
        return ("**Available.** No injury record, but his minutes played rule out a long "
                "absence — an independent check that does not depend on injury reporting.")
    if ev.value is None:
        return ("Injury record present, but availability is **not scored** for this "
                "competition — no fixture count is configured for it.")
    return (f"**{ev.value:.0%}** of matches available across {seasons}. "
            "Counts matches missed through injury only — a fit player who was not selected "
            "is not penalised.")


def coverage_caption(competition_id: int) -> str:
    """How much an empty injury record is worth in THIS player's league (spec section 10.3).

    Sits beside the availability figure, never in a footer: a blank record in the
    Championship and a blank record in the National League are different statements and
    must not look identical.
    """
    figures = COVERAGE.get(competition_id)
    if figures is None:
        return ("We hold **no coverage figure** for this competition, so an empty injury "
                "record here says nothing either way.")
    with_record = f"{figures['with_record']:.0%}"
    knowable = figures.get("knowable")
    line = (f"In this league **{with_record}** of players have any injury record at all, "
            "so an empty record often means we have nothing rather than that nothing "
            "happened.")
    if knowable is not None:
        line += (f" Counting minutes played as a cross-check, availability is establishable "
                 f"for about **{knowable:.0%}** of players here.")
    return line


def render(engine, player_id: int, competition_id: int, season_id: int,
           minutes_played: int | None) -> None:
    """Draw the panel. Read-only everywhere it appears."""
    injuries = load_for_player(engine, player_id)
    window = window_labels(season_id)
    missed = games_missed_in_window(injuries, season_id)
    ev = availability_with_evidence(injuries, missed, competition_id, minutes_played,
                                    seasons=AVAILABILITY_SEASONS, minutes_seasons=1)

    st.markdown("#### Availability and injury record")

    figure = "—" if ev.value is None else f"{ev.value:.0%}"
    left, middle, right = st.columns([1, 1, 2])
    left.metric("Availability", figure)
    middle.metric("Matches missed", missed if not injuries.empty else "—")
    right.metric("Minutes played", f"{minutes_played:,}" if minutes_played else "—")

    # Both captions sit HERE, beside the figures they qualify -- not in a page footer.
    st.caption(availability_caption(ev, window))
    st.caption(coverage_caption(competition_id))

    spells = spell_rows(injuries, window)
    if spells.empty:
        st.info("No injury spells on record for this player.")
        return

    display = spells.assign(
        Window=spells["in_window"].map({True: "In window", False: "Outside window"}),
        Source=spells["source"].map({"transfermarkt": "Scraped",
                                     "manual": "Entered by hand"}).fillna(spells["source"]),
    )[["season_label", "injury_type_raw", "injury_category", "date_from", "date_until",
       "days_out", "games_missed", "Window", "Source"]]
    display.columns = ["Season", "Injury", "Category", "From", "Until", "Days out",
                       "Matches missed", "Window", "Source"]

    def _grey(row):
        # Words carry the meaning (the Window column); the grey only reinforces it.
        faded = "color:#9a9a9a;" if row["Window"] == "Outside window" else ""
        return [faded] * len(row)

    st.dataframe(display.style.apply(_grey, axis=1), use_container_width=True,
                 hide_index=True)
    st.caption("Spells outside the two-season window are shown greyed — they are part of "
               "the player's history but do not count towards the figure above.")
```

- [ ] **Step 11: Run the evidence tests**

Run: `docker compose exec app pytest tests/test_evidence.py -v`
Expected: 11 passed

- [ ] **Step 12: Verify the caption logic against a real player**

```bash
docker compose exec app python -c "
from lofc.dashboard.loaders import get_engine
from lofc.dashboard.evidence import availability_caption, coverage_caption
from lofc.store.injuries import load_for_player
from lofc.model.medical import games_missed_in_window, availability_with_evidence, window_labels
e = get_engine()
inj = load_for_player(e, 3516)
missed = games_missed_in_window(inj, 318)
ev = availability_with_evidence(inj, missed, 4, None, minutes_seasons=1)
print('spells:', len(inj), 'missed:', missed, ev)
print(availability_caption(ev, window_labels(318)))
print(coverage_caption(4))
"
```

Expected: the caption matches the status, and no output claims a clean record where the status is UNKNOWN.

- [ ] **Step 13: Run the full suite**

Run: `docker compose exec app pytest -q`
Expected: **412 passed** (398 + 14)

- [ ] **Step 14: Commit**

```bash
git add src/lofc/store/injuries.py src/lofc/dashboard/evidence.py \
        tests/test_store_injuries.py tests/test_evidence.py
git commit -m "dashboard: the injury and availability evidence panel"
```

---

## Task 3: Assessment rules and storage

The pure logic and the database layer for assessments, built and tested **before** any form exists. Doing it this way means every scoring rule — the Psychological mean, what makes an assessment complete, when the screening flag raises — is verified without touching Streamlit.

**Files:**
- Create: `src/lofc/model/assessment_rules.py`
- Create: `src/lofc/store/assessments.py`
- Test: `tests/test_assessment_rules.py`, `tests/test_store_assessments.py`

**Interfaces:**
- Consumes: `club_criteria.PSYCHOLOGICAL_CRITERIA`, `club_criteria.MEDICAL_CRITERIA`, `club_criteria.MedicalCriterion`, `club_criteria.POSITION_GROUPS`, `scout_scores.PSYCHOLOGICAL`, `scout_scores.MEDICAL`.
- Produces:
  - `assessment_rules.criterion_key(text: str) -> str` — stable slug for a criterion's stored key
  - `assessment_rules.psychological_band(scores: dict[str, int], position: str) -> float | None`
  - `assessment_rules.psychological_status(scores, position) -> str` — `"draft"` or `"submitted"`
  - `assessment_rules.screening_failed(passes: dict[str, bool], position: str) -> bool`
  - `assessment_rules.medical_status(band, passes, position) -> str`
  - `assessment_rules.MEDICAL_CEILING_NOTE: str`
  - `assessment_rules.BAND_LABELS: dict[int, str]`
  - `store.assessments.save(engine, *, player_id, competition_id, season_id, dimension, author_id, band, notes, criterion_scores, criterion_passes, screening_failed, status) -> int`
  - `store.assessments.load_for_player(engine, player_id, competition_id, season_id) -> pd.DataFrame`
  - `store.assessments.load_all(engine) -> pd.DataFrame` — the frame `scout_scores.resolve_bands` consumes
  - `store.assessments.pending_signoff(engine) -> pd.DataFrame`
  - `store.assessments.sign_off(engine, assessment_id: int, approver_id: int, now) -> None`
  - `store.assessments.criterion_scores_for(engine, assessment_id: int) -> pd.DataFrame`

- [ ] **Step 1: Write the failing tests for the Psychological band**

Create `tests/test_assessment_rules.py`:

```python
"""The scoring rules behind an assessment. Pure functions -- no database, no Streamlit.

These are the rules a reviewer must be able to check without running the app: what the
Psychological band is, when an assessment is complete enough to score, and when the
screening flag raises.
"""

import pytest

from lofc.model import assessment_rules as rules
from lofc.model import club_criteria as cc


def _all_psych(position: str, score: int) -> dict[str, int]:
    return {rules.criterion_key(text): score
            for text in cc.PSYCHOLOGICAL_CRITERIA[position]}


def test_psychological_band_is_the_equal_weighted_mean():
    """Decision 8: equal weights, no criterion counts more than another."""
    scores = _all_psych("Centre Back", 4)
    assert rules.psychological_band(scores, "Centre Back") == 4.0


def test_psychological_band_averages_mixed_scores():
    keys = [rules.criterion_key(t) for t in cc.PSYCHOLOGICAL_CRITERIA["Goalkeeper"]]
    scores = dict(zip(keys, [5, 3, 1]))          # Goalkeeper has exactly 3 criteria
    assert rules.psychological_band(scores, "Goalkeeper") == 3.0


def test_psychological_band_is_none_when_a_criterion_is_unscored():
    """Spec section 5: all of the position's criteria must be scored or it stays a draft.
    Averaging over only the answered ones would let a scout raise a band by skipping the
    criteria the player is weak on."""
    scores = _all_psych("Centre Back", 4)
    scores.pop(next(iter(scores)))
    assert rules.psychological_band(scores, "Centre Back") is None


def test_psychological_band_ignores_criteria_that_are_not_the_positions():
    """A stale key left over from a different position must not enter the mean."""
    scores = _all_psych("Goalkeeper", 3)
    scores["not-a-goalkeeper-criterion"] = 5
    assert rules.psychological_band(scores, "Goalkeeper") == 3.0


def test_psychological_band_raises_for_an_unknown_position():
    """Spec section 18: an unknown position group blocks assessment with a clear message --
    never scored against no criteria."""
    with pytest.raises(KeyError):
        rules.psychological_band({}, "Sweeper Keeper")


def test_psychological_status_is_draft_when_incomplete():
    scores = _all_psych("Winger", 3)
    scores.pop(next(iter(scores)))
    assert rules.psychological_status(scores, "Winger") == "draft"


def test_psychological_status_is_submitted_when_complete():
    assert rules.psychological_status(_all_psych("Winger", 3), "Winger") == "submitted"


def test_criterion_key_is_stable_and_slug_like():
    key = rules.criterion_key("Composure under pressure; calm decision-making in own box")
    assert key == rules.criterion_key("Composure under pressure; calm decision-making in own box")
    assert " " not in key


def test_criterion_key_distinguishes_the_two_full_back_hamstring_bullets():
    """Full Back carries two distinct hamstring criteria. If the key collapsed them, one
    would silently overwrite the other's answer."""
    texts = [c.text for c in cc.MEDICAL_CRITERIA["Full Back"] if "hamstring" in c.text]
    assert len(texts) == 2
    assert rules.criterion_key(texts[0]) != rules.criterion_key(texts[1])
```

- [ ] **Step 2: Run to verify they fail**

Run: `docker compose exec app pytest tests/test_assessment_rules.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lofc.model.assessment_rules'`

- [ ] **Step 3: Write the failing tests for the medical rules**

Append to `tests/test_assessment_rules.py`:

```python
def _screening_keys(position: str) -> list[str]:
    return [rules.criterion_key(c.text)
            for c in cc.MEDICAL_CRITERIA[position] if c.kind == "screening"]


def test_screening_failed_is_false_when_all_pass():
    passes = {key: True for key in _screening_keys("Centre Back")}
    assert rules.screening_failed(passes, "Centre Back") is False


def test_screening_failed_is_true_when_any_fails():
    keys = _screening_keys("Centre Back")
    passes = {key: True for key in keys}
    passes[keys[0]] = False
    assert rules.screening_failed(passes, "Centre Back") is True


def test_screening_failed_ignores_protocol_and_availability_criteria():
    """Decision 7: only `screening` criteria are pass/fail. A protocol step ('undergo MRI
    scan') is a club process, not a player attribute, and must never raise the flag."""
    protocol = [rules.criterion_key(c.text)
                for c in cc.MEDICAL_CRITERIA["Goalkeeper"] if c.kind == "protocol"]
    assert protocol
    passes = {key: True for key in _screening_keys("Goalkeeper")}
    passes[protocol[0]] = False
    assert rules.screening_failed(passes, "Goalkeeper") is False


def test_screening_failure_does_not_change_the_band():
    """Decision 13, the single most important rule in this module. A failed screening
    criterion WARNS. The platform never overwrites a qualified human's number -- if this
    test ever fails, the reversal of Decision 13 has been silently reintroduced."""
    keys = _screening_keys("Centre Back")
    passes = {key: True for key in keys}
    passes[keys[0]] = False
    status = rules.medical_status(4.0, passes, "Centre Back")
    assert status == "submitted"
    assert rules.screening_failed(passes, "Centre Back") is True


def test_medical_status_is_draft_without_a_band():
    passes = {key: True for key in _screening_keys("Centre Back")}
    assert rules.medical_status(None, passes, "Centre Back") == "draft"


def test_medical_status_is_draft_when_a_screening_criterion_is_unanswered():
    keys = _screening_keys("Centre Back")
    passes = {key: True for key in keys[:-1]}
    assert rules.medical_status(3.0, passes, "Centre Back") == "draft"


def test_medical_ceiling_note_explains_why_three_is_the_practical_ceiling():
    note = rules.MEDICAL_CEILING_NOTE
    assert "elite" in note.lower()
    assert "3" in note


def test_band_labels_are_the_clubs_own_wording():
    assert rules.BAND_LABELS == {1: "Unacceptable", 2: "Below Standard",
                                 3: "Meets Standard", 4: "Above Standard", 5: "Elite"}
```

- [ ] **Step 4: Run to verify they fail**

Run: `docker compose exec app pytest tests/test_assessment_rules.py -v`
Expected: FAIL — module still missing

- [ ] **Step 5: Implement `model/assessment_rules.py`**

```python
"""The scoring rules for a scout assessment. Pure -- no database, no Streamlit.

Two dimensions, two very different rules:

  Psychological -- the equal-weighted mean of the club's criteria for the player's position
                   (Decision 8). Every criterion must be scored, or it stays a draft.
  Medical       -- NO FORMULA (Decision 12). A person enters the band with the injury
                   evidence in front of them. The screening checklist WARNS and never
                   changes that number (Decision 13).
"""

from __future__ import annotations

import re

from lofc.model import club_criteria as cc

# The club's own 1-5 rubric, verbatim. Not invented here and not to be reworded.
BAND_LABELS: dict[int, str] = {
    1: "Unacceptable",
    2: "Below Standard",
    3: "Meets Standard",
    4: "Above Standard",
    5: "Elite",
}

# Shown next to the Medical input. The club's metric tables carry both a "Minimum Standard"
# and an "Elite Threshold" column; Medical & Durability lists minimum requirements only. So
# 4 and 5 have nothing to be measured against. The form SAYS this rather than clamping the
# value -- the ceiling is a consequence of the club's rubric, not a rule the platform imposes.
MEDICAL_CEILING_NOTE = (
    "The club defines minimum medical requirements but no elite threshold, so 4 and 5 have "
    "nothing to be scored against — in practice 3 is the ceiling here. You may still enter "
    "4 or 5; nothing is capped."
)


def criterion_key(text: str) -> str:
    """A stable storage key for one criterion.

    Derived from the criterion's own wording so it survives a reordering of the club's lists,
    which a positional index would not. Kept long enough to stay unique: Full Back carries
    two hamstring criteria whose openings match, and collapsing them would let one silently
    overwrite the other's answer.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:120]


def _psych_keys(position: str) -> list[str]:
    return [criterion_key(t) for t in cc.PSYCHOLOGICAL_CRITERIA[position]]


def _screening_keys(position: str) -> list[str]:
    return [criterion_key(c.text)
            for c in cc.MEDICAL_CRITERIA[position] if c.kind == "screening"]


def psychological_band(scores: dict[str, int], position: str) -> float | None:
    """The equal-weighted mean of this position's criteria, or None if any is unscored.

    Raises KeyError for an unknown position -- spec section 18 requires assessment to be
    BLOCKED with a clear message rather than scored against no criteria, and returning None
    here would be indistinguishable from an incomplete form.

    Keys not belonging to this position are ignored, so a stale answer left over from a
    different position group cannot enter the mean.
    """
    keys = _psych_keys(position)
    answered = [scores[key] for key in keys if scores.get(key) is not None]
    if len(answered) != len(keys):
        return None
    return sum(answered) / len(answered)


def psychological_status(scores: dict[str, int], position: str) -> str:
    """`submitted` once every criterion is scored, `draft` until then."""
    return "draft" if psychological_band(scores, position) is None else "submitted"


def screening_failed(passes: dict[str, bool], position: str) -> bool:
    """True if any `screening` criterion was marked failed.

    Only `screening` criteria count (Decision 7): an `availability` criterion is a computed
    figure shown as evidence, and a `protocol` criterion ("undergo MRI scan") is a club
    process step rather than a player attribute. Neither can raise this flag.

    Unanswered criteria are NOT failures -- an incomplete form is a draft, which
    `medical_status` handles; treating a blank as a failure would flag every half-filled form.
    """
    return any(passes.get(key) is False for key in _screening_keys(position))


def medical_status(band: float | None, passes: dict[str, bool], position: str) -> str:
    """`submitted` once a band is entered and every screening criterion is answered.

    DECISION 13: a failed screening criterion does NOT change the returned status and does
    NOT cap the band. It raises `screening_failed`, which the form, the profile and the
    export all show prominently -- and the assessor's number stands. The platform never
    overrules the better-informed party; it surfaces the disagreement instead.
    """
    if band is None:
        return "draft"
    keys = _screening_keys(position)
    if any(passes.get(key) is None for key in keys):
        return "draft"
    return "submitted"
```

- [ ] **Step 6: Run to verify they pass**

Run: `docker compose exec app pytest tests/test_assessment_rules.py -v`
Expected: 17 passed

- [ ] **Step 7: Mutation-test Decision 13**

Temporarily edit `medical_status` so a screening failure returns `"draft"`, and separately so it caps the band at 2.0. Run `docker compose exec app pytest tests/test_assessment_rules.py -q` after each.

Expected: `test_screening_failure_does_not_change_the_band` FAILS both times. If it passes, the test is not pinning Decision 13 and must be strengthened before proceeding. **Revert both mutations.**

- [ ] **Step 8: Write the failing tests for assessment storage**

Create `tests/test_store_assessments.py`:

```python
"""Reading and writing assessments. In-memory sqlite; no live Postgres, no network."""

import datetime as dt

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from lofc.model import scout_scores
from lofc.store import assessments as store_assess
from lofc.store.models import Base, Player, ScoutAssessment, ScoutCriterionScore, User

NOW = dt.datetime(2026, 8, 14, 12, 0)


@pytest.fixture()
def engine():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Player(player_id=1, player_name="A Player"))
        session.add(User(id=1, username="scout1", full_name="Scout One", role="scout",
                         password_hash="x"))
        session.add(User(id=2, username="hor", full_name="Head Of Rec",
                         role="head_of_recruitment", password_hash="x"))
        session.commit()
    return engine


def _save(engine, **overrides):
    kwargs = dict(player_id=1, competition_id=4, season_id=318,
                  dimension=scout_scores.PSYCHOLOGICAL, author_id=1, band=4.0,
                  notes="solid character", criterion_scores={"composure": 4},
                  criterion_passes={}, screening_failed=False, status="submitted")
    kwargs.update(overrides)
    return store_assess.save(engine, **kwargs)


def test_save_writes_the_assessment_and_returns_its_id(engine):
    assessment_id = _save(engine)
    with Session(engine) as session:
        row = session.get(ScoutAssessment, assessment_id)
        assert row.band == 4.0
        assert row.status == "submitted"
        assert row.author_id == 1


def test_save_writes_the_criterion_scores(engine):
    assessment_id = _save(engine, criterion_scores={"composure": 4, "leadership": 2})
    with Session(engine) as session:
        rows = session.scalars(select(ScoutCriterionScore)
                               .where(ScoutCriterionScore.assessment_id == assessment_id)).all()
        assert {r.criterion_key: r.score for r in rows} == {"composure": 4, "leadership": 2}


def test_save_writes_criterion_passes_as_passed_not_score(engine):
    """Psychological criteria carry `score`; medical screening criteria carry `passed`.
    Exactly one of the two is set per row."""
    assessment_id = _save(engine, dimension=scout_scores.MEDICAL, criterion_scores={},
                          criterion_passes={"no-acl": True, "no-hamstring": False},
                          screening_failed=True)
    with Session(engine) as session:
        rows = session.scalars(select(ScoutCriterionScore)
                               .where(ScoutCriterionScore.assessment_id == assessment_id)).all()
        assert {r.criterion_key: r.passed for r in rows} == {"no-acl": True,
                                                             "no-hamstring": False}
        assert all(r.score is None for r in rows)


def test_two_assessors_both_keep_their_rows(engine):
    """Nothing is overwritten or averaged away: disagreement between two assessors must stay
    visible on the profile. Guards against a unique constraint being added."""
    first = _save(engine, band=4.0)
    second = _save(engine, band=2.0)
    assert first != second
    frame = store_assess.load_for_player(engine, 1, 4, 318)
    assert sorted(frame["band"].tolist()) == [2.0, 4.0]


def test_load_for_player_carries_the_authors_name_and_role(engine):
    """Decision 16: the role is a RECORD, displayed beside the band so a reader can see that
    a scout entered a medical judgement. It is useless if the load does not carry it."""
    _save(engine, dimension=scout_scores.MEDICAL)
    frame = store_assess.load_for_player(engine, 1, 4, 318)
    assert frame["author_name"].tolist() == ["Scout One"]
    assert frame["author_role"].tolist() == ["scout"]


def test_load_for_player_returns_empty_frame_with_columns_for_no_assessments(engine):
    frame = store_assess.load_for_player(engine, 99999, 4, 318)
    assert frame.empty
    for column in ("dimension", "band", "status", "author_name"):
        assert column in frame.columns


def test_sign_off_records_approver_and_time_and_changes_status(engine):
    assessment_id = _save(engine)
    store_assess.sign_off(engine, assessment_id, approver_id=2, now=NOW)
    with Session(engine) as session:
        row = session.get(ScoutAssessment, assessment_id)
        assert row.status == "signed_off"
        assert row.approved_by == 2
        assert row.approved_at == NOW


def test_sign_off_refuses_a_draft(engine):
    """A draft has not been submitted for review; approving one would put an incomplete
    assessment into the record as reviewed."""
    assessment_id = _save(engine, status="draft", band=None)
    with pytest.raises(ValueError):
        store_assess.sign_off(engine, assessment_id, approver_id=2, now=NOW)


def test_pending_signoff_lists_submitted_only(engine):
    submitted = _save(engine)
    _save(engine, status="draft", band=None)
    signed = _save(engine, band=3.0)
    store_assess.sign_off(engine, signed, approver_id=2, now=NOW)
    frame = store_assess.pending_signoff(engine)
    assert frame["id"].tolist() == [submitted]


def test_load_all_returns_the_columns_resolve_bands_consumes(engine):
    """The contract with model/scout_scores.resolve_bands. If these column names drift, the
    scorecard rebuild silently stops seeing assessments."""
    _save(engine)
    frame = store_assess.load_all(engine)
    for column in ("player_id", "competition_id", "season_id", "dimension", "band",
                   "status", "updated_at"):
        assert column in frame.columns


def test_load_all_output_flows_through_resolve_bands(engine):
    """End-to-end on the real resolver rather than a mock: a submitted assessment must
    actually produce a band."""
    _save(engine, dimension=scout_scores.PSYCHOLOGICAL, band=4.0)
    _save(engine, dimension=scout_scores.MEDICAL, band=3.0)
    resolved = scout_scores.resolve_bands(store_assess.load_all(engine))
    assert len(resolved) == 1
    assert resolved.iloc[0]["psychological_band"] == 4.0
    assert resolved.iloc[0]["medical_band"] == 3.0
```

- [ ] **Step 9: Run to verify they fail**

Run: `docker compose exec app pytest tests/test_store_assessments.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lofc.store.assessments'`

- [ ] **Step 10: Implement `store/assessments.py`**

```python
"""Reading and writing scout assessments.

USER DATA: nothing here is ever written or cleared by the pipeline.

NOTHING IS EVER DELETED OR OVERWRITTEN. Every save is a new row, so two assessors who
disagree both stay on the record and the disagreement is visible on the profile rather than
silently resolved. `scout_assessments` deliberately carries no unique constraint on
(player, competition, season, dimension) -- see the model's docstring and the regression
test in tests/test_store.py.

Plain SQLAlchemy Core so this runs identically on production Postgres and the sqlite used
in tests, matching store/watchlist.py.
"""

from __future__ import annotations

import datetime

import pandas as pd
from sqlalchemy import select

from lofc.store.models import ScoutAssessment, ScoutCriterionScore, User

_A = ScoutAssessment.__table__
_C = ScoutCriterionScore.__table__
_U = User.__table__

_LOAD_COLUMNS = ["id", "player_id", "competition_id", "season_id", "dimension", "band",
                 "band_note", "screening_failed", "notes", "status", "author_id",
                 "approved_by", "approved_at", "created_at", "updated_at"]


def save(engine, *, player_id: int, competition_id: int, season_id: int, dimension: str,
         author_id: int, band: float | None, notes: str | None,
         criterion_scores: dict[str, int], criterion_passes: dict[str, bool],
         screening_failed: bool, status: str) -> int:
    """Insert one assessment and its criterion rows. Returns the new assessment id.

    Always an INSERT, never an update: a re-assessment is a new judgement, and the old one
    stays on the record attributed to whoever made it.
    """
    with engine.begin() as conn:
        result = conn.execute(_A.insert().values(
            player_id=player_id, competition_id=competition_id, season_id=season_id,
            dimension=dimension, author_id=author_id, band=band, notes=notes,
            screening_failed=screening_failed, status=status))
        assessment_id = int(result.inserted_primary_key[0])

        rows = [{"assessment_id": assessment_id, "criterion_key": key,
                 "score": score, "passed": None}
                for key, score in criterion_scores.items()]
        rows += [{"assessment_id": assessment_id, "criterion_key": key,
                  "score": None, "passed": passed}
                 for key, passed in criterion_passes.items()]
        if rows:
            conn.execute(_C.insert(), rows)
    return assessment_id


def _frame(conn, query, columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(conn.execute(query).fetchall(), columns=columns)


def load_for_player(engine, player_id: int, competition_id: int,
                    season_id: int) -> pd.DataFrame:
    """Every assessment for one player-season, newest first, with the author's name and role.

    The author's ROLE is carried deliberately: Decision 16 lets any role enter any band, and
    the honest-record principle does the work a hard gate would otherwise do -- but only if
    the reader can see that a scout entered a medical judgement.
    """
    author = _U.alias("author")
    approver = _U.alias("approver")
    columns = _LOAD_COLUMNS + ["author_name", "author_role", "approver_name"]
    query = (select(*[_A.c[name] for name in _LOAD_COLUMNS],
                    author.c.full_name.label("author_name"),
                    author.c.role.label("author_role"),
                    approver.c.full_name.label("approver_name"))
             .select_from(_A.join(author, author.c.id == _A.c.author_id)
                            .outerjoin(approver, approver.c.id == _A.c.approved_by))
             .where(_A.c.player_id == player_id,
                    _A.c.competition_id == competition_id,
                    _A.c.season_id == season_id)
             .order_by(_A.c.updated_at.desc(), _A.c.id.desc()))
    with engine.connect() as conn:
        return _frame(conn, query, columns)


def criterion_scores_for(engine, assessment_id: int) -> pd.DataFrame:
    columns = ["criterion_key", "score", "passed"]
    query = (select(*[_C.c[name] for name in columns])
             .where(_C.c.assessment_id == assessment_id).order_by(_C.c.id))
    with engine.connect() as conn:
        return _frame(conn, query, columns)


def load_all(engine) -> pd.DataFrame:
    """Every assessment, in the shape `model/scout_scores.resolve_bands` consumes.

    The column names here are a CONTRACT with that function. If they drift, the scorecard
    rebuild stops seeing assessments and every assessed_composite silently goes NULL --
    tests/test_store_assessments.py pins the contract.
    """
    columns = ["player_id", "competition_id", "season_id", "dimension", "band", "status",
               "updated_at"]
    query = select(*[_A.c[name] for name in columns])
    with engine.connect() as conn:
        return _frame(conn, query, columns)


def pending_signoff(engine) -> pd.DataFrame:
    """Submitted assessments awaiting approval, oldest first -- a work queue, so the longest
    waiting is at the top."""
    author = _U.alias("author")
    columns = ["id", "player_id", "competition_id", "season_id", "dimension", "band",
               "screening_failed", "notes", "created_at", "author_name", "author_role"]
    query = (select(_A.c.id, _A.c.player_id, _A.c.competition_id, _A.c.season_id,
                    _A.c.dimension, _A.c.band, _A.c.screening_failed, _A.c.notes,
                    _A.c.created_at,
                    author.c.full_name.label("author_name"),
                    author.c.role.label("author_role"))
             .select_from(_A.join(author, author.c.id == _A.c.author_id))
             .where(_A.c.status == "submitted")
             .order_by(_A.c.created_at.asc(), _A.c.id.asc()))
    with engine.connect() as conn:
        return _frame(conn, query, columns)


def sign_off(engine, assessment_id: int, approver_id: int,
             now: datetime.datetime) -> None:
    """Approve one submitted assessment.

    Refuses a draft: a draft has not been offered for review, and approving one would put an
    incomplete assessment into the record as reviewed. Self-approval IS permitted (Decision
    16) -- with three people, requiring a different approver would jam the queue, and since
    a submitted assessment already scores, blocking it would gain nothing. The display layer
    labels it '(self-approved)' so one pair of eyes and two never look identical.
    """
    with engine.begin() as conn:
        current = conn.execute(select(_A.c.status)
                               .where(_A.c.id == assessment_id)).scalar_one_or_none()
        if current is None:
            raise ValueError(f"no assessment {assessment_id}")
        if current != "submitted":
            raise ValueError(f"assessment {assessment_id} is {current!r}, not 'submitted'")
        conn.execute(_A.update().where(_A.c.id == assessment_id)
                     .values(status="signed_off", approved_by=approver_id,
                             approved_at=now))
```

- [ ] **Step 11: Run to verify they pass**

Run: `docker compose exec app pytest tests/test_store_assessments.py -v`
Expected: 11 passed

- [ ] **Step 12: Run the full suite**

Run: `docker compose exec app pytest -q`
Expected: **440 passed** (412 + 28)

- [ ] **Step 13: Commit**

```bash
git add src/lofc/model/assessment_rules.py src/lofc/store/assessments.py \
        tests/test_assessment_rules.py tests/test_store_assessments.py
git commit -m "model: assessment scoring rules and assessment storage"
```

---

## Task 4: The assessment form

**Files:**
- Create: `src/lofc/dashboard/tabs/assess.py`
- Create: `src/lofc/dashboard/transparency.py`
- Modify: `src/lofc/dashboard/app.py` (register the tab)
- Test: `tests/test_transparency.py`

**Interfaces:**
- Consumes: everything produced by Tasks 1–3, plus `auth.can`, `club_criteria.*`, `evidence.render`.
- Produces:
  - `transparency.DISCLOSURES: list[tuple[str, str]]` — the 13 §10 items as (heading, plain-English line)
  - `transparency.render_panel() -> None` — the compact "what this covers / what it doesn't" panel
  - `assess.render(engine, user, player_row) -> None`

- [ ] **Step 1: Write the failing tests for the transparency disclosures**

Create `tests/test_transparency.py`:

```python
"""The 'what this covers / what it doesn't' disclosures (spec section 10).

Spec section 10 is a HARD requirement: every assumption and coverage limit behind these
scores must reach the user on the page. These tests pin the ones that would mislead a
recruiter if they went missing."""

from lofc.dashboard import transparency


def test_there_are_thirteen_disclosures():
    """Spec section 10 lists thirteen. A missing one is a caveat the user never sees."""
    assert len(transparency.DISCLOSURES) == 13


def test_every_disclosure_has_a_heading_and_a_body():
    for heading, body in transparency.DISCLOSURES:
        assert heading.strip()
        assert body.strip()


def test_a_disclosure_says_the_medical_score_is_human_judgement():
    text = " ".join(body for _, body in transparency.DISCLOSURES).lower()
    assert "judgement" in text or "judgment" in text
    assert "turned into that score by the platform" in text


def test_a_disclosure_states_the_league_coverage_figures():
    text = " ".join(body for _, body in transparency.DISCLOSURES)
    for figure in ("74%", "39%", "32%", "18%"):
        assert figure in text


def test_a_disclosure_states_what_is_actually_knowable():
    text = " ".join(body for _, body in transparency.DISCLOSURES)
    for figure in ("84%", "64%", "58%", "49%"):
        assert figure in text


def test_a_disclosure_says_nothing_excludes_a_player():
    text = " ".join(body for _, body in transparency.DISCLOSURES).lower()
    assert "advisory" in text


def test_a_disclosure_distinguishes_no_injuries_from_not_known():
    text = " ".join(body for _, body in transparency.DISCLOSURES).lower()
    assert "not known" in text


def test_the_disclosures_stay_short_enough_to_be_read():
    """A wall of text fails the requirement as surely as saying nothing -- a recruiter reads
    this between meetings."""
    for heading, body in transparency.DISCLOSURES:
        assert len(body) <= 320, f"{heading!r} is too long to be read between meetings"
```

- [ ] **Step 2: Run to verify they fail**

Run: `docker compose exec app pytest tests/test_transparency.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lofc.dashboard.transparency'`

- [ ] **Step 3: Implement `dashboard/transparency.py`**

```python
"""What the page must tell the user (spec section 10).

A HARD requirement, not a nice-to-have: every assumption, caveat and coverage limit behind
these scores belongs on the page, not in a design document nobody opens. Short plain
English -- a recruiter reads this between meetings, so a wall of text fails the requirement
as surely as saying nothing.

Held as data rather than inline markdown so the assessment form, the player profile and the
exported report all show the identical wording, and so the tests can check none has gone
missing.
"""

from __future__ import annotations

import streamlit as st

DISCLOSURES: list[tuple[str, str]] = [
    ("The Medical score is a person's judgement",
     "A member of staff scored this player against the club's requirement checklist. "
     "No number on this page was turned into that score by the platform."),
    ("Injury data informs that judgement, never determines it",
     "Availability, matches missed, days out and the injury table are shown to the "
     "assessor as evidence. They are not added up, weighted, or mapped to a band."),
    ("A blank injury record is worth different things in different leagues",
     "Share of players with any injury record: Championship 74%, League One 39%, "
     "League Two 32%, National League 18%; PL2 4%, Scottish Premiership 5%, Scottish "
     "Championship 1%. Empty means 'we have nothing' far more often lower down."),
    ("What is actually knowable",
     "Counting minutes played as a cross-check, availability can be established for "
     "Championship 84%, League One 64%, League Two 58%, National League 49%. About half "
     "of National League targets cannot be established either way."),
    ("What availability counts",
     "Matches missed through injury over the last two seasons, against a 92-match "
     "window. A fit player who simply was not picked is not penalised."),
    ("What minutes played is for",
     "It is not part of availability — 73% of players would fall below the club's 60% "
     "bar on minutes alone, which reflects rotation, not fitness. It is an independent "
     "check: 2,000+ minutes is proof of availability whatever the injury record says."),
    ("What the injury categories do and do not affect",
     "Illness, knocks and unspecified entries land in 'other'. Category never changes "
     "the availability figure, which counts matches missed regardless. Categories matter "
     "only for the club's specific screening criteria."),
    ("Where the 1–5 scale comes from",
     "The club's own rubric — 1 Unacceptable, 2 Below Standard, 3 Meets Standard, "
     "4 Above Standard, 5 Elite. For Medical the club defines minimum requirements but "
     "no elite threshold, so 3 is the practical ceiling. Nothing here is invented."),
    ("A known blind spot",
     "A player who joined part-way through the window is measured against the full 92 "
     "matches, which understates his availability. It affects only players who were also "
     "injured, and the spells behind the figure are shown so you can see it."),
    ("'No injuries recorded' is not 'no injuries'",
     "Where the platform cannot tell, it says 'not known' rather than showing a clean "
     "record."),
    ("Psychological is entirely human judgement",
     "There is no data behind it. It is the scout's assessment against the club's own "
     "criteria for that position."),
    ("Nothing here excludes a player",
     "Every flag is advisory, consistent with the rest of the platform. A flag marks a "
     "player; it never removes them from any list."),
    ("Every figure shows its provenance and its date",
     "Scraped versus entered by hand, who entered it, and when."),
]


def render_panel() -> None:
    """The compact 'what this covers / what it doesn't' panel.

    Collapsed by default so it does not push the assessor's work below the fold, but it sits
    at the TOP of the form rather than in a footer -- a caveat below the thing it qualifies
    has already failed.
    """
    with st.expander("What this covers, and what it doesn't", expanded=False):
        for heading, body in DISCLOSURES:
            st.markdown(f"**{heading}.** {body}")
```

- [ ] **Step 4: Run to verify they pass**

Run: `docker compose exec app pytest tests/test_transparency.py -v`
Expected: 8 passed

- [ ] **Step 5: INVOKE THE FRONTEND DESIGN SKILL**

Before writing `tabs/assess.py`, invoke the frontend design skill and follow it. Spec §16 names the assessment form as one of three surfaces where presentation is part of the product. It is used at speed, so it must satisfy:

- the club's criteria legible without scrolling back and forth to the evidence
- the evidence panel **beside** the Medical input, so the assessor judges with it in view
- `MEDICAL_CEILING_NOTE` next to the Medical band input, not in a footer
- the screening-failure warning prominent, stating in words that the band is unchanged
- draft vs submitted state obvious before the assessor leaves the page

- [ ] **Step 6: Implement `dashboard/tabs/assess.py`**

```python
"""The assessment form: the club's criteria for a player's position, scored by a person.

Decision 16: ANY authenticated user may enter EITHER band. The role is recorded and shown
beside the band rather than restricting who may enter it. Sign-off is the only gated action,
and it lives in tabs/signoff.py.

Decision 13: a failed screening criterion warns. Nothing here caps, clamps or overwrites the
band the assessor entered.
"""

from __future__ import annotations

import streamlit as st

from lofc.dashboard import evidence, transparency
from lofc.dashboard.session import CurrentUser
from lofc.model import assessment_rules as rules
from lofc.model import club_criteria as cc
from lofc.model import scout_scores
from lofc.store import assessments as store_assess

_BAND_HELP = " · ".join(f"{n} {label}" for n, label in rules.BAND_LABELS.items())


def _band_select(label: str, key: str) -> float | None:
    """A 1-5 band input that starts EMPTY. Defaulting to 3 would silently score every player
    a scout opened and abandoned."""
    options = [None] + list(rules.BAND_LABELS)
    return st.selectbox(
        label, options, key=key, format_func=lambda v: "—" if v is None
        else f"{v} · {rules.BAND_LABELS[v]}", help=_BAND_HELP)


def _psychological_form(engine, user: CurrentUser, player_id: int, competition_id: int,
                        season_id: int, position: str) -> None:
    st.markdown("##### Psychological")
    st.caption("The club's criteria for this position, each scored 1–5. The band is their "
               "equal-weighted mean. Every criterion must be scored before it submits.")

    scores: dict[str, int] = {}
    for text in cc.PSYCHOLOGICAL_CRITERIA[position]:
        key = rules.criterion_key(text)
        value = _band_select(text, key=f"psych_{player_id}_{key}")
        if value is not None:
            scores[key] = value

    band = rules.psychological_band(scores, position)
    status = rules.psychological_status(scores, position)
    notes = st.text_area("Notes (optional)", key=f"psych_notes_{player_id}")

    if band is None:
        st.info(f"Scored {len(scores)} of {len(cc.PSYCHOLOGICAL_CRITERIA[position])} "
                "criteria. Saving now keeps this as a **draft**, which does not score.")
    else:
        st.success(f"Band **{band:.2f}** — the mean of "
                   f"{len(cc.PSYCHOLOGICAL_CRITERIA[position])} criteria. Saving submits "
                   "it, and it scores immediately.")

    if st.button("Save psychological assessment", type="primary",
                 key=f"save_psych_{player_id}"):
        store_assess.save(engine, player_id=player_id, competition_id=competition_id,
                          season_id=season_id, dimension=scout_scores.PSYCHOLOGICAL,
                          author_id=user.id, band=band, notes=notes or None,
                          criterion_scores=scores, criterion_passes={},
                          screening_failed=False, status=status)
        st.success(f"Saved as **{status}**.")


def _medical_form(engine, user: CurrentUser, player_id: int, competition_id: int,
                  season_id: int, position: str, minutes_played: int | None) -> None:
    st.markdown("##### Medical")
    st.caption("There is no formula here. You enter the band, having read the evidence "
               "beside it. The platform never converts injury data into this score.")

    left, right = st.columns([1, 1])

    with right:
        # The evidence sits BESIDE the input, in view while the assessor decides.
        evidence.render(engine, player_id, competition_id, season_id, minutes_played)

    with left:
        passes: dict[str, bool] = {}
        for criterion in cc.MEDICAL_CRITERIA[position]:
            key = rules.criterion_key(criterion.text)
            if criterion.kind == "screening":
                answer = st.radio(criterion.text, ["—", "Meets", "Does not meet"],
                                  horizontal=True, key=f"med_{player_id}_{key}")
                if answer != "—":
                    passes[key] = (answer == "Meets")
            elif criterion.kind == "protocol":
                st.checkbox(f"{criterion.text} *(club process — not scored)*",
                            key=f"med_proto_{player_id}_{key}", disabled=True)
            else:
                st.caption(f"{criterion.text} *(shown as evidence — see the panel)*")

        band = _band_select("Medical band", key=f"med_band_{player_id}")
        st.caption(rules.MEDICAL_CEILING_NOTE)

        failed = rules.screening_failed(passes, position)
        if failed:
            st.warning("**One or more screening criteria are not met.** This is a flag, "
                       "not a cap — the band you enter stands unchanged, and the "
                       "disagreement is shown to whoever signs off. Please say why in the "
                       "notes.")

        notes = st.text_area("Notes" + (" (required — a screening criterion failed)"
                                        if failed else " (optional)"),
                             key=f"med_notes_{player_id}")
        status = rules.medical_status(band, passes, position)

        blocked = failed and not (notes or "").strip()
        if blocked:
            st.error("A reason is required when a screening criterion is not met.")
        if st.button("Save medical assessment", type="primary",
                     key=f"save_med_{player_id}", disabled=blocked):
            store_assess.save(engine, player_id=player_id, competition_id=competition_id,
                              season_id=season_id, dimension=scout_scores.MEDICAL,
                              author_id=user.id, band=float(band) if band else None,
                              notes=notes or None, criterion_scores={},
                              criterion_passes=passes, screening_failed=failed,
                              status=status)
            st.success(f"Saved as **{status}**.")


def render(engine, user: CurrentUser, player_id: int, player_name: str,
           competition_id: int, season_id: int, position: str,
           minutes_played: int | None) -> None:
    """The assessment page for one player-season."""
    st.subheader(f"Assess — {player_name}")
    st.caption(f"{position} · signed in as {user.full_name} ({user.role}). Your name and "
               "role are recorded against anything you save.")

    if position not in cc.POSITION_GROUPS:
        # Spec section 18: never scored against no criteria.
        st.error(f"No club criteria exist for the position group {position!r}, so this "
                 "player cannot be assessed. Check the player's position group.")
        return

    transparency.render_panel()
    psych_tab, med_tab = st.tabs(["Psychological", "Medical"])
    with psych_tab:
        _psychological_form(engine, user, player_id, competition_id, season_id, position)
    with med_tab:
        _medical_form(engine, user, player_id, competition_id, season_id, position,
                      minutes_played)
```

- [ ] **Step 7: Verify the form end to end against the live database**

```bash
docker compose restart dashboard
```

Sign in as the test account, open a player, click **Assess**. Then:
1. Score every Psychological criterion → the band appears and says it will submit. Save.
2. Score all but one → it says **draft**. Save, and confirm it does not score.
3. On Medical: mark a screening criterion "Does not meet", enter band **4** → the warning appears, the band is **still 4**, and the notes field becomes required.
4. Confirm the rows landed:

```bash
docker compose exec db psql -U lofc lofc -c \
  "SELECT id, dimension, band, status, screening_failed, author_id FROM scout_assessments ORDER BY id DESC LIMIT 5;"
```

Expected: the draft is stored as `draft` with a NULL band, and the screening-flagged row has `band = 4` with `screening_failed = true`. **If the band came back as anything other than 4, Decision 13 has been violated — stop and fix it.**

- [ ] **Step 8: Run the full suite**

Run: `docker compose exec app pytest -q`
Expected: **448 passed** (440 + 8)

- [ ] **Step 9: Commit**

```bash
git add src/lofc/dashboard/transparency.py src/lofc/dashboard/tabs/assess.py \
        src/lofc/dashboard/app.py tests/test_transparency.py
git commit -m "dashboard: the scout assessment form and the transparency panel"
```

---

## Task 5: Badges, the profile section, and the sign-off queue

**Files:**
- Create: `src/lofc/dashboard/badges.py`
- Create: `src/lofc/dashboard/tabs/signoff.py`
- Modify: `src/lofc/dashboard/tabs/players.py` (inside `_render_profile_body`)
- Test: `tests/test_badges.py`

**Interfaces:**
- Consumes: Tasks 1–4; `auth.can(role, "sign_off")`; `store_assess.pending_signoff`, `sign_off`, `load_for_player`.
- Produces:
  - `badges.AssessmentBadge` — frozen dataclass `(text: str, colour: str, tone: str)`
  - `badges.for_status(status: str | None, author_name=None, approver_name=None, approved_at=None) -> AssessmentBadge`
  - `badges.render(badge: AssessmentBadge) -> None`
  - `badges.signoff_label(author_name: str, approver_name: str | None) -> str`

- [ ] **Step 1: Write the failing tests for the badges**

Create `tests/test_badges.py`:

```python
"""Assessment status badges.

Spec section 16 and Decision 14: colour NEVER carries the meaning alone -- printed reports
and colour-blind readers lose the colour, so every badge must state its status in words.
These tests are what stop that rule quietly regressing into a coloured dot."""

import datetime as dt

from lofc.dashboard import badges


def test_no_assessment_badge_says_so_in_words():
    badge = badges.for_status(None)
    assert "Not assessed" in badge.text


def test_submitted_badge_states_awaiting_sign_off_in_words():
    badge = badges.for_status("submitted", author_name="J. Smith")
    assert "Assessed" in badge.text
    assert "awaiting sign-off" in badge.text.lower()


def test_submitted_badge_names_the_assessor():
    """Decision 14 accepts an unsigned assessment moving the ranking ONLY because the
    assessor's name is visible. An anonymous badge would not be acceptable."""
    badge = badges.for_status("submitted", author_name="J. Smith")
    assert "J. Smith" in badge.text


def test_signed_off_badge_names_the_approver_and_the_date():
    badge = badges.for_status("signed_off", author_name="J. Smith",
                              approver_name="A. Approver",
                              approved_at=dt.datetime(2026, 8, 14))
    assert "Signed off" in badge.text
    assert "A. Approver" in badge.text
    assert "2026" in badge.text or "Aug" in badge.text


def test_every_badge_carries_words_not_only_a_colour():
    for status in (None, "draft", "submitted", "signed_off"):
        badge = badges.for_status(status, author_name="J. Smith",
                                  approver_name="A. Approver")
        stripped = "".join(ch for ch in badge.text if ch.isalpha())
        assert len(stripped) > 3, f"{status!r} badge has no words"


def test_self_approval_is_labelled():
    """One pair of eyes and two must not look identical in a report going to a director."""
    label = badges.signoff_label("J. Smith", "J. Smith")
    assert "self-approved" in label.lower()


def test_a_different_approver_is_not_labelled_self_approved():
    label = badges.signoff_label("J. Smith", "A. Approver")
    assert "self-approved" not in label.lower()
    assert "A. Approver" in label


def test_an_unknown_status_does_not_crash_and_says_it_is_unknown():
    badge = badges.for_status("something-new")
    assert badge.text
    assert "unknown" in badge.text.lower()
```

- [ ] **Step 2: Run to verify they fail**

Run: `docker compose exec app pytest tests/test_badges.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lofc.dashboard.badges'`

- [ ] **Step 3: Implement `dashboard/badges.py`**

```python
"""Assessment status badges, rendered identically everywhere they appear.

Decision 14 and spec section 16: COLOUR NEVER CARRIES THE MEANING ALONE. Every badge states
its status in words, because printed reports and colour-blind readers lose the colour. The
emoji and the colour reinforce the words; they never replace them.

One module so a watchlist row and a player-profile row can never disagree about a player by
rendering two different badge sets.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

import streamlit as st

from lofc.dashboard.theme import RED


@dataclass(frozen=True)
class AssessmentBadge:
    text: str          # always carries the status in words
    colour: str        # reinforcement only
    tone: str          # "none" | "draft" | "pending" | "approved" | "unknown"


def signoff_label(author_name: str, approver_name: str | None) -> str:
    """How to name the approver. Self-approval is permitted (Decision 16) and LABELLED:
    with three people, requiring a different approver would jam the queue, but a second pair
    of eyes and one pair must not look identical in a report going to a director."""
    if approver_name is None:
        return ""
    if approver_name == author_name:
        return f"{approver_name} (self-approved)"
    return approver_name


def for_status(status: str | None, author_name: str | None = None,
               approver_name: str | None = None,
               approved_at: datetime.datetime | None = None) -> AssessmentBadge:
    """The badge for one assessment's status."""
    if status is None:
        return AssessmentBadge("Not assessed", "#6b6b6b", "none")
    if status == "draft":
        return AssessmentBadge("Draft — does not score", "#6b6b6b", "draft")
    if status == "submitted":
        who = f" by {author_name}" if author_name else ""
        return AssessmentBadge(f"🟠 Assessed{who} — awaiting sign-off", "#E8A33D", "pending")
    if status == "signed_off":
        who = signoff_label(author_name or "", approver_name)
        when = f", {approved_at:%d %b %Y}" if approved_at else ""
        tail = f" by {who}{when}" if who else when
        return AssessmentBadge(f"🟢 Signed off{tail}", "#2E7D32", "approved")
    # An unrecognised status must be visible, not silently rendered as one of the known ones.
    return AssessmentBadge(f"Unknown status ({status})", RED, "unknown")


def render(badge: AssessmentBadge) -> None:
    st.markdown(
        f'<span style="background:{badge.colour}1A;color:{badge.colour};'
        f'border:1px solid {badge.colour}55;border-radius:4px;padding:.15rem .5rem;'
        f'font-size:.8rem;font-weight:600;">{badge.text}</span>',
        unsafe_allow_html=True)
```

- [ ] **Step 4: Run to verify they pass**

Run: `docker compose exec app pytest tests/test_badges.py -v`
Expected: 8 passed

- [ ] **Step 5: INVOKE THE FRONTEND DESIGN SKILL**

Before writing `tabs/signoff.py` and the profile section, invoke the frontend design skill and follow it. Spec §16 names the workflow/sign-off view as the second of three surfaces where presentation is part of the product. It must satisfy:

- the decision first — the composite, both human bands, the flags — with evidence supporting below
- provenance never optional: assessor name, approver name, both dates, on every figure
- competing assessments visible side by side, never collapsed to the winner
- the screening flag prominent, stating in words that the band was not changed

- [ ] **Step 6: Implement `dashboard/tabs/signoff.py`**

```python
"""The sign-off queue: submitted assessments awaiting approval.

Sign-off is the ONLY gated assessment action (Decision 16). It changes no number and hides
no player (Decision 14) -- it marks an assessment reviewed, and controls what may leave the
building as final rather than provisional.
"""

from __future__ import annotations

import datetime

import streamlit as st

from lofc.dashboard import badges
from lofc.dashboard.auth import can
from lofc.dashboard.session import CurrentUser
from lofc.store import assessments as store_assess


def render(engine, user: CurrentUser, player_names: dict[int, str]) -> None:
    st.subheader("Sign-off queue")

    if not can(user.role, "sign_off"):
        st.info("Sign-off is restricted to the Head of Recruitment and administrators. "
                "You can still assess any player — sign-off is the only gated action.")
        return

    st.caption("Signing off does not change any score and does not hide any player. It "
               "marks the assessment reviewed, so it can be exported as final rather than "
               "provisional.")

    pending = store_assess.pending_signoff(engine)
    if pending.empty:
        st.success("Nothing awaiting sign-off.")
        return

    st.caption(f"{len(pending)} awaiting review, oldest first.")
    for row in pending.itertuples():
        name = player_names.get(row.player_id, f"Player {row.player_id}")
        with st.container(border=True):
            head, action = st.columns([4, 1])
            with head:
                st.markdown(f"**{name}** — {row.dimension}")
                band = "—" if row.band is None else f"{row.band:.2f}"
                st.markdown(f"Band **{band}** · entered by **{row.author_name}** "
                            f"({row.author_role}) on {row.created_at:%d %b %Y}")
                if row.screening_failed:
                    st.warning("**A screening criterion was not met.** The assessor's band "
                               "stands unchanged — this flag records the disagreement for "
                               "you to weigh.")
                if row.notes:
                    st.caption(f"Notes: {row.notes}")
                if row.author_name == user.full_name:
                    st.caption("You entered this assessment. Approving it is permitted and "
                               "will be recorded as **self-approved**.")
            with action:
                if st.button("Sign off", key=f"signoff_{row.id}", type="primary"):
                    store_assess.sign_off(engine, row.id, approver_id=user.id,
                                          now=datetime.datetime.now())
                    st.rerun()
```

- [ ] **Step 7: Add the scout section to the player profile**

In `src/lofc/dashboard/tabs/players.py`, define this new module-level function, and call it as `_scout_section(get_engine(), row)` from the end of `_render_profile_body` — after the existing stats section, so the decision and the performance data are read first and the assessment sits below them rather than displacing them:

```python
def _scout_section(engine, row) -> None:
    """The two human bands, who entered them, who approved them, and when.

    Shows EVERY assessment, not just the one that scores: two assessors who disagree must
    both be visible, because Decision 14 accepts an unsigned assessment moving the ranking
    only on the basis that the competing view is on the page.
    """
    st.markdown("#### Scout assessment")
    frame = store_assess.load_for_player(engine, int(row["player_id"]),
                                         int(row["competition_id"]), int(row["season_id"]))
    if frame.empty:
        badges.render(badges.for_status(None))
        st.caption("No psychological or medical assessment has been recorded for this "
                   "player-season.")
    else:
        for dimension in (scout_scores.PSYCHOLOGICAL, scout_scores.MEDICAL):
            rows = frame[frame["dimension"] == dimension]
            st.markdown(f"**{dimension}**")
            if rows.empty:
                badges.render(badges.for_status(None))
                continue
            for entry in rows.itertuples():
                band = "—" if entry.band is None else f"{entry.band:.2f}"
                st.markdown(f"Band **{band}** — entered by **{entry.author_name}** "
                            f"({entry.author_role}), {entry.created_at:%d %b %Y}")
                badges.render(badges.for_status(entry.status, entry.author_name,
                                                entry.approver_name, entry.approved_at))
                if entry.screening_failed:
                    st.warning("A screening criterion was not met. The band above is the "
                               "assessor's own and was not changed by this flag.")
                if entry.notes:
                    st.caption(f"Notes: {entry.notes}")
        if len(frame) > frame["dimension"].nunique():
            st.caption("More than one assessment exists for a dimension. All are shown; "
                       "the signed-off one scores, otherwise the most recent submitted one.")

    evidence.render(engine, int(row["player_id"]), int(row["competition_id"]),
                    int(row["season_id"]), row.get("minutes_played"))

    if st.button("Assess this player", key=f"assess_{row['player_id']}"):
        # Any authenticated user may assess either dimension (Decision 16).
        st.session_state["assess_player_id"] = int(row["player_id"])
        st.rerun()
```

Add the imports `from lofc.dashboard import badges, evidence`, `from lofc.model import scout_scores`, and `from lofc.store import assessments as store_assess` to `players.py`.

- [ ] **Step 8: Register both tabs in `app.py`**

Add "Assess" and "Sign-off" to the existing `st.tabs([...])` list and wire them to `assess.render` and `signoff.render`, passing `user` through. Follow the pattern the existing tabs already use in that file.

- [ ] **Step 9: Verify the sign-off flow end to end**

```bash
docker compose exec app python -m lofc.admin create-user \
    --username testhor --name "Test Head" --role head_of_recruitment
docker compose restart dashboard
```

1. Signed in as `testscout`, open the **Sign-off** tab. Expected: the "restricted" message, no queue.
2. Sign in as `testhor`. Expected: the queue lists the assessments saved in Task 4, oldest first.
3. Sign one off. Expected: it leaves the queue, and the player profile badge turns 🟢 with the approver's name and date.
4. Confirm the score did not move:

```bash
docker compose exec db psql -U lofc lofc -c \
  "SELECT objective_composite FROM player_scorecards WHERE player_id = <the player> AND archetype = 'All Metrics';"
```

Expected: **unchanged**. Sign-off changes no number (Decision 14). If it moved, stop.

- [ ] **Step 10: Run the full suite**

Run: `docker compose exec app pytest -q`
Expected: **456 passed** (448 + 8)

- [ ] **Step 11: Commit**

```bash
git add src/lofc/dashboard/badges.py src/lofc/dashboard/tabs/signoff.py \
        src/lofc/dashboard/tabs/players.py src/lofc/dashboard/app.py tests/test_badges.py
git commit -m "dashboard: status badges, profile scout section and the sign-off queue"
```

---

## Task 6: Watchlist integration and the Assessed ranking mode

**Files:**
- Create: `src/lofc/model/assessment_status.py`
- Modify: `src/lofc/dashboard/tabs/watchlist.py`
- Modify: `src/lofc/dashboard/tabs/players.py`
- Modify: `src/lofc/dashboard/loaders.py` (one cached loader)
- Test: `tests/test_assessment_status.py`

**Interfaces:**
- Consumes: `store_assess.load_all`, `badges.for_status`, `scout_scores.PSYCHOLOGICAL`, `scout_scores.MEDICAL`.
- Produces:
  - `assessment_status.STATUSES: tuple[str, ...]` = `("Not assessed", "Awaiting sign-off", "Signed off")`
  - `assessment_status.per_player(assessments: pd.DataFrame) -> pd.DataFrame` — one row per (player, competition, season) with a `assessment_status` column
  - `assessment_status.attach(frame, statuses) -> pd.DataFrame`
  - `loaders.load_assessment_status(season_id=None) -> pd.DataFrame`

- [ ] **Step 1: Write the failing tests for the derived status**

Create `tests/test_assessment_status.py`:

```python
"""Deriving one assessment status per player-season, for the watchlist and the Players list.

The status is DERIVED by joining on the same (player, competition, season) triple both
tables already use -- no new column, no new table, and therefore no way for the watchlist
and the profile to disagree."""

import pandas as pd

from lofc.model import assessment_status as astat
from lofc.model import scout_scores

KEY = ["player_id", "competition_id", "season_id"]


def _rows(*rows) -> pd.DataFrame:
    return pd.DataFrame(list(rows),
                        columns=KEY + ["dimension", "band", "status", "updated_at"])


def test_a_player_with_no_assessment_is_absent():
    result = astat.per_player(_rows())
    assert result.empty
    assert "assessment_status" in result.columns


def test_one_dimension_only_is_still_awaiting_sign_off_not_signed_off():
    """A single submitted dimension is real work and must show as such -- but it is not
    signed off, and assessed_composite stays NULL until BOTH exist (Decision 9)."""
    result = astat.per_player(_rows(
        (1, 4, 318, scout_scores.PSYCHOLOGICAL, 4.0, "submitted", "2026-08-14")))
    assert result.iloc[0]["assessment_status"] == "Awaiting sign-off"


def test_both_dimensions_signed_off_is_signed_off():
    result = astat.per_player(_rows(
        (1, 4, 318, scout_scores.PSYCHOLOGICAL, 4.0, "signed_off", "2026-08-14"),
        (1, 4, 318, scout_scores.MEDICAL, 3.0, "signed_off", "2026-08-14")))
    assert result.iloc[0]["assessment_status"] == "Signed off"


def test_one_signed_off_and_one_submitted_is_awaiting_sign_off():
    """The weaker of the two governs. Reporting 'Signed off' when half the assessment is
    still unreviewed would overstate what a director is being shown."""
    result = astat.per_player(_rows(
        (1, 4, 318, scout_scores.PSYCHOLOGICAL, 4.0, "signed_off", "2026-08-14"),
        (1, 4, 318, scout_scores.MEDICAL, 3.0, "submitted", "2026-08-14")))
    assert result.iloc[0]["assessment_status"] == "Awaiting sign-off"


def test_drafts_alone_do_not_count_as_assessed():
    """Decision 14: a draft never scores. It must not read as assessed either."""
    result = astat.per_player(_rows(
        (1, 4, 318, scout_scores.PSYCHOLOGICAL, None, "draft", "2026-08-14")))
    assert result.empty


def test_statuses_are_separate_per_season():
    """A player assessed in 25/26 must not show as assessed in 26/27."""
    result = astat.per_player(_rows(
        (1, 4, 318, scout_scores.PSYCHOLOGICAL, 4.0, "submitted", "2026-08-14"),
        (1, 4, 318, scout_scores.MEDICAL, 3.0, "submitted", "2026-08-14")))
    assert len(result) == 1
    assert result.iloc[0]["season_id"] == 318


def test_attach_leaves_unassessed_rows_as_not_assessed():
    frame = pd.DataFrame([{"player_id": 1, "competition_id": 4, "season_id": 318},
                          {"player_id": 2, "competition_id": 4, "season_id": 318}])
    statuses = astat.per_player(_rows(
        (1, 4, 318, scout_scores.PSYCHOLOGICAL, 4.0, "submitted", "2026-08-14"),
        (1, 4, 318, scout_scores.MEDICAL, 3.0, "submitted", "2026-08-14")))
    merged = astat.attach(frame, statuses)
    assert merged.set_index("player_id").loc[2, "assessment_status"] == "Not assessed"


def test_attach_never_drops_a_row():
    """A LEFT join, not an inner one: filtering the Players list down to assessed players is
    an explicit opt-in mode, never a side effect of showing the badge column."""
    frame = pd.DataFrame([{"player_id": i, "competition_id": 4, "season_id": 318}
                          for i in range(50)])
    merged = astat.attach(frame, astat.per_player(_rows()))
    assert len(merged) == 50
```

- [ ] **Step 2: Run to verify they fail**

Run: `docker compose exec app pytest tests/test_assessment_status.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lofc.model.assessment_status'`

- [ ] **Step 3: Implement `model/assessment_status.py`**

```python
"""One assessment status per player-season, for the watchlist and the Players list.

DERIVED, never stored: the status comes from joining on the same (player, competition,
season) triple both tables already use, so a watchlist row and a player-profile row cannot
disagree about a player by reading two different sources.
"""

from __future__ import annotations

import pandas as pd

from lofc.model.scout_scores import MEDICAL, PSYCHOLOGICAL

KEY = ["player_id", "competition_id", "season_id"]

NOT_ASSESSED = "Not assessed"
AWAITING = "Awaiting sign-off"
SIGNED_OFF = "Signed off"
STATUSES: tuple[str, ...] = (NOT_ASSESSED, AWAITING, SIGNED_OFF)

_OUTPUT = KEY + ["assessment_status"]
_SCORING = ("submitted", "signed_off")


def per_player(assessments: pd.DataFrame) -> pd.DataFrame:
    """One row per assessed player-season with its overall status.

    SIGNED_OFF requires BOTH dimensions signed off. The weaker of the two governs: reporting
    'Signed off' while half the assessment is still unreviewed would overstate what a
    director is being shown. Drafts are excluded entirely -- a draft never scores
    (Decision 14) and must not read as assessed either.
    """
    if assessments.empty:
        return pd.DataFrame(columns=_OUTPUT)

    scoring = assessments[assessments["status"].isin(_SCORING)]
    scoring = scoring[scoring["dimension"].isin([PSYCHOLOGICAL, MEDICAL])]
    if scoring.empty:
        return pd.DataFrame(columns=_OUTPUT)

    records = []
    for key, group in scoring.groupby(KEY):
        dimensions = set(group["dimension"])
        both_signed = (len(dimensions) == 2
                       and (group["status"] == "signed_off").all())
        records.append(dict(zip(KEY, key),
                            assessment_status=SIGNED_OFF if both_signed else AWAITING))
    return pd.DataFrame(records, columns=_OUTPUT)


def attach(frame: pd.DataFrame, statuses: pd.DataFrame) -> pd.DataFrame:
    """Add `assessment_status` to `frame`, defaulting to NOT_ASSESSED.

    A LEFT join, deliberately: showing the badge column must never drop a player. Filtering
    to assessed players is an explicit opt-in mode, never a side effect of rendering a badge.
    """
    if frame.empty:
        out = frame.copy()
        out["assessment_status"] = pd.Series(dtype=object)
        return out
    merged = frame.merge(statuses, on=KEY, how="left")
    merged["assessment_status"] = merged["assessment_status"].fillna(NOT_ASSESSED)
    return merged
```

- [ ] **Step 4: Run to verify they pass**

Run: `docker compose exec app pytest tests/test_assessment_status.py -v`
Expected: 8 passed

- [ ] **Step 5: Add the cached loader**

In `src/lofc/dashboard/loaders.py`, beside the other `@st.cache_data(ttl=600)` loaders:

```python
@st.cache_data(ttl=60)
def load_assessment_status(season_id: int | None = None) -> pd.DataFrame:
    """One status per assessed player-season.

    A 60s TTL rather than the 600s used elsewhere: assessments change while people are
    working, and a scout who saves an assessment and does not see the badge update for ten
    minutes will reasonably conclude the save failed.
    """
    frame = store_assess.load_all(get_engine())
    if season_id is not None and not frame.empty:
        frame = frame[frame["season_id"] == season_id]
    return assessment_status.per_player(frame)
```

Add `from lofc.model import assessment_status` and `from lofc.store import assessments as store_assess` to that module's imports.

- [ ] **Step 6: INVOKE THE FRONTEND DESIGN SKILL**

Before modifying the watchlist and Players tables, invoke the frontend design skill and follow it. These tables must stay dense and scannable with a badge column added, and the badge wording must be **identical** to the profile's — spec §7.1 requires that a watchlist row and a profile row never disagree.

- [ ] **Step 7: Add the status column, filter and Assess action to the watchlist**

In `src/lofc/dashboard/tabs/watchlist.py`, after the frame is loaded:

```python
    frame = assessment_status.attach(frame, load_assessment_status())

    chosen = st.multiselect(
        "Assessment status", list(assessment_status.STATUSES),
        default=list(assessment_status.STATUSES),
        help="Which of your targets still need a scout?")
    frame = frame[frame["assessment_status"].isin(chosen)]

    st.caption("‘Scout sent’ is a note you enter — it records that you asked someone to "
               "look at a player. The assessment status records that someone did. They are "
               "deliberately separate.")
```

Render `assessment_status` as a column in the existing table, and add an **Assess** button per row that sets `st.session_state["assess_player_id"]` exactly as the profile's button does.

- [ ] **Step 8: Add the Assessed ranking mode to the Players tab**

In `src/lofc/dashboard/tabs/players.py`, inside `_players`, above the table:

```python
    assessed_mode = st.toggle(
        "Rank on assessed composite", value=False,
        help="Ranks on Performance + Physical + Psychological + Medical (86% of the "
             "framework's weight), and shows only players where a person has completed "
             "both human dimensions. Off by default — the standard ranking is unchanged.")

    if assessed_mode:
        # attach() must run BEFORE the signed-off filter reads the column -- the Players
        # pool does not carry assessment_status otherwise, and the filter would KeyError.
        pool = assessment_status.attach(pool, load_assessment_status(season_id))
        pool = pool[pool["assessed_composite"].notna()]
        rank_column = "assessed_composite"
        signed_only = st.checkbox(
            "Signed-off assessments only", value=False,
            help="For presenting a shortlist formally. Off by default — an unsigned "
                 "assessment still scores and still ranks.")
        if signed_only:
            pool = pool[pool["assessment_status"] == assessment_status.SIGNED_OFF]
        st.caption(f"{len(pool)} players have both human dimensions assessed. "
                   "This is a different ranking from the default, not a filter on it.")
    else:
        rank_column = cf.RANK_COLUMN
```

Use `rank_column` for the sort. **The `else` branch must leave the existing behaviour byte-for-byte identical** — the default ranking does not change.

Add `from lofc.model import assessment_status` and `from lofc.dashboard.loaders import load_assessment_status` to `players.py`'s imports (it already imports `club_framework as cf`, which supplies `cf.RANK_COLUMN`).

- [ ] **Step 9: Verify nothing moved in the default ranking**

```bash
docker compose exec app python -c "
from lofc.dashboard.loaders import load_scorecards
import pandas as pd
sc = load_scorecards()
print('rows:', len(sc))
print('objective mean:', round(sc['objective_composite'].mean(), 6))
print('assessed non-null:', sc['assessed_composite'].notna().sum())
"
```

Expected: `rows: 6573`, `objective mean: 3.029285`, and a small non-null count matching the assessments saved during Tasks 4–5. **If the objective mean moved, stop** — something in this task reached the default ranking.

- [ ] **Step 10: Verify the badge wording matches in both places**

Open the same player on the Players tab and on the watchlist. Expected: identical badge text, word for word. Spec §7.1 requires this; two badge sets drifting apart is the failure it names.

- [ ] **Step 11: Run the full suite**

Run: `docker compose exec app pytest -q`
Expected: **464 passed** (456 + 8)

- [ ] **Step 12: Commit**

```bash
git add src/lofc/model/assessment_status.py src/lofc/dashboard/loaders.py \
        src/lofc/dashboard/tabs/watchlist.py src/lofc/dashboard/tabs/players.py \
        tests/test_assessment_status.py
git commit -m "dashboard: watchlist assessment status and the assessed ranking mode"
```

---

## Task 7: Documentation

**Files:**
- Modify: `plan/BUILD_PLAN.md`, `CLAUDE.md`, `docs/architecture.md`, `README.md`, `cli_commands.txt`

- [ ] **Step 1: Update `plan/BUILD_PLAN.md`**

In the CURRENT STATE box, record: the interface is built; the login gate is live; the evidence panel, assessment form, sign-off queue, watchlist integration and assessed ranking mode all exist; the final test count. Move R3a-2 out of the pending register. Close the three auth gaps (password reset, rate limiting, strength rules) that Task 0 fixed, and record what remains open (no email address on the users table, so resets are admin-only and in person).

- [ ] **Step 2: Update `CLAUDE.md`**

Update the status paragraph: the interface exists, the test count, and the next task (R3c, the player report export). Keep it to the same length — it is a pointer, not a second BUILD_PLAN.

- [ ] **Step 3: Update `docs/architecture.md`**

Add the new modules to the dashboard section, keeping the stated dependency direction: `theme/labels → badges → charts → store/* → loaders → evidence → controls → tabs → app`.

- [ ] **Step 4: Append to `cli_commands.txt`**

```
# Create a platform user (there is no self-service sign-up)
docker compose exec app python -m lofc.admin create-user --username <name> --name "<Full Name>" --role scout
# Reset a forgotten password (admin only; the users table holds no email address)
docker compose exec app python -m lofc.admin set-password --username <name>
# List accounts and their lockout state
docker compose exec app python -m lofc.admin list-users
```

- [ ] **Step 5: Update `README.md`**

Add a short "Signing in" section: accounts are created by an administrator, there is no self-service sign-up, and a forgotten password is reset by an administrator.

- [ ] **Step 6: Verify no confidential file is staged**

```bash
git status --short
git ls-files | grep -iE '\.docx|\.xlsx|backup|efl_values' || echo "clean"
```
Expected: `clean`.

- [ ] **Step 7: Commit**

```bash
git add plan/BUILD_PLAN.md CLAUDE.md docs/architecture.md README.md cli_commands.txt
git commit -m "docs: record the scout assessment interface as built"
```

---

## Final verification

- [ ] `docker compose exec app pytest -q` → **464 passed**
- [ ] `objective_composite` mean is **3.029285** across **6,573** rows — unchanged
- [ ] The dashboard shows only a login form when signed out
- [ ] A screening failure warns and leaves the entered band untouched
- [ ] A blank injury record reads "Not known", never as a clean record
- [ ] Badge wording is identical on the profile, the watchlist and the sign-off queue
- [ ] `git log --oneline` shows 8 commits, none mentioning Claude or AI
- [ ] **Nothing pushed**
