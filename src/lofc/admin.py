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
from lofc.dashboard.auth import ROLES, hash_password
from lofc.store.models import User


def create_user(username: str, full_name: str, role: str, password: str) -> None:
    if role not in ROLES:
        raise SystemExit(f"unknown role {role!r}; expected one of {', '.join(ROLES)}")
    # hide_parameters: an IntegrityError from the insert below would otherwise print the
    # failing statement's bound parameters -- including the salt and password hash -- to
    # stderr. Not plaintext, but there is no reason for either to appear in a terminal or log.
    engine = create_engine(settings.database_url, hide_parameters=True)
    with Session(engine) as session:
        if session.scalar(select(User).where(User.username == username)):
            raise SystemExit(f"user {username!r} already exists")
        session.add(User(username=username, full_name=full_name, role=role,
                         password_hash=hash_password(password)))
        session.commit()
    print(f"created {role} {username!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage platform users")
    sub = parser.add_subparsers(dest="command", required=True)
    new = sub.add_parser("create-user")
    new.add_argument("--username", required=True)
    new.add_argument("--name", required=True)
    new.add_argument("--role", required=True, choices=ROLES)
    args = parser.parse_args()

    if args.command == "create-user":
        if not sys.stdin.isatty():
            # Without a TTY, getpass degrades to echoing the password to the terminal (with
            # a warning) instead of hiding it -- refuse rather than display it.
            raise SystemExit("refusing to prompt for a password on a non-interactive stdin")
        password = getpass.getpass("password: ")
        if not password:
            raise SystemExit("empty password")
        create_user(args.username, args.name, args.role, password)


if __name__ == "__main__":
    main()
