"""Compare page API (src/lofc/web/api/compare.py). Access + page tests run anywhere; the parity
tests need the real database: the API's figures must equal what the Streamlit Compare page
renders for the same players (its own `_compare`, driven with a recording stand-in for `st`)."""
import contextlib
import html as htmllib
import re

import pytest
from sqlalchemy import create_engine

from lofc.config import settings
from web_fakes import FakeStore, login, make


def _client():
    s = FakeStore()
    s.add(username="u", full_name="Ann Scout", role="head_of_recruitment", password="correct-horse-1")
    c, *_ = make(s)
    login(c, "u", "correct-horse-1")
    return c


def _need_db():
    try:
        create_engine(settings.database_url).connect().close()
    except Exception:
        pytest.skip("no database")


@pytest.mark.parametrize("path", ["/api/compare", "/api/compare/pool", "/api/compare/search"])
def test_every_endpoint_needs_a_session(path):
    c, *_ = make()
    assert c.get(path).status_code == 401


def test_page_needs_a_session_and_has_every_control():
    c, *_ = make()
    assert c.get("/compare").status_code == 303
    page = _client().get("/compare").text
    for label in ("Season", "Position", "Leagues", "Rank as", "Player A", "Player B",
                  "Player C (optional)", "Market value", "Packing zones", "Measure",
                  # C4 (owner 2026-11-09): the Players page's extra filters, folded away
                  "More filters", "Minimum minutes", "Maximum age", "Preferred foot",
                  "Contract expiry", "Loan status", "Playing style", "Strong only"):
        assert label in page, label
    assert re.search(r'<script type="module" src="/static/v/[0-9a-f]+/js/compare.js">', page)
    assert not re.search(r"<script(?![^>]*\bsrc=)", page) and not re.search(r"\son[a-z]+=", page)


def test_slot_keys_parse_and_junk_is_ignored():
    from lofc.web.api import compare as api
    assert api.parse_key("39154-5") == (39154, 5)
    for junk in ("", None, "abc", "1-2-3", "-5", "1-"):
        assert api.parse_key(junk) is None


def test_each_slot_may_carry_its_own_season_and_old_urls_use_the_page_season():
    """Owner 2026-11-20: `a=pid-cid&a_season=318`; a slot without one (every old URL) is in the
    page season, and so is one naming a season we do not hold."""
    from lofc.web.api import compare as api
    seasons = (317, 318, 319)
    got = api.slot_keys({"a": "1-4", "a_season": "318", "b": "2-5", "c": "3-6",
                         "c_season": "999"}, 319, seasons)
    assert got == {"a": (1, 4, 318), "b": (2, 5, 319), "c": (3, 6, 319)}
    assert api.slot_keys({"a": "1-4"}, 318, seasons) == {"a": (1, 4, 318), "b": None, "c": None}
    assert api.slot_keys({"a": "junk", "a_season": "318"}, 319, seasons)["a"] is None


def test_page_has_a_season_picker_per_slot():
    page = _client().get("/compare").text
    for slot, label in (("a", "Player A"), ("b", "Player B"), ("c", "Player C")):
        assert f'id="season-{slot}"' in page and f'aria-label="{label} season"' in page


# ---- real database: parity with what Streamlit renders ------------------------------------

class _Col:
    def __init__(self, rec):
        self.rec = rec

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def selectbox(self, label, options, key=None, **kw):
        return self.rec.session_state.get(key)


class _St:
    """Records what `tabs/compare._compare` draws."""
    def __init__(self, state):
        self.session_state = state
        self.calls = []

    def _add(self, kind, value):
        self.calls.append((kind, value))

    def warning(self, t): self._add("warning", t)
    def info(self, t): self._add("info", t)
    def error(self, t): self._add("error", t)
    def caption(self, t): self._add("caption", t)
    def markdown(self, t, **kw): self._add("markdown", t)
    def iframe(self, h, height=None): self._add("iframe", h)

    def columns(self, n):
        return [_Col(self) for _ in range(n if isinstance(n, int) else len(n))]

    def plotly_chart(self, fig, **kw):
        self._add("plotly", [(t["name"], list(t["theta"])[:-1], list(t["r"])[:-1])
                             for t in fig.to_plotly_json()["data"]])

    @contextlib.contextmanager
    def expander(self, label):
        self._add("expander", label)
        yield

    def selectbox(self, label, options, key=None, format_func=None, **kw):
        return self.session_state.get(key, options[0])


def _plain(markup):
    markup = re.sub(r"<style>.*?</style>", "", markup, flags=re.S)
    return htmllib.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", markup))).strip()


def _html_rows(markup):
    """[[cell text, ...], ...] of an HTML table's body rows (header cell first)."""
    body = re.search(r"<tbody>(.*)</tbody>", markup, re.S).group(1)
    return [[_plain(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S)]
            for tr in re.findall(r"<tr>(.*?)</tr>", body, re.S)]


def _streamlit(season, position, archetype, keys, leagues=(), money=False, extra=None):
    """Draw the Streamlit Compare page for these players; return the recorder. `extra`: more
    PoolFilters fields (the sidebar's minutes / age / foot / contract / loan / style)."""
    from lofc.core.players_pool import PoolFilters, build_pool
    from lofc.dashboard import loaders as L
    from lofc.dashboard.tabs import compare as T
    from lofc.dashboard.theme import NONE_OPTION
    built = build_pool(PoolFilters(season_id=season, position=position, archetype=archetype,
                                   leagues=tuple(leagues), **(extra or {})))
    idx = built.search_index
    label = {(int(r.player_id), int(r.competition_id)): r.label for r in idx.itertuples()}
    state = {k: label[p] for k, p in zip(("cmp_a", "cmp_b", "cmp_c"), keys)}
    state.setdefault("cmp_c", NONE_OPTION)
    rec = _St(state)
    real = T.st
    T.st = rec
    try:
        T._compare(_Col(rec), built.pool, position, archetype, season, money,
                   L.load_metric_values(season), idx)
    finally:
        T.st = real
    return rec


def _api(c, season, position, archetype, keys, leagues=(), money=False, params=()):
    q = [("season", season), ("position", position), ("rank_as", archetype), *params]
    q += [(slot, f"{p}-{cc}") for slot, (p, cc) in zip("abc", keys)]
    q += [("leagues", lg) for lg in leagues]
    if money:
        q.append(("money", "1"))
    r = c.get("/api/compare", params=q)
    assert r.status_code == 200
    return r.json()


CASES = [
    ("wingers, three", 318, "Winger", "All Metrics", [(39154, 5), (150216, 5), (47739, 5)], (), False),
    ("winger lens + money", 318, "Winger", "Direct & 1v1 Specialist", [(39154, 5), (150216, 5)], (), True),
    ("centre forwards, three leagues", 318, "Centre Forward", "All Metrics",
     [(307566, 65), (2000253655, 10243), (47357, 5)], (), False),
    ("goalkeepers", 318, "Goalkeeper", "All Metrics", [(66767, 3), (6423, 4)], (), False),
    ("2024/25 no physical", 317, "Winger", "All Metrics", [(142372, 903), (36385, 901)], (), False),
    ("2026/27", 319, "Centre Forward", "All Metrics", [(2000026608, 10243), (2000019608, 10097)], (), False),
    ("league filter", 318, "Centre Back", "All Metrics", [(38876, 3), (37162, 65)],
     ("Championship", "National League"), False),
]


@pytest.fixture(scope="module")
def client():
    _need_db()
    return _client()


def _resolve(client, case):
    """Keep only cases whose players exist in this database's season (the local DB is a dump)."""
    label, season, position, arch, keys, leagues, money = case
    d = _api(client, season, position, arch, keys, leagues, money)
    got = [(p["player_id"], p["competition_id"]) for p in d.get("players") or []]
    if got != [tuple(k) for k in keys]:
        pytest.skip(f"{label}: players not all in this database ({d.get('message')})")
    return d


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_summary_table_equals_streamlits(client, case):
    label, season, position, arch, keys, leagues, money = case
    d = _resolve(client, case)
    rec = _streamlit(season, position, arch, keys, leagues, money)
    summary = next(v for k, v in rec.calls if k == "markdown" and "lofc-cmp" in v)
    old = {r[0]: r[1:] for r in _html_rows(summary)}
    rename = {"Composite": "Overall", "Composite trend": "Overall trend"}
    assert [rename.get(r["attribute"], r["attribute"]) for r in d["summary"]["rows"]] == list(old)
    for r in d["summary"]["rows"]:
        want = old[rename.get(r["attribute"], r["attribute"])]
        got = [" ".join(x for x in (c.get("now"), c.get("sub")) if x) if r["kind"] == "value"
               else c["text"] for c in r["cells"]]
        assert got == want, r["attribute"]
    head = re.search(r"<thead>(.*?)</thead>", summary, re.S).group(1)
    names = [_plain(n) for n in re.findall(r'<span class="nm">(.*?)</span>', head)]
    assert [p["header_name"] for p in d["players"]] == names


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_metric_tables_equal_streamlits(client, case):
    label, season, position, arch, keys, leagues, money = case
    d = _resolve(client, case)
    rec = _streamlit(season, position, arch, keys, leagues, money)
    tables = [v for k, v in rec.calls if k == "markdown" and "lofc-mt" in v]

    def api_rows(block):
        return [[r["label"] + (f" {r['tier']}" if r.get("tier") else "")]
                + [" ".join(x for x in (c["text"], c.get("pct_text")) if x) for c in r["cells"]]
                for r in block["rows"]]
    api_tables = [d["perf_table"]] + ([d["perf_other"]] if d["perf_other"]["rows"] else []) \
        + ([d["phys_table"]] if d.get("phys_table") and d["phys_table"]["rows"] else []) \
        + ([d["phys_other"]] if d.get("phys_other") and d["phys_other"]["rows"] else [])
    assert len(api_tables) == len(tables)
    for a, old in zip(api_tables, tables):
        assert api_rows(a) == _html_rows(old)
        # best / worst colouring is Streamlit's
        old_cls = [re.findall(r'<td(?: class="(best|worst)")?>', tr)
                   for tr in re.findall(r"<tr>(.*?)</tr>", re.search(r"<tbody>(.*)</tbody>", old, re.S).group(1), re.S)]
        if len({p["competition_id"] for p in d["players"]}) > 1:
            # owner 2026-11-20: percentiles of different leagues are not compared -- no colour
            assert all(c["cls"] is None for r in a["rows"] for c in r["cells"])
        else:
            assert [[c["cls"] or "" for c in r["cells"]] for r in a["rows"]] == old_cls


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_radars_and_captions_equal_streamlits(client, case):
    label, season, position, arch, keys, leagues, money = case
    d = _resolve(client, case)
    rec = _streamlit(season, position, arch, keys, leagues, money)
    charts = [v for k, v in rec.calls if k == "plotly"]
    api_charts = [x for x in (d["perf_radar"], d.get("phys_radar")) if x and x["traces"]]
    assert len(api_charts) == len(charts)
    for a, old in zip(api_charts, charts):
        assert [t["name"] for t in a["traces"]] == [t[0] for t in old]
        assert a["labels"] == old[0][1]
        for t, (_, _, r) in zip(a["traces"], old):
            assert [0 if v is None else v for v in t["values"]] == pytest.approx(r)
    captions = [v for k, v in rec.calls if k == "caption"]
    for cap in (d["perf_radar"].get("no_data"), d["perf_radar"].get("leagues_note"),
                (d.get("phys_radar") or {}).get("no_data"), d["summary"]["note"]):
        if cap:
            assert cap in captions


def test_zones_equal_streamlits_for_every_measure(client):
    from lofc.dashboard import compare_tables as ct
    from lofc.dashboard.tabs.compare import row_for_label  # noqa: F401  (import check)
    d = _resolve(client, CASES[0])
    if not d.get("zones"):
        pytest.skip("no zone data")
    recs = []
    from lofc.core.card import card_row
    for p in d["players"]:
        row, _, _ = card_row(p["player_id"], p["competition_id"], p["season_id"])
        recs.append(row)
    for fam in ct.ZONE_FAMILIES:
        old = ct.zone_panels(recs, fam)
        new = d["zones"]["measures"][fam]
        for o, n in zip(old, new):
            if o is None:
                assert n is None
                continue
            assert set(o) == set(n)
            for code, (text, pct) in o.items():
                assert n[code]["text"] == text
                assert n[code]["pct"] == (None if pct is None or pct != pct else round(float(pct)))


def test_thin_pool_player_shows_no_composite_and_no_percentiles(client):
    """Owner D1 (new site): a pool under MIN_PEERS_FOR_RANKING is never shown as a rating, and
    (owner 2026-11-16) no percentile either: "—" in the tables, off the radars, and the card's
    line. Streamlit's Compare still shows one (live site unchanged by owner decision)."""
    # Harry Gathercole, a Premier League 2 Winger (pool of 8 on 2026-11-16).
    q = [("season", 319), ("position", "Winger"), ("a", "2000159726-903")]
    d = client.get("/api/compare", params=q).json()
    if not d.get("players") or d["players"][0]["player_id"] != 2000159726:
        pytest.skip("Gathercole not in this database")
    if not d["players"][0]["not_rated"]:
        pytest.skip("the pool has reached the floor")
    p = d["players"][0]
    assert re.fullmatch(r"Not rated: only \d+ Wingers in Premier League 2 with 450\+ minutes "
                        r"\(needs 10\)\.", p["not_rated"])
    assert p["pool_tag"] is None
    comp = next(r for r in d["summary"]["rows"] if r["attribute"] == "Composite")
    assert comp["cells"][0]["now"] == "—"
    assert p["name"] not in [t["name"] for t in d["perf_radar"]["traces"]]
    assert not d["perf_radar"]["no_data"] or p["name"] not in d["perf_radar"]["no_data"]
    cells = [r["cells"][0] for r in d["perf_table"]["rows"] if r["cells"][0]["text"] != "—"]
    assert cells and all(c["pct"] is None and c["pct_text"] == "—" for c in cells)
    other = [r["cells"][1] for r in d["perf_table"]["rows"]]
    assert any(c["pct_text"] and c["pct_text"].startswith("P") for c in other)
    assert re.search(r"\b\d+ Premier League 2 Wingers", d["perf_radar"]["sub"])


def test_midfield_pool_player_is_tagged_and_keeps_percentiles(client):
    """Lyall Cameron, the only rankable Scottish Premiership Central Mid in 2026/27: rated
    against all Scottish Premiership midfielders (the midfield fallback), tagged so."""
    q = [("season", 319), ("position", "Central Mid"), ("a", "2000169232-901")]
    d = client.get("/api/compare", params=q).json()
    if not d.get("players") or d["players"][0]["player_id"] != 2000169232:
        pytest.skip("Cameron not in this database")
    p = d["players"][0]
    if p["not_rated"]:
        pytest.skip("not rated in this database")
    assert p["pool_tag"] == "Rated against all midfielders"
    assert p["vs"] == "Scottish Premiership midfielders"
    assert any(v is not None for t in d["perf_radar"]["traces"] if t["name"] == p["header_name"]
               for v in t["values"])


def test_defaults_come_from_the_pool_and_the_url_slots_are_returned(client):
    d = client.get("/api/compare", params={"season": 318, "position": "Winger"}).json()
    assert len(d["players"]) == 2 and d["slots"]["a"] and d["slots"]["b"] and d["slots"]["c"] is None
    pool = client.get("/api/compare/pool", params={"season": 318, "position": "Winger"}).json()
    assert [p["key"] for p in pool["players"][:2]] == [d["slots"]["a"], d["slots"]["b"]]


def test_other_position_slot_is_dropped_and_messages_are_streamlits(client):
    d = client.get("/api/compare", params={"season": 318, "position": "Winger",
                                           "a": "44875-3"}).json()     # a goalkeeper
    assert d["slots"]["a"] != "44875-3"
    d = client.get("/api/compare", params={"season": 318, "position": "Winger",
                                           "a": "39154-5", "b": "39154-5"}).json()
    assert d["message"] == {"level": "info", "text": "Pick two different players to compare."}


def test_no_blank_leaks(client):
    d = _resolve(client, CASES[0])

    def walk(x, path="$"):
        if isinstance(x, dict):
            for k, v in x.items():
                walk(v, f"{path}.{k}")
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, f"{path}[{i}]")
        elif isinstance(x, str):
            assert not re.fullmatch(r"(?i)\s*(nan|none|null|undefined)\s*", x), path
            assert "nan" not in x.split(), path
        elif isinstance(x, float):
            assert x == x, path
    walk(d)


# ---- C4: the Players page's "More filters" narrow the picker list ---------------------------
MORE = {"min_minutes": 1500, "max_age": 24, "foot": "Left"}
MORE_Q = [("min_minutes", "1500"), ("max_age", "24"), ("foot", "Left")]


def test_more_filters_narrow_the_picker_list_as_the_pool(client):
    """The list a picker shows = the Players pool for the same filters, in ranking order."""
    from lofc.core.players_pool import PoolFilters, build_pool
    q = [("season", "318"), ("position", "Winger")]
    full = client.get("/api/compare/pool", params=q).json()["players"]
    narrow = client.get("/api/compare/pool", params=q + MORE_Q).json()["players"]
    assert 0 < len(narrow) < len(full)
    from lofc.core import compare as C
    from lofc.dashboard import loaders as L
    built = build_pool(PoolFilters(season_id=318, position="Winger", **MORE))
    # owner 2026-11-20: league by league (League One first), the pool's order within each
    grouped = C.league_grouped(built.pool, (), L.league_names())
    want = [f"{int(r.player_id)}-{int(r.competition_id)}" for r in grouped.itertuples()]
    assert [p["key"] for p in narrow] == [k for k in want if k in {p["key"] for p in full}]


def test_style_filter_narrows_and_strong_only_needs_a_style(client):
    from lofc.core import players_pool as pp
    style = pp.styles_by_position()["Winger"][0]
    q = [("season", "318"), ("position", "Winger")]
    full = client.get("/api/compare/pool", params=q).json()["players"]
    st = client.get("/api/compare/pool", params=q + [("style", style)]).json()["players"]
    strong = client.get("/api/compare/pool", params=q + [("style", style), ("strong_only", "1")]).json()["players"]
    assert len(strong) <= len(st) < len(full)
    assert client.get("/api/compare/pool", params=q + [("strong_only", "1")]).json()["players"] == full


def test_a_pick_hidden_by_the_filters_is_still_compared(client):
    """Typing a name searches everyone: a picked player outside the filters still shows."""
    d = _api(client, 318, "Winger", "All Metrics", [(39154, 5), (150216, 5)],
             params=[("max_age", "18"), ("min_minutes", "3000")])
    if not d.get("players"):
        pytest.skip(d.get("message"))
    assert [(p["player_id"], p["competition_id"]) for p in d["players"]] == [(39154, 5), (150216, 5)]


def test_summary_with_more_filters_equals_streamlits(client):
    keys = [(39154, 5), (150216, 5)]
    d = _api(client, 318, "Winger", "All Metrics", keys, params=MORE_Q)
    if [(p["player_id"], p["competition_id"]) for p in d.get("players") or []] != keys:
        pytest.skip("players not in this database")
    rec = _streamlit(318, "Winger", "All Metrics", keys, extra=MORE)
    summary = next(v for k, v in rec.calls if k == "markdown" and "lofc-cmp" in v)
    old = {r[0]: r[1:] for r in _html_rows(summary)}
    rename = {"Composite": "Overall", "Composite trend": "Overall trend"}
    for r in d["summary"]["rows"]:
        got = [" ".join(x for x in (c.get("now"), c.get("sub")) if x) if r["kind"] == "value"
               else c["text"] for c in r["cells"]]
        assert got == old[rename.get(r["attribute"], r["attribute"])], r["attribute"]


# ---- C1: a compared Orient player is left out of the Orient median line ---------------------
# Owner 2026-11-20: the line is drawn only when every shown player is League One in its season.
DOBRA, AKHAMRICH, OTHER = (32656, 5), (298316, 5), (39154, 5)
ONEILL, COZIER, TANNER = (139708, 4), (161878, 4), (286402, 4)       # League One wingers, 2025/26


def _orient_label(d):
    return d["perf_radar"]["orient"]["label"] if d["perf_radar"].get("orient") else None


def _keys(d):
    return [(p["player_id"], p["competition_id"]) for p in d.get("players") or []]


def test_orient_median_leaves_out_a_compared_orient_player(client):
    from lofc.core import squad
    # owner 2B (2026-11-20): only ours rated in League One that season make the line
    _, n_all = squad.orient_median("Winger", 318, competition_id=4)
    d = _api(client, 318, "Winger", "All Metrics", [ONEILL, COZIER])
    if n_all < 2 or _keys(d) != [ONEILL, COZIER]:
        pytest.skip("Orient League One wingers not in this database")
    want, n = squad.orient_median("Winger", 318, exclude_player_id=ONEILL[0], competition_id=4)
    assert n == n_all - 1
    assert _orient_label(d) == f"Leyton Orient median ({n}), Wingers"
    axes = d["perf_radar"]["axes"]
    assert d["perf_radar"]["orient"]["values"] == pytest.approx([want.get(m) for m in axes])
    phys = d["phys_radar"]["orient"]
    assert phys["label"] == _orient_label(d)
    assert phys["values"] == pytest.approx([want.get(m) for m in d["phys_radar"]["axes"]])


def test_orient_median_leaves_out_each_compared_orient_player(client):
    from lofc.core import squad
    from lofc.web.api import compare as api
    out = (DOBRA[0], AKHAMRICH[0], ONEILL[0])
    l1 = [p for p in squad._ours("Winger", 318) if p.competition_id == 4]
    if not l1:
        pytest.skip("Orient League One wingers not in this database")
    want = len([p for p in l1 if p.player_id not in out])
    assert api._orient("Winger", 318, out)[1] == want


def test_orient_median_unchanged_when_no_compared_player_is_ours(client):
    from lofc.core import squad
    want, n_all = squad.orient_median("Winger", 318, competition_id=4)
    d = _api(client, 318, "Winger", "All Metrics", [COZIER, TANNER])
    if not n_all or _keys(d) != [COZIER, TANNER]:
        pytest.skip("no Orient wingers")
    assert _orient_label(d) == f"Leyton Orient median ({n_all}), Wingers"
    assert d["perf_radar"]["orient"]["values"] == pytest.approx(
        [want.get(m) for m in d["perf_radar"]["axes"]])
    assert d["perf_radar"]["orient_note"] is None


def test_no_orient_median_beside_players_of_another_league(client):
    from lofc.core import squad
    d = _resolve(client, CASES[0])                       # League Two wingers, 2025/26
    if not squad.orient_median("Winger", 318)[1]:
        pytest.skip("no Orient wingers")
    assert d["perf_radar"]["orient"] is None and d["phys_radar"]["orient"] is None
    assert d["perf_radar"]["orient_note"] == "Orient median shown for League One 2025/26 only."


# ---- C5 (owner 2026-11-09): search lists only the selected Position ------------------------
def test_search_lists_only_the_selected_position(client):
    from lofc.core import players_pool as pp
    everyone = pp.search(318, "Mendez")
    if len({r["position"] for r in everyone}) < 2:
        pytest.skip("'Mendez' does not span two positions in this database")
    for pos in {r["position"] for r in everyone}:
        got = client.get("/api/compare/search", params={"season": 318, "position": pos,
                                                        "q": "Mendez"}).json()["results"]
        assert got and {r["position"] for r in got} == {pos}
        want = [r["label"] for r in pp.search(318, "Mendez", limit=10_000)
                if r["position"] == pos][:30]
        # the page season first, as before; then players we only hold in another season
        assert [r["label"] for r in got][:len(want)] == want
        assert all(r["season_id"] == 318 for r in got[:len(want)])
        here = {r["player_id"] for r in got[:len(want)]}
        assert all(r["season_id"] != 318 and r["player_id"] not in here for r in got[len(want):])
    assert client.get("/api/compare/search", params={"season": 318, "q": ""}).json() == {"results": []}


# ---- owner 2026-11-20: one season per slot ---------------------------------------------------
DIAMOND, LISBIE = (32960, 4), (150216, 4)      # League One wingers, 2026/27
LISBIE_25 = (150216, 5)                        # Lisbie, League Two, 2025/26


def _mixed(client):
    d = client.get("/api/compare", params=[("season", 319), ("position", "Winger"),
                                           ("a", "%d-%d" % DIAMOND), ("b", "%d-%d" % LISBIE_25),
                                           ("b_season", 318)]).json()
    if [(p["player_id"], p["competition_id"], p["season_id"]) for p in d.get("players") or []] \
            != [(*DIAMOND, 319), (*LISBIE_25, 318)]:
        pytest.skip(f"players not in this database ({d.get('message')})")
    return d


def test_a_slot_in_another_season_is_compared_with_its_season_and_league_shown(client):
    d = _mixed(client)
    assert d["slots"] == {"a": "%d-%d" % DIAMOND, "b": "%d-%d" % LISBIE_25, "c": None}
    assert d["slot_seasons"] == {"a": None, "b": 318, "c": None}
    assert [p["season_league"] for p in d["players"]] == ["2026/27 · League One",
                                                          "2025/26 · League Two"]
    assert d["slot_labels"]["b"].endswith("2025/26")
    opts = d["slot_options"]["b"]
    assert {"season": 318, "competition_id": 5, "label": "2025/26 · League Two"} in opts
    assert {"season": 319, "competition_id": 4, "label": "2026/27 · League One"} in opts
    assert [o["season"] for o in opts] == sorted((o["season"] for o in opts), reverse=True)


def test_different_league_or_season_has_no_best_worst_colour_and_says_why(client):
    d = _mixed(client)
    tables = [d["perf_table"], d["perf_other"], d.get("phys_table") or {"rows": []},
              d.get("phys_other") or {"rows": []}]
    cells = [c for t in tables for r in t["rows"] for c in r["cells"]]
    assert cells and all(c["cls"] is None for c in cells)
    assert any(c["pct_text"] for c in cells)                       # percentiles still shown
    assert "best green" not in d["perf_table"]["sub"]
    assert d["summary"]["mixed_note"] == "Ratings and percentiles are within each player's own league and season."
    assert d["perf_radar"]["leagues_note"] is None                  # one line, not two
    assert d["perf_radar"]["orient"] is None
    assert "2025/26" in d["perf_radar"]["sub"] and "2026/27" in d["perf_radar"]["sub"]


def test_same_league_and_season_keeps_colours_and_no_mixed_note(client):
    d = _resolve(client, CASES[0])
    assert d["summary"]["mixed_note"] is None
    assert d["slot_seasons"] == {"a": None, "b": None, "c": None}
    assert any(c["cls"] for r in d["perf_table"]["rows"] for c in r["cells"])
    assert d["perf_table"]["sub"].endswith("best green, worst red")


def test_a_player_can_be_compared_with_himself_in_another_season(client):
    d = client.get("/api/compare", params=[("season", 319), ("position", "Winger"),
                                           ("a", "%d-%d" % LISBIE), ("b", "%d-%d" % LISBIE_25),
                                           ("b_season", 318)]).json()
    if len(d.get("players") or []) != 2:
        pytest.skip(f"Lisbie not in this database ({d.get('message')})")
    names = [p["header_name"] for p in d["players"]]
    assert names == ["Kyreece Lisbie (2026/27)", "Kyreece Lisbie (2025/26)"]
    # his 2026/27 change from 2025/26 crosses leagues: what he had, no delta, no colour
    comp = next(r for r in d["summary"]["rows"] if r["attribute"] == "Composite")
    a = comp["cells"][0]
    if a.get("sub"):
        assert a["sub"].startswith("was ") and a["sub"].endswith("(League Two)")
        assert a["tone"] == "neutral"


def test_search_finds_a_player_held_only_in_another_season(client):
    """Picking him defaults his slot to the page season when he has data then, else his latest."""
    got = client.get("/api/compare/search", params={"season": 319, "position": "Winger",
                                                    "q": "Dobra"}).json()["results"]
    hit = [r for r in got if r["player_id"] == DOBRA[0]]
    if not hit:
        pytest.skip("Dobra not in this database")
    assert hit[0]["season_id"] == 318 and hit[0]["label"].endswith("2025/26")


def test_opening_picks_come_from_league_one_in_its_own_order(client):
    from lofc.core.players_pool import PoolFilters, build_pool
    d = client.get("/api/compare", params={"season": 318, "position": "Winger"}).json()
    built = build_pool(PoolFilters(season_id=318, position="Winger"))
    l1 = built.pool[built.pool["competition_id"] == 4]
    want = [f"{int(r.player_id)}-{int(r.competition_id)}" for r in l1.itertuples()][:2]
    assert [d["slots"]["a"], d["slots"]["b"]] == want


def test_orient_median_uses_only_ours_rated_in_league_one(monkeypatch):
    """Owner decision 2B (2026-11-20), applied to Compare: the Orient line is drawn only beside
    League One players, so it is built only from our players rated in League One that season --
    never one of ours rated in another league."""
    from types import SimpleNamespace as NS
    import pandas as pd
    from lofc.core import squad
    from lofc.dashboard import loaders as L
    from lofc.web.api import compare as api
    ours = [NS(player_id=1, competition_id=4), NS(player_id=2, competition_id=5),
            NS(player_id=3, competition_id=4)]
    seen = {}
    monkeypatch.setattr(squad, "squad", lambda: pd.DataFrame({"player_id": [1, 2, 3]}))
    monkeypatch.setattr(squad, "_ours", lambda *a, **k: list(ours))
    monkeypatch.setattr(squad, "_metric_cols", lambda pf: ["m"])
    monkeypatch.setattr(L, "load_scorecard_percentiles", lambda sid: None)
    monkeypatch.setattr(squad, "median_pct",
                        lambda ps, ms: (seen.setdefault("ids", [p.player_id for p in ps]), ({}, len(ps)))[1])
    for exclude in ((), (9,), (8, 9)):
        seen.clear()
        api._orient("Winger", 9319, exclude)          # a season no other test caches
        assert seen["ids"] == [1, 3], exclude
