"""Authentication against the users table. In-memory sqlite; no live Postgres, no network."""

import datetime as dt
import hashlib
import secrets

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


def test_the_unknown_user_path_still_pays_the_password_check_cost(engine, monkeypatch):
    """Finding 1: the outcome string is identical for an unknown user and a wrong password,
    but if the unknown-user branch skipped the hash check entirely, the RESPONSE TIME would
    still give away which usernames exist. Pin the mechanism (verify_password is actually
    invoked, against the fixed dummy hash) rather than a wall-clock duration -- timing
    assertions are flaky."""
    calls = []
    real_verify = store_users.verify_password

    def counting_verify(password, stored):
        calls.append(stored)
        return real_verify(password, stored)

    monkeypatch.setattr(store_users, "verify_password", counting_verify)
    store_users.authenticate(engine, "nobody", GOOD, NOW)
    assert calls == [store_users._DUMMY_HASH]


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


def test_an_inactive_user_with_a_wrong_password_gets_bad_credentials_not_inactive(engine):
    """Finding 2: the ORDER of the is_active and password checks matters, not just that both
    exist. If is_active were checked first, a wrong password against an inactive account
    would still come back 'inactive' -- telling an attacker holding nothing but a guess that
    the account exists, even though it is deactivated. Checking the password first means a
    wrong password against an inactive account looks identical to a wrong password anywhere
    else."""
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.username == "jsmith"))
        user.is_active = False
        session.commit()
    result = store_users.authenticate(engine, "jsmith", "the wrong passphrase", NOW)
    assert result.outcome == "bad_credentials"


def test_a_stale_hash_is_upgraded_on_a_successful_login(engine):
    """Finding 3: the needs_rehash upgrade path (store/users.py) is otherwise never reached
    by any test, so it could be silently removed or moved without a test noticing. Build a
    hash under non-current scrypt parameters (auth._N_MIN is in-range and cheap), log in
    with it, and confirm the stored hash changed, still verifies the same password, and no
    longer needs a rehash."""
    stale_n, stale_r, stale_p = auth._N_MIN, 8, 1
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(GOOD.encode("utf-8"), salt=salt, n=stale_n, r=stale_r, p=stale_p,
                            dklen=32, maxmem=128 * 1024 * 1024)
    stale_hash = f"scrypt${stale_n}${stale_r}${stale_p}${salt.hex()}${digest.hex()}"
    assert auth.verify_password(GOOD, stale_hash)
    assert auth.needs_rehash(stale_hash)

    with Session(engine) as session:
        user = session.scalar(select(User).where(User.username == "jsmith"))
        user.password_hash = stale_hash
        session.commit()
        user_id = user.id

    result = store_users.authenticate(engine, "jsmith", GOOD, NOW)
    assert result.outcome == "ok"

    with Session(engine) as session:
        user = session.scalar(select(User).where(User.id == user_id))
        assert user.password_hash != stale_hash
        assert auth.verify_password(GOOD, user.password_hash)
        assert not auth.needs_rehash(user.password_hash)


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


# --- Admin user management: list_users / create_user / reset_password / clear_lockout /
# set_active -- the functions the Users page and lofc.admin's CLI both call. ----------------


def test_list_users_reports_every_account_with_no_password_hash():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(User(username="jsmith", full_name="J. Smith", role="scout",
                         password_hash=auth.hash_password(GOOD)))
        session.commit()

    rows = store_users.list_users(engine, NOW)
    assert len(rows) == 1
    row = rows[0]
    assert row.username == "jsmith"
    assert row.full_name == "J. Smith"
    assert row.role == "scout"
    assert row.is_active is True
    assert row.locked is False
    assert not hasattr(row, "password_hash")


def test_list_users_reports_a_currently_locked_account():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(User(username="jsmith", full_name="J. Smith", role="scout",
                         password_hash=auth.hash_password(GOOD),
                         failed_logins=5, locked_until=NOW + dt.timedelta(minutes=5)))
        session.commit()

    row = store_users.list_users(engine, NOW)[0]
    assert row.locked is True
    assert row.locked_seconds_remaining > 0


def test_list_users_reports_an_expired_lock_as_not_locked():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(User(username="jsmith", full_name="J. Smith", role="scout",
                         password_hash=auth.hash_password(GOOD),
                         failed_logins=5, locked_until=NOW - dt.timedelta(minutes=1)))
        session.commit()

    row = store_users.list_users(engine, NOW)[0]
    assert row.locked is False


def test_create_user_creates_a_row_that_can_then_authenticate(engine):
    new_id = store_users.create_user(engine, "newscout", "New Scout", "scout", GOOD)
    assert isinstance(new_id, int)
    result = store_users.authenticate(engine, "newscout", GOOD, NOW)
    assert result.outcome == "ok"
    assert result.role == "scout"


def test_create_user_rejects_a_weak_password_before_writing_a_row(engine):
    with pytest.raises(ValueError):
        store_users.create_user(engine, "newscout", "New Scout", "scout", "short")
    with Session(engine) as session:
        assert session.scalar(select(User).where(User.username == "newscout")) is None


def test_create_user_rejects_an_unknown_role(engine):
    with pytest.raises(ValueError):
        store_users.create_user(engine, "newscout", "New Scout", "goalkeeper coach", GOOD)


def test_create_user_rejects_a_duplicate_username(engine):
    with pytest.raises(ValueError):
        store_users.create_user(engine, "jsmith", "Someone Else", "scout", GOOD)


def test_create_user_forces_a_password_change_at_first_login(engine):
    """The password on a freshly created account is temporary by definition -- an admin
    chose it, not the person who will use it -- so it must force a change at first login,
    the same way reset_password does."""
    new_id = store_users.create_user(engine, "newscout", "New Scout", "scout", GOOD)
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.id == new_id))
        assert user.must_change_password is True


def test_reset_password_replaces_the_hash_clears_lockout_and_forces_a_change(engine):
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.username == "jsmith"))
        user.failed_logins = 5
        user.locked_until = NOW + dt.timedelta(minutes=15)
        session.commit()
        user_id = user.id

    store_users.reset_password(engine, user_id, "a replacement passphrase")

    with Session(engine) as session:
        user = session.scalar(select(User).where(User.id == user_id))
        assert auth.verify_password("a replacement passphrase", user.password_hash)
        assert not auth.verify_password(GOOD, user.password_hash)
        assert user.failed_logins == 0
        assert user.locked_until is None
        assert user.must_change_password is True


def test_reset_password_rejects_a_weak_password(engine):
    with Session(engine) as session:
        user_id = session.scalar(select(User).where(User.username == "jsmith")).id
    with pytest.raises(ValueError):
        store_users.reset_password(engine, user_id, "short")


def test_reset_password_rejects_an_unknown_user_id(engine):
    with pytest.raises(ValueError):
        store_users.reset_password(engine, 999999, GOOD)


def test_clear_lockout_clears_state_without_touching_the_password_or_must_change(engine):
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.username == "jsmith"))
        original_hash = user.password_hash
        user.failed_logins = 5
        user.locked_until = NOW + dt.timedelta(minutes=15)
        # Pinned explicitly rather than relying on the column's default: clear_lockout must
        # leave must_change_password exactly as it found it either way.
        user.must_change_password = False
        session.commit()
        user_id = user.id

    store_users.clear_lockout(engine, user_id)

    with Session(engine) as session:
        user = session.scalar(select(User).where(User.id == user_id))
        assert user.failed_logins == 0
        assert user.locked_until is None
        assert user.password_hash == original_hash
        assert user.must_change_password is False


def test_clear_lockout_rejects_an_unknown_user_id(engine):
    with pytest.raises(ValueError):
        store_users.clear_lockout(engine, 999999)


def test_set_active_false_blocks_login(engine):
    with Session(engine) as session:
        user_id = session.scalar(select(User).where(User.username == "jsmith")).id

    store_users.set_active(engine, user_id, False)

    assert store_users.authenticate(engine, "jsmith", GOOD, NOW).outcome == "inactive"


def test_set_active_true_restores_login(engine):
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.username == "jsmith"))
        user.is_active = False
        session.commit()
        user_id = user.id

    store_users.set_active(engine, user_id, True)

    assert store_users.authenticate(engine, "jsmith", GOOD, NOW).outcome == "ok"


def test_set_active_never_deletes_the_row(engine):
    """Deactivate, never delete: assessments reference users.id via author_id/approved_by,
    so the row -- and its id -- must still exist afterwards."""
    with Session(engine) as session:
        user_id = session.scalar(select(User).where(User.username == "jsmith")).id

    store_users.set_active(engine, user_id, False)

    with Session(engine) as session:
        assert session.scalar(select(User).where(User.id == user_id)) is not None


def test_set_active_rejects_an_unknown_user_id(engine):
    with pytest.raises(ValueError):
        store_users.set_active(engine, 999999, True)
