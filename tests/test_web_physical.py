"""Web front end: the Physical page shell and API (no database: every source is faked).
Real-database parity: test_web_physical_parity.py."""
import types

import pandas as pd
import pytest

from lofc.core import physical_page as core
from lofc.web.api import physical as api
from web_fakes import FakeStore, login, make


def _client():
    s = FakeStore()
    s.add(username="u", full_name="Ann Scout", role="scout", password="correct-horse-1")
    c, *_ = make(s)
    login(c, "u", "correct-horse-1")
    return c


def _season_frames(sid, comp=4, n=12):
    c = pd.DataFrame({"player_id": range(1, n + 1), "competition_id": comp, "season_id": sid,
                      "position_group": "Centre Forward",
                      "player_name": [f"P<{i}>" for i in range(1, n + 1)],
                      "team_name": "Club", "minutes": 1000.0, "age": 25.0})
    v = c[["player_id", "competition_id"]].copy()
    p = c[["player_id", "competition_id", "season_id", "position_group"]].copy()
    for k in core.KEYS:
        v[k] = [float(i) for i in c["player_id"]]
        p[k] = ((v[k].rank() - 0.5) / v[k].count() * 100.0).values
    return c, v, p


@pytest.fixture
def fake(monkeypatch):
    src = install_fake(monkeypatch)
    yield src
    api.clear()


def install_fake(monkeypatch):
    """Swap the Physical page's data sources for in-memory frames (also used by test_web_speed)."""
    frames = {318: _season_frames(318), 319: _season_frames(319)}
    rows = frames[319][0].set_index("player_id")[["competition_id", "position_group", "team_name",
                                                  "minutes"]].assign(
        physical_band=3.2, peer_count=12.0, thin=False)
    squad = pd.DataFrame({"player_id": [3, 4], "player_name": ["Our <A>", "Our B"],
                          "position_group": ["Centre Forward", "Centre Forward"]})
    src = types.SimpleNamespace(
        seasons=lambda: [{"id": 319, "name": "2026/27"}, {"id": 318, "name": "2025/26"},
                         {"id": 317, "name": "2024/25"}],
        default_season=lambda ids: 319,
        candidates=lambda s: frames.get(s, _season_frames(s, n=0))[0],
        values=lambda s: frames.get(s, _season_frames(s, n=0))[1],
        pcts=lambda s: frames.get(s, _season_frames(s, n=0))[2],
        squad=lambda: squad, rated_rows=lambda s: rows,
        has_physical=lambda c, s: s in (318, 319),
        match_counts=lambda s: {(3, 4): 23} if s == 319 else {},
        cards=lambda pos, s: frames.get(s, _season_frames(s, n=0))[0].assign(
            position_group=pos, archetype="All Metrics",
            physical_band=lambda d: 1.0 + d["player_id"] * 0.25),
        league_names=lambda: {4: "League One", 5: "League Two"})
    monkeypatch.setattr(api, "_sources", lambda: src)
    api.clear()
    return src


def test_page_shell_renders_with_filters_and_script(fake):
    r = _client().get("/physical")
    assert r.status_code == 200
    assert "<h1>Physical</h1>" in r.text and "/js/physical.js" in r.text
    assert "Currently building" not in r.text
    for label in ('for="f-season"', 'for="f-league"', 'for="f-position"', 'for="f-metric"'):
        assert label in r.text


def test_api_needs_login():
    c, *_ = make(FakeStore())
    assert c.get("/api/physical").status_code == 401


def test_defaults_and_payload(fake):
    d = _client().get("/api/physical").json()
    f = d["filters"]
    assert f["season"] == 319 and f["league"] == 4 and f["position"] == "Centre Forward"
    assert [x["id"] for x in f["leagues"]] == [4]
    assert f["positions"] == core.positions()
    assert d["empty"] is None
    assert d["defaults"] == {"metric": "top5_psv99_kmh", "x": "sprint_count_p90",
                             "y": "top5_psv99_kmh"}
    pool = d["pool"]
    assert pool["title"] == "League One Centre Forwards" and pool["sub"] == "2026/27 · 450+ minutes"
    assert len(pool["players"]) == 12
    top = pool["leaders"]["top5_psv99_kmh"]
    assert top["n"] == 12 and top["thin"] is None
    first = pool["players"][top["order"][0][0]]
    assert first["name"] == "P<12>" and first["p"]["top5_psv99_kmh"] == 96
    assert first["href"] == "/player/12/4/319"
    assert {p["name"] for p in pool["players"] if p["orient"]} == {"P<3>", "P<4>"}
    assert [r["name"] for r in d["squad"]["rows"]] == ["Our <A>", "Our B"]   # minutes, then name
    assert d["squad"]["columns"] == core.RATED
    assert d["squad"]["sub"] == "2026/27 · percentile vs his league and position"


def test_season_without_tracking_data_says_so(fake):
    d = _client().get("/api/physical?season=317").json()
    assert d["empty"] == "No physical data for 2024/25."
    assert d["pool"] is None and d["squad"] is None
    assert d["filters"]["season"] == 317


def test_bad_parameters_fall_back_to_defaults(fake):
    d = _client().get("/api/physical?season=x&league=99&position=Goalkeeper").json()
    f = d["filters"]
    assert (f["season"], f["league"], f["position"]) == (319, 4, "Centre Forward")


def test_other_season_and_position(fake):
    d = _client().get("/api/physical?season=318&league=4&position=Winger").json()
    assert d["filters"]["season"] == 318 and d["filters"]["position"] == "Winger"
    assert d["pool"]["players"] == [] and d["pool"]["none"] == core.NO_PLAYERS


def test_no_nan_anywhere(fake):
    import json
    text = _client().get("/api/physical").text
    assert "NaN" not in text and json.loads(text)["pool"]["players"]


# --- 2.36 additions ---------------------------------------------------------------------------
def test_physical_rating_rank_and_leaders(fake):
    d = _client().get("/api/physical").json()
    pool = d["pool"]
    assert d["rating"]["key"] == core.RATING_KEY and d["rating"]["label"] == "Physical rating"
    L = pool["leaders"][core.RATING_KEY]
    assert L["n"] == 12 and L["thin"] is None
    best = pool["players"][L["order"][0][0]]
    assert best["name"] == "P<12>" and best["phys_t"] == "1st of 12" and best["phys"] == 4.0
    ours = {r["name"]: r for r in d["squad"]["rows"]}
    assert ours["Our <A>"]["phys_t"] == "10th of 12"


def test_age_bands_and_scatter_follow_the_url(fake):
    d = _client().get("/api/physical?x=sprint_count_p90&y=top5_psv99_kmh&age=u23").json()
    assert [b["key"] for b in d["age_bands"]] == ["", "u21", "u23", "23-29", "30+"]
    assert d["filters"]["age"] == "u23"
    sc = d["scatter"]
    assert sc["x"] == "sprint_count_p90" and sc["y"] == "top5_psv99_kmh"
    assert sc["idx"] == [] and sc["top"] == []                  # everyone is 25
    full = _client().get("/api/physical?age=bad").json()
    assert full["filters"]["age"] == "" and len(full["scatter"]["idx"]) == 12
    assert full["scatter"]["median"]["x_t"] == "6.5"
    assert len(full["scatter"]["top"]) == 5


def test_tracked_matches_in_pool_and_squad(fake):
    d = _client().get("/api/physical").json()
    by = {p["name"]: p for p in d["pool"]["players"]}
    assert by["P<3>"]["matches"] == 23 and by["P<5>"]["matches"] is None
    ours = {r["name"]: r for r in d["squad"]["rows"]}
    assert ours["Our <A>"]["matches"] == 23 and ours["Our B"]["matches"] is None
