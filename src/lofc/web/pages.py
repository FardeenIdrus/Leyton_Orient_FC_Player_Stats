"""Navigation and page registry: the single list the nav rail and the routes are built from,
so a page cannot exist in one and not the other. Order and wording follow mockup v5's <nav>."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Page:
    key: str         # highlighted via `nav a.on`; also the template variable `active`
    path: str
    title: str       # nav label and page heading
    group: str


# (group, [(key, path, title), ...]) -- Admin is filtered by permission in `nav_for`.
_NAV: list[tuple[str, list[tuple[str, str, str]]]] = [
    ("Find", [("players", "/players", "Players"), ("squads", "/squads", "Squads & loans")]),
    ("Assess a player", [("compare", "/compare", "Compare"),
                         ("scout-reports", "/scout-reports", "Scout reports")]),
    ("Decide", [("watchlist", "/watchlist", "Watchlist"), ("report", "/report", "Report"),
                ("assess", "/assess", "Assess"), ("sign-off", "/sign-off", "Sign-off")]),
    ("Analysis", [("physical", "/physical", "Physical"),
                  ("club-vs-league", "/club-vs-league", "Club vs League One")]),
    ("Reference", [("rating-reference", "/rating-reference", "What goes into each rating"),
                   ("playing-styles", "/playing-styles", "How playing styles work"),
                   ("glossary", "/glossary", "Glossary")]),
    ("Admin", [("users", "/users", "Users")]),
]

PAGES: dict[str, Page] = {
    key: Page(key, path, title, group)
    for group, items in _NAV for key, path, title in items}

# Pages only some roles may open: key -> the `auth.can` action required.
PERMISSION_FOR: dict[str, str] = {"users": "manage_users"}


def nav_for(role: str, can) -> list[tuple[str, list[Page]]]:
    """The nav groups this role sees. `can` is `lofc.dashboard.auth.can`; a page with a
    required permission is dropped, and a group left empty is dropped with it."""
    out = []
    for group, items in _NAV:
        pages = [PAGES[k] for k, _, _ in items
                 if k not in PERMISSION_FOR or can(role, PERMISSION_FOR[k])]
        if pages:
            out.append((group, pages))
    return out
