"""User administration CLI. There is deliberately no self-service signup.

    python -m lofc.admin create-user --username fi --name "..." --role admin
    python -m lofc.admin set-password --username fi
    python -m lofc.admin deactivate-user --username fi
    python -m lofc.admin reactivate-user --username fi
    python -m lofc.admin list-users

Every write here goes through `store.users` -- the SAME functions the dashboard's admin
Users page calls -- so the CLI and the browser page can never enforce different rules for
the same action. This module's job is only: parse args, prompt for a password without
echoing it, and turn a `ValueError` from `store.users` into a `SystemExit` with the same
message (a CLI failure is a nonzero exit + stderr, not a raised exception).
"""

from __future__ import annotations

import argparse
import datetime
import getpass
import sys

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from lofc.config import settings
from lofc.dashboard.auth import ROLES
from lofc.model import user_admin
from lofc.store import users as store_users
from lofc.store.models import User


def _engine():
    # hide_parameters: an IntegrityError from an insert would otherwise print the failing
    # statement's bound parameters -- including the salt and password hash -- to stderr.
    # Not plaintext, but there is no reason for either to appear in a terminal or log.
    return create_engine(settings.database_url, hide_parameters=True)


def _user_id_for(engine, username: str) -> int:
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.username == username))
        if user is None:
            raise SystemExit(f"no such user {username!r}")
        return user.id


def create_user(engine, username: str, full_name: str, role: str, password: str) -> None:
    try:
        store_users.create_user(engine, username, full_name, role, password)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"created {role} {username!r}")


def set_password(engine, username: str, password: str) -> None:
    """Replace a user's password, clear any lockout, and require a change at next login.

    This is the ONLY password-reset route: the users table holds no email address, so there
    is no self-service reset and no token to send anywhere. An admin does this in person.
    """
    user_id = _user_id_for(engine, username)
    try:
        store_users.reset_password(engine, user_id, password)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"password set for {username!r}; they must change it at next login")


def deactivate_user(engine, username: str) -> None:
    """Block an account from signing in. Never deletes the row -- see
    `store.users.set_active`. Unlike the Users page, the CLI runs as whoever has a shell on
    the server, not as a signed-in user, so there is no "who is doing this" identity to check
    `user_admin.guard_deactivate` against here; the guard against self-lockout applies to
    the browser page, where the actor is known.
    """
    user_id = _user_id_for(engine, username)
    store_users.set_active(engine, user_id, False)
    print(f"deactivated {username!r}")


def reactivate_user(engine, username: str) -> None:
    user_id = _user_id_for(engine, username)
    store_users.set_active(engine, user_id, True)
    print(f"reactivated {username!r}")


def list_users(engine) -> None:
    """Print every account and its state. No hashes are printed."""
    rows = store_users.list_users(engine, datetime.datetime.now())
    if not rows:
        print("no users")
        return
    print(f"{'username':<16} {'name':<24} {'role':<20} {'status':<12} lockout")
    for r in rows:
        status = user_admin.account_status_label(r.is_active)
        lockout = user_admin.lockout_label(r.locked, r.locked_seconds_remaining)
        print(f"{r.username:<16} {r.full_name:<24} {r.role:<20} {status:<12} {lockout}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage platform users")
    sub = parser.add_subparsers(dest="command", required=True)

    new = sub.add_parser("create-user")
    new.add_argument("--username", required=True)
    new.add_argument("--name", required=True)
    new.add_argument("--role", required=True, choices=ROLES)

    reset = sub.add_parser("set-password")
    reset.add_argument("--username", required=True)

    deact = sub.add_parser("deactivate-user")
    deact.add_argument("--username", required=True)

    react = sub.add_parser("reactivate-user")
    react.add_argument("--username", required=True)

    sub.add_parser("list-users")
    args = parser.parse_args()

    if args.command == "list-users":
        list_users(_engine())
        return
    if args.command == "deactivate-user":
        deactivate_user(_engine(), args.username)
        return
    if args.command == "reactivate-user":
        reactivate_user(_engine(), args.username)
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
