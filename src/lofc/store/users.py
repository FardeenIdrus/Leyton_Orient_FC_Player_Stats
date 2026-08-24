"""Authentication against the users table.

USER DATA: nothing here is ever written or cleared by the pipeline.

Kept separate from `dashboard/auth.py` on purpose: `auth.py` holds pure cryptography and
permission rules with no database import, so it can be reasoned about and tested in
isolation. This module is the only place those rules meet a live row.
"""

from __future__ import annotations

import datetime
import secrets
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from lofc.dashboard.auth import (ROLES, hash_password, lockout_state, needs_rehash,
                                 next_failure_state, password_problems, verify_password)
from lofc.store.models import User

# A fixed, never-matched hash used to burn the same ~50ms of scrypt work on the
# unknown-user path as a real login spends verifying a wrong password. Built ONCE at
# import time -- building it per call would double the real cost of every login attempt
# for no benefit. Without this, `outcome` is "bad_credentials" either way but the RESPONSE
# TIME is not: an unknown username returns instantly while a known one always pays the
# scrypt cost, so an attacker can still enumerate accounts by timing the response even
# though the returned outcome string is identical. Do not remove this as "dead code" --
# its return value is discarded on purpose; it exists purely for the CPU time it costs.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(32))


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
            # No row to update, but spend the same ~50ms a real password check would cost
            # (see _DUMMY_HASH above) before returning the same outcome as a wrong
            # password -- otherwise the outcome string matches but the response TIME
            # gives away whether the username exists.
            verify_password(password, _DUMMY_HASH)
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


# --- Admin user management (the Users page, and lofc.admin's CLI commands) ---------------
#
# USER DATA (see the module docstring): nothing below is ever written or cleared by the
# pipeline. `admin.py` and the Users page both call these rather than touching `User` rows
# directly, so the two surfaces can never drift into different rules for the same action.


@dataclass(frozen=True)
class UserRow:
    """One account's administrable state. Deliberately holds no `password_hash` field --
    there is no way for a caller of `list_users` to receive one, even by accident."""

    id: int
    username: str
    full_name: str
    role: str
    is_active: bool
    locked: bool
    locked_seconds_remaining: int
    failed_logins: int
    created_at: datetime.datetime


def list_users(engine, now: datetime.datetime) -> list[UserRow]:
    """Every account, ordered by username. `now` is passed in (not read from the clock) so
    whether an account currently reads as locked is testable without sleeping -- the same
    reason `authenticate` takes `now` as a parameter."""
    with Session(engine) as session:
        rows = session.scalars(select(User).order_by(User.username)).all()
        return [_to_row(u, now) for u in rows]


def _to_row(user: User, now: datetime.datetime) -> UserRow:
    locked, remaining = lockout_state(user.failed_logins, user.locked_until, now)
    return UserRow(id=user.id, username=user.username, full_name=user.full_name,
                   role=user.role, is_active=user.is_active, locked=locked,
                   locked_seconds_remaining=remaining, failed_logins=user.failed_logins,
                   created_at=user.created_at)


def create_user(engine, username: str, full_name: str, role: str, password: str) -> int:
    """Create a new account. Raises ValueError -- never SystemExit, so this is usable from
    both the CLI (which converts it) and the Streamlit page (which shows it) -- if the role
    is unknown, the password fails `password_problems`, or the username is already taken.
    Returns the new row's id.

    The password check runs BEFORE any database write, so a rejected password never leaves
    a half-created account behind.
    """
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}; expected one of {', '.join(ROLES)}")
    problems = password_problems(password)
    if problems:
        raise ValueError("password rejected: " + "; ".join(problems))
    username = username.strip()
    if not username:
        raise ValueError("username is required")
    with Session(engine) as session:
        if session.scalar(select(User).where(User.username == username)):
            raise ValueError(f"user {username!r} already exists")
        # The password on a freshly created account is temporary by definition -- an admin
        # chose it, not the person who will use it -- so it forces a change at first login,
        # exactly like `reset_password` below.
        user = User(username=username, full_name=full_name.strip(), role=role,
                    password_hash=hash_password(password), must_change_password=True)
        session.add(user)
        session.commit()
        return user.id


def reset_password(engine, user_id: int, new_password: str) -> None:
    """Replace a user's password, clear any lockout, and force a change at next login.

    This is the ONLY password-reset route (see `lofc.admin`'s module docstring): the users
    table holds no email address, so there is no self-service reset and no token to send
    anywhere. Reusable by both the CLI's `set-password` and the Users page's "reset
    password" action -- neither reimplements this.
    """
    problems = password_problems(new_password)
    if problems:
        raise ValueError("password rejected: " + "; ".join(problems))
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.id == user_id))
        if user is None:
            raise ValueError(f"no such user id {user_id}")
        user.password_hash = hash_password(new_password)
        user.failed_logins = 0
        user.locked_until = None
        user.must_change_password = True
        session.commit()


def clear_lockout(engine, user_id: int) -> None:
    """Clear a lockout WITHOUT touching the password -- for the ordinary case of someone
    mistyping their password five times. Unlike `reset_password`, this issues no new
    temporary password and does not force a change at next login."""
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.id == user_id))
        if user is None:
            raise ValueError(f"no such user id {user_id}")
        user.failed_logins = 0
        user.locked_until = None
        session.commit()


def set_active(engine, user_id: int, active: bool) -> None:
    """Deactivate or reactivate an account. NEVER deletes a row: `ScoutAssessment` rows
    reference `users.id` via `author_id` and `approved_by`, so deleting a user who has ever
    assessed or approved anything would break that foreign key and erase the attribution the
    whole assessment system depends on. Deactivating instead blocks login (`authenticate`
    checks `is_active`) while leaving every past assessment attributed exactly as before.
    """
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.id == user_id))
        if user is None:
            raise ValueError(f"no such user id {user_id}")
        user.is_active = active
        session.commit()
