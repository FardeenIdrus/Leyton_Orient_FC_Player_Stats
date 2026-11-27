"""Web front end: the player card's page shell and API (no database: the data layer is faked).
The numbers themselves are tested in test_core_card.py / test_core_squad.py and, against the
real database, in test_web_card_parity.py."""
import pytest

from lofc.web.api import card as card_api
from web_fakes import FakeStore, login, make

KEY = "/api/card/39154/5/318"


def _client(role="scout"):
    s = FakeStore()
    s.add(username="u", full_name="Ann Scout", role=role, password="correct-horse-1")
    c, *_ = make(s)
    login(c, "u", "correct-horse-1")
    return c


class FakeCore:
    def __init__(self, data=None):
        self.data, self.calls = data, []

    def build_card(self, engine, p, c, s, rank_as=None, show_money=False):
        self.calls.append(("build", p, c, s, rank_as, show_money))
        return self.data

    def card_row(self, p, c, s, rank_as=None):
        import pandas as pd
        self.calls.append(("row", p, c, s, rank_as))
        if self.data is None:
            return None, "All Metrics", "not_found"
        return (pd.Series({"player_id": p, "player_name": "Dilan Markanday", "season_id": s,
                           "position_group": "Winger", "birth_date": None, "contract_until": None}),
                "All Metrics", "ok")

    def clean(self, x):
        return x

    def scorecard_csv(self, engine, p, c, s, kind, rank_as=None):
        self.calls.append(("csv", kind))
        return ("Dilan_Markanday_318_scorecard_metrics.csv", "Metric,Percentile\nA,50\n") \
            if self.data else None


class FakeSquad:
    calls = []

    @classmethod
    def section(cls, *a, **k):
        cls.calls.append((a, k))
        return {"title": "Against our Wingers", "season": a[3]}


class FakeWatchlist:
    def __init__(self):
        self.watched, self.calls = False, []

    def add(self, engine, p, c, s, user_id=None, snapshot=None):
        self.calls.append(("add", p, c, s)); self.watched = True
        self.added = (user_id, snapshot)

    def remove(self, engine, p, c, s):
        self.calls.append(("remove", p, c, s)); self.watched = False

    def is_watched(self, *a):
        return self.watched


@pytest.fixture
def fake(monkeypatch):
    core = FakeCore({"meta": {"player_id": 39154}, "rating": {"overall": {"value": None}}})
    wl = FakeWatchlist()
    monkeypatch.setattr(card_api, "_core", lambda: core)
    monkeypatch.setattr(card_api, "_squad", lambda: FakeSquad)
    monkeypatch.setattr(card_api, "_watchlist", lambda: wl)
    monkeypatch.setattr(card_api, "get_engine", lambda: object())
    FakeSquad.calls.clear()
    return core, wl


# --- sign-in rules --------------------------------------------------------------------------
def test_api_is_401_and_page_redirects_when_signed_out():
    c, *_ = make()
    assert c.get(KEY).status_code == 401
    assert c.get(KEY + "/squad").status_code == 401
    assert c.get(KEY + "/csv").status_code == 401
    r = c.get("/player/39154/5/318")
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_watchlist_post_needs_session_and_the_request_header(fake):
    c, *_ = make()
    assert c.post(KEY + "/watchlist", json={"action": "add"}).status_code == 401
    c = _client()
    r = c.post(KEY + "/watchlist", json={"action": "add"})
    assert r.status_code == 403 and r.json()["detail"] == "missing_request_header"
    assert fake[1].calls == []                          # nothing was written


# --- page shell ----------------------------------------------------------------------------------
def test_page_shell_has_the_sections_controls_and_script(fake):
    r = _client().get("/player/39154/5/318?back=%2Fplayers%3Fposition%3DWinger")
    assert r.status_code == 200
    for needle in ('id="v-card"', 'data-player="39154"', 'data-competition="5"', 'data-season="318"',
                   'id="back"', 'aria-label="Show affordability (modelled)"', 'id="h-watch"',
                   'id="h-tm"', 'id="r-tiles"', 'id="sbs"', 'id="cf"', 'id="sf"',
                   'id="so"', 'id="pr"', 'id="pp"', 'id="pz"', 'id="rc"', 'id="prad"', 'id="ph"',
                   'id="sr"', 'id="av"', 'id="c-squad"', '/js/card.js',
                   '/css/card.css', 'Packing zones', 'Season by season',
                   'Availability and injury record'):
        assert needle in r.text, needle
    # the card sits under Players in the nav
    assert 'href="/players" class="on"' in r.text
    # retired (owner 2026-11-16): no Assess link, no in-platform scout assessment block
    for gone in ('id="h-assess"', "Assess this player", 'id="sa"', "Scout assessment"):
        assert gone not in r.text, gone


def test_page_shell_rejects_non_numeric_ids():
    assert _client().get("/player/abc/5/318").status_code == 422


# --- JSON ----------------------------------------------------------------------------------------
def test_card_json_passes_the_query_to_the_core(fake):
    r = _client().get(KEY + "?rank_as=Direct%20%26%201v1%20Specialist&money=1")
    assert r.status_code == 200 and r.json()["meta"]["player_id"] == 39154
    assert fake[0].calls == [("build", 39154, 5, 318, "Direct & 1v1 Specialist", True)]
    _client().get(KEY)
    assert fake[0].calls[-1] == ("build", 39154, 5, 318, None, False)


def test_card_json_404_for_an_unknown_player_season(fake):
    fake[0].data = None
    r = _client().get(KEY)
    assert r.status_code == 404 and r.json()["detail"] == "no_such_player_season"


def test_squad_json_uses_the_requested_season_and_lens(fake):
    r = _client().get(KEY + "/squad?season=319&rank_as=Target%20Man")
    assert r.status_code == 200 and r.json()["season"] == 319
    args, kwargs = FakeSquad.calls[-1]
    assert args[:4] == (39154, "Dilan Markanday", "Winger", 319)
    assert fake[0].calls[-1] == ("row", 39154, 5, 318, "Target Man")
    # no season given: the card's own season
    assert _client().get(KEY + "/squad").json()["season"] == 318
    assert _client().get(KEY + "/squad?season=junk").json()["season"] == 318


def test_squad_json_404(fake):
    fake[0].data = None
    assert _client().get(KEY + "/squad").status_code == 404


def test_csv_download_has_the_streamlit_file_name(fake):
    r = _client().get(KEY + "/csv?kind=scorecard")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert 'filename="Dilan_Markanday_318_scorecard_metrics.csv"' in r.headers["content-disposition"]
    assert r.text.startswith("Metric,Percentile")
    _client().get(KEY + "/csv?kind=metrics")
    assert fake[0].calls[-1] == ("csv", "metrics")
    _client().get(KEY + "/csv?kind=whatever")
    assert fake[0].calls[-1] == ("csv", "scorecard")
    fake[0].data = None
    assert _client().get(KEY + "/csv").status_code == 404


# --- watchlist -----------------------------------------------------------------------------------
def test_watchlist_add_then_remove_with_the_header(fake):
    c = _client()
    h = {"X-LOFC-Request": "1"}
    r = c.post(KEY + "/watchlist", json={"action": "add"}, headers=h)
    assert r.status_code == 200 and r.json() == {"ok": True, "watched": True}
    r = c.post(KEY + "/watchlist", json={"action": "remove"}, headers=h)
    assert r.json() == {"ok": True, "watched": False}
    assert fake[1].calls == [("add", 39154, 5, 318), ("remove", 39154, 5, 318)]
    # owner 2026-11-23: who added him and a snapshot for "What changed since added"
    who, snap = fake[1].added
    assert isinstance(who, int) and snap["competition_id"] == 5 and set(snap) == {"rating", "club", "competition_id"}


@pytest.mark.parametrize("body", [{"action": "nuke"}, {}, {"action": None}])
def test_watchlist_rejects_a_bad_action(fake, body):
    r = _client().post(KEY + "/watchlist", json=body, headers={"X-LOFC-Request": "1"})
    assert r.status_code == 400 and fake[1].calls == []


def test_watchlist_404_for_an_unknown_player_season(fake):
    fake[0].data = None
    r = _client().post(KEY + "/watchlist", json={"action": "add"}, headers={"X-LOFC-Request": "1"})
    assert r.status_code == 404 and fake[1].calls == []


def test_csv_with_a_non_latin1_name_downloads(fake, monkeypatch):
    import types
    monkeypatch.setattr(fake[0], "scorecard_csv", lambda *a, **k: ("Baran_Yıldız_318_metrics.csv", "A\n"))
    from lofc.core import card as real
    monkeypatch.setattr(card_api, "_core", lambda: types.SimpleNamespace(
        scorecard_csv=fake[0].scorecard_csv, csv_disposition=real.csv_disposition))
    r = _client().get(KEY + "/csv?kind=metrics")
    assert r.status_code == 200
    assert "filename*=UTF-8''Baran_Y%C4%B1ld%C4%B1z_318_metrics.csv" in r.headers["content-disposition"]


def test_watchlist_rejects_a_non_json_body(fake):
    r = _client().post(KEY + "/watchlist", content="x", headers={"X-LOFC-Request": "1"})
    assert r.status_code == 400


def test_card_js_draws_the_not_compared_line_tags_and_raw_matrix():
    """Owner 2026-11-20: the section draws the API's line and the "Rated in <league>" tag, and
    the metric-by-metric table of RAW values (green best, red worst) for every target."""
    from pathlib import Path
    import lofc.web
    js = (Path(lofc.web.__file__).parent / "static" / "js" / "card.js").read_text()
    sq = js[js.index("function renderSquad"):js.index("function bindSquad")]
    for needle in ("S.not_compared", "p.elsewhere", "M.note", "x.kind", "x.value"):
        assert needle in sq, needle
    assert "raw_physical" not in sq and "pcol(" not in sq
    # the matrix is drawn in the not-compared case too
    nc = sq[sq.index("if (S.not_compared) { box.innerHTML"):]
    assert nc.startswith("if (S.not_compared) { box.innerHTML = h + matrix;")
    css = (Path(lofc.web.__file__).parent / "static" / "css" / "card.css").read_text()
    assert ".sq-matrix td.best" in css and ".sq-matrix td.worst" in css



def test_card_js_switches_the_matrix_physical_rows_by_phase():
    """Owner 2026-11-23: All phases / In possession / Out of possession above the physical rows."""
    from pathlib import Path
    import lofc.web
    js = (Path(lofc.web.__file__).parent / "static" / "js" / "card.js").read_text()
    body = js[js.index("function matrixBody"):js.index("function bindSquad")]
    assert "M.phases" in body and "data-phase" in body and "'All phases'" in body
    assert "Speed and agility have no possession split." in body
    bind = js[js.index("function bindSquad"):]
    assert "button[data-phase]" in bind[:600] and "showPhase(" in bind[:600]
    assert "innerHTML" not in js[js.index("function showPhase"):js.index("function bindSquad")]


def test_games_endpoint_returns_the_block_or_null(fake, monkeypatch):
    """Owner 2026-11-23 (phase 4): /games -> his last games with % and level; null without any."""
    import pandas as pd
    from lofc.core import game_performances as gp
    rows = pd.DataFrame({"match_id": [1], "scheduled_at": [pd.Timestamp("2026-11-21")], "squad_id": [10],
                         "home_squad_id": [10], "home_name": ["Orient"], "away_name": ["Bolton"], "competition_id": [4],
                         "position_group": ["Winger"], "minutes": [90.0], "impect": [1.2], "offensive": [1.0],
                         "defensive": [0.2], "impect_pct": [91.4], "offensive_pct": [50.0], "defensive_pct": [10.0]})
    monkeypatch.setattr(gp, "load", lambda engine, ids, season: rows)
    b = _client().get(KEY + "/games").json()["block"]
    assert b["games"][0]["opponent"] == "Bolton" and b["games"][0]["scores"]["impect"] == {"pct": 91, "level": "Top"}
    assert b["counts"]["defensive"] == {"Top": 0, "Average": 0, "Low": 1}
    monkeypatch.setattr(gp, "load", lambda engine, ids, season: rows.head(0))
    assert _client().get(KEY + "/games").json() == {"block": None}


def test_card_js_draws_game_performances_with_a_percent_on_every_dot():
    from pathlib import Path
    import lofc.web
    root = Path(lofc.web.__file__).parent
    js = (root / "static" / "js" / "card.js").read_text()
    body = js[js.index("function drawGames"):js.index("async function loadGames")]
    assert 'class="gp-pct"' in body and "${sc.pct}%" in body and "gp-sub" in body
    # owner 2026-11-24: real pixel size (no scaling viewBox), the site's own hover tip
    assert "viewBox" not in body and "clientWidth" in body and 'data-tip="${esc(tip)}"' in body
    assert "/games" in js and 'id="c-games"' in (root / "templates" / "card.html").read_text()


def _club_games():
    import pandas as pd
    perf = {"pass_completion_pct": {"v": 0.75, "n": 30.0, "d": 40.0}}
    phys = {"distance_p90": {"v": 10400.0, "n": 10400.0, "d": None}}
    return pd.DataFrame({"match_id": [1], "scheduled_at": [pd.Timestamp("2026-11-21")], "squad_id": [10],
                         "home_squad_id": [10], "home_name": ["Orient"], "away_name": ["Bolton"],
                         "competition_id": [4], "position_group": ["Central Mid"], "minutes": [90.0],
                         "impect_pct": [91.4], "offensive_pct": [50.0], "defensive_pct": [10.0],
                         "overall": [3.8], "performance": [3.6], "physical": [4.1], "overall_pct": [78.0],
                         "performance_pct": [71.0], "physical_pct": [86.0], "perf": [perf], "phys": [phys],
                         "metric_pcts": [{"pass_completion_pct": 71.0, "distance_p90": 60.0}]})


def test_one_games_tables_endpoint(fake, monkeypatch):
    """Owner 2026-11-23 (N21): click a game -> every metric behind its club scores."""
    from lofc.core import game_performances as gp
    monkeypatch.setattr(gp, "load_club", lambda engine, p, s, m=None: _club_games())
    d = _client().get(KEY + "/games/1").json()
    pc = next(r for r in d["perf"] if r["metric"] == "pass_completion_pct")
    assert pc["game"] == "30 of 40 (75%)" and pc["pct"] == 71
    assert next(r for r in d["phys"] if r["metric"] == "distance_p90")["game"] == "10,400 m"
    monkeypatch.setattr(gp, "load_club", lambda engine, p, s, m=None: _club_games().head(0))
    assert _client().get(KEY + "/games/1").status_code == 404


def test_games_workbook_endpoint(fake, monkeypatch):
    from lofc.core import game_performances as gp
    monkeypatch.setattr(gp, "load_club", lambda engine, p, s, m=None: _club_games())
    r = _client().get(KEY + "/games.xlsx")
    assert r.status_code == 200 and r.content[:2] == b"PK"
    assert "games.xlsx" in r.headers["content-disposition"]


def test_card_js_has_the_club_tabs_and_the_game_panel():
    from pathlib import Path
    import lofc.web
    root = Path(lofc.web.__file__).parent
    js = (root / "static" / "js" / "card.js").read_text()
    assert "['overall', 'Overall'], ['performance', 'Performance'], ['physical', 'Physical'], ['impect', 'Impect']" in js
    assert "/games/${m.match_id}" in js and "games.xlsx" in js and "no rating: under 45 min" in js
    html = (root / "templates" / "card.html").read_text()
    assert 'id="gd"' in html and 'id="gp-imp"' in html and 'id="gp-xl"' in html


def test_game_chart_redraws_when_its_box_gets_its_real_width():
    """Owner 2026-11-23: the chart was drawn while the page was still hidden (width 0 -> a
    small fallback) and never redrawn, so it opened tiny. It now follows its box's width."""
    from pathlib import Path
    import lofc.web
    js = (Path(lofc.web.__file__).parent / "static" / "js" / "card.js").read_text()
    assert "new ResizeObserver" in js and "observe($('gp'))" in js
    body = js[js.index("function drawGames"):js.index("const gpRow")]
    assert "clientWidth || 760" not in body                 # no silent fallback width


def test_without_club_scores_one_switch_and_the_game_still_opens():
    """Owner 2026-11-23: with Impect scores only, "Impect" sat above its own IMPECT / Offensive /
    Defensive switch, and clicking a game did nothing. One switch; a click opens the game and
    says the club scores are not in yet."""
    from pathlib import Path
    import lofc.web
    js = (Path(lofc.web.__file__).parent / "static" / "js" / "card.js").read_text()
    body = js[js.index("function drawGames"):js.index("const gpRow")]
    assert "$('gp-tabs').hidden = !GP.has_club" in body
    assert "Club scores for this game are not in yet." in js
    click = js[js.index("document.addEventListener('click'"):]
    assert "if (d && GP) {" in click


def test_game_metric_tables_are_closed_until_asked_for():
    """Owner 2026-11-23: the full metric breakdown of a game takes a lot of room. The chart and
    the game's score tiles stay; the two tables open only from a "Show all metrics" button
    (and are only fetched then). Open or closed is kept while clicking between games."""
    from pathlib import Path
    import lofc.web
    js = (Path(lofc.web.__file__).parent / "static" / "js" / "card.js").read_text()
    body = js[js.index("async function drawGameDetail"):js.index("async function loadGames")]
    assert "let gdOpen = false" in js
    assert 'aria-expanded="${gdOpen}"' in body and "Show all metrics" in body and "Hide all metrics" in body
    # nothing is fetched while closed
    assert body.index("if (!gdOpen) return") < body.index("await api(")
    click = js[js.index("document.addEventListener('click'"):]
    assert "#gd-more" in click and "gdOpen = !gdOpen" in click


def test_a_games_scores_are_a_table_of_band_and_better_than():
    """Owner 2026-11-27 (N26, option A): the four grey tiles (headline = a band in three, a % in
    Impect's) become one table -- Score / Band (1 to 5) / Better than (% of games); Impect has
    "no band". Only the tabs switch the chart. The formula line (it gave 5.15 for a 3.69) is gone."""
    from pathlib import Path
    import lofc.web
    root = Path(lofc.web.__file__).parent
    js = (root / "static" / "js" / "card.js").read_text()
    body = js[js.index("async function drawGameDetail"):js.index("async function loadGames")]
    assert "Band (1 to 5)" in body and "Better than (% of games)" in body and "no band" in body
    assert "/ 5" in body and "gd-score" in body
    assert "gd-tile" not in js and "data-gt" not in js
    assert "Band 1–5 = 3 + (% − 50) ÷ 20" not in js
    games = js[js.index("function drawGames"):js.index("const gpRow")]
    assert "GP.pool" in games and "GP.club_note" not in games
    css = (root / "static" / "css" / "card.css").read_text()
    assert ".gp-a{fill:#A87B00}" in css                      # Average dot readable (3.8:1, was 2.4:1)
    assert ".gp-hit:focus-visible" in css


def test_game_chart_names_clubs_in_full_on_two_lines():
    """Owner 2026-11-27 (N26): "Heart of M..." / "St. Johnst..." were cut; when the games have
    room (one row of names) a long name wraps onto a second line instead."""
    from pathlib import Path
    import lofc.web
    js = (Path(lofc.web.__file__).parent / "static" / "js" / "card.js").read_text()
    games = js[js.index("function drawGames"):js.index("const gpRow")]
    assert "clubLines(" in games and "<tspan" in games


def test_no_games_shows_one_line_instead_of_hiding_the_section():
    """Owner 2026-11-27 (N26): with no game data the section vanished, which looked like a bug.
    It now stays, with one line; a failed load says so instead."""
    from pathlib import Path
    import lofc.web
    js = (Path(lofc.web.__file__).parent / "static" / "js" / "card.js").read_text()
    games = js[js.index("function drawGames"):js.index("const gpRow")]
    assert "if (!GP) { box.hidden = true; return; }" not in games
    assert "No game data for him this season." in games and "Could not load the games." in js
    load = js[js.index("async function loadGames"):]
    assert "gpErr = true" in load[:300]
