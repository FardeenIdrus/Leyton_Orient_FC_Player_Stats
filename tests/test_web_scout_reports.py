"""Web front end: the Scout reports page shell and API (no database, no Google sheet: the data
layer and the sheet sync are faked). Real-database parity: test_web_scout_watchlist_parity.py."""
import pandas as pd
import pytest

from lofc.web.api import scout_reports as api
from web_fakes import FakeStore, login, make

H = {"X-LOFC-Request": "1"}


def _client(role="scout"):
    s = FakeStore()
    s.add(username="u", full_name="Ann Scout", role=role, password="correct-horse-1")
    c, *_ = make(s)
    login(c, "u", "correct-horse-1")
    return c


def _raw():
    cols = ["submission_id", "scout", "observation", "player_name", "club_name", "foot",
            "home_team", "away_team", "fixture_date", "comments", "positions_played",
            "recommended_positions", "grade", "squad_role", "verdict", "player_id", "linkable",
            "missing_since", "name_from_report", "composite", "composite_live", "rated_in",
            "birth_date", "league_id", "in_rating_season", "in_live_season"]
    rows = [
        dict(submission_id="s1", scout="Ann", observation="Live", player_name="Al <One>",
             club_name="Gills", verdict="Sign", player_id=1, composite=2.5, rated_in=4,
             league_id=4, in_rating_season=True, in_live_season=True, positions_played=["CM"],
             fixture_date=pd.Timestamp("2026-10-01"), home_team="Gills", away_team="Orient",
             comments="<script>alert(1)</script>\nSecond line", grade="B"),
        dict(submission_id="s2", scout="Bob", observation="Video", player_name="Bo Two",
             club_name="Mill", verdict="Don't sign", player_id=2, composite=3.07, rated_in=903,
             league_id=903, in_rating_season=True, in_live_season=False,
             positions_played=["RB"], name_from_report=True),
        dict(submission_id="s3", scout="Ann", observation="Live", player_name="Cy Three",
             club_name="X", verdict="Monitor", player_id=None),
        dict(submission_id="s4", scout="Ann", observation="Live", player_name="Di Four",
             club_name="Y", verdict="Sign", player_id=4, composite=None, rated_in=None,
             league_id=4, in_rating_season=True),
    ]
    base = dict.fromkeys(cols)
    return pd.DataFrame([{**base, **r} for r in rows], columns=cols)


def _scorecards():
    # player 1 in a 10-strong League One pool; player 2 in an 8-strong one (thin)
    rows = [(1, 4, "Central Mid")] + [(100 + i, 4, "Central Mid") for i in range(9)] \
        + [(2, 903, "Right Back")] + [(200 + i, 903, "Right Back") for i in range(7)]
    return pd.DataFrame([{"player_id": p, "competition_id": c, "season_id": 318,
                          "position_group": g, "objective_composite": 3.0} for p, c, g in rows])


def _rated_rows():
    return pd.DataFrame({"player_id": [1, 2], "competition_id": [4, 903], "season_id": [318, 318],
                         "minutes": [900, 800], "objective_composite": [2.5, 3.07]})


class FakeSync:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def __call__(self, engine, force=False):
        self.calls.append(force)
        if self.error:
            raise RuntimeError(self.error)
        return self.result


@pytest.fixture
def fake(monkeypatch):
    bundle = api.build_bundle(_raw(), 318, 319, {4: "League One", 903: "Scottish Championship"},
                              _scorecards(), _rated_rows())
    monkeypatch.setattr(api, "_bundle", lambda: bundle)
    monkeypatch.setattr(api, "_synced_at", lambda: None)
    sync = FakeSync({"changed": True, "written": 3})
    monkeypatch.setattr(api, "_sheet_sync", lambda: sync)
    monkeypatch.setattr(api, "get_engine", lambda: object())
    monkeypatch.setattr(api, "_after_sync", lambda: None)
    return bundle, sync


def test_page_and_api_need_a_session(fake):
    c, *_ = make(FakeStore())
    assert c.get("/scout-reports").status_code == 303
    assert c.get("/api/scout-reports").status_code == 401
    assert c.get("/api/scout-reports/report/s1").status_code == 401


def test_page_shell_renders(fake):
    r = _client().get("/scout-reports")
    assert r.status_code == 200
    assert 'id="v-scout-reports"' in r.text and "/js/scout_reports.js" in r.text
    assert "Currently building" not in r.text


def test_all_tab_rows_columns_and_counts(fake):
    d = _client().get("/api/scout-reports").json()
    assert d["tabs"] == [{"key": "all", "label": "All reports (4)"},
                         {"key": "disagree", "label": "Data disagrees (1)"},
                         {"key": "activity", "label": "Scout activity"}]
    assert d["caption"] == "4 of 4 reports · 4 players · 2 scouts · 3 matched to our data"
    heads = [c["label"] for c in d["columns"]]
    assert heads == ["Watched", "Player", "Fixture", "Club", "Position", "Scout", "Seen",
                     "Grade", "Verdict", "Rating (2025/26)", "Rating (2026/27)", "Data vs scout"]
    first = d["rows"][0]
    assert first["id"] == "s1" and first["cells"]["Watched"] == "2026-10-01"
    assert first["cells"]["Rating"] == "2.50" and first["href"] == "/player/1/4/318"
    assert d["rows"][1]["cells"]["Player"] == "Bo Two †"


def test_thin_last_season_rating_is_withheld_with_the_note(fake):
    d = _client().get("/api/scout-reports").json()
    bo = next(r for r in d["rows"] if r["id"] == "s2")
    assert bo["cells"]["Rating"] == "—"
    assert bo["cells"]["Data vs scout"] == "Not rated: only 8 comparable players (needs 10)"


def test_no_blank_reaches_the_page(fake):
    d = _client().get("/api/scout-reports").json()
    for r in d["rows"]:
        for v in r["cells"].values():
            assert v not in (None, "", "nan", "None", "NaN")


def test_filters_come_from_the_query(fake):
    c = _client()
    assert [r["id"] for r in c.get("/api/scout-reports?scout=Bob").json()["rows"]] == ["s2"]
    d = c.get("/api/scout-reports?dvs=No%20rating&data=In%20our%20data").json()
    assert [r["id"] for r in d["rows"]] == ["s2", "s4"]
    assert d["caption"].startswith("2 of 4 reports")
    assert [r["id"] for r in c.get("/api/scout-reports?q=three").json()["rows"]] == ["s3"]
    # a value that is not an option filters nothing out silently: it matches nothing
    assert c.get("/api/scout-reports?league=Nowhere").json()["rows"] == []


def test_options_are_the_streamlit_lists(fake):
    o = _client().get("/api/scout-reports").json()["options"]
    assert o["League"] == ["All", "League One", "Scottish Championship"]
    assert o["Scout"] == ["All", "Ann", "Bob"]
    assert o["Data vs scout"][0] == "All"


def test_disagree_tab_ignores_the_filters(fake):
    d = _client().get("/api/scout-reports?tab=disagree&scout=Bob").json()
    assert [r["id"] for r in d["rows"]] == ["s1"]
    assert d["caption"] == "1 reports: Sign but rated under 3.0, or Don't sign but rated 3.5+."


def test_activity_tab(fake):
    d = _client().get("/api/scout-reports?tab=activity").json()
    assert d["activity"]["columns"] == ["Scout", "Reports", "Live", "Video", "Sign", "Players"]
    assert d["activity"]["rows"][0] == ["Ann", 3, 3, 0, 2, 3]
    assert "rows" not in d or d["rows"] == []


def test_sync_line(fake):
    d = _client().get("/api/scout-reports").json()
    assert d["sync"]["warn"] is True and d["sync"]["line"].startswith("Never synced")


def test_report_detail_is_raw_text_for_the_page_to_escape(fake):
    d = _client().get("/api/scout-reports/report/s1").json()
    assert d["card"]["body"] == "<script>alert(1)</script>\nSecond line"
    assert d["card"]["player"] == "Al <One>"
    assert d["card"]["meta"] == "Ann · Live · Grade B"
    assert d["open"] == {"href": "/player/1/4/318", "label": "Open card"}


def test_report_detail_captions(fake):
    c = _client()
    assert c.get("/api/scout-reports/report/s3").json()["caption"] == \
        "Not in our data: no rating or peer comparison exists for him."
    assert c.get("/api/scout-reports/report/s4").json()["caption"] == \
        "In our data, but no rated season yet: no card to open."
    assert c.get("/api/scout-reports/report/nope").status_code == 404


def test_empty_state(monkeypatch, fake):
    monkeypatch.setattr(api, "_bundle", lambda: None)
    d = _client().get("/api/scout-reports").json()
    assert d["empty"] is True and d["text"] == "No scout reports have been synced yet."


# --- the Refresh write -----------------------------------------------------------------------
def test_sync_needs_session_and_header(fake):
    _, sync = fake
    c, *_ = make(FakeStore())
    assert c.post("/api/scout-reports/sync").status_code == 401
    assert _client().post("/api/scout-reports/sync").status_code == 403
    assert sync.calls == []


@pytest.mark.parametrize("role", ["scout", "medical", "head_of_recruitment", "admin"])
def test_sync_open_to_every_role_as_streamlit(fake, role):
    _, sync = fake
    r = _client(role).post("/api/scout-reports/sync", headers=H)
    assert r.status_code == 200 and r.json()["ok"] is True
    assert r.json()["sync"]["line"].endswith(" · 3 reports updated")
    assert sync.calls == [False]                         # force=False, as the Streamlit button


def test_sync_unchanged_suffix(monkeypatch, fake):
    monkeypatch.setattr(api, "_sheet_sync", lambda: FakeSync({"changed": False, "written": 0}))
    r = _client().post("/api/scout-reports/sync", headers=H)
    assert r.json()["sync"]["line"].endswith(" · sheet unchanged")


def test_sync_failure_is_shown_not_raised(monkeypatch, fake):
    monkeypatch.setattr(api, "_sheet_sync", lambda: FakeSync(error="sheet not configured"))
    r = _client().post("/api/scout-reports/sync", headers=H)
    assert r.status_code == 200
    assert r.json() == {"ok": False,
                        "error": "Could not read the scouting sheet: sheet not configured"}


def test_sync_clears_the_web_caches(monkeypatch, fake):
    calls = []
    monkeypatch.setattr(api, "_after_sync", lambda: calls.append(1))
    _client().post("/api/scout-reports/sync", headers=H)
    assert calls == [1]


def test_squad_role_filter_and_options(monkeypatch):
    raw = _raw()
    raw["squad_role"] = ["Core (>70% of Minutes)", "Fringe (<20% of Minutes)",
                         "Core (>70% of Minutes)", None]
    bundle = api.build_bundle(raw, 318, 319, {4: "League One", 903: "Scottish Championship"},
                              _scorecards(), _rated_rows())
    monkeypatch.setattr(api, "_bundle", lambda: bundle)
    monkeypatch.setattr(api, "_synced_at", lambda: None)
    c = _client()
    d = c.get("/api/scout-reports").json()
    assert d["options"]["Squad role"] == ["All", "Core (>70% of Minutes)", "Fringe (<20% of Minutes)"]
    d = c.get("/api/scout-reports?role=Core%20(%3E70%25%20of%20Minutes)").json()
    assert [r["id"] for r in d["rows"]] == ["s1", "s3"]
    assert d["caption"].startswith("2 of 4 reports")
    assert "f-role" in c.get("/scout-reports").text
