"""Find similar players on the REAL database (skipped without one): Charlie Wellens, Leyton
Orient, rated as a Full Back in League One 2026/27 (in 2025/26 he was an Attacking Mid)."""
import time

import pytest
from sqlalchemy import create_engine

from lofc.config import settings

PID, CID, SID = 52123, 4, 319


@pytest.fixture(scope="module")
def engine():
    try:
        e = create_engine(settings.database_url)
        e.connect().close()
    except Exception:
        pytest.skip("no database")
    return e


@pytest.fixture(scope="module")
def league(engine):
    from lofc.core import similar
    return similar.section(PID, CID, SID, "league")


def test_wellens_top_five_same_league(league, capsys):
    from lofc.core import similar
    assert league["available"] is True
    rows = league["rows"]
    assert len(rows) == similar.TOP_N
    assert all(r["competition_id"] == CID and r["season_id"] == SID for r in rows)
    assert PID not in [r["player_id"] for r in rows]
    sims = [r["similarity"] for r in rows]
    assert sims == sorted(sims, reverse=True) and all(0 < s <= 100 for s in sims)
    assert league["sub"].startswith("Closest Full Backs in League One")
    assert league["note"] is None
    with capsys.disabled():
        print("\nWellens 2026/27, League One full backs:")
        for r in rows[:5]:
            print(f"  {r['similarity']:>3}  {r['name']:<26} {r['club']:<24} age {r['age']:.1f}  "
                  f"{r['minutes']:.0f} min  Overall {r['overall']}  {r['differences_text']}")


def test_every_listed_player_is_a_rated_full_back(engine, league):
    import pandas as pd
    ids = tuple(r["player_id"] for r in league["rows"])
    sc = pd.read_sql(
        "SELECT player_id, position_group, objective_composite, peer_pool_size FROM player_scorecards "
        f"WHERE archetype = 'All Metrics' AND season_id = {SID} AND competition_id = {CID} "
        f"AND player_id IN {ids}", engine)
    assert len(sc) == len(ids)
    assert set(sc["position_group"]) == {"Full Back"}
    assert sc["objective_composite"].notna().all() and (sc["peer_pool_size"] >= 10).all()
    shown = {r["player_id"]: r["overall"] for r in league["rows"]}
    for _, r in sc.iterrows():
        assert shown[int(r["player_id"])] == pytest.approx(float(r["objective_composite"]))


def test_all_leagues_adds_other_leagues_and_the_line(engine):
    from lofc.core import similar
    out = similar.section(PID, CID, SID, "all")
    assert out["note"] == "Measures are compared within each player's own league."
    assert len(out["rows"]) == similar.TOP_N
    assert PID not in [r["player_id"] for r in out["rows"]]


def test_section_is_fast_once_built(league):
    from lofc.core import similar
    t = time.perf_counter()
    similar.section(PID, CID, SID, "all", 25)
    assert time.perf_counter() - t < 0.3


def test_card_json_says_the_section_is_available(engine):
    from lofc.core import card
    c = card.build_card(engine, PID, CID, SID)
    assert c["similar"] == {"available": True, "heading": "Similar players"}


def test_full_back_pool_correlation_and_pair_scale(league):
    """The running measures move together (linked); R is a positive-definite correlation
    matrix; the pair scale holds every eligible pair, sorted."""
    import numpy as np
    from lofc.core import similar
    pool = similar.pool_for(SID, "Full Back")
    assert "sprint_count_p90" in pool.linked.get("hsr_count_p90", [])
    assert np.diag(pool.R) == pytest.approx(np.ones(len(pool.measures)))
    assert np.linalg.eigvalsh(pool.R).min() > 0
    n = len(pool.meta)
    assert 0 < len(pool.ref) <= n * (n - 1) // 2 and np.all(np.diff(pool.ref) >= 0)


def test_every_similarity_is_between_0_and_100_and_sorted_for_every_filter():
    from lofc.core import similar
    for kw in ({"scope": "all"}, {"scope": "all", "min_minutes": 1800},
               {"scope": "all", "contract": 12}, {"scope": "league", "max_age": 25}):
        out = similar.section(PID, CID, SID, **kw)
        sims = [r["similarity"] for r in out["rows"]]
        assert out["rows"] and len(out["rows"]) <= similar.TOP_N, kw
        assert all(0 <= s <= 100 for s in sims) and sims == sorted(sims, reverse=True), kw


def test_filters_never_change_a_similarity():
    from lofc.core import similar
    every = {r["key"]: r["similarity"] for r in similar.find_similar(
        similar.pool_for(SID, "Full Back"), PID, CID, "all", n=5000)["rows"]}
    for kw in ({"min_minutes": 1350}, {"contract": 12}, {"max_age": 23}, {"league": 5}):
        out = similar.section(PID, CID, SID, "all", **kw)
        for r in out["rows"]:
            assert every[r["key"]] == r["similarity"], (kw, r["name"])


def test_page_breaks_down_the_first_match_on_the_pools_measures():
    from lofc.core import similar
    p = similar.page(PID, CID, SID, "league")
    pool = similar.pool_for(SID, "Full Back")
    assert p["selected"] == p["rows"][0]["key"]
    b = p["breakdown"]
    assert {r["measure"] for r in b["rows"]} == set(pool.measures)
    assert b["similarity"] == p["rows"][0]["similarity"]
    assert p["compare_href"].startswith(f"/compare?season={SID}&position=Full+Back&a={PID}-{CID}&b=")
    used = [r for r in b["rows"] if r["used"]]
    assert used and all(r["him"] != "—" and r["match"] != "—" for r in used)
    second = p["rows"][1]["key"]
    assert similar.page(PID, CID, SID, "league", match=second)["selected"] == second


def test_page_request_is_fast_once_built():
    from lofc.core import similar
    similar.page(PID, CID, SID, "all")
    t = time.perf_counter()
    similar.page(PID, CID, SID, "all", 25, None, 900, 12)
    assert time.perf_counter() - t < 0.3
