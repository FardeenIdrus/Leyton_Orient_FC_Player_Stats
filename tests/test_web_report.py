"""Web front end: the Report page shell and API (no database: the data layer is faked). The
view itself is tested in test_core_report_page.py and, on the real database, in
test_web_report_parity.py."""
import pytest

from lofc.report import data
from lofc.web.api import report as report_api
from web_fakes import FakeStore, login, make

KEY = "/api/report/39154/5/318"


def _report(**overrides):
    base = dict(
        player_name="Dilan Markanday", position="Winger", club="FC Chesterfield",
        league="League Two", season_label="25/26", age=24.1, foot="left", height_cm=175,
        nationality="England", contract_until="30 Jun 2027", minutes=2000.0, goals=5.0,
        assists=4.0, composite=3.4,
        dimension_bands={"Performance": 3.5, "Physical": 3.1, "Psychological": None,
                         "Medical": None},
        rank=5, peer_count=70, percentiles={}, physical={}, availability=None,
        availability_status="unknown", matches_missed=0, injuries=[], narrative=None,
        stamp=data.STAMP_DATA_ONLY, snapshot_date="09 Nov 2026",
        comparison_text="25/26 · League Two only · compared to 70 League Two Wingers over 450 minutes")
    base.update(overrides)
    return data.ReportData(**base)


class FakeCore:
    """report_page with the cached build swapped out; every other function is the real one."""

    def __init__(self, report=None):
        from lofc.core import report_page
        self.real, self.report, self.calls = report_page, report, []

    def __getattr__(self, name):
        return getattr(self.real, name)

    def base_report(self, p, c, s):
        self.calls.append((p, c, s))
        if self.report == "broken":
            raise ValueError("season_id 316 is not in _SEASON_LABELS")
        if self.report is None:
            raise ValueError("no player-season for player 1 in competition 2, season 3")
        return self.report


def _client(role="scout"):
    s = FakeStore()
    s.add(username="u", full_name="Ann Scout", role=role, password="correct-horse-1")
    c, *_ = make(s)
    login(c, "u", "correct-horse-1")
    return c


@pytest.fixture
def fake(monkeypatch):
    core = FakeCore(_report())
    monkeypatch.setattr(report_api, "_core", lambda: core)
    monkeypatch.setattr(report_api, "_season_choices",
                        lambda: ([{"id": 319, "name": "2026/27"}, {"id": 318, "name": "2025/26"}], 319))
    return core


def test_page_shell_needs_login_and_renders(fake):
    s = FakeStore()
    c, *_ = make(s)
    assert c.get("/report", follow_redirects=False).status_code == 303
    c = _client()
    r = c.get("/report?player=39154&competition=5&season=318")
    assert r.status_code == 200
    assert 'id="v-report"' in r.text and "/js/report.js" in r.text
    assert "Currently building" not in r.text
    assert '<option value="318">2025/26</option>' in r.text
    assert 'data-default-season="319"' in r.text


def test_api_needs_login(fake):
    s = FakeStore()
    c, *_ = make(s)
    assert c.get(KEY).status_code == 401


def test_view_json_has_the_report_and_the_form(fake):
    r = _client().get(KEY)
    assert r.status_code == 200
    j = r.json()
    assert j["name"] == "Dilan Markanday" and j["verdict"]["composite"] == "3.40"
    assert j["form"]["psychological"] and j["psych_caption"] == "Band: —"
    assert j["ids"] == {"player": 39154, "competition": 5, "season": 318}
    assert fake.calls == [(39154, 5, 318)]


def test_unknown_player_season_is_a_page_state_not_an_http_error(fake):
    """The page shows it as a message; a 404 would also log a console error in the browser."""
    fake.report = None
    c = _client()
    for r in (c.get(KEY), c.post(KEY, json={}, headers={"X-LOFC-Request": "1"})):
        assert r.status_code == 200 and r.json()["error"]["kind"] == "missing"
    assert c.get(KEY + "/download?variant=data_only").status_code == 404


def test_post_without_the_request_header_is_refused(fake):
    assert _client().post(KEY, json={"summary": "x"}).status_code == 403


def test_post_applies_the_author_and_never_writes(fake):
    crit = data.authored_from_inputs  # noqa: F841  (the real function is used underneath)
    from lofc.model import club_criteria as cc
    first = cc.PSYCHOLOGICAL_CRITERIA["Winger"][0]
    r = _client().post(KEY, json={"summary": "Quick and brave.", "psych": {first: 4}},
                       headers={"X-LOFC-Request": "1"})
    assert r.status_code == 200
    j = r.json()
    assert j["authored"] and j["stamp"].startswith("Report by Ann Scout · ")
    assert j["narrative"]["summary"] == ["Quick and brave."]
    assert j["psych_caption"] == "Band: 4.00"
    assert "form" not in j


def test_blank_post_is_the_base_report(fake):
    j = _client().post(KEY, json={}, headers={"X-LOFC-Request": "1"}).json()
    assert not j["authored"] and j["stamp"] == "Data only"


def test_data_only_download(fake):
    r = _client().get(KEY + "/download?variant=data_only")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "Dilan_Markanday_25_26_data_only_report.html" in r.headers["content-disposition"]
    assert "Data only" in r.text and "<!doctype html>" in r.text


def test_authored_download_carries_the_authors_text(fake):
    r = _client().post(KEY + "/download", json={"summary": "<b>Quick</b>"},
                       headers={"X-LOFC-Request": "1"})
    assert r.status_code == 200
    assert "Dilan_Markanday_25_26_report.html" in r.headers["content-disposition"]
    assert "&lt;b&gt;Quick&lt;/b&gt;" in r.text and "Report by Ann Scout" in r.text


def test_thin_pool_download_withholds_the_composite(fake):
    fake.report = _report(peer_count=8, composite=4.49, rank=1)
    r = _client().get(KEY + "/download?variant=data_only")
    assert "4.49" not in r.text and "Not rated: only 8 comparable players (needs 10)" in r.text
    j = _client().get(KEY).json()
    assert j["verdict"]["composite"] is None and j["verdict"]["not_rated"]


def test_a_build_error_is_not_reported_as_a_missing_player(fake):
    """Only an unknown player-season is "missing"; another error says the report could not be
    built (Streamlit's own two messages)."""
    fake.report = "broken"
    j = _client().get(KEY).json()
    assert j["error"] == {"kind": "failed", "text": "The report could not be built."}
