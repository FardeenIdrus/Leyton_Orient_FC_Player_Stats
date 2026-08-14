"""User administration CLI. There is deliberately no self-service signup.

    python -m lofc.admin create-user --username fi --name "..." --role admin
"""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from lofc.config import settings
from lofc.dashboard.auth import ROLES, hash_password, password_problems
from lofc.store.models import User


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


if __name__ == "__main__":
    main()
