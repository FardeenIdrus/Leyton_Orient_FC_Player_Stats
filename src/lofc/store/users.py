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
