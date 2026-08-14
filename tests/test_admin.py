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
