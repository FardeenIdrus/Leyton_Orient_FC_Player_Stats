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


def test_thin_pool_player_shows_no_composite_but_keeps_percentiles(client):
    """Owner D1 (new site): a pool under MIN_PEERS_FOR_RANKING is never shown as a rating.
    Streamlit's Compare still shows one (live site unchanged by owner decision)."""
    from lofc.model.scorecard import MIN_PEERS_FOR_RANKING
    q = [("season", 319), ("position", "Attacking Mid"), ("a", "2000030124-901")]
    d = client.get("/api/compare", params=q).json()
    if not d.get("players") or d["players"][0]["player_id"] != 2000030124:
        pytest.skip("Nygren not in this database")
    p = d["players"][0]
    assert p["not_rated"] and f"needs {MIN_PEERS_FOR_RANKING}" in p["not_rated"]
    comp = next(r for r in d["summary"]["rows"] if r["attribute"] == "Composite")
    assert comp["cells"][0]["now"] == "—"
    assert any(v is not None for v in d["perf_radar"]["traces"][0]["values"])
    assert re.search(r"\b\d+ Scottish Premiership Attacking Mids", d["perf_radar"]["sub"])


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
    built = build_pool(PoolFilters(season_id=318, position="Winger", **MORE))
    want = [f"{int(r.player_id)}-{int(r.competition_id)}" for r in built.pool.itertuples()]
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
DOBRA, AKHAMRICH, OTHER = (32656, 5), (298316, 5), (39154, 5)


def _orient_label(d):
    return d["perf_radar"]["orient"]["label"] if d["perf_radar"].get("orient") else None


def test_orient_median_leaves_out_a_compared_orient_player(client):
    from lofc.core import squad
    _, n_all = squad.orient_median("Winger", 318)
    d = _api(client, 318, "Winger", "All Metrics", [DOBRA, OTHER])
    if n_all < 3 or [(p["player_id"], p["competition_id"]) for p in d.get("players") or []] != [DOBRA, OTHER]:
        pytest.skip("Orient wingers not in this database")
    want, n = squad.orient_median("Winger", 318, exclude_player_id=DOBRA[0])   # = the card
    assert n == n_all - 1
    assert _orient_label(d) == f"Leyton Orient median ({n}), Wingers"
    axes = d["perf_radar"]["axes"]
    assert d["perf_radar"]["orient"]["values"] == pytest.approx([want.get(m) for m in axes])
    phys = d["phys_radar"]["orient"]
    assert phys["label"] == _orient_label(d)
    assert phys["values"] == pytest.approx([want.get(m) for m in d["phys_radar"]["axes"]])


def test_orient_median_leaves_out_each_compared_orient_player(client):
    from lofc.core import squad
    _, n_all = squad.orient_median("Winger", 318)
    d = _api(client, 318, "Winger", "All Metrics", [DOBRA, AKHAMRICH, OTHER])
    if n_all < 3 or len(d.get("players") or []) != 3:
        pytest.skip("Orient wingers not in this database")
    assert _orient_label(d) == f"Leyton Orient median ({n_all - 2}), Wingers"


def test_orient_median_unchanged_when_no_compared_player_is_ours(client):
    from lofc.core import squad
    want, n_all = squad.orient_median("Winger", 318)
    d = _resolve(client, CASES[0])
    if not n_all:
        pytest.skip("no Orient wingers")
    assert _orient_label(d) == f"Leyton Orient median ({n_all}), Wingers"
    assert d["perf_radar"]["orient"]["values"] == pytest.approx(
        [want.get(m) for m in d["perf_radar"]["axes"]])


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
        assert [r["label"] for r in got] == [r["label"] for r in pp.search(318, "Mendez", limit=10_000)
                                             if r["position"] == pos][:30]
    assert client.get("/api/compare/search", params={"season": 318, "q": ""}).json() == {"results": []}
