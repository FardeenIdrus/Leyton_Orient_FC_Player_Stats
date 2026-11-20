"""Web: the card's "Similar players" endpoint, the Similar players page (/similar/...) and its
JSON (no database: the data layer is faked). The method is tested in test_core_similar.py; the
real database in test_similar_real.py."""
import re
from pathlib import Path

import pytest

from lofc.web.api import card as card_api
from lofc.web.api import similar as similar_api
from web_fakes import FakeStore, login, make

URL = "/api/card/52123/4/318/similar"
PAGE_API = "/api/similar/52123/4/318"
PAGE = "/similar/52123/4/318"
STATIC = Path(__file__).resolve().parents[1] / "src" / "lofc" / "web" / "static"


def _client():
    s = FakeStore()
    s.add(username="u", full_name="Ann Scout", role="scout", password="correct-horse-1")
    c, *_ = make(s)
    login(c, "u", "correct-horse-1")
    return c


class FakeSimilar:
    def __init__(self):
        self.calls = []
        self.page_calls = []

    def section(self, p, c, s, scope="league", max_age=None, league=None, min_minutes=None,
                contract=None):
        self.calls.append((p, c, s, scope, max_age, league, min_minutes, contract))
        return {"heading": "Similar players", "available": True, "scope": scope,
                "max_age": max_age, "rows": [{"name": "A"}]}

    def page(self, p, c, s, scope="league", max_age=None, league=None, min_minutes=None,
             contract=None, match=None):
        self.page_calls.append((p, c, s, scope, max_age, league, min_minutes, contract, match))
        return {"heading": "Similar players", "available": True, "rows": [{"name": "A"}],
                "selected": match, "breakdown": {"rows": []}}


@pytest.fixture
def fake(monkeypatch):
    f = FakeSimilar()
    monkeypatch.setattr(card_api, "_similar", lambda: f)
    monkeypatch.setattr(similar_api, "_similar", lambda: f)
    return f


# --- the card section's endpoint ------------------------------------------------------------
def test_similar_needs_a_session(fake):
    c, *_ = make()
    assert c.get(URL).status_code == 401
    assert fake.calls == []


def test_similar_defaults_to_same_league_and_no_filters(fake):
    r = _client().get(URL)
    assert r.status_code == 200
    assert fake.calls == [(52123, 4, 318, "league", None, None, None, None)]
    assert r.json()["rows"] == [{"name": "A"}]


def test_similar_passes_every_filter(fake):
    _client().get(URL + "?scope=all&max_age=23&league=5&min_minutes=1350&contract=6")
    assert fake.calls[-1] == (52123, 4, 318, "all", 23, 5, 1350, 6)


@pytest.mark.parametrize("q", ["?scope=everything", "?max_age=abc", "?max_age=-4", "?max_age=999",
                               "?league=abc", "?league=-3", "?min_minutes=77", "?min_minutes=x",
                               "?contract=7", "?contract=%00", "?min_minutes=1e9"])
def test_similar_ignores_bad_values(fake, q):
    assert _client().get(URL + q).status_code == 200
    _p, _c, _s, scope, age, league, mins, contract = fake.calls[-1]
    assert scope == "league" and age is None and league is None and mins is None and contract is None


def test_page_shell_has_the_section_the_button_and_the_filters():
    html = _client().get("/player/52123/4/318").text
    assert 'id="c-similar"' in html and ">Similar players<" in html
    assert 'id="h-similar"' in html and "Find similar" in html
    for i in ("sim-scope", "sim-age", "sim-league", "sim-min", "sim-contract", "sim-how"):
        assert f'id="{i}"' in html, i
    assert "How these are matched →" in html


def test_card_script_links_rows_and_the_section_to_the_page():
    js = (STATIC / "js" / "card.js").read_text()
    assert "/similar/${KEY}" in js and "match:" in js and ">Why<" in js


# --- the Similar players page -----------------------------------------------------------------
@pytest.mark.parametrize("path", [PAGE_API, PAGE_API + "?match=1-2"])
def test_page_api_needs_a_session(fake, path):
    c, *_ = make()
    assert c.get(path).status_code == 401
    assert fake.page_calls == []


def test_page_needs_a_session_and_is_highlighted_in_the_nav():
    c, *_ = make()
    assert c.get(PAGE).status_code == 303
    html = _client().get(PAGE).text
    assert re.search(r'<script type="module" src="/static/v/[0-9a-f]+/js/similar.js">', html)
    assert not re.search(r"<script(?![^>]*\bsrc=)", html) and not re.search(r"\son[a-z]+=", html)
    nav = html.split("<nav", 1)[1].split("</nav>", 1)[0]
    assert re.search(r'<a href="/similar" class="on"', nav)          # owner 2026-11-20: own page
    for i in ("sim-scope", "sim-age", "sim-league", "sim-min", "sim-contract", "sim-list",
              "sim-break", "sim-player"):
        assert f'id="{i}"' in html, i
    assert 'data-player="52123"' in html and 'data-competition="4"' in html and 'data-season="318"' in html


def test_page_api_passes_filters_and_the_match(fake):
    r = _client().get(PAGE_API + "?scope=all&max_age=25&league=3&min_minutes=900&contract=12&match=777-3")
    assert r.status_code == 200
    assert fake.page_calls[-1] == (52123, 4, 318, "all", 25, 3, 900, 12, "777-3")
    assert r.json()["selected"] == "777-3"


@pytest.mark.parametrize("q", ["?match=abc", "?match=1-2-3", "?match=", "?match=%ff%fe",
                               "?scope=x&league=y&min_minutes=z&contract=w&max_age=q"])
def test_page_api_junk_never_errors(fake, q):
    r = _client().get(PAGE_API + q)
    assert r.status_code == 200
    _p, _c, _s, scope, age, league, mins, contract, match = fake.page_calls[-1]
    assert scope == "league" and age is None and league is None and mins is None and contract is None
    assert match is None


def test_page_script_draws_the_breakdown_and_the_compare_link():
    js = (STATIC / "js" / "similar.js").read_text()
    assert "compare_href" in js and "not used" in js and "linked" in js
    html = _client().get(PAGE).text
    assert 'id="sim-compare"' in html and ">Open in Compare<" in html


def test_similar_page_in_the_nav_opens_with_a_player_search():
    """Owner 2026-11-20: Similar players is its own page in the sidebar: search any player of a
    season, then his list and breakdown (the card's links still open it on a player)."""
    c, *_ = make()
    assert c.get("/similar").status_code == 303
    html = _client().get("/similar").text
    nav = html.split("<nav", 1)[1].split("</nav>", 1)[0]
    assert re.search(r'<a href="/similar" class="on"[^>]*>Similar players</a>', nav)
    for i in ("sim-search", "sim-results", "sim-season"):
        assert f'id="{i}"' in html, i
    assert 'data-player=""' in html
    assert re.search(r'<script type="module" src="/static/v/[0-9a-f]+/js/similar.js">', html)


def test_page_script_searches_players_without_ids():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / "src/lofc/web/static/js/similar.js").read_text()
    assert "/api/report/players" in js and "filterRows" in js
    assert "location.href = `/similar/" in js or "location.assign(`/similar/" in js
