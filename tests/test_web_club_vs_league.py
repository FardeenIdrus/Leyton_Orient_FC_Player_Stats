"""The web "Club vs League One" page: shell, login, and the API's shape on fake frames.
Real-database parity: tests/test_web_club_vs_league_parity.py."""
import types

import pandas as pd
import pytest

from lofc.core import club_vs_league as cv
from lofc.web.api import club_vs_league as api
from web_fakes import FakeStore, login, make

CUR, PREV = 319, 318
CLUBS = ["Leyton Orient"] + [f"Club {c}" for c in "ABCDEFGH"]


def _frames():
    cards, neutral, pid = [], [], 100
    for season in (CUR, PREV):
        for k, club in enumerate(CLUBS):
            for pos in ("Winger", "Centre Back", "Central Mid"):
                pid += 1
                ovr = 2.5 + k * 0.15
                cards.append((pid, 4, season, pos, ovr, ovr, 3.0))
                neutral.append((pid, 4, season, 900.0, club, f"<{club}> {pos} {season}", 10.0 + k))
    cards.append((900, 5, CUR, "Winger", 4.9, 4.0, 4.0))
    neutral.append((900, 5, CUR, 1200.0, "League Two side", "L2 star", 9.0))
    c = pd.DataFrame(cards, columns=["player_id", "competition_id", "season_id", "position_group",
                                     "objective_composite", "performance_band", "physical_band"])
    n = pd.DataFrame(neutral, columns=["player_id", "competition_id", "season_id", "minutes",
                                       "team_name", "player_name", "sprint_count_p90"])
    return c, n


@pytest.fixture
def fake(monkeypatch):
    cards, neutral = _frames()
    ours = neutral[(neutral.team_name == "Leyton Orient") & (neutral.season_id == CUR)]
    squad = ours.rename(columns={})[["player_id", "player_name"]].assign(
        position_group=["Winger", "Centre Back", "Central Mid"])
    keys = ["player_id", "competition_id", "season_id"]
    pcts = cards[keys + ["position_group"]].assign(sprint_count_p90=50.0)
    src = types.SimpleNamespace(
        seasons=lambda: (CUR, PREV), season_name=lambda s: {CUR: "2026/27", PREV: "2025/26"}[s],
        cards=lambda: cards, neutral=lambda: neutral, squad=lambda: squad,
        pcts=lambda s: pcts[pcts.season_id == s],
        candidates=lambda s: cards[cards.season_id == s][keys].assign(age=24.0, contract_until=pd.NaT),
        league_names=lambda: {3: "Championship", 4: "League One", 5: "League Two"},
        metrics=lambda pos: ["sprint_count_p90"], physical=["sprint_count_p90"],
        label=lambda m: {"sprint_count_p90": "Sprints"}.get(m, m),
        watched=lambda: {(900, 5, CUR)})
    monkeypatch.setattr(api, "_sources", lambda: src)
    api.clear()
    yield src
    api.clear()


def _client():
    s = FakeStore()
    s.add(username="u", full_name="Ann Scout", role="scout", password="correct-horse-1")
    c, *_ = make(s)
    login(c, "u", "correct-horse-1")
    return c


def test_page_shell_and_nav_entry(fake):
    r = _client().get("/club-vs-league")
    assert r.status_code == 200 and "/js/club_vs_league.js" in r.text
    assert "Where we fall short of a top-6 League One side this season, and who could close the gap." in r.text
    assert 'href="/club-vs-league"' in r.text and "Club vs League One" in r.text


def test_api_needs_login():
    c, *_ = make(FakeStore())
    assert c.get("/api/club-vs-league").status_code == 401


def test_payload(fake):
    d = _client().get("/api/club-vs-league").json()
    assert d["season"] == "2026/27" and d["prev_season"] == "2025/26"
    assert [t["club"] for t in d["top6"]] == [f"Club {c}" for c in "HGFEDC"]
    assert d["orient"] == {"rank": 9, "of": 9, "text": "9th of 9"}
    groups = [g["group"] for g in d["gaps"]]
    assert set(groups) == set(cv.GROUPS)
    first = d["gaps"][0]
    assert first["gap"] is not None and first["bar"]["players"][0]["club"] == "Club H"
    assert d["selected"] == first["group"]
    rec = d["recommendations"]
    assert rec["group"] == d["selected"] and rec["leagues"][0]["league"] == "League One"
    assert all(r["overall"] > first["level"]["rating"] for r in rec["leagues"][0]["rows"])
    assert [b["measure"] for b in d["big_picture"]][:3] == ["Overall", "Performance", "Physical"]


def test_group_and_filters_follow_the_url(fake):
    d = _client().get("/api/club-vs-league?group=Winger&age=u21").json()
    assert d["selected"] == "Winger" and d["filters"]["age"] == "u21"
    assert all(not l["rows"] for l in d["recommendations"]["leagues"]) or d["recommendations"]["leagues"] == []
    d2 = _client().get("/api/club-vs-league?group=Nonsense&contract=bad").json()
    assert d2["selected"] == d2["gaps"][0]["group"] and d2["filters"]["contract"] == ""


def test_watched_flag_and_card_links(fake):
    d = _client().get("/api/club-vs-league?group=Winger").json()
    l2 = next(l for l in d["recommendations"]["leagues"] if l["league"] == "League Two")
    row = l2["rows"][0]
    assert row["name"] == "L2 star" and row["watched"] is True and row["href"] == "/player/900/5/319"


def test_no_financial_figures_anywhere(fake):
    text = _client().get("/api/club-vs-league").text.lower()
    for word in ("market", "fee", "wage", "value_eur", "budget"):
        assert word not in text


def test_strong_filter_is_off_by_default_and_follows_the_url(fake):
    d = _client().get("/api/club-vs-league?group=Winger").json()
    assert d["filters"]["strong"] is False
    on = _client().get("/api/club-vs-league?group=Winger&strong=1").json()
    assert on["filters"]["strong"] is True
    assert all(len(r["tags"]) >= 2 for l in on["recommendations"]["leagues"] for r in l["rows"])


def test_top6_level_badge_and_the_pages_wording(fake):
    d = _client().get("/api/club-vs-league").json()
    sel = next(g for g in d["gaps"] if g["group"] == d["selected"])
    for l in d["recommendations"]["leagues"]:
        for r in l["rows"]:
            assert r["top6_level"] == (r["overall"] >= sel["bar"]["median"])
    html = _client().get("/club-vs-league").text
    from markupsafe import escape
    for k in ("Top 6", "Our level", "Top-6 bar", "Gap", "Top-6 level"):
        assert str(escape(cv.TERMS[k])) in html
