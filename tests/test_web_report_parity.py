"""The web Report page's numbers are Streamlit's, on the REAL database (skipped without one).

Streamlit's Report page calls `report.data.build(engine, p, c, s)` (plain, every frame read
fresh) and downloads `report.render.to_html` of it. The web page calls the same `build` with the
season-wide frames cached (`core.report_page.base_report`) and draws `core.report_page.view`.
Here: the cached build equals the plain build, every figure in the view is the plain build's
figure, the API's JSON is that view, and the download is Streamlit's document byte for byte
(except a thin pool, which the web page never shows as a rating)."""
import pytest
from sqlalchemy import create_engine

from lofc.config import settings

# (label, player_id, competition_id, season_id)
CASES = [
    ("winger", 39154, 5, 318),
    ("centre forward 2026/27", 47357, 5, 319),
    ("goalkeeper", 44875, 3, 318),
    ("Leyton Orient player", 24835, 4, 318),
    ("loanee at Orient", 391964, 903, 318),
    ("scout reports", 52132, 3, 318),
    ("thin pool", 2000030124, 901, 319),
    ("other league", 2000030124, 901, 318),
]
IDS = [c[0] for c in CASES]


@pytest.fixture(scope="module")
def engine():
    try:
        e = create_engine(settings.database_url)
        e.connect().close()
    except Exception:
        pytest.skip("no database")
    return e


@pytest.fixture(scope="module")
def pairs(engine):
    from lofc.core import report_page as rp
    from lofc.report import data
    out = {}
    for label, p, c, s in CASES:
        try:
            plain = data.build(engine, p, c, s)
        except ValueError:
            pytest.skip(f"{label}: no player-season in this database")
        out[label] = (plain, rp.base_report(p, c, s))
    return out


def _norm(x):
    """Comparable form: NaN (style fits of other positions) equals NaN."""
    import dataclasses
    import math
    if dataclasses.is_dataclass(x):
        return {f.name: _norm(getattr(x, f.name)) for f in dataclasses.fields(x)}
    if isinstance(x, dict):
        return {k: _norm(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_norm(v) for v in x]
    if isinstance(x, float) and math.isnan(x):
        return "NaN"
    return x


@pytest.mark.parametrize("label", IDS)
def test_cached_build_is_the_plain_build(pairs, label):
    plain, cached = pairs[label]
    assert _norm(cached) == _norm(plain)


@pytest.mark.parametrize("label", IDS)
def test_view_figures_are_the_reports(pairs, label):
    from lofc.core import report_page as rp
    from lofc.model.scorecard import MIN_PEERS_FOR_RANKING
    from lofc.report import render
    plain, _ = pairs[label]
    v = rp.view(plain)
    thin = plain.composite is not None and plain.peer_count < MIN_PEERS_FOR_RANKING
    ver = v["verdict"]
    if thin:
        assert ver["composite"] is None and ver["not_rated"].startswith(
            f"Not rated: only {plain.peer_count} comparable players")
    elif plain.composite is not None:
        assert ver["value"] == plain.composite and ver["composite"] == f"{plain.composite:.2f}"
        if plain.rank:
            assert ver["rank"].startswith(f"{plain.rank}") and f"of {plain.peer_count} " in ver["rank"]
    for b in ver["bands"]:
        band = plain.dimension_bands[b["name"]]
        if thin and b["name"] in ("Performance", "Physical"):
            assert b["value"] is None
        else:
            assert b["value"] == band
    counts = {c["label"]: c["text"] for c in v["technical"]["counts"]}
    half_up = lambda x: "—" if x is None else f"{int(float(x) + 0.5):,}"
    assert counts["Minutes"] == half_up(plain.minutes)
    assert counts["Goals"] == half_up(plain.goals)
    assert counts["Assists"] == half_up(plain.assists)
    bars = render.bar_inputs(plain)
    assert [b["value"] for b in v["technical"]["bars"]] == [b["shown"] for b in bars]
    assert [b["orient"] for b in v["technical"]["bars"]] == [b["orient"] for b in bars]
    assert v["physical"]["player"] == [plain.physical.get(k) for k, _ in render._PHYSICAL_AXES]
    assert v["technical"]["orient"] == (
        {"n": plain.benchmark_n, "label": f"Leyton Orient median (n={plain.benchmark_n})"}
        if plain.benchmark_n else None)


@pytest.mark.parametrize("label", IDS)
def test_download_is_streamlits_document(pairs, label):
    """Streamlit's page: `variants(base, None)` -> to_html(base). The web download is the same
    call with the thin-pool note (None when the pool is big enough)."""
    from lofc.core import report_page as rp
    from lofc.report import render
    plain, cached = pairs[label]
    _, html, data_only = rp.variants(cached, None, not_rated=rp.not_rated_note(cached))
    strip = lambda h: h.replace(plain.snapshot_date, "")
    if rp.not_rated_note(plain) is None:
        assert strip(html) == strip(render.to_html(plain))
    else:
        assert f"{plain.composite:.2f}" not in html.split("Club composite")[1][:400]


def test_api_json_is_the_view(engine, pairs):
    """Through the HTTP layer: the JSON equals the view of the same report."""
    import json
    from fastapi.testclient import TestClient  # noqa: F401
    from lofc.core import report_page as rp
    from web_fakes import FakeStore, login, make
    s = FakeStore()
    s.add(username="u", full_name="Ann Scout", role="scout", password="correct-horse-1")
    c, *_ = make(s)
    login(c, "u", "correct-horse-1")
    for label, p, comp, season in CASES:
        got = c.get(f"/api/report/{p}/{comp}/{season}").json()
        want = json.loads(json.dumps(rp.view(pairs[label][0],
                                             {"player": p, "competition": comp, "season": season})))
        got.pop("form")
        assert got == want, label
