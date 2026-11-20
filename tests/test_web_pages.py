"""Web front end: the shell (nav, info bar, page routes)."""

import re

import pytest

from lofc.web import pages
from web_fakes import FakeStore, login, make

# Every nav page is a real page now. Assess and Sign-off are retired (owner 2026-11-16: scouts
# report through the JotForm sheet, never the platform): their old links go to Players.
RETIRED = ["/assess", "/sign-off", "/signoff",
           "/assess?player=1&competition=5&season=318"]


def _client(role="scout", name="Ann Scout"):
    s = FakeStore()
    s.add(username="u", full_name=name, role=role, password="correct-horse-1")
    c, *_ = make(s)
    login(c, "u", "correct-horse-1")
    return c


@pytest.mark.parametrize("path", RETIRED)
def test_retired_assess_and_signoff_redirect_to_players(path):
    r = _client().get(path, follow_redirects=False)
    assert r.status_code in (301, 302, 303, 307, 308) and r.headers["location"] == "/players"


def test_no_page_is_a_placeholder_any_more():
    assert not {"assess", "sign-off"} & set(pages.PAGES)
    assert all(p.path not in ("/assess", "/sign-off") for p in pages.PAGES.values())


def test_users_page_exists_for_admin_and_is_403_for_others():
    assert _client("admin").get("/users").status_code == 200
    r = _client("scout").get("/users")
    assert r.status_code == 403 and "Your role cannot open this page" in r.text


NAV_LABELS = ["Players", "Squads &amp; loans", "Compare", "Similar players", "Scout reports", "Watchlist", "Report",
              "Physical", "Club vs League One", "What goes into each rating",
              "How playing styles work", "Glossary"]


def test_nav_matches_the_mockup_groups_and_links():
    html = _client("admin").get("/players").text
    nav = html.split("<nav>")[1].split("</nav>")[0]
    groups = re.findall(r'<div class="group">([^<]+)</div>', nav)
    assert groups == ["Find", "Assess a player", "Decide", "Analysis", "Reference", "Admin"]
    links = re.findall(r'<a href="/[a-z-]+"[^>]*>([^<]+)</a>', nav)
    assert links == NAV_LABELS + ["Users", "Sign out"]   # Sign out sits at the foot


@pytest.mark.parametrize("role,sees", [("scout", False), ("medical", False),
                                       ("head_of_recruitment", False), ("admin", True)])
def test_users_link_only_for_manage_users_roles(role, sees):
    html = _client(role).get("/players").text
    assert ('href="/users"' in html) is sees
    assert ('<div class="group">Admin</div>' in html) is sees


def test_signed_in_user_and_signout_at_bottom_of_nav():
    html = _client("head_of_recruitment").get("/players").text
    assert "<b>Ann Scout</b>Head of recruitment" in html and 'id="signout"' in html


def test_info_bar_shows_counts():
    html = _client().get("/players").text
    assert '<div class="infobar"' in html and "<b>4,376</b> players" in html and "<b>7</b> leagues" in html


def test_user_name_is_escaped_in_the_layout():
    html = _client(name='<script>alert(1)</script>"x').get("/players").text
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_no_inline_script_or_event_handlers_or_cdn():
    html = _client("admin").get("/players").text
    assert not re.search(r"<script(?![^>]*\bsrc=)", html)
    assert not re.search(r"\son[a-z]+=", html)
    assert "googleapis" not in html and "cdn" not in html.lower()


def test_static_assets_served():
    c = _client()
    for p in ("/static/css/app.css", "/static/js/common.js", "/static/js/shell.js"):
        assert c.get(p).status_code == 200
    css = c.get("/static/css/app.css").text
    for token in (".c4", ".c0", ".pill", ".pb", ".tiles", ".pitch", ".legend", ".rkey", ".seg",
                  ".switch", ".notice", "--orient:#1F5FA8", "--nav:#14161B"):
        assert token in css
