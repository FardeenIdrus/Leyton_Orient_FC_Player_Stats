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


def test_how_it_is_worked_out_explains_the_big_picture_ranks(fake):
    """Owner 2026-11-10: the fold-out says how Big picture ranks are built; the ⓘ no longer
    says "physical" only, since the table holds performance measures too."""
    html = _client().get("/club-vs-league").text
    how = html.split('id="cv-how"')[1].split("</details>")[0]
    assert ("<b>Big picture</b>: each club's average of its players' figures, weighted by "
            "minutes, then ranked 1–24. Ratings rows use rated players (450+ minutes); "
            "measure rows use every player, per 90.") in how
    assert how.index("<b>Top 6</b>") < how.index("<b>Big picture</b>") < how.index("<b>Our level</b>")
    assert ("Our rank among League One clubs on the minutes-weighted average of our players' "
            "ratings and per-90 figures.") in html
    assert "per-90 physical figures" not in html


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
    assert all(sum(v is not None and v >= 70 for v in r["weak"]) >= 2
               for l in on["recommendations"]["leagues"] for r in l["rows"])


def test_weak_metric_columns_follow_the_positions_shortfalls(fake):
    d = _client().get("/api/club-vs-league?group=Winger").json()
    sel = next(g for g in d["gaps"] if g["group"] == "Winger")
    rec = d["recommendations"]
    assert [w["metric"] for w in rec["weak_metrics"]] == [s["metric"] for s in sel["shortfalls"]]
    assert all(len(r["weak"]) == len(rec["weak_metrics"]) for l in rec["leagues"] for r in l["rows"])


def test_top6_level_badge_and_the_pages_wording(fake):
    d = _client().get("/api/club-vs-league").json()
    sel = next(g for g in d["gaps"] if g["group"] == d["selected"])
    for l in d["recommendations"]["leagues"]:
        for r in l["rows"]:
            assert r["top6_level"] == (r["overall"] >= sel["bar"]["median"])
    html = _client().get("/club-vs-league").text
    from markupsafe import escape
    for k in ("Top 6", "Our level", "Top-6 bar", "Gap", "Top-6 level", "Players who could close the gap"):
        assert str(escape(cv.TERMS[k])) in html


def test_the_recommendations_help_is_the_owners_sentence(fake):
    assert cv.TERMS["Players who could close the gap"] == (
        "Players rated above our best at this position, best first; the three right-hand columns "
        "show how each scores on the areas where we're weakest.")
    html = _client().get("/club-vs-league").text
    assert "Strong where we are weak" not in html


def test_owner_additions_vs_best_top6_filter_and_all_shortfalls(fake):
    d = _client().get("/api/club-vs-league?group=Winger").json()
    sel = next(g for g in d["gaps"] if g["group"] == "Winger")
    assert d["filters"]["top6"] is False and "all_shortfalls" in sel
    for l in d["recommendations"]["leagues"]:
        for r in l["rows"]:
            assert r["vs_best"] == cv.vs_best(r["overall"], sel["level"]["rating"])
    on = _client().get("/api/club-vs-league?group=Winger&top6=1").json()
    assert on["filters"]["top6"] is True
    assert all(r["top6_level"] for l in on["recommendations"]["leagues"] for r in l["rows"])
    assert d["terms"]["vs our best"] == ("His rating minus our best at this position; the gap is "
                                         "closed when this reaches the gap size.")   # the column's ⓘ


def test_weakness_labels_use_the_fewer_is_better_wording(fake, monkeypatch):
    from lofc.model import club_framework as cf
    monkeypatch.setattr(cf, "LOWER_IS_BETTER", {"sprint_count_p90"})
    ours = set(fake.neutral().query("team_name == 'Leyton Orient'")["player_id"])
    base = fake.pcts
    fake.pcts = lambda season: base(season).assign(
        sprint_count_p90=lambda f: f["player_id"].map(lambda p: 10.0 if p in ours else 60.0))
    api.clear()
    d = _client().get("/api/club-vs-league?group=Winger").json()
    sel = next(g for g in d["gaps"] if g["group"] == "Winger")
    labels = [s["label"] for s in sel["shortfalls"]] + [w["label"] for w in d["recommendations"]["weak_metrics"]]
    assert labels and all(l == "Sprints (fewer is better)" for l in labels)
    assert [b for b in d["big_picture"] if b["measure"] == "sprint_count_p90"][0]["label"] == "Sprints"
