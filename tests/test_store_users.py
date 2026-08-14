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
