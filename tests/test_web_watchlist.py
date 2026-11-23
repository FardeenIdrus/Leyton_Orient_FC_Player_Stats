"""Web front end: the redesigned Watchlist (owner 2026-11-23) -- page shell, API and writes. The
store is the real `lofc.store.watchlist` over an in-memory sqlite database; every loader is
faked. One shared list, one entry per player, grouped by position with our best (League One)
for reference only; stages, owner, next step, due date, notes, optional drop reason;
"Suggested from scout reports"; "What changed since added"."""
import types

import pandas as pd
import pytest
from sqlalchemy import create_engine

from lofc.store import watchlist as store
from lofc.store.models import Base, PlayerMetricNeutral
from lofc.web.api import card as card_api
from lofc.web.api import watchlist as api
from web_fakes import FakeStore, login, make

H = {"X-LOFC-Request": "1"}
NOW = pd.Timestamp("2026-11-23")


def _client(role="scout"):
    s = FakeStore()
    s.add(username="u", full_name="Ann Scout", role=role, password="correct-horse-1")
    c, *_ = make(s)
    login(c, "u", "correct-horse-1")
    return c


def _full(table, partial):
    row = dict(partial)
    for col in table.columns:
        if col.name not in row and not col.nullable and col.name != "id":
            row[col.name] = 0
    return row


@pytest.fixture
def db():
    # one shared in-memory database across the API's worker threads
    from sqlalchemy.pool import StaticPool
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    pd.DataFrame([{"player_id": 1, "player_name": "Al <One>", "contract_until": "2027-03-01", "birth_date": "2002-01-01"},
                  {"player_id": 2, "player_name": "Bo Two", "contract_until": None, "birth_date": None},
                  {"player_id": 3, "player_name": "Cy Three", "contract_until": None, "birth_date": None}]).to_sql(
        "players", eng, index=False, if_exists="append")
    pd.DataFrame([_full(PlayerMetricNeutral.__table__, dict(player_id=p, competition_id=c, season_id=319,
                                                            player_name=n, team_name=t, position_group=g,
                                                            minutes=900.0, rankable=True))
                  for p, c, n, t, g in [(1, 5, "Al <One>", "Gills", "Winger"),
                                        (2, 901, "Bo Two", "Celtic", "Attacking Mid"),
                                        (3, 5, "Cy Three", "Crewe", "Winger")]]).to_sql(
        "player_metrics_neutral", eng, index=False, if_exists="append")
    import datetime as dt
    with eng.begin() as conn:
        conn.execute(store._TABLE.insert().values(player_id=1, competition_id=5, season_id=319, status="Watching",
                                                  added_rating=3.10, added_club="Old FC", created_at=dt.datetime(2026, 11, 1)))
        conn.execute(store._TABLE.insert().values(player_id=2, competition_id=901, season_id=319, status="Shortlisted",
                                                  created_at=dt.datetime(2026, 11, 2)))
    return eng


def _live():
    return pd.DataFrame({"competition_id": [5, 901, 5], "position_group": ["Winger", "Attacking Mid", "Winger"],
                         "team_name": ["Gills", "Celtic", "Crewe"], "objective_composite": [3.41, None, 3.7]},
                        index=pd.Index([1, 2, 3], name="player_id"))


def _games():
    """Player 1's six games this season (phase 4): the last five counted -> 85 · 90 · 50 · 95 · 81."""
    d = pd.date_range("2026-10-01", periods=7, freq="7D")
    return pd.DataFrame({"player_id": 1, "match_id": range(7), "scheduled_at": d,
                         "minutes": [90, 90, 90, 90, 90, 20, 90],
                         "impect_pct": [10, 85, 90, 50, 95, 99, 81.2]})


def _reports():
    return pd.DataFrame([
        dict(id=10, player_id=1, verdict="Sign", scout="Scout A", fixture_date="2026-11-15", submitted_at="2026-11-16",
             missing_since=None, player_name="Al <One>", club_name="Gills"),
        dict(id=30, player_id=3, verdict="Monitor Priority", scout="Scout B", fixture_date="2026-11-20",
             submitted_at="2026-11-20", missing_since=None, player_name="Cy Three", club_name="Crewe")])


@pytest.fixture
def fake(monkeypatch, db):
    src = types.SimpleNamespace(
        engine=db, store=store, live_season_id=319, current_form=lambda: pd.DataFrame(
            columns=["player_id", "competition_id", "season_id", "minutes", "goals_p90", "assists_p90"]),
        injuries_for=lambda ids: pd.DataFrame(columns=["player_id", "date_from", "date_until", "injury_category",
                                                       "injury_type_raw", "days_out", "games_missed"]),
        scorecards_for=lambda sid: pd.DataFrame(columns=["player_id", "competition_id", "season_id", "position_group",
                                                         "objective_composite", "performance_band", "physical_band"]),
        names={5: "League Two", 901: "Scottish Premiership"}, openable={(1, 5, 319), (3, 5, 319)}, now=NOW,
        live_rows=_live, current_clubs=lambda: pd.DataFrame({"player_id": [1], "current_club": ["Gills"]}),
        reports=_reports, users=lambda: [{"id": 1, "name": "Ann Scout"}, {"id": 7, "name": "Head of Rec"}],
        our_best=lambda: {"Winger": {"name": "Yusuf Akhamrich", "rating": 3.10}},
        games=lambda ids, season: _games())
    monkeypatch.setattr(api, "_sources", lambda: src)
    monkeypatch.setattr(card_api, "_watchlist", lambda: store)
    monkeypatch.setattr(card_api, "get_engine", lambda: db)
    return src


def test_page_and_api_need_a_session(fake):
    c, *_ = make(FakeStore())
    assert c.get("/watchlist").status_code == 303
    assert c.get("/api/watchlist").status_code == 401
    assert c.post("/api/watchlist/1", json={"stage": "Watching"}).status_code == 401


def test_page_shell_is_the_new_layout(fake):
    r = _client().get("/watchlist")
    assert r.status_code == 200 and 'id="v-watchlist"' in r.text
    for i in ("wl-tiles", "wl-sugg", "f-stage", "f-pos", "f-owner", "f-q", "wl-groups", "wl-closed", "wl-feed"):
        assert f'id="{i}"' in r.text, i
    assert "Market value" not in r.text and 'id="f-money"' not in r.text
    assert "News feed not connected yet." in r.text


def test_groups_tiles_our_best_and_rows(fake):
    d = _client().get("/api/watchlist").json()
    assert d["stages"] == store.STAGES and d["users"][1] == {"id": 7, "name": "Head of Rec"}
    assert [t["label"] for t in d["tiles"]] == ["On the list", "Shortlisted", "In form (3+ Top in last 5)",
                                                "New scout report (14 days)"]
    assert [t["value"] for t in d["tiles"]] == [2, 1, 1, 1]          # Al: 4 Top in his last 5
    groups = {g["group"]: g for g in d["groups"]}
    assert list(groups) == ["Midfield", "Winger"]
    assert groups["Winger"]["our_best"] == {"name": "Yusuf Akhamrich", "rating": 3.10, "league": "L1"}
    al = groups["Winger"]["rows"][0]
    assert (al["name"], al["club"], al["league"], al["overall"], al["stage"], al["verdict"]) == \
        ("Al <One>", "Gills", "League Two", 3.41, "Watching", "Sign")
    assert al["href"] == "/player/1/5/319" and al["new_report"] is True
    # phase 4: his last five counted games (20 minutes not counted), newest last
    assert al["last5"] == [85, 90, 50, 95, 81] and al["in_form"] is True
    assert al["last5_levels"] == ["Top", "Top", "Average", "Top", "Top"]
    bo = groups["Midfield"]["rows"][0]
    assert bo["overall"] is None and bo["href"] is None and bo["stage"] == "Shortlisted"


def test_suggestions_and_changes(fake):
    d = _client().get("/api/watchlist").json()
    s = d["suggestions"]
    assert (s["count_30"], s["count_all"], s["window"]) == (1, 1, "30")
    assert s["rows"][0]["name"] == "Cy Three" and s["rows"][0]["overall"] == 3.7 and s["rows"][0]["href"] == "/player/3/5/319"
    texts = [(c["name"], c["text"]) for c in d["changes"]]
    assert ("Al <One>", "new scout report: Sign (Scout A, 15 Nov)") in texts
    assert ("Al <One>", "rating 3.10 → 3.41") in texts
    assert ("Al <One>", "moved: Old FC → Gills") in texts
    assert texts[0][1].startswith("new scout report")              # dated first


def test_save_needs_the_header(fake):
    assert _client().post("/api/watchlist/1", json={"stage": "Shortlisted"}).status_code == 403


@pytest.mark.parametrize("role", ["scout", "head_of_recruitment", "admin"])
def test_save_stage_owner_next_step_due_note_any_role(fake, role):
    c = _client(role)
    assert c.post("/api/watchlist/1", json={"stage": "Shortlisted", "owner": 7, "next_step": "Watch vs Crewe",
                                            "due": "2026-12-02", "note": " quick "}, headers=H).json() == {"ok": True}
    r = next(r for g in c.get("/api/watchlist").json()["groups"] for r in g["rows"] if r["name"] == "Al <One>")
    assert (r["stage"], r["owner"], r["next_step"], r["due"], r["note"]) == \
        ("Shortlisted", "Head of Rec", "Watch vs Crewe", "2026-12-02", "quick")
    assert r["note_meta"] is not None
    # dropping needs no reason (owner 2026-11-23); it moves to "Dropped and signed"
    assert c.post("/api/watchlist/1", json={"stage": "Dropped"}, headers=H).status_code == 200
    d = c.get("/api/watchlist").json()
    assert [r["name"] for r in d["closed"]] == ["Al <One>"] and d["tiles"][0]["value"] == 1
    assert c.post("/api/watchlist/1", json={"drop_reason": "Level", "owner": None, "due": ""}, headers=H).status_code == 200
    r = c.get("/api/watchlist").json()["closed"][0]
    assert r["drop_reason"] == "Level" and r["owner"] is None and r["due"] is None


@pytest.mark.parametrize("body", [{"stage": "Signed!!"}, {"owner": 99}, {"owner": "7"}, {"due": "2/12/26"},
                                  {"note": 5}, {"player_id": 2}, []])
def test_save_rejects_a_bad_body(fake, body):
    assert _client().post("/api/watchlist/1", json=body, headers=H).status_code == 400


def test_save_unknown_player_is_404(fake):
    assert _client().post("/api/watchlist/99", json={"note": "x"}, headers=H).status_code == 404


def test_suggestion_add_and_dismiss(fake):
    c = _client()
    assert c.post("/api/watchlist/suggestions/30", json={"action": "add"}, headers=H).json() == {"ok": True}
    d = c.get("/api/watchlist").json()
    assert d["suggestions"]["count_all"] == 0
    cy = next(r for g in d["groups"] for r in g["rows"] if r["name"] == "Cy Three")
    assert cy["stage"] == "Watching"
    row = store.load(fake.engine).set_index("player_id").loc[3]
    assert (row["added_rating"], row["added_club"], row["added_by_user_id"]) == (3.7, "Crewe", 1)
    # dismiss: report 30's player is now watched, so check dismiss on its own
    store.remove(fake.engine, 3)
    assert c.post("/api/watchlist/suggestions/30", json={"action": "dismiss"}, headers=H).status_code == 200
    assert c.get("/api/watchlist").json()["suggestions"]["count_all"] == 0
    assert c.post("/api/watchlist/suggestions/30", json={"action": "nuke"}, headers=H).status_code == 400
    assert c.post("/api/watchlist/suggestions/999", json={"action": "add"}, headers=H).status_code == 404


def test_all_window_in_the_api(fake):
    d = _client().get("/api/watchlist?sugg=all").json()
    assert d["suggestions"]["window"] == "all"


def test_csv_is_the_list(fake):
    r = _client().get("/api/watchlist/csv")
    assert r.status_code == 200
    lines = r.text.splitlines()
    assert lines[0] == ",".join(api.CSV_COLUMNS) and len(lines) == 3


def test_empty_list(fake):
    store.remove(fake.engine, 1)
    store.remove(fake.engine, 2)
    d = _client().get("/api/watchlist").json()
    assert d["empty"] is True and d["groups"] == [] and "No players on the watchlist yet" in d["text"]
    assert _client().get("/api/watchlist/csv").status_code == 404


def test_page_script_saves_as_you_go_and_keeps_filters_in_the_url():
    from pathlib import Path
    root = Path(api.__file__).parents[1] / "static"
    js = (root / "js" / "watchlist.js").read_text()
    assert "rememberState('watchlist', {drop: ['open']})" in js
    assert "'/api/watchlist/' + p" in js and "/api/watchlist/suggestions/" in js
    assert "Reason (optional)" in js and "data-field=\"drop_reason\"" in js
    assert "Market value" not in js
    assert "Last 5" in js and ">Contract<" not in js                  # owner 2026-11-23: Contract column dropped
