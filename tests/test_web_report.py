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

    scouts = []

    def player_scout_verdicts(self, player_id):
        self.scout_calls = getattr(self, "scout_calls", []) + [player_id]
        return self.scouts

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
    assert c.get(KEY + "?variant=data_only").json()["error"]["kind"] == "missing"


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


def _assessed():
    return _report(stamp="Scout-verified", narrative=data.Narrative(
        summary="Scout's own words.", why_sign=None, considerations=None, assessor="Bo Scout",
        assessor_role=None, approver=None, approved_at=None),
        dimension_bands={"Performance": 3.5, "Physical": 3.1, "Psychological": 4.0,
                         "Medical": 3.0})


def test_data_only_variant_leaves_out_every_authored_part(fake):
    """The data-only download is drawn in the browser from this view: no narrative, no
    Psychological / Medical value, the "Data only" stamp, and no form (it is not edited)."""
    fake.report = _assessed()
    c = _client()
    full = c.get(KEY).json()
    assert full["narrative"]["summary"] == ["Scout's own words."]
    j = c.get(KEY + "?variant=data_only").json()
    assert j["stamp"] == "Data only" and not j["authored"]
    assert j["narrative"]["summary"] == [] and "form" not in j
    bands = {b["name"]: b["value"] for b in j["verdict"]["bands"]}
    assert bands["Psychological"] is None and bands["Medical"] is None
    assert bands["Performance"] == 3.5


def test_view_names_both_files(fake):
    j = _client().get(KEY).json()
    assert j["filename"] == "Dilan_Markanday_25_26_report.html"
    assert j["data_only_filename"] == "Dilan_Markanday_25_26_data_only_report.html"


def test_downloads_are_built_in_the_browser_not_by_the_old_renderer(fake):
    """Both downloads are the page's own preview, saved by the browser (the photo never leaves
    it): the server's old-document routes are gone."""
    c = _client()
    assert c.get(KEY + "/download?variant=data_only").status_code in (404, 405)
    assert c.post(KEY + "/download", json={}, headers={"X-LOFC-Request": "1"}).status_code in (404, 405)
    import inspect
    src = inspect.getsource(report_api)
    assert "variants(" not in src and "to_html" not in src and "lofc.report.render" not in src


def test_thin_pool_data_only_withholds_the_composite(fake):
    fake.report = _report(peer_count=8, composite=4.49, rank=1)
    for q in ("", "?variant=data_only"):
        j = _client().get(KEY + q).json()
        assert j["verdict"]["composite"] is None and j["verdict"]["not_rated"]
        assert "4.49" not in str(j)


def test_page_has_the_photo_box_and_availability_rows(fake):
    t = _client().get("/report?player=39154&competition=5&season=318").text
    assert 'id="rp-photo"' in t and 'accept="image/*"' in t and "Add photo" in t
    assert 'id="f-avail"' in t and 'id="f-avail-add"' in t
    assert 'id="rp-dl-data"' in t and "<a class=\"btn\" id=\"rp-dl-data\"" not in t


def test_a_build_error_is_not_reported_as_a_missing_player(fake):
    """Only an unknown player-season is "missing"; another error says the report could not be
    built (Streamlit's own two messages)."""
    fake.report = "broken"
    j = _client().get(KEY).json()
    assert j["error"] == {"kind": "failed", "text": "The report could not be built."}


VERDICTS = [{"scout": "Bob", "verdict": "Don't sign", "date": "3 Oct 2026", "tone": "negative"},
            {"scout": "Ann", "verdict": "Sign", "date": "12 Sep 2026", "tone": "positive"}]


def test_scout_verdicts_in_the_report_and_its_preview_not_in_data_only(fake):
    """Owner 2026-11-13: each scout's latest verdict under Playing style; the data-only
    download is numbers only, so it carries none."""
    fake.scouts = VERDICTS
    c = _client()
    assert c.get(KEY).json()["scouts"] == VERDICTS
    assert c.post(KEY, json={"summary": "x"}, headers={"X-LOFC-Request": "1"}).json()["scouts"] == VERDICTS
    assert fake.scout_calls == [39154, 39154]
    j = c.get(KEY + "?variant=data_only").json()
    assert j["scouts"] == [] and "Bob" not in str(j)
    assert fake.scout_calls == [39154, 39154]


def test_page_has_the_scout_verdict_block_and_no_position_picker(fake):
    """Owner 2026-11-13: no Position picker; the search covers every player of the season."""
    t = _client().get("/report?player=39154&competition=5&season=318").text
    assert 'id="c-scouts"' in t and "Scout verdicts" in t
    assert 'id="rp-position"' not in t and 'for="rp-position"' not in t
    assert 'id="rp-season"' in t and 'id="rp-search"' in t


def test_season_players_list(fake, monkeypatch):
    """Owner 2026-11-13: the empty box lists every player of the season A-Z, from one cached
    answer: [player_id, competition_id, name, position, club, league, search key]."""
    from lofc.core import players_pool as pp
    rows = [[2, 4, "Aaron Ball", "Centre Back", "Club A", "League One", "aaronball"],
            [1, 5, "Zak Young", "Winger", "Club Z", None, "zakyoung"]]
    asked = []
    monkeypatch.setattr(pp, "season_players", lambda s: asked.append(s) or rows)
    from lofc.web.api import report as api
    monkeypatch.setattr(api, "_data_version", lambda: "v")
    api._players_json.cache_clear()
    c = _client()
    r = c.get("/api/report/players?season=318")
    assert r.status_code == 200 and r.json() == {"season": 318, "rows": rows}
    assert c.get("/api/report/players?season=318").json()["rows"] == rows
    assert asked == [318]                                              # built once
    assert c.get("/api/report/players?season=x").status_code == 400
    s = FakeStore()
    c2, *_ = make(s)
    assert c2.get("/api/report/players?season=318").status_code == 401


def _sheet(t):
    """The report sheet's own markup (from its opening tag to the end of the page section)."""
    i = t.index('id="rp-sheet"')
    return t[t.rindex("<", 0, i):t.index("</article>", i)]


def test_preview_is_one_sheet_without_cards(fake):
    """Owner 2026-11-13: one clean A4 page, not separate cards on a grey page; the controls sit
    outside it, so the downloads (built from the sheet) carry none."""
    t = _client().get("/report?player=39154&competition=5&season=318").text
    assert t.count('id="rp-sheet"') == 1 and '<article class="rp-sheet"' in t
    sheet = _sheet(t)
    assert 'class="card' not in sheet and "rp-form" not in sheet
    for i in ("rp-write", "rp-dl", "rp-dl-data", "rp-draft-clear"):
        assert f'id="{i}"' in t and f'id="{i}"' not in sheet
    for i in ("rp-photo", "h-name", "h-stamp", "c-verdict", "c-summary", "c-tech", "c-style",
              "c-scouts", "c-phys", "p-avail"):
        assert f'id="{i}"' in sheet, i
    # rows: Composite | Summary, Technical, (Playing style + Scout verdicts) | (Physical + Availability)
    assert sheet.index('id="c-verdict"') < sheet.index('id="c-summary"') < sheet.index('id="c-tech"') \
        < sheet.index('id="c-style"') < sheet.index('id="c-scouts"') < sheet.index('id="c-phys"') \
        < sheet.index('id="p-avail"')


def test_clear_draft_asks_first(fake):
    """Owner 2026-11-13: Clear draft asks inline ("Clear your draft? Yes · No"), no browser dialog."""
    t = _client().get("/report?player=39154&competition=5&season=318").text
    box = t.split('id="rp-draft-confirm"')[1].split("</span>")[0]
    import re
    assert re.search(r'id="rp-draft-confirm"[^>]*\bhidden', t)                # shut until asked
    assert "Clear your draft?" in box and 'id="rp-draft-yes"' in box and 'id="rp-draft-no"' in box
    assert ">Yes<" in box and ">No<" in box
    from pathlib import Path
    js = (Path(report_api.__file__).parents[1] / "static" / "js" / "report.js").read_text()
    assert "confirm(" not in js.replace("draftConfirm(", "") and "alert(" not in js


def test_draft_is_kept_in_the_browser_only(fake):
    """Owner 2026-11-13: the writer's draft survives leaving the page; it is never sent."""
    from pathlib import Path
    t = _client().get("/report?player=39154&competition=5&season=318").text
    assert "Clear draft" in t
    js = Path(report_api.__file__).parents[1] / "static" / "js"
    rules = (js / "report_draft.js").read_text()
    assert "'lofc.report.draft.'" in rules and "Photo not kept — too large to save" in rules
    assert "localStorage" not in rules                # storage is passed in (testable, optional)
    page = (js / "report.js").read_text()
    assert "./report_draft.js" in page and "localStorage" in page
