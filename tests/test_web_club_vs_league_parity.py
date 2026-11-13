"""Club vs League One on the REAL database (skipped without one): the top 6, our level and a gap
equal values computed here independently, straight from the stored tables with plain SQL."""
import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from lofc.config import settings


@pytest.fixture(scope="module")
def engine():
    try:
        e = create_engine(settings.database_url)
        e.connect().close()
    except Exception:
        pytest.skip("no database")
    return e


@pytest.fixture(scope="module")
def page(engine):
    from lofc.web.api import club_vs_league as api
    api.clear()
    return api.page_json()


@pytest.fixture(scope="module")
def stored(engine):
    cur = int(pd.read_sql("SELECT MAX(season_id) AS s FROM player_metrics_neutral", engine)["s"][0])
    rated = pd.read_sql(text(
        "SELECT c.player_id, c.competition_id, c.season_id, c.position_group, c.objective_composite AS ovr, "
        "n.minutes, n.team_name, n.player_name FROM player_scorecards c JOIN player_metrics_neutral n "
        "USING (player_id, competition_id, season_id) WHERE c.archetype = 'All Metrics' "
        "AND c.objective_composite IS NOT NULL AND c.season_id = :s"), engine, params={"s": cur})
    return cur, rated


def test_top6_is_the_minutes_weighted_club_average(page, stored):
    cur, rated = stored
    l1 = rated[(rated.competition_id == 4) & (rated.minutes > 0)]
    avg = (l1.ovr * l1.minutes).groupby(l1.team_name).sum() / l1.minutes.groupby(l1.team_name).sum()
    want = list(avg.sort_values(ascending=False).head(6).index)
    assert [t["club"] for t in page["top6"]] == want
    assert [t["avg"] for t in page["top6"]] == [round(float(avg[c]), 2) for c in want]
    orient = [c for c in avg.index if c.lower().startswith("leyton orient")]
    rank = int(avg.rank(ascending=False, method="min")[orient[0]])
    assert page["orient"]["rank"] == rank and page["orient"]["of"] == len(avg)


def test_our_level_and_a_gap(page, stored, engine):
    cur, rated = stored
    from lofc.core.squad import ORIENT_SQUAD_ID
    ours = pd.read_sql(text("SELECT player_id FROM player_current_club WHERE impect_squad_id = :sid "
                            "OR lower(club_name) LIKE 'leyton orient%'"), engine,
                       params={"sid": ORIENT_SQUAD_ID})
    l1 = rated[rated.competition_id == 4]
    mine = l1[l1.player_id.isin(set(ours.player_id)) & (l1.position_group == "Centre Back")]
    level = float(mine.ovr.max())
    row = next(g for g in page["gaps"] if g["group"] == "Centre Back")
    assert row["level"]["rating"] == pytest.approx(level)
    assert row["level"]["name"] == mine.sort_values("ovr", ascending=False).iloc[0].player_name
    # the bar: this season's top 6 by minutes-weighted average, each club's best centre back
    w = l1[l1.minutes > 0]
    avg = (w.ovr * w.minutes).groupby(w.team_name).sum() / w.minutes.groupby(w.team_name).sum()
    top6 = list(avg.sort_values(ascending=False).head(6).index)
    best = l1[l1.team_name.isin(top6) & (l1.position_group == "Centre Back")].groupby("team_name").ovr.max()
    if len(best) >= 4:
        assert row["bar"]["season_id"] == cur and not row["bar"]["fallback"]
        assert row["bar"]["median"] == pytest.approx(float(best.median()))
        assert row["gap"] == pytest.approx(float(best.median()) - level)
        assert {p["club"]: p["rating"] for p in row["bar"]["players"]} == pytest.approx(best.to_dict())


def test_recommendations_are_per_league_above_our_level_and_never_ours(page, stored, engine):
    rec = page["recommendations"]
    sel = next(g for g in page["gaps"] if g["group"] == page["selected"])
    level = sel["level"]["rating"] if sel["level"] else None
    for lg in rec["leagues"]:
        assert len(lg["rows"]) == lg["count"]                     # owner 2026-11-13: no top-15 cap
        ov = [r["overall"] for r in lg["rows"]]
        assert ov == sorted(ov, reverse=True)
        assert all(level is None or o > level for o in ov)
        assert all(not r["club"].lower().startswith("leyton orient") for r in lg["rows"])
        assert all(r["ids"][1] == lg["competition_id"] for r in lg["rows"])


def test_every_big_picture_measure_has_league_one_data_this_season(page):
    """Owner 2026-11-10: no all-"—" row. Progressive passes / Ball recoveries were NULL under
    Impect and were replaced by Deep progressions / Ball wins."""
    empty = [b["label"] for b in page["big_picture"] if b["now"] is None]
    assert empty == []
    labels = [b["label"] for b in page["big_picture"]]
    assert "Deep progressions" in labels and "Ball wins" in labels
    assert "Progressive Passes" not in labels and "Ball Recoveries" not in labels


def test_every_big_picture_metric_is_held_this_season(engine, stored):
    """Guard: each metric the Big picture lists has at least one value this season."""
    from lofc.web.api import club_vs_league as api
    cur, _ = stored
    picture = api._sources().picture
    counts = pd.read_sql(text("SELECT " + ", ".join(f"COUNT({m}) AS {m}" for m in picture)
                              + " FROM player_metrics_neutral WHERE season_id = :s"), engine,
                         params={"s": cur}).iloc[0]
    assert [m for m in picture if counts[m] == 0] == []


def test_top6_performance_physical_and_orients_row(page, engine, stored):
    """Owner 2026-11-10: Performance / Physical columns and Orient's own row, recomputed here
    with plain SQL (minutes-weighted over rated players that have the figure)."""
    cur, _ = stored
    df = pd.read_sql(text(
        "SELECT n.team_name, n.minutes, c.objective_composite AS ovr, c.performance_band AS perf, "
        "c.physical_band AS phys FROM player_scorecards c JOIN player_metrics_neutral n "
        "USING (player_id, competition_id, season_id) WHERE c.archetype = 'All Metrics' "
        "AND c.objective_composite IS NOT NULL AND c.season_id = :s AND c.competition_id = 4 "
        "AND n.minutes > 0"), engine, params={"s": cur})

    def avg(col):
        f = df[df[col].notna()]
        return (f[col] * f.minutes).groupby(f.team_name).sum() / f.minutes.groupby(f.team_name).sum()
    perf, phys, ovr = avg("perf"), avg("phys"), avg("ovr")
    for t in page["top6"]:
        assert t["performance"] == round(float(perf[t["club"]]), 2)
        assert t["physical"] == round(float(phys[t["club"]]), 2)
    us = page["us"]
    assert us["club"].lower().startswith("leyton orient")
    assert us["avg"] == round(float(ovr[us["club"]]), 2)
    assert us["performance"] == round(float(perf[us["club"]]), 2)
    assert us["physical"] == round(float(phys[us["club"]]), 2)
    assert us["rank"] == page["orient"]["rank"] and us["players"] == int((df.team_name == us["club"]).sum())
    for g in page["gaps"]:
        every = {s["metric"]: s["short"] for s in g["all_shortfalls"]}
        for s in g["shortfalls"]:
            assert isinstance(s["short"], int) and every.get(s["metric"], s["short"]) == s["short"]


def test_gap_closed_matches_a_plain_recomputation(engine):
    """Owner 2026-11-13: Gap closed for Centre Back, recomputed here from the stored season
    figures: percentiles, the top-6 medians, the Overall weights (Performance 40 : Physical 30,
    the club's per-metric Performance weights, Physical equal) and the capped, weighted share."""
    from lofc.model import club_framework as cf
    from lofc.model.performance_weights import WEIGHTS
    from lofc.model.scorecard import metric_percentiles
    from lofc.web.api import club_vs_league as api
    api.clear()
    page = api.page_json(group="Centre Back")
    row = next(g for g in page["gaps"] if g["group"] == "Centre Back")
    if row["level"] is None or not row["bar"]["players"]:
        pytest.skip("no Centre Back level or bar")
    pcts = {}

    def pct(pid, comp, season, pos):
        if season not in pcts:
            n = pd.read_sql(text("SELECT * FROM player_metrics_neutral WHERE season_id = :s"), engine,
                            params={"s": season})
            pcts[season] = metric_percentiles(n)
        key = (pid, comp, season, pos)
        return pcts[season].loc[key] if key in pcts[season].index else None
    L = row["level"]
    ours = pct(L["player_id"], L["competition_id"], L["season_id"], L["position"])
    bar = [pct(p["player_id"], p["competition_id"], p["season_id"], p["position"]) for p in row["bar"]["players"]]
    perf = {m: float(w) for m, (_t, w) in WEIGHTS[("Centre Back", "All Metrics")].items()}
    phys = cf.PHYSICAL_METRICS["Centre Back"]
    weight = {m: w * 0.40 / 0.70 for m, w in perf.items()} | {m: 0.30 / 0.70 / len(phys) for m in phys}
    gaps = {}
    for m in weight:
        mine = ours.get(m)
        theirs = [b.get(m) for b in bar if b is not None and pd.notna(b.get(m))]
        if pd.notna(mine) and theirs and float(pd.Series(theirs).median()) > float(mine):
            gaps[m] = (float(mine), float(pd.Series(theirs).median()))
    assert set(gaps) == {s["metric"] for s in row["all_shortfalls"]}
    checked = 0
    for lg in page["recommendations"]["leagues"]:
        for r in lg["rows"]:
            p, c, s = r["ids"]
            cand = pct(p, c, s, r["position"])
            if cand is None or not gaps:
                assert r["gap_closed"] is None
                continue
            num = sum(weight[m] * min(max((0.0 if pd.isna(cand.get(m)) else float(cand.get(m))) - o, 0.0), b - o)
                      for m, (o, b) in gaps.items())
            den = sum(weight[m] * (b - o) for m, (o, b) in gaps.items())
            assert abs(r["gap_closed"] - 100 * num / den) <= 0.5 + 1e-6, (r["name"], r["gap_closed"], 100 * num / den)
            checked += 1
    assert checked > 0


def test_full_back_against_our_second_rated_full_back(engine):
    """Owner 2026-11-13: pick our second-best rated full back -- gap = bar - his Overall, the list
    holds only players rated above him, and "vs him" is measured from him."""
    from lofc.web.api import club_vs_league as api
    api.clear()
    base = api.page_json(group="Full Back")
    row = next(g for g in base["gaps"] if g["group"] == "Full Back")
    rated = sorted([p for p in row["players"] if p["counts"]], key=lambda p: -p["rating"])
    if len(rated) < 2 or row["bar"]["median"] is None:
        pytest.skip("fewer than two rated full backs")
    him = rated[1]
    d = api.page_json(group="Full Back", vs=str(him["player_id"]))
    sel = next(g for g in d["gaps"] if g["group"] == "Full Back")
    assert d["filters"]["vs"] == him["player_id"] and d["compare"]["name"] == him["name"]
    assert sel["level"]["player_id"] == him["player_id"] and sel["best"]["player_id"] == rated[0]["player_id"]
    assert sel["gap"] == pytest.approx(row["bar"]["median"] - him["rating"])
    assert d["recommendations"]["level"] == pytest.approx(him["rating"])
    rows = [r for lg in d["recommendations"]["leagues"] for r in lg["rows"]]
    assert rows and all(r["overall"] > him["rating"] for r in rows)
    assert all(abs(r["vs_best"] - (r["overall"] - him["rating"])) <= 0.005 + 1e-9 for r in rows)
    assert [w["metric"] for w in d["recommendations"]["weak_metrics"]] == [s["metric"] for s in sel["shortfalls"]]
    # his own percentiles, straight from the stored figures
    from lofc.dashboard import loaders as L
    p = L.load_scorecard_percentiles(sel["level"]["season_id"])
    mine = p[(p.player_id == him["player_id"]) & (p.competition_id == him["competition_id"])
             & (p.position_group == him["position"])].iloc[0]
    for s in sel["all_shortfalls"]:
        assert s["ours"] == round(float(mine[s["metric"]]))


def test_big_picture_in_possession_distance_rank(page, engine, stored):
    """Owner 2026-11-13: Orient's In-possession Distance rank among League One clubs, recomputed
    with plain SQL: minutes-weighted club average of SkillCorner's phys_tip.distance_p90."""
    cur, _ = stored
    df = pd.read_sql(text(
        "SELECT n.team_name, SUM(d.value_p90 * n.minutes) / SUM(n.minutes) AS v "
        "FROM player_detail_metrics d JOIN player_metrics_neutral n "
        "USING (player_id, competition_id, season_id) WHERE d.metric = 'phys_tip.distance_p90' "
        "AND d.competition_id = 4 AND d.season_id = :s AND d.value_p90 IS NOT NULL AND n.minutes > 0 "
        "GROUP BY n.team_name"), engine, params={"s": cur})
    if df.empty:
        pytest.skip("no in-possession data this season")
    rank = df.set_index("team_name")["v"].rank(ascending=False, method="min")
    orient = [c for c in rank.index if c.lower().startswith("leyton orient")][0]
    row = next(b for b in page["big_picture"] if b["measure"] == "distance_p90")
    tip = row["phases"]["tip"]["now"]
    assert (tip["rank"], tip["of"]) == (int(rank[orient]), len(rank))
    for m in ("psv99_kmh", "top5_psv99_kmh"):                       # no split: "—"
        r = next(b for b in page["big_picture"] if b["measure"] == m)
        assert r["phases"]["tip"]["now"] is None and r["phases"]["otip"]["now"] is None


def test_gap_closed_example_is_the_lists_first_player_by_gap_closed(engine):
    """Owner 2026-11-13: the fold-out's example names each league's first player by Gap closed
    and his figure is the list's."""
    from lofc.web.api import club_vs_league as api
    for group in ("Full Back", "Centre Back"):
        d = api.page_json(group=group, rank="gap")
        for lg in d["recommendations"]["leagues"]:
            ex, top = lg["example"], lg["rows"][0] if lg["rows"] else None
            if ex is None:
                continue
            assert ex["candidate"] == {"name": top["name"], "club": top["club"]}
            assert f"= {top['gap_closed']}%." in ex["total"] and f"in the {group} rating" in ex["total"]
            assert ex["columns"][4] == f"Target ({top['name'].split()[-1]})"
            assert 1 <= len(ex["rows"]) <= 3
