"""The web Glossary: the Streamlit page's own entries (`glossary_data.glossary_entries`), its
intro line and "In rating" set; search is the same name-or-definition match (`tabs.glossary.search`)."""
import pytest

from lofc.dashboard import glossary_data as gd
from lofc.dashboard.tabs import glossary as g
from web_fakes import FakeStore, login, make

ENTRIES = [
    {"key": "ball_wins_p90", "label": "Ball wins", "group": "Performance", "source": "Impect",
     "text": "Winning the ball **back**."},
    {"key": "sprint_count_p90", "label": "Sprints", "group": "Physical", "source": "SkillCorner",
     "text": "Runs above 25 km/h."},
    {"key": "x", "label": "<b>Odd</b>", "group": "Impect scores", "source": "Impect", "text": "a"},
]


def _client():
    s = FakeStore()
    s.add(username="u", full_name="Ann Scout", role="scout", password="correct-horse-1")
    c, *_ = make(s)
    login(c, "u", "correct-horse-1")
    return c


@pytest.fixture(autouse=True)
def _entries(monkeypatch):
    from lofc.web.api import reference as api
    monkeypatch.setattr(api, "_glossary_entries", lambda: ENTRIES)
    monkeypatch.setattr(gd, "rating_metrics", lambda: {"ball_wins_p90"})
    monkeypatch.setattr(g, "rating_metrics", lambda: {"ball_wins_p90"})


def test_page_shell():
    r = _client().get("/glossary")
    assert r.status_code == 200 and "/js/glossary.js" in r.text and "Currently building" not in r.text


def test_api_needs_login():
    c, *_ = make(FakeStore())
    assert c.get("/api/glossary").status_code == 401


def test_entries_groups_and_rating_flag():
    d = _client().get("/api/glossary").json()
    assert d["groups"] == gd.GROUPS + ["Club vs League One"]
    assert d["intro"] == g.intro_caption()
    provider = [e for e in d["entries"] if e["group"] != "Club vs League One"]
    assert [e["label"] for e in provider] == ["<b>Odd</b>", "Ball wins", "Sprints"]   # A-Z, raw text
    assert [e["in_rating"] for e in provider] == [False, True, False]
    assert d["entries"][1]["text"] == "Winning the ball **back**."


def test_club_vs_league_terms_are_searchable_with_the_pages_wording():
    from lofc.core import club_vs_league as cv
    d = _client().get("/api/glossary").json()
    terms = {e["label"]: e["text"] for e in d["entries"] if e["group"] == "Club vs League One"}
    assert {"Our level", "Top-6 bar", "Gap", "Top-6 level"} <= set(terms)
    for k, v in cv.TERMS.items():
        assert terms[k] == v
