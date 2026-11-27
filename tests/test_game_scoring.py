"""Per-game club scoring (owner 2026-11-23, N21): the club's own Performance / Physical /
Overall formula applied to ONE game, from Impect's per-match KPIs and SkillCorner's per-match
physical rows. Per 90; a ratio with nothing to divide by is left out (never estimated); games
under 45 minutes keep their values but get no rating. Display only -- never the ranking (P11).
Pure functions: no API call, no database."""
import pandas as pd
import pytest

from lofc.model import club_framework as cf
from lofc.model import game_scoring as gs


def test_parse_player_kpis_sums_positions_and_keeps_game_totals():
    names = {1: "SUCCESSFUL_PASSES", 2: "UNSUCCESSFUL_PASSES", 3: "GOALS"}
    payload = {"matchId": 7, "squadHome": {"id": 10, "players": [
        {"id": 100, "position": "LEFT_WINGER", "playDuration": 3000.0,
         "kpis": [{"kpiId": 1, "value": 20.0}, {"kpiId": 3, "value": 1.0}]},
        {"id": 100, "position": "CENTER_FORWARD", "playDuration": 1800.0,
         "kpis": [{"kpiId": 1, "value": 5.0}, {"kpiId": 2, "value": 4.0}]}]},
        "squadAway": {"id": 20, "players": []}}
    f = gs.parse_player_kpis(payload, names)
    r = f.iloc[0]
    assert (r["match_id"], r["impect_player_id"], r["squad_id"], r["position_group"], r["minutes"]) == \
        (7, 100, 10, "Winger", 80.0)
    assert r["kpis"] == {"SUCCESSFUL_PASSES": 25.0, "GOALS": 1.0, "UNSUCCESSFUL_PASSES": 4.0}


def test_impect_metrics_per_90_and_ratios_with_their_counts():
    m = gs.impect_game_metrics({"SUCCESSFUL_PASSES": 30.0, "UNSUCCESSFUL_PASSES": 10.0,
                                "WON_GROUND_DUELS": 4.0, "LOST_GROUND_DUELS": 5.0}, minutes=45.0)
    assert m["pass_completion_pct"] == {"v": pytest.approx(0.75), "n": 30.0, "d": 40.0}
    assert m["ground_duel_win_pct"] == {"v": pytest.approx(4 / 9), "n": 4.0, "d": 9.0}
    assert m["turnovers_p90"] == {"v": 0.0, "n": 0.0, "d": None}       # absent KPI = none happened
    # a ratio with nothing to divide by is left out, never estimated
    assert m["aerial_win_pct"] == {"v": None, "n": 0.0, "d": 0.0}
    goals = gs.impect_game_metrics({"GOALS": 1.0}, minutes=45.0)["goals_p90"]
    assert goals == {"v": pytest.approx(2.0), "n": 1.0, "d": None}     # 1 goal in 45 min = 2 per 90


def test_only_the_clubs_performance_metrics_are_kept():
    m = gs.impect_game_metrics({}, minutes=90.0)
    assert set(m) == set(gs.PERF_METRICS)
    assert "long_ball_pct" not in m and "ball_wins_p90" in m           # club metric -> stored successor


def test_physical_per_90_from_skillcorner_minutes():
    row = {"minutes_full_all": 45.0, "physical_check_passed": True, "total_distance_full_all": 5000.0,
           "hsr_count_full_all": 10.0, "hsr_distance_full_all": 400.0, "sprint_count_full_all": 4.0,
           "sprint_distance_full_all": 120.0, "psv99": 31.5}
    p = gs.physical_game_metrics(row)
    assert p["distance_p90"] == {"v": pytest.approx(10000.0), "n": 5000.0, "d": None}
    assert p["psv99_kmh"] == {"v": 31.5, "n": 31.5, "d": None}         # a peak speed is not scaled
    assert "top5_psv99_kmh" not in p                                    # not available per game
    assert gs.physical_game_metrics({**row, "physical_check_passed": False}) is None


def _pool(n=12, position="Central Mid", minutes=90.0, phys=True):
    rows = []
    for i in range(n):
        perf = {m: {"v": float(i), "n": float(i), "d": None} for m in gs.PERF_METRICS}
        ph = {m: {"v": float(i), "n": float(i), "d": None} for m in gs.PHYS_METRICS} if phys else None
        rows.append({"competition_id": 4, "season_id": 319, "position_group": position,
                     "minutes": minutes, "perf": perf, "phys": ph})
    return pd.DataFrame(rows)


def test_scores_use_the_club_formula_within_the_games_pool():
    g = _pool()
    out = gs.score_games(g)
    top, mid = out.iloc[-1], out.iloc[5]
    # Overall = Performance 65 : Physical 35, as in the ranking
    w = cf.DIMENSION_WEIGHTS["Central Mid"]
    exp = (top["performance"] * w[cf.PERFORMANCE] + top["physical"] * w[cf.PHYSICAL]) / (w[cf.PERFORMANCE] + w[cf.PHYSICAL])
    assert top["overall"] == pytest.approx(exp, abs=0.006)
    assert top["overall"] > mid["overall"]
    assert top["overall_pct"] == 100.0 and out.iloc[0]["overall_pct"] == 0.0
    # metric percentile: mid-rank, as in the season scoring; turnovers inverted (lower is better)
    assert top["metric_pcts"]["goals_p90"] == pytest.approx((12 - 0.5) / 12 * 100, abs=0.05)
    assert top["metric_pcts"]["turnovers_p90"] == pytest.approx(100 - (12 - 0.5) / 12 * 100, abs=0.05)


def test_short_games_keep_values_but_get_no_rating():
    g = pd.concat([_pool(), _pool(1, minutes=30.0)], ignore_index=True)
    out = gs.score_games(g)
    short = out.iloc[-1]
    assert pd.isna(short["overall"]) and pd.isna(short["performance"]) and short["metric_pcts"] == {}
    assert out.iloc[:-1]["overall"].notna().all()


def test_no_physical_rates_on_performance_alone():
    g = _pool(phys=False)
    out = gs.score_games(g)
    assert out["physical"].isna().all()
    assert (out["overall"] == out["performance"]).all()


def _engine():
    import sqlalchemy as sa
    from sqlalchemy.pool import StaticPool
    from lofc.store.models import Base
    e = sa.create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(e)
    return e


def test_write_club_scores_joins_physical_by_player_and_date_and_keeps_old_games():
    import datetime
    from lofc.ingest import impect_matches as im
    e = _engine()
    n = 12
    pd.DataFrame({"match_id": range(1, n + 1), "iteration_id": 1, "competition_id": 4, "season_id": 319,
                  "scheduled_at": [datetime.datetime(2026, 9, 1 + i, 15) for i in range(n)],
                  "available": True}).to_sql("impect_matches", e, if_exists="append", index=False)
    # one player per game, rising quality; games 1-6 first, then 7-12 in a second run
    def kpis(i):
        return pd.DataFrame({"match_id": [i], "impect_player_id": [500 + i], "squad_id": [10],
                             "position_group": ["Central Mid"], "minutes": [90.0],
                             "kpis": [{"SUCCESSFUL_PASSES": 10.0 + i, "UNSUCCESSFUL_PASSES": 5.0, "GOALS": i % 2}]})
    link = {500 + i: 9000 + i for i in range(1, n + 1)}
    phys = pd.DataFrame({"player_id": [9000 + i for i in range(1, n + 1)],
                         "match_date": [datetime.date(2026, 9, 1 + i) for i in range(n)],
                         "minutes_full_all": 90.0, "physical_check_passed": True,
                         "total_distance_full_all": [9000.0 + 100 * i for i in range(n)], "psv99": 30.0})
    first = pd.concat([kpis(i) for i in range(1, 7)], ignore_index=True)
    im.write_club(e, 4, 319, first, list(range(1, 7)), phys, link)
    second = pd.concat([kpis(i) for i in range(7, n + 1)], ignore_index=True)
    im.write_club(e, 4, 319, second, list(range(7, n + 1)), None, link)   # SkillCorner unavailable
    rows = pd.read_sql("SELECT * FROM player_match_club ORDER BY match_id", e)
    assert len(rows) == n and rows["player_id"].tolist() == [9000 + i for i in range(1, n + 1)]
    import json
    p1 = json.loads(rows.iloc[0]["phys"]) if isinstance(rows.iloc[0]["phys"], str) else rows.iloc[0]["phys"]
    assert p1["distance_p90"]["n"] == 9000.0                     # kept from the first run
    assert pd.isna(rows.iloc[-1]["phys"])                        # never had physical
    assert rows["overall"].notna().all()                         # 12 games: a full pool
    done = pd.read_sql("SELECT kpis_pulled_at FROM impect_matches", e)
    assert done["kpis_pulled_at"].notna().all()
    assert im.to_pull_kpis(e, 4, 319) == []


def test_refreshing_the_fixture_list_keeps_when_kpis_were_pulled():
    """Owner 2026-11-27: the server pull made 1,766 calls where the dry run expected ~880 --
    rewriting the fixture list dropped kpis_pulled_at, so every played match's KPIs were pulled
    again on every run. Both pulled-at times survive a fixture refresh."""
    import datetime
    from lofc.ingest import impect_matches as im
    e = _engine()
    f = pd.DataFrame({"match_id": [1, 2], "iteration_id": 1, "competition_id": 4, "season_id": 319,
                      "scheduled_at": [datetime.datetime(2026, 9, 1, 15)] * 2, "available": True,
                      "last_calculated_at": [datetime.datetime(2026, 9, 2)] * 2})
    im.write_matches(e, f)
    with e.begin() as c:
        c.exec_driver_sql("UPDATE impect_matches SET scores_pulled_at = '2026-09-03', kpis_pulled_at = '2026-09-03'")
    im.write_matches(e, f)                                   # the next run refreshes the fixtures
    assert im.to_pull_kpis(e, 4, 319) == []
    got = pd.read_sql("SELECT scores_pulled_at, kpis_pulled_at FROM impect_matches", e)
    assert got.notna().all().all()
