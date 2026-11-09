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

    def add(self, engine, p, c, s):
        self.calls.append(("add", p, c, s)); self.watched = True

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
                   'id="h-assess"', 'id="h-tm"', 'id="r-tiles"', 'id="sbs"', 'id="cf"', 'id="sf"',
                   'id="so"', 'id="pr"', 'id="pp"', 'id="pz"', 'id="rc"', 'id="prad"', 'id="ph"',
                   'id="sr"', 'id="sa"', 'id="av"', 'id="c-squad"', '/js/card.js',
                   '/css/card.css', 'Packing zones', 'Season by season',
                   'Availability and injury record'):
        assert needle in r.text, needle
    # the card sits under Players in the nav
    assert 'href="/players" class="on"' in r.text


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
