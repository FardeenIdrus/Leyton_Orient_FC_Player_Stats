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
                       "away": "Bolton", "hs": 10, "as": 20, "manual": False, "assigned": 1, "scout": "Ann Scout"}],
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
    assert st.assignments(db) == {"m:1": {"user_id": 4, "name": None}}
    # a scout with no account: any name (owner 2026-11-27)
    assert c.post("/api/fixtures/assign", json={"key": "m:2", "name": "John Smith"}, headers=H).json() == {"ok": True}
    assert st.assignments(db)["m:2"] == {"user_id": None, "name": "John Smith"}
    assert c.post("/api/fixtures/assign", json={"key": "m:1", "user_id": None}, headers=H).json() == {"ok": True}
    assert list(st.assignments(db)) == ["m:2"]
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
    assert api.why(p) == ["Sign (12 Nov 2026)", "Top 20% in 3 of last 5 games"]
    p2 = {**p, "rep": [], "pri": False, "f5": False, "rise": True, "rise_by": 25, "rise_from": 40, "rise_to": 65,
          "br": {"on": True, "before": 37, "after": 343}}
    assert api.why(p2) == ["Rising: 40% → 65% (last 5 games vs 5 before)",
                           "U23, minutes 37 → 343 (last 5 club games vs 5 before)"]
    older = {**p2, "rise": False, "br": {"on": False, "up": True, "before": 37, "after": 343}}
    assert api.why(older) == ["Minutes up: 37 → 343 (last 5 club games vs 5 before)"]
    assert api.why({**older, "br": {"on": False, "up": False}, "ns": True}) == ["Never scouted, rated 3.5+"]


def test_workbook_by_region_one_row_per_player_and_only_the_filtered_players():
    """Owner 2026-11-27: the head of recruitment sends the Excel to scouts -- a Games sheet (with
    the filters used), then one sheet per region (where the game is played: the home club), each
    game a shaded row with one row per player under it; only the players the filters kept, plus
    scout priorities marked "outside your filters"."""
    from io import BytesIO
    from openpyxl import load_workbook
    d = _data()
    d["games"][0]["region"] = ["London & South East", "North"]
    other = {**d["players"]["7"], "n": "Other Man", "rep": [], "pri": False, "f5": False, "ns": True}
    key = {**d["players"]["7"], "n": "Key Man", "f5": False}
    d["players"].update({"8": other, "9": key})
    wb = load_workbook(BytesIO(api.workbook(d, ["m:1"], pids={"7"}, filters="In form; U23")))
    assert wb.sheetnames == ["Games", "London & South East"]
    g = [r for r in wb["Games"].values]
    assert g[0][0] == "Filters: In form; U23"
    assert ("Leyton Orient", "Bolton", "League One", "London & South East", "Ann Scout", 2) == tuple(g[3][2:8])
    rows = [r for r in wb["London & South East"].values]
    assert rows[1][0].startswith("Sun 29 Nov 15:00") and "Leyton Orient v Bolton" in rows[1][0]
    names = [r[0] for r in rows[2:] if r[0]]
    assert names == ["Form Man", "Key Man"]                       # Other Man was filtered out
    form = next(r for r in rows if r[0] == "Form Man")
    assert form[4] == "Sign (12 Nov 2026)\nTop 20% in 3 of last 5 games" and form[5] == "90% 90% 90%"
    assert form[8] == "Sign 12 Nov 2026 (Ann)"
    assert "outside your filters" in next(r for r in rows if r[0] == "Key Man")[4]


def test_page_script_states_what_each_signal_means_and_links_players():
    from pathlib import Path
    import lofc.web
    js = (Path(lofc.web.__file__).parent / "static" / "js" / "fixtures.js").read_text()
    assert "Rising: ${p.rise_from}% → ${p.rise_to}% (last 5 games vs 5 before)" in js and 'title="${esc(d)}"' in js
    assert "hidden by filters" in js and "Clear filters" in js
    assert "/player/${encodeURIComponent(p.id)}" in js and "back=" in js
    assert "Also in this game: scout priorities and watchlist" in js       # never filtered out of a game


def test_wording_says_what_top_and_matching_mean_and_excel_follows_filters():
    """Owner 2026-11-27: "Top in 3+ of 5" and "Matching players per game" were unclear; the
    Excel must cover only what the filters show."""
    from pathlib import Path
    import lofc.web
    root = Path(lofc.web.__file__).parent
    html = (root / "templates" / "fixtures.html").read_text()
    assert "3+ of last 5 games in the top 20%" in html and "6+ of last 10 games in the top 20%" in html
    assert "Show only games with at least" in html and "2 matching players" in html
    assert "Matching players per game" not in html and "Top in 3+ of last 5" not in html
    js = (root / "static" / "js" / "fixtures.js").read_text()
    assert "Top 20% in ${p.t5} of last 5 games" in js
    assert "&pids=" in js and "&f=" in js


def test_players_follow_a_stated_order_on_the_page_and_in_the_excel():
    """Owner 2026-11-27: no hidden points -- watchlist, Sign / Monitor Priority, scouts disagree,
    most reasons to watch, season Overall; said in one line above the players."""
    from pathlib import Path
    import lofc.web
    js = (Path(lofc.web.__file__).parent / "static" / "js" / "fixtures.js").read_text()
    assert "weight(" not in js and "? 8 : 0" not in js
    assert "Order: watchlist, Sign / Monitor Priority, scouts disagree, most reasons to watch, season Overall" in js
    base = _data()["players"]["7"]
    a = {**base, "rep": [], "pri": False, "watch": "Watching", "f5": False}
    b = {**base, "dis": True}
    c = {**base, "rep": [], "pri": False, "rise": True, "rise_by": 25, "rise_from": 40, "rise_to": 65, "ov": 2.0}
    d = {**base, "rep": [], "pri": False, "ov": 3.9}
    assert sorted([d, c, b, a], key=api._order) == [a, b, c, d]


def test_leagues_and_regions_take_several_ticks():
    """Owner 2026-11-27: pick several leagues and several regions at once (none ticked = all)."""
    from pathlib import Path
    import lofc.web
    root = Path(lofc.web.__file__).parent
    html = (root / "templates" / "fixtures.html").read_text()
    assert 'id="fx-lg-list" data-ms="lg"' in html and 'id="fx-region-list" data-ms="region"' in html
    assert 'id="fx-lg"' not in html and 'id="fx-region"' not in html          # the one-choice menus are gone
    js = (root / "static" / "js" / "fixtures.js").read_text()
    assert "sel.lg.has(x.g.lg)" in js and "sel.region.has(" in js


def test_the_scout_box_takes_any_typed_name():
    from pathlib import Path
    import lofc.web
    root = Path(lofc.web.__file__).parent
    js = (root / "static" / "js" / "fixtures.js").read_text()
    assert 'list="fx-scouts"' in js and 'placeholder="Assign a scout"' in js and "json: {key: s.dataset.as, name}" in js
    assert 'id="fx-scouts"' in (root / "templates" / "fixtures.html").read_text()


def test_labels_say_why_never_scouted_possible_report_and_minutes():
    from pathlib import Path
    import lofc.web
    js = (Path(lofc.web.__file__).parent / "static" / "js" / "fixtures.js").read_text()
    assert "'Never scouted, rated 3.5+'" in js and "'Possible scout report, not linked'" in js
    assert "`U23, minutes ${p.br.before} → ${p.br.after}`" in js and "`Minutes up: ${p.br.before} → ${p.br.after}`" in js
    assert 'value="up"' in (Path(lofc.web.__file__).parent / "templates" / "fixtures.html").read_text()


def test_days_filter_in_every_window():
    """Owner 2026-11-27: pick one or several days (Next 7 / 14 days, Past 3 weeks)."""
    from pathlib import Path
    import lofc.web
    root = Path(lofc.web.__file__).parent
    assert 'id="fx-day-list" data-ms="day"' in (root / "templates" / "fixtures.html").read_text()
    js = (root / "static" / "js" / "fixtures.js").read_text()
    assert "sel.day.has(dayKey(x.g))" in js and "sel.day.clear(); load();" in js


def test_one_choice_filters_can_be_cleared_and_scouts_filter_and_by_scout():
    """Owner 2026-11-27: "at least N matching players" (and Overall, Age) could not be
    unticked; filter by scout and see who watches what, when."""
    from pathlib import Path
    import lofc.web
    root = Path(lofc.web.__file__).parent
    html = (root / "templates" / "fixtures.html").read_text()
    assert 'type="radio"' not in html and html.count("data-one") == 3
    assert "Show only games with at least" in html and "1 matching player" not in html
    assert 'id="fx-scout-list" data-ms="scout"' in html and 'data-b="scout"' in html
    js = (root / "static" / "js" / "fixtures.js").read_text()
    assert "function drawScouts" in js and "Not assigned" in js
