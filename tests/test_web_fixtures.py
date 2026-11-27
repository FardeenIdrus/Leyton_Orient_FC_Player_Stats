"""Web front end: the Fixtures page (owner 2026-11-27, phase 5) -- page shell, who may assign
scouts and link reports (head of recruitment / admin), adding a game by hand, the Excel."""
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from lofc.store import fixtures as st
from lofc.store.models import Base
from lofc.web.api import fixtures as api
from web_fakes import FakeStore, login, make

H = {"X-LOFC-Request": "1"}


def _client(role="scout"):
    s = FakeStore()
    s.add(username="u", full_name="Ann Scout", role=role, password="correct-horse-1")
    c, *_ = make(s)
    login(c, "u", "correct-horse-1")
    return c


@pytest.fixture
def db(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    monkeypatch.setattr(api, "_engine", lambda: eng)
    return eng


def _data():
    p = {"n": "Form Man", "sq": 10, "lg": 4, "pos": "Winger", "age": 24, "f": [90, 90, 90], "t5": 3, "t10": 3,
         "f5": True, "f10": False, "rise": False, "rise_by": None, "rise_from": None, "rise_to": None,
         "br": {"on": False, "before": None, "after": None}, "ov": 3.4, "rk": 2, "of": 20,
         "rep": [{"v": "Sign", "d": "2026-11-12", "s": "Ann", "g": "Orient v Bolton"}], "pri": True, "dis": False,
         "seen": True, "ns": False, "watch": None}
    return {"games": [{"key": "m:1", "at": "2026-11-29T15:00:00", "lg": "League One", "home": "Leyton Orient",
                       "away": "Bolton", "hs": 10, "as": 20, "manual": False, "assigned": 1}],
            "players": {"7": p}, "squads": {"10": {"name": "Leyton Orient"}}, "users": [{"id": 1, "name": "Ann Scout"}]}


def test_page_shell_and_nav():
    c = _client()
    r = c.get("/fixtures")
    assert r.status_code == 200 and 'id="fx-list"' in r.text and "js/fixtures.js" in r.text
    assert 'href="/fixtures"' in r.text


def test_a_scout_cannot_assign_or_link_the_head_of_recruitment_can(db):
    assert _client("scout").post("/api/fixtures/assign", json={"key": "m:1", "user_id": 1}, headers=H).status_code == 403
    assert _client("scout").post("/api/fixtures/link", json={"submission_id": "s", "player_id": 1}, headers=H).status_code == 403
    c = _client("head_of_recruitment")
    assert c.post("/api/fixtures/assign", json={"key": "m:1", "user_id": 4}, headers=H).json() == {"ok": True}
    assert st.assignments(db) == {"m:1": 4}
    assert c.post("/api/fixtures/assign", json={"key": "m:1", "user_id": None}, headers=H).json() == {"ok": True}
    assert st.assignments(db) == {}
    assert c.post("/api/fixtures/assign", json={"key": "bad", "user_id": 4}, headers=H).status_code == 400


def test_any_user_adds_a_game_in_uk_time_and_only_they_or_the_hor_remove_it(db):
    c = _client("scout")
    r = c.post("/api/fixtures/games", json={"date": "2026-12-02", "time": "19:45", "competition": "EFL Trophy",
                                            "home": {"name": "Cambridge United", "id": 10}, "away": {"name": "Brighton U21"}},
               headers=H)
    assert r.json()["ok"] is True
    row = pd.read_sql("SELECT * FROM manual_fixtures", db).iloc[0]
    assert str(row["scheduled_at"]).startswith("2026-12-02 19:45") and row["home_squad_id"] == 10   # December: UK = UTC
    assert pd.isna(row["away_squad_id"])
    assert c.post("/api/fixtures/games", json={"date": "", "home": {"name": "A"}, "away": {"name": "B"}}, headers=H).status_code == 400
    assert c.post("/api/fixtures/games", json={"date": "2026-12-02", "home": {"name": ""}, "away": {"name": "B"}}, headers=H).status_code == 400
    # added by user id 1 (the fake store's first user); another scout account is the same id here,
    # so check the HoR path and a missing game instead
    assert _client("head_of_recruitment").post(f"/api/fixtures/games/{int(row['id'])}/remove", json={}, headers=H).json() == {"ok": True}
    assert _client("head_of_recruitment").post("/api/fixtures/games/999/remove", json={}, headers=H).status_code == 404


def test_why_reads_the_same_as_the_page():
    p = _data()["players"]["7"]
    assert api.why(p) == ["Sign (2026-11-12)", "Top in 3 of last 5"]
    p2 = {**p, "rep": [], "pri": False, "f5": False, "rise": True, "rise_by": 25, "rise_from": 40, "rise_to": 65,
          "br": {"on": True, "before": 37, "after": 343}}
    assert api.why(p2) == ["Rising: avg 40% to 65% (5 games before vs last 5)",
                           "Breaking through: 37 to 343 min (5 club games before vs last 5)"]


def test_workbook_lists_games_and_their_players():
    from io import BytesIO
    from openpyxl import load_workbook
    wb = load_workbook(BytesIO(api.workbook(_data(), ["m:1"])))
    g = list(wb["Games"].values)
    assert g[1][3:6] == ("Leyton Orient", "Bolton", "Ann Scout") and "Form Man (Sign (2026-11-12))" in g[1][6]
    pl = list(wb["Players"].values)
    assert pl[1][0] == "Form Man" and pl[1][6] == "2 of 20" and "Sign 2026-11-12 (Ann)" in pl[1][7]


def test_page_script_states_what_each_signal_means_and_links_players():
    from pathlib import Path
    import lofc.web
    js = (Path(lofc.web.__file__).parent / "static" / "js" / "fixtures.js").read_text()
    assert "Rising: avg ${p.rise_from}% → ${p.rise_to}%" in js and 'title="${esc(d)}"' in js
    assert "hidden by filters" in js and "Clear filters" in js
    assert "/player/${encodeURIComponent(p.id)}" in js and "back=" in js
    assert "Also in this game: scout priorities and watchlist" in js       # never filtered out of a game
