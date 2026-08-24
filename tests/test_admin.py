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


def test_create_user_rejects_a_weak_password_before_writing_a_row(engine):
    """Pins that the password check runs BEFORE the database write, not after: if the check
    were removed or reordered past session.add()/commit(), this would still raise SystemExit
    (from the weak password) but the row would already exist -- the assertion below on
    session.scalar(...) is what would catch that regression."""
    with pytest.raises(SystemExit):
        admin.create_user(engine, "newuser", "New User", "scout", "short")

    with Session(engine) as session:
        assert session.scalar(select(User).where(User.username == "newuser")) is None


def test_create_user_creates_the_row_with_a_verifying_hash_and_role(engine):
    admin.create_user(engine, "newuser", "New User", "scout", "a perfectly fine passphrase")

    with Session(engine) as session:
        user = session.scalar(select(User).where(User.username == "newuser"))
        assert user is not None
        assert user.role == "scout"
        assert user.full_name == "New User"
        assert auth.verify_password("a perfectly fine passphrase", user.password_hash)


def test_create_user_rejects_an_unknown_role(engine):
    with pytest.raises(SystemExit):
        admin.create_user(engine, "newuser", "New User", "goalkeeper coach",
                          "a perfectly fine passphrase")


def test_create_user_rejects_a_duplicate_username(engine):
    with Session(engine) as session:
        session.add(User(username="jsmith", full_name="J. Smith", role="scout",
                         password_hash=auth.hash_password("original passphrase")))
        session.commit()

    with pytest.raises(SystemExit):
        admin.create_user(engine, "jsmith", "Someone Else", "scout",
                          "a perfectly fine passphrase")


def test_deactivate_user_blocks_login(engine):
    from lofc.store import users as store_users
    with Session(engine) as session:
        session.add(User(username="jsmith", full_name="J. Smith", role="scout",
                         password_hash=auth.hash_password("a perfectly fine passphrase")))
        session.commit()

    admin.deactivate_user(engine, "jsmith")

    import datetime as dt
    result = store_users.authenticate(engine, "jsmith", "a perfectly fine passphrase",
                                      dt.datetime.now())
    assert result.outcome == "inactive"


def test_reactivate_user_restores_login(engine):
    from lofc.store import users as store_users
    with Session(engine) as session:
        session.add(User(username="jsmith", full_name="J. Smith", role="scout",
                         password_hash=auth.hash_password("a perfectly fine passphrase"),
                         is_active=False))
        session.commit()

    admin.reactivate_user(engine, "jsmith")

    import datetime as dt
    result = store_users.authenticate(engine, "jsmith", "a perfectly fine passphrase",
                                      dt.datetime.now())
    assert result.outcome == "ok"


def test_deactivate_user_rejects_an_unknown_user(engine):
    with pytest.raises(SystemExit):
        admin.deactivate_user(engine, "nobody")


def test_reactivate_user_rejects_an_unknown_user(engine):
    with pytest.raises(SystemExit):
        admin.reactivate_user(engine, "nobody")


def test_deactivate_user_never_deletes_the_row(engine):
    with Session(engine) as session:
        session.add(User(username="jsmith", full_name="J. Smith", role="scout",
                         password_hash=auth.hash_password("a perfectly fine passphrase")))
        session.commit()

    admin.deactivate_user(engine, "jsmith")

    with Session(engine) as session:
        assert session.scalar(select(User).where(User.username == "jsmith")) is not None
