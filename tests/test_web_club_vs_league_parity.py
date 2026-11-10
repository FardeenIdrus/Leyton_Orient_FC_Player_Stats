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
        assert len(lg["rows"]) <= 15 and lg["count"] >= len(lg["rows"])
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
