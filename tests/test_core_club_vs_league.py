"""core.club_vs_league: the "Club vs League One" page's rules (owner 2026-11-09), on synthetic
frames. Every rating is a stored one; this module only selects, weights by minutes and compares.
Real-database checks: tests/test_web_club_vs_league_parity.py."""
import pandas as pd
import pytest

from lofc.core import club_vs_league as cv

CUR, PREV = 319, 318


def _cards(rows):
    """rows: (pid, comp, season, position, overall, perf, phys, minutes, team, name)."""
    df = pd.DataFrame(rows, columns=["player_id", "competition_id", "season_id", "position_group",
                                     "objective_composite", "performance_band", "physical_band",
                                     "minutes", "team_name", "player_name"])
    return df


def _league(season, clubs, base=3.0, step=0.1, positions=("Winger", "Centre Back"), start=1000):
    """One rated player per club per position; club k's players rate base + k*step."""
    rows, pid = [], start
    for k, club in enumerate(clubs):
        for j, pos in enumerate(positions):
            pid += 1
            rows.append((pid, cv.LEAGUE_ONE, season, pos, base + k * step + j * 0.01, 3.0, 3.0,
                         900.0, club, f"{club} {pos}"))
    return rows


CLUBS = ["Leyton Orient"] + [f"Club {c}" for c in "ABCDEFGHIJ"]      # Orient lowest


def test_groups():
    assert cv.GROUPS == ["Goalkeeper", "Centre Back", "Full Back", "Midfield", "Winger", "Centre Forward"]
    for p in ("Defensive Mid", "Central Mid", "Attacking Mid"):
        assert cv.group_of(p) == "Midfield"
    assert cv.group_of("Winger") == "Winger"


def test_club_table_is_minutes_weighted_and_top6_and_orient_rank():
    rated = _cards([
        (1, 4, CUR, "Winger", 4.0, 3, 3, 900.0, "A", "a1"), (2, 4, CUR, "Winger", 2.0, 3, 3, 100.0, "A", "a2"),
        (3, 4, CUR, "Winger", 3.5, 3, 3, 500.0, "B", "b1"),
        (4, 4, CUR, "Winger", 3.0, 3, 3, 500.0, "Leyton Orient", "o1"),
        (5, 5, CUR, "Winger", 5.0, 3, 3, 900.0, "Other league", "x"),      # not League One
        (6, 4, PREV, "Winger", 5.0, 3, 3, 900.0, "C", "c"),                # other season
    ])
    t = cv.club_table(rated, CUR)
    assert list(t["team_name"]) == ["A", "B", "Leyton Orient"]
    assert t.iloc[0]["avg"] == pytest.approx((4.0 * 900 + 2.0 * 100) / 1000)
    assert cv.orient_rank(t) == (3, 3)
    assert cv.top_clubs(t, 2) == ["A", "B"]


def test_bar_is_the_median_of_each_top6_clubs_best_and_names_them():
    rated = _cards(_league(CUR, CLUBS))
    t = cv.club_table(rated, CUR)
    top6 = cv.top_clubs(t)
    b = cv.bar(rated, CUR, top6, "Winger")
    assert b["n"] == 6 and len(b["players"]) == 6
    vals = sorted(p["rating"] for p in b["players"])
    assert b["median"] == pytest.approx((vals[2] + vals[3]) / 2)
    assert {p["club"] for p in b["players"]} == set(top6)


def test_midfield_bar_takes_each_clubs_best_across_the_three_mid_groups():
    rows = [(1, 4, CUR, "Defensive Mid", 3.1, 3, 3, 900.0, "A", "a-dm"),
            (2, 4, CUR, "Attacking Mid", 3.9, 3, 3, 900.0, "A", "a-am"),
            (3, 4, CUR, "Central Mid", 3.4, 3, 3, 900.0, "B", "b-cm")]
    b = cv.bar(_cards(rows), CUR, ["A", "B"], "Midfield")
    assert {(p["club"], p["player"], p["position"]) for p in b["players"]} == {
        ("A", "a-am", "Attacking Mid"), ("B", "b-cm", "Central Mid")}
    assert b["median"] == pytest.approx(3.65)


def test_our_players_level_only_from_league_one_this_season():
    rated = _cards([
        (10, 4, CUR, "Winger", 3.2, 3, 3, 800.0, "Leyton Orient", "Ours A"),
        (11, 4, CUR, "Winger", 3.5, 3, 3, 300.0, "Leyton Orient", "Ours B"),
        (12, 903, CUR, "Winger", 4.4, 3, 3, 900.0, "Somewhere U21", "On loan"),   # other league
        (13, 4, PREV, "Centre Back", 3.9, 3, 3, 2000.0, "Leyton Orient", "Last season"),
    ])
    squad = pd.DataFrame({"player_id": [10, 11, 12, 13, 14],
                          "player_name": ["Ours A", "Ours B", "On loan", "Last season", "Unrated"],
                          "position_group": ["Winger", "Winger", "Winger", "Centre Back", "Full Back"]})
    ours = cv.our_players(squad, rated, CUR, PREV, {4: "League One", 903: "Premier League 2"})
    by = {o["name"]: o for o in ours}
    assert by["Ours B"]["counts"] and by["Ours B"]["tag"] is None
    assert not by["On loan"]["counts"] and by["On loan"]["tag"] == "Premier League 2"
    assert not by["Last season"]["counts"] and by["Last season"]["tag"] == "25/26"
    assert by["Last season"]["group"] == "Centre Back"
    assert by["Unrated"]["rating"] is None and by["Unrated"]["group"] == "Full Back"
    lvl = cv.our_level(ours, "Winger")
    assert lvl["name"] == "Ours B" and lvl["rating"] == 3.5          # best, not most minutes
    assert cv.our_level(ours, "Centre Back") is None                  # only a last-season rating


def test_gap_map_uses_last_seasons_top6_when_fewer_than_4_clubs_have_a_rated_player():
    cur = _league(CUR, CLUBS, positions=("Centre Back",))
    # only 3 of this season's top-6 clubs have a rated winger
    top_now = [c for c in CLUBS[::-1] if c != "Leyton Orient"][:3]
    cur += [(5000 + i, 4, CUR, "Winger", 3.6, 3, 3, 900.0, c, f"{c} W") for i, c in enumerate(top_now)]
    cur += [(6000, 4, CUR, "Winger", 3.0, 3, 3, 900.0, "Leyton Orient", "Our winger"),
            (6001, 4, CUR, "Centre Back", 2.5, 3, 3, 900.0, "Leyton Orient", "Our CB")]
    prev = _league(PREV, CLUBS, positions=("Winger", "Centre Back"), start=8000)
    rated = _cards(cur + prev)
    squad = pd.DataFrame({"player_id": [6000, 6001], "player_name": ["Our winger", "Our CB"],
                          "position_group": ["Winger", "Centre Back"]})
    ours = cv.our_players(squad, rated, CUR, PREV, {4: "League One"})
    rows = cv.gap_map(rated, ours, CUR, PREV, season_names={CUR: "26/27", PREV: "25/26"})
    by = {r["group"]: r for r in rows}
    w = by["Winger"]
    assert w["bar"]["season_id"] == PREV and w["bar"]["fallback"]
    assert w["bar"]["label"] == "Bar from 25/26 — not enough rated wingers at this season's top-6 clubs yet (3 of 6)"
    assert w["gap"] == pytest.approx(w["bar"]["median"] - 3.0)
    cb = by["Centre Back"]
    assert cb["bar"]["season_id"] == CUR and not cb["bar"]["fallback"]
    # biggest gap first; positions with no Orient level last
    gaps = [r["gap"] for r in rows if r["gap"] is not None]
    assert gaps == sorted(gaps, reverse=True)
    assert rows[-1]["level"] is None and rows[-1]["note"] == "No Orient player rated here this season"


def test_shortfalls_three_biggest_against_the_bar_players_median():
    ours = pd.Series({"a": 20.0, "b": 50.0, "c": 90.0, "d": 10.0, "e": 60.0})
    bar = [pd.Series({"a": 80.0, "b": 60.0, "c": 70.0, "d": 30.0, "e": 50.0}),
           pd.Series({"a": 70.0, "b": 70.0, "c": 80.0, "d": 40.0, "e": 40.0})]
    out = cv.shortfalls(ours, bar, ["a", "b", "c", "d", "e"], lambda m: m.upper())
    assert [s["metric"] for s in out] == ["a", "d", "b"]
    assert out[0] == {"metric": "a", "label": "A", "ours": 20, "top6": 75, "text": "A: ours 20th, top-6 75th"}


def test_recommendations_per_league_top15_above_our_level_never_orient():
    rows = []
    for comp in (3, 4, 5):
        rows += [(comp * 1000 + i, comp, CUR, "Winger", 2.0 + i * 0.1, 3, 3, 900.0, f"T{comp}-{i}", f"P{comp}-{i}")
                 for i in range(25)]
    rows.append((99, 4, CUR, "Winger", 4.9, 3, 3, 900.0, "Leyton Orient", "Ours"))
    rated = _cards(rows)
    cands = rated[["player_id", "competition_id", "season_id"]].assign(age=24.0, contract_until=pd.NaT)
    rec = cv.recommendations(rated, cands, CUR, "Winger", level=3.05, exclude_ids={99},
                             league_names={3: "Championship", 4: "League One", 5: "League Two"})
    by = {l["league"]: l for l in rec["leagues"]}
    one = by["League One"]
    assert one["count"] == 14 and len(one["rows"]) == 14                     # 3.1 .. 4.4
    assert all(r["overall"] > 3.05 for r in one["rows"]) and "Ours" not in [r["name"] for r in one["rows"]]
    overall = [r["overall"] for r in one["rows"]]
    assert overall == sorted(overall, reverse=True)
    assert [l["league"] for l in rec["leagues"]][:3] == ["League One", "Championship", "League Two"]
    assert len(cv.recommendations(rated, cands, CUR, "Winger", level=2.0, exclude_ids={99},
                                  league_names={3: "C", 4: "L1", 5: "L2"})["leagues"][0]["rows"]) == 15


def test_recommendation_filters_age_band_and_contract():
    rated = _cards([(1, 4, CUR, "Winger", 3.5, 3, 3, 900.0, "T", "Young"),
                    (2, 4, CUR, "Winger", 3.6, 3, 3, 900.0, "T", "Old"),
                    (3, 4, CUR, "Winger", 3.7, 3, 3, 900.0, "T", "No contract date")])
    cands = pd.DataFrame({"player_id": [1, 2, 3], "competition_id": 4, "season_id": CUR,
                          "age": [20.5, 31.0, 22.0],
                          "contract_until": pd.to_datetime(["2027-06-30", "2027-06-30", None])})
    names = {4: "League One"}
    u23 = cv.recommendations(rated, cands, CUR, "Winger", 3.0, set(), names, age="u23")
    assert [r["name"] for r in u23["leagues"][0]["rows"]] == ["No contract date", "Young"]
    c27 = cv.recommendations(rated, cands, CUR, "Winger", 3.0, set(), names,
                             contract="Out of contract summer 2027", today=pd.Timestamp("2026-11-09"))
    assert [r["name"] for r in c27["leagues"][0]["rows"]] == ["Old", "Young"]


def test_strength_tag_on_a_shortfall_metric():
    rated = _cards([(1, 4, CUR, "Winger", 3.5, 3, 3, 900.0, "T", "Quick")])
    cands = rated[["player_id", "competition_id", "season_id"]].assign(age=24.0, contract_until=pd.NaT)
    pcts = pd.DataFrame({"player_id": [1], "competition_id": [4], "season_id": [CUR],
                         "position_group": ["Winger"], "sprint_count_p90": [82.4], "distance_p90": [40.0]})
    rec = cv.recommendations(rated, cands, CUR, "Winger", 3.0, set(), {4: "League One"},
                             pcts=pcts, tag_metrics=["sprint_count_p90", "distance_p90"],
                             label=lambda m: {"sprint_count_p90": "Sprints"}.get(m, m))
    assert rec["leagues"][0]["rows"][0]["tags"] == ["Sprints 82nd"]


def test_big_picture_ranks_this_season_and_last():
    neutral = pd.DataFrame({
        "player_id": [1, 2, 3, 4], "competition_id": 4, "season_id": [CUR, CUR, CUR, PREV],
        "team_name": ["A", "Leyton Orient", "Leyton Orient", "Leyton Orient"],
        "minutes": [900.0, 900.0, 100.0, 900.0],
        "sprint_count_p90": [10.0, 20.0, 0.0, 5.0]})
    rated = _cards([(1, 4, CUR, "Winger", 3.0, 3.0, 2.0, 900.0, "A", "a"),
                    (2, 4, CUR, "Winger", 4.0, 2.0, 4.0, 900.0, "Leyton Orient", "o"),
                    (4, 4, PREV, "Winger", 3.0, 3.0, 3.0, 900.0, "Leyton Orient", "p")])
    bp = cv.big_picture(rated, neutral, CUR, PREV, metrics=["sprint_count_p90"], label=str)
    rows = {r["measure"]: r for r in bp}
    assert rows["Overall"]["now"] == {"rank": 1, "of": 2, "text": "1st of 2"}
    assert rows["Performance"]["now"]["rank"] == 2
    assert rows["sprint_count_p90"]["now"]["rank"] == 1                  # (20*900+0*100)/1000 = 18 > 10
    assert rows["Overall"]["prev"] == {"rank": 1, "of": 1, "text": "1st of 1"}


def test_big_picture_sections():
    neutral = pd.DataFrame({"player_id": [1, 2], "competition_id": 4, "season_id": CUR,
                            "team_name": ["A", "Leyton Orient"], "minutes": [900.0, 900.0],
                            "sprint_count_p90": [10.0, 20.0], "np_xg_p90": [0.3, 0.1]})
    rated = _cards([(1, 4, CUR, "Winger", 3.0, 3.0, 2.0, 900.0, "A", "a")])
    bp = cv.big_picture(rated, neutral, CUR, PREV, metrics=["sprint_count_p90", "np_xg_p90"], label=str,
                        sections={"sprint_count_p90": "Physical", "np_xg_p90": "Attack"})
    rows = {r["measure"]: r for r in bp}
    assert rows["Overall"]["section"] == "Ratings" and rows["np_xg_p90"]["section"] == "Attack"
    assert rows["np_xg_p90"]["now"]["rank"] == 2


def test_strong_on_two_of_our_weaknesses_filter():
    rated = _cards([(1, 4, CUR, "Winger", 3.5, 3, 3, 900.0, "T", "Two"),
                    (2, 4, CUR, "Winger", 3.6, 3, 3, 900.0, "T", "One"),
                    (3, 4, CUR, "Winger", 3.7, 3, 3, 900.0, "T", "Three")])
    cands = rated[["player_id", "competition_id", "season_id"]].assign(age=24.0, contract_until=pd.NaT)
    pcts = pd.DataFrame({"player_id": [1, 2, 3], "competition_id": 4, "season_id": CUR,
                         "position_group": "Winger", "a": [80.0, 90.0, 75.0], "b": [70.0, 10.0, 71.0],
                         "c": [20.0, 30.0, 99.0]})
    kw = dict(pcts=pcts, tag_metrics=["a", "b", "c"], label=str)
    off = cv.recommendations(rated, cands, CUR, "Winger", 3.0, set(), {4: "League One"}, **kw)
    assert off["leagues"][0]["count"] == 3
    on = cv.recommendations(rated, cands, CUR, "Winger", 3.0, set(), {4: "League One"}, strong2=True, **kw)
    assert [r["name"] for r in on["leagues"][0]["rows"]] == ["Three", "Two"] and on["leagues"][0]["count"] == 2
