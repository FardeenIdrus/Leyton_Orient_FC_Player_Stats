"""Web front end: the Watchlist page shell, API and writes (no database: the watchlist store and
every loader are faked). Real-database parity: test_web_scout_watchlist_parity.py."""
import types

import pandas as pd
import pytest

from lofc.model import assessment_status as AS
from lofc.web.api import card as card_api
from lofc.web.api import watchlist as api
from web_fakes import FakeStore, login, make

H = {"X-LOFC-Request": "1"}
KEY = "/api/watchlist/1/5/318"


def _client(role="scout"):
    s = FakeStore()
    s.add(username="u", full_name="Ann Scout", role=role, password="correct-horse-1")
    c, *_ = make(s)
    login(c, "u", "correct-horse-1")
    return c


class FakeWatch:
    """`lofc.store.watchlist` over a list of rows."""
    WATCHLIST_STATUSES = ["Watching", "Scout sent", "Contact agent", "Dropped"]

    def __init__(self):
        self.rows = {(1, 5, 318): dict(note="Watch his <b>first</b> touch", status="Watching",
                                       created_at="2026-09-14 11:05", player_name="Al <One>",
                                       contract_until="2027-03-01", tm_player_id=123.0,
                                       team_name="Gills", position_group="Winger", age=24.04),
                     (2, 901, 319): dict(note=None, status="Scout sent",
                                         created_at="2026-10-12 15:14", player_name="Bo Two",
                                         contract_until=None, tm_player_id=None,
                                         team_name="Celtic", position_group="Attacking Mid",
                                         age=None)}
        self.calls = []

    def load(self, engine):
        recs = [{"player_id": k[0], "competition_id": k[1], "season_id": k[2],
                 "competition_name": None, "performance_score": None, "fit_score": None,
                 "market_value_eur": None, **v} for k, v in self.rows.items()]
        cols = ["player_id", "competition_id", "season_id", "note", "status", "created_at",
                "player_name", "contract_until", "tm_player_id", "team_name", "position_group",
                "competition_name", "performance_score", "fit_score", "market_value_eur", "age"]
        df = pd.DataFrame(recs, columns=cols)
        df["created_at"] = pd.to_datetime(df["created_at"])
        return df

    def is_watched(self, engine, p, c, s):
        return (p, c, s) in self.rows

    def set_note(self, engine, p, c, s, note):
        self.calls.append(("note", p, c, s, note)); self.rows[(p, c, s)]["note"] = note

    def set_status(self, engine, p, c, s, status):
        if status not in self.WATCHLIST_STATUSES:
            raise ValueError(status)
        self.calls.append(("status", p, c, s, status)); self.rows[(p, c, s)]["status"] = status

    def add(self, engine, p, c, s):
        self.calls.append(("add", p, c, s)); self.rows.setdefault((p, c, s), dict(status="Watching"))

    def remove(self, engine, p, c, s):
        self.calls.append(("remove", p, c, s)); self.rows.pop((p, c, s), None)


def _scorecards(sid):
    if sid == 318:      # a 10-strong League Two winger pool
        return pd.DataFrame({"player_id": [1] + list(range(100, 109)), "competition_id": [5] * 10,
                             "season_id": [318] * 10, "position_group": ["Winger"] * 10,
                             "objective_composite": [3.41] + [3.0] * 9,
                             "performance_band": [3.2] + [3.0] * 9,
                             "physical_band": [3.7] + [3.0] * 9})
    return pd.DataFrame({"player_id": [2, 8], "competition_id": [901, 901], "season_id": [319] * 2,
                         "position_group": ["Attacking Mid"] * 2, "objective_composite": [4.49, 3.1],
                         "performance_band": [4.6, 3.0], "physical_band": [4.2, 3.0]})


@pytest.fixture
def fake(monkeypatch):
    wl = FakeWatch()
    live = pd.DataFrame({"player_id": [1], "competition_id": [5], "season_id": [319],
                         "minutes": [455.0], "goals_p90": [0.4], "assists_p90": [0.2]})
    src = types.SimpleNamespace(
        engine=object(), store=wl,
        assessment=pd.DataFrame(columns=["player_id", "competition_id", "season_id",
                                         "assessment_status"]),
        live_season_id=319, current_form=lambda: live,
        injuries_for=lambda ids: pd.DataFrame(columns=["player_id", "date_from", "date_until",
                                                       "injury_category", "injury_type_raw",
                                                       "days_out", "games_missed"]),
        scorecards_for=_scorecards, names={5: "League Two", 901: "Scottish Premiership"},
        valuations=lambda ids: pd.DataFrame({"player_id": [1], "season_id": [317],
                                             "market_value_eur": [1.5e6]}),
        openable={(1, 5, 318)}, now=pd.Timestamp("2026-11-09"))
    monkeypatch.setattr(api, "_sources", lambda: src)
    monkeypatch.setattr(card_api, "_watchlist", lambda: wl)
    monkeypatch.setattr(card_api, "get_engine", lambda: object())

    class NoCard:
        def card_row(self, p, c, s, rank_as=None):
            return None, "All Metrics", "not_found"
    monkeypatch.setattr(card_api, "_core", lambda: NoCard())
    return wl


def test_page_and_api_need_a_session(fake):
    c, *_ = make(FakeStore())
    assert c.get("/watchlist").status_code == 303
    assert c.get("/api/watchlist").status_code == 401
    assert c.post(KEY, json={"note": "x", "status": "Watching"}).status_code == 401


def test_page_shell(fake):
    r = _client().get("/watchlist")
    assert r.status_code == 200 and 'id="v-watchlist"' in r.text
    assert "/js/watchlist.js" in r.text and "Currently building" not in r.text


def test_rows_tiles_and_columns(fake):
    d = _client().get("/api/watchlist").json()
    assert d["empty"] is False
    assert [t["label"] for t in d["tiles"]] == ["On the list", "Contract ≤ 6 months",
                                                "Currently injured", "Not yet assessed"]
    assert [t["value"] for t in d["tiles"]] == [2, 1, 0, 2]
    assert d["columns"][:8] == ["Player", "Club", "League", "Position", "Age", "Composite",
                                "Performance", "Physical"]
    assert "Market value" not in d["columns"]
    al = d["rows"][0]
    assert al["key"] == "1-5-318" and al["cells"]["Player"] == "Al <One>"
    assert al["cells"]["Composite"] == "3.41" and al["ratings"]["Composite"] == 3.41
    assert al["cells"]["This season (2026/27)"].startswith("455 min")
    assert al["href"] == "/player/1/5/318"
    assert al["assess_href"] == "/assess?player=1&competition=5&season=318"
    assert al["note"] == "Watch his <b>first</b> touch" and al["status"] == "Watching"
    assert al["tm"] == "https://www.transfermarkt.com/-/profil/spieler/123"
    assert d["statuses"] == list(AS.STATUSES)
    assert d["manual_statuses"] == FakeWatch.WATCHLIST_STATUSES


def test_thin_pool_shows_no_rating_and_the_note(fake):
    bo = _client().get("/api/watchlist").json()["rows"][1]
    assert bo["cells"]["Composite"] == "—" and bo["ratings"]["Composite"] is None
    assert bo["not_rated"] == "Not rated: only 2 comparable players (needs 10)"
    assert bo["href"] is None                                   # no card for him


def test_no_blank_reaches_the_page(fake):
    for r in _client().get("/api/watchlist?money=1").json()["rows"]:
        for k, v in r["cells"].items():
            if k != "Note":
                assert v not in (None, "", "nan", "None", "NaN"), k


def test_money_adds_market_value(fake):
    d = _client().get("/api/watchlist?money=1").json()
    cols = d["columns"]
    assert cols.index("Market value") == cols.index("Contract") - 1
    assert d["rows"][0]["cells"]["Market value"] == "€1.5m"


def test_status_filter(fake):
    c = _client()
    assert len(c.get("/api/watchlist?status=Not%20assessed").json()["rows"]) == 2
    d = c.get("/api/watchlist?status=Signed%20off").json()
    assert d["rows"] == [] and d["none_match"] == "No watched players match the chosen assessment status."
    d = c.get("/api/watchlist?status=").json()                     # nothing ticked
    assert d["rows"] == [] and d["chosen"] == []


def test_empty_list(fake):
    fake.rows.clear()
    d = _client().get("/api/watchlist").json()
    assert d["empty"] is True and d["text"].startswith("No players on the watchlist yet.")


def test_csv_is_the_table(fake):
    r = _client().get("/api/watchlist/csv?money=1")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "lofc_watchlist.csv" in r.headers["content-disposition"]
    head = r.text.splitlines()[0]
    assert head.startswith("Player,Club,League,Position,Age,Composite") and "Market value" in head


# --- writes ----------------------------------------------------------------------------------
def test_save_needs_the_header(fake):
    assert _client().post(KEY, json={"note": "x", "status": "Watching"}).status_code == 403
    assert fake.calls == []


@pytest.mark.parametrize("role", ["scout", "medical", "head_of_recruitment", "admin"])
def test_save_note_and_status_any_role_as_streamlit(fake, role):
    r = _client(role).post(KEY, json={"note": "  Seen twice  ", "status": "Scout sent"}, headers=H)
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert fake.calls == [("note", 1, 5, 318, "Seen twice"), ("status", 1, 5, 318, "Scout sent")]


def test_save_blank_note_stores_none(fake):
    _client().post(KEY, json={"note": "   ", "status": "Watching"}, headers=H)
    assert fake.calls[0] == ("note", 1, 5, 318, None)


@pytest.mark.parametrize("body", [{"note": "x", "status": "Bogus"}, {"note": 5, "status": "Watching"},
                                  {"status": "Watching"}, {"note": "x"}, []])
def test_save_rejects_a_bad_body(fake, body):
    r = _client().post(KEY, json=body, headers=H)
    assert r.status_code == 400 and fake.calls == []


def test_save_404_when_not_on_the_list(fake):
    r = _client().post("/api/watchlist/9/5/318", json={"note": "x", "status": "Watching"}, headers=H)
    assert r.status_code == 404 and fake.calls == []


def test_remove_reuses_the_card_post_even_without_a_card(fake):
    """A watched row whose card cannot open (e.g. under 450 minutes) is still removable."""
    r = _client().post("/api/card/2/901/319/watchlist", json={"action": "remove"}, headers=H)
    assert r.status_code == 200 and r.json() == {"ok": True, "watched": False}
    assert ("remove", 2, 901, 319) in fake.calls


def test_card_add_still_404_without_a_card(fake):
    r = _client().post("/api/card/9/5/318/watchlist", json={"action": "add"}, headers=H)
    assert r.status_code == 404 and fake.calls == []


def test_card_remove_404_when_neither_card_nor_watched(fake):
    r = _client().post("/api/card/9/5/318/watchlist", json={"action": "remove"}, headers=H)
    assert r.status_code == 404 and fake.calls == []
