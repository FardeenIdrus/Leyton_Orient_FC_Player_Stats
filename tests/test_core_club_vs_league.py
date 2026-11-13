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
    assert out[0] == {"metric": "a", "label": "A", "ours": 20, "top6": 75, "short": 55}


def test_recommendations_per_league_every_player_above_our_level_never_orient():
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
    # owner 2026-11-13: no top-15 cap -- every player above our level (2.1 .. 4.4)
    every = cv.recommendations(rated, cands, CUR, "Winger", level=2.0, exclude_ids={99},
                               league_names={3: "C", 4: "L1", 5: "L2"})["leagues"][0]
    assert len(every["rows"]) == every["count"] == 24


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


def test_one_percentile_column_per_shortfall_metric():
    """Owner 2026-11-09: the tag column became three columns, one per weak metric of the position;
    each cell is the player's percentile (None where he has no figure)."""
    rated = _cards([(1, 4, CUR, "Winger", 3.5, 3, 3, 900.0, "T", "Quick")])
    cands = rated[["player_id", "competition_id", "season_id"]].assign(age=24.0, contract_until=pd.NaT)
    pcts = pd.DataFrame({"player_id": [1], "competition_id": [4], "season_id": [CUR],
                         "position_group": ["Winger"], "sprint_count_p90": [82.4], "distance_p90": [40.0],
                         "hsr_p90": [None]})
    rec = cv.recommendations(rated, cands, CUR, "Winger", 3.0, set(), {4: "League One"},
                             pcts=pcts, tag_metrics=["sprint_count_p90", "distance_p90", "hsr_p90"],
                             label=lambda m: {"sprint_count_p90": "Sprints"}.get(m, m))
    assert rec["weak_metrics"] == [{"metric": "sprint_count_p90", "label": "Sprints"},
                                   {"metric": "distance_p90", "label": "distance_p90"},
                                   {"metric": "hsr_p90", "label": "hsr_p90"}]
    row = rec["leagues"][0]["rows"][0]
    assert row["weak"] == [82, 40, None] and "tags" not in row


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


# --- owner additions 2026-11-09: vs our best, Top-6 level only, every big shortfall ------------
def test_vs_our_best_is_overall_minus_our_level_rounded_half_up():
    rated = _cards([(1, 4, CUR, "Winger", 3.705, 3, 3, 900.0, "T", "A"),
                    (2, 4, CUR, "Winger", 3.2, 3, 3, 900.0, "T", "B")])
    cands = rated[["player_id", "competition_id", "season_id"]].assign(age=24.0, contract_until=pd.NaT)
    rec = cv.recommendations(rated, cands, CUR, "Winger", 2.75, set(), {4: "League One"})
    assert [r["vs_best"] for r in rec["leagues"][0]["rows"]] == [0.96, 0.45]
    none = cv.recommendations(rated, cands, CUR, "Winger", None, set(), {4: "League One"})
    assert all(r["vs_best"] is None for r in none["leagues"][0]["rows"])


def test_vs_best_rounding_matches_the_card_half_up():
    assert cv.vs_best(3.705, 2.75) == 0.96 and cv.vs_best(2.745, 3.0) == -0.25
    assert cv.vs_best(3.0, None) is None


def test_top6_level_only_keeps_players_at_or_above_the_bar():
    rated = _cards([(1, 4, CUR, "Winger", 3.9, 3, 3, 900.0, "T", "At"),
                    (2, 4, CUR, "Winger", 3.5, 3, 3, 900.0, "T", "Below"),
                    (3, 4, CUR, "Winger", 4.2, 3, 3, 900.0, "T", "Above")])
    cands = rated[["player_id", "competition_id", "season_id"]].assign(age=24.0, contract_until=pd.NaT)
    on = cv.recommendations(rated, cands, CUR, "Winger", 3.0, set(), {4: "League One"}, bar=3.9, top6_only=True)
    assert [r["name"] for r in on["leagues"][0]["rows"]] == ["Above", "At"] and on["leagues"][0]["count"] == 2
    off = cv.recommendations(rated, cands, CUR, "Winger", 3.0, set(), {4: "League One"}, bar=3.9)
    assert off["leagues"][0]["count"] == 3


def test_every_shortfall_lists_every_metric_we_are_behind_on_biggest_first():
    """Owner 2026-11-10: no cut-off -- "Every shortfall" lists every metric where our player is
    below the top-6 players' median, biggest first, so its heading is always literally true."""
    ours = pd.Series({"a": 20.0, "b": 50.0, "c": 90.0, "d": 10.0, "e": 60.0, "f": 40.0})
    bar = [pd.Series({"a": 80.0, "b": 60.0, "c": 70.0, "d": 30.0, "e": 50.0, "f": 59.0}),
           pd.Series({"a": 70.0, "b": 70.0, "c": 80.0, "d": 40.0, "e": 40.0, "f": 60.0})]
    out = cv.all_shortfalls(ours, bar, list("abcdef"), lambda m: m.upper())
    # a: 75-20=55, d: 35-10=25, f: 59.5-40=19.5 -> 20 (half up), b: 65-50=15; c, e: ahead (out)
    assert [(s["metric"], s["ours"], s["top6"], s["short"]) for s in out] == [
        ("a", 20, 75, 55), ("d", 10, 35, 25), ("f", 40, 60, 20), ("b", 50, 65, 15)]
    assert out[0]["label"] == "A"


def test_lower_is_better_metrics_say_so_in_the_weakness_labels():
    """Coordinator review 2026-11-10: turnovers' percentile is already inverted (higher = better,
    model.scorecard), so "ours 1st" means many turnovers; the label says fewer is better."""
    lab = cv.weak_label(lambda m: {"turnovers_p90": "Turnovers"}.get(m, m))
    assert lab("turnovers_p90") == "Turnovers (fewer is better)"
    assert lab("sprint_count_p90") == "sprint_count_p90"
    out = cv.shortfalls(pd.Series({"turnovers_p90": 1.0}), [pd.Series({"turnovers_p90": 57.0})],
                        ["turnovers_p90"], lab)
    assert out[0]["label"] == "Turnovers (fewer is better)" and out[0]["short"] == 56


def test_one_behind_figure_for_the_top3_and_every_shortfall():
    """Owner 2026-11-10: the gap map shows ONE "Behind" per shortfall -- the same whole number in
    the summary row (top 3) and in "Every shortfall" -- and a top-3 shortfall under 20 points
    still carries it (e.g. keeper catches 59 vs 68)."""
    ours = pd.Series({"a": 20.0, "f": 40.0, "k": 59.0})
    bar = [pd.Series({"a": 80.0, "f": 59.0, "k": 68.0}), pd.Series({"a": 70.0, "f": 60.0, "k": 68.0})]
    top = cv.shortfalls(ours, bar, ["a", "f", "k"], str)
    every = cv.all_shortfalls(ours, bar, ["a", "f", "k"], str)
    # f: 59.5 - 40 = 19.5 -> 20 (half up) in BOTH lists; the old rounded figures said 60 - 40 = 20
    # in one and 19.5 in the other
    assert [(s["metric"], s["short"]) for s in top] == [("a", 55), ("f", 20), ("k", 9)]
    # owner 2026-11-10: "Every shortfall" has no cut-off, so it always contains the summary's top 3
    assert [(s["metric"], s["short"]) for s in every] == [("a", 55), ("f", 20), ("k", 9)]
    for s in top:
        hit = [e for e in every if e["metric"] == s["metric"]]
        assert not hit or hit[0]["short"] == s["short"]


def test_club_ratings_give_overall_performance_and_physical_for_every_club():
    """Owner 2026-11-10: the Top 6 card shows Performance and Physical beside Overall, each the
    same minutes-weighted club average (club_table), and Orient's own row."""
    rated = _cards([
        (1, 4, CUR, "Winger", 4.0, 3.0, 2.0, 900.0, "A", "a1"),
        (2, 4, CUR, "Winger", 2.0, 4.0, None, 100.0, "A", "a2"),
        (3, 4, CUR, "Winger", 3.0, 2.5, 3.5, 500.0, "Leyton Orient", "o1"),
        (4, 5, CUR, "Winger", 5.0, 5.0, 5.0, 900.0, "Other league", "x"),
    ])
    t = cv.club_ratings(rated, CUR)
    assert list(t["team_name"]) == ["A", "Leyton Orient"]
    a = t.iloc[0]
    assert a["overall"] == pytest.approx((4.0 * 900 + 2.0 * 100) / 1000)
    assert a["performance"] == pytest.approx((3.0 * 900 + 4.0 * 100) / 1000)
    assert a["physical"] == pytest.approx(2.0)                   # a2 has no Physical
    assert (int(a["n"]), int(a["rank"])) == (2, 1)
    for col, name in (("objective_composite", "overall"), ("performance_band", "performance"),
                      ("physical_band", "physical")):
        ct = cv.club_table(rated, CUR, column=col).set_index("team_name")["avg"]
        assert t.set_index("team_name")[name].to_dict() == pytest.approx(ct.to_dict())
    o = cv.orient_club(t)
    assert o["team_name"] == "Leyton Orient" and o["rank"] == 2 and o["overall"] == pytest.approx(3.0)


def test_recommendation_leagues_englands_first_then_by_name():
    """Owner 2026-11-10 (Leagues picker): England's leagues first, then the rest by name."""
    rows, pid = [], 0
    for comp in (10047, 903, 65, 5, 4, 3, 10015):
        pid += 1
        rows.append((pid, comp, CUR, "Winger", 4.0, 3, 3, 900.0, f"T{comp}", f"P{comp}"))
    rated = _cards(rows)
    cands = rated[["player_id", "competition_id", "season_id"]].assign(age=24.0, contract_until=pd.NaT)
    names = {3: "Championship", 4: "League One", 5: "League Two", 65: "National League",
             903: "Premier League 2", 10047: "Allsvenskan (Sweden)", 10015: "Superligaen (Denmark)"}
    rec = cv.recommendations(rated, cands, CUR, "Winger", level=3.0, exclude_ids=set(), league_names=names)
    assert [l["competition_id"] for l in rec["leagues"]] == [4, 3, 5, 65, 903, 10047, 10015]
    assert rec["default_leagues"] == [4, 3, 5]


# --- owner 2026-11-13: "Gap closed" ------------------------------------------------------------
# ours a=20 b=50 c=90; top-6 medians a=75 b=65 c=75 -> shortfalls a (gap 55) and b (gap 15)
GC_OURS = pd.Series({"a": 20.0, "b": 50.0, "c": 90.0})
GC_BAR = [pd.Series({"a": 80.0, "b": 60.0, "c": 70.0}), pd.Series({"a": 70.0, "b": 70.0, "c": 80.0})]
GC_W = {"a": 0.1, "b": 0.3, "c": 0.6}


def test_gap_profile_is_every_shortfall_unrounded():
    prof = cv.gap_profile(GC_OURS, GC_BAR, ["a", "b", "c", "x"])
    assert prof == {"a": (20.0, 75.0), "b": (50.0, 65.0)}            # c: ahead; x: no figure
    assert set(prof) == {s["metric"] for s in cv.all_shortfalls(GC_OURS, GC_BAR, ["a", "b", "c"], str)}
    assert cv.gap_profile(None, GC_BAR, ["a"]) == {}


def test_gap_closed_weights_and_caps_at_the_top6_level():
    prof = cv.gap_profile(GC_OURS, GC_BAR, ["a", "b", "c"])
    # a: 50-20 = 30 of 55; b: 90-50 = 40, capped at the gap 15
    # 100 * (0.1*30 + 0.3*15) / (0.1*55 + 0.3*15) = 100 * 7.5 / 10 = 75
    assert cv.gap_closed(prof, {"a": 50.0, "b": 90.0, "c": 0.0}, GC_W) == 75
    # past the bar on both: 100
    assert cv.gap_closed(prof, {"a": 99.0, "b": 99.0}, GC_W) == 100
    # weighting matters: the same player with a and b's weights swapped
    # 100 * (0.3*30 + 0.1*15) / (0.3*55 + 0.1*15) = 100 * 10.5 / 18 = 58.33 -> 58
    assert cv.gap_closed(prof, {"a": 50.0, "b": 90.0}, {"a": 0.3, "b": 0.1}) == 58


def test_gap_closed_gives_no_negative_credit():
    prof = cv.gap_profile(GC_OURS, GC_BAR, ["a", "b", "c"])
    # a: 10 < ours 20 -> 0 (not -10); b: 55-50 = 5 -> 100 * (0 + 1.5) / 10 = 15
    assert cv.gap_closed(prof, {"a": 10.0, "b": 55.0}, GC_W) == 15
    assert cv.gap_closed(prof, {"a": 0.0, "b": 0.0}, GC_W) == 0


def test_gap_closed_missing_metric_counts_as_nothing_closed():
    prof = cv.gap_profile(GC_OURS, GC_BAR, ["a", "b", "c"])
    # a missing -> 0; b: 65-50 = 15 (the whole gap) -> 100 * 4.5 / 10 = 45
    assert cv.gap_closed(prof, {"b": 65.0}, GC_W) == 45
    assert cv.gap_closed(prof, pd.Series({"a": float("nan"), "b": 65.0}), GC_W) == 45
    assert cv.gap_closed(prof, None, GC_W) is None                    # no percentiles at all


def test_gap_closed_none_without_shortfalls_or_weights():
    assert cv.gap_closed({}, {"a": 50.0}, GC_W) is None
    prof = cv.gap_profile(GC_OURS, GC_BAR, ["a", "b", "c"])
    assert cv.gap_closed(prof, {"a": 50.0}, {}) is None               # no weight on any shortfall


def test_gap_closed_over_chosen_metrics_only():
    prof = cv.gap_profile(GC_OURS, GC_BAR, ["a", "b", "c"])
    # only b chosen: 55-50 = 5 of 15 -> 33.3 -> 33
    assert cv.gap_closed(prof, {"a": 99.0, "b": 55.0}, GC_W, metrics=["b", "c"]) == 33
    # none of the chosen metrics is a shortfall -> None
    assert cv.gap_closed(prof, {"c": 99.0}, GC_W, metrics=["c"]) is None


def test_gap_closed_rounds_half_up():
    prof = {"a": (0.0, 8.0)}
    assert cv.gap_closed(prof, {"a": 1.0}, {"a": 1.0}) == 13          # 12.5 -> 13


def test_overall_weights_are_each_metrics_share_of_overall():
    """Overall = Performance x 4/7 + Physical x 3/7 for outfielders (DIMENSION_WEIGHTS 40:30,
    renormalised); within Performance the club's All Metrics weights; Physical equal (1/7 each).
    Goalkeepers: Performance only."""
    from lofc.model import club_framework as cf
    from lofc.model import performance_weights as pw
    w = cv.overall_weights("Centre Back")
    d = cf.DIMENSION_WEIGHTS["Centre Back"]
    perf = d[cf.PERFORMANCE] / (d[cf.PERFORMANCE] + d[cf.PHYSICAL])
    assert perf == pytest.approx(4 / 7, abs=1e-4)
    assert w["ball_wins_p90"] == pytest.approx(0.1 * perf)
    assert w["pressures_p90"] == pytest.approx(0.065 * perf)
    assert w["distance_p90"] == pytest.approx((1 - perf) / 7)
    assert sum(w.values()) == pytest.approx(1.0)
    assert set(w) == set(pw.weights_for("Centre Back", cf.DEFAULT_ARCHETYPE)) | set(cf.PHYSICAL_METRICS["Centre Back"])
    g = cv.overall_weights("Goalkeeper")
    assert g["gk_gsaa_p90"] == pytest.approx(9 / 41) and sum(g.values()) == pytest.approx(1.0)
    assert not set(g) & set(cf.PHYSICAL_METRICS["Centre Back"])
    for pos in cf.DIMENSION_WEIGHTS:
        assert sum(cv.overall_weights(pos).values()) == pytest.approx(1.0)


def _gc_setup():
    rated = _cards([(1, 4, CUR, "Winger", 3.5, 3, 3, 900.0, "T", "Half"),
                    (2, 4, CUR, "Winger", 3.9, 3, 3, 900.0, "T", "None closed"),
                    (3, 4, CUR, "Winger", 3.4, 3, 3, 900.0, "T", "All closed"),
                    (4, 4, CUR, "Winger", 3.6, 3, 3, 900.0, "T", "Tie high"),
                    (5, 4, CUR, "Winger", 3.3, 3, 3, 900.0, "T", "No pcts")])
    cands = rated[["player_id", "competition_id", "season_id"]].assign(age=24.0, contract_until=pd.NaT)
    pcts = pd.DataFrame({"player_id": [1, 2, 3, 4], "competition_id": 4, "season_id": CUR,
                         "position_group": "Winger", "a": [47.5, 10.0, 80.0, 47.5],
                         "b": [57.5, 10.0, 80.0, 57.5], "c": [0.0, 0.0, 0.0, 0.0]})
    prof = cv.gap_profile(GC_OURS, GC_BAR, ["a", "b", "c"])
    return rated, cands, pcts, prof


def test_recommendations_carry_gap_closed_and_rank_by_it():
    rated, cands, pcts, prof = _gc_setup()
    kw = dict(pcts=pcts, tag_metrics=["a", "b", "c"], label=str, gap=prof, weights=GC_W)
    rec = cv.recommendations(rated, cands, CUR, "Winger", 3.0, set(), {4: "League One"}, **kw)
    rows = rec["leagues"][0]["rows"]
    # Half: a 27.5 of 55, b 7.5 of 15 -> 100 * (2.75 + 2.25) / 10 = 50
    assert [(r["name"], r["gap_closed"]) for r in rows] == [
        ("None closed", 0), ("Tie high", 50), ("Half", 50), ("All closed", 100), ("No pcts", None)]
    by = cv.recommendations(rated, cands, CUR, "Winger", 3.0, set(), {4: "League One"}, rank="gap", **kw)
    # Gap closed high first, ties by Overall, no figure last
    assert [r["name"] for r in by["leagues"][0]["rows"]] == ["All closed", "Tie high", "Half", "None closed", "No pcts"]
    assert by["rank"] == "gap" and rec["rank"] == ""


def test_rank_by_gap_closed_picks_the_top_n_by_it():
    rated, cands, pcts, prof = _gc_setup()
    kw = dict(pcts=pcts, tag_metrics=["a"], label=str, gap=prof, weights=GC_W, n=1)
    by = cv.recommendations(rated, cands, CUR, "Winger", 3.0, set(), {4: "League One"}, rank="gap", **kw)
    assert [r["name"] for r in by["leagues"][0]["rows"]] == ["All closed"] and by["leagues"][0]["count"] == 5


def test_chosen_columns_set_the_score_and_strong_keeps_the_default_three():
    rated, cands, pcts, prof = _gc_setup()
    pcts = pcts.assign(d=[90.0, 90.0, 10.0, 90.0])
    kw = dict(pcts=pcts, label=str, gap=prof, weights=GC_W)
    # columns b and d: the score counts b only (d is not a shortfall): Half 7.5 of 15 -> 50
    rec = cv.recommendations(rated, cands, CUR, "Winger", 3.0, set(), {4: "League One"},
                             tag_metrics=["b", "d"], score_metrics=["b", "d"], **kw)
    got = {r["name"]: (r["weak"], r["gap_closed"]) for r in rec["leagues"][0]["rows"]}
    assert got["Half"] == ([58, 90], 50) and got["All closed"] == ([80, 10], 100)
    assert [w["metric"] for w in rec["weak_metrics"]] == ["b", "d"]
    # "Strong on 2+" still uses the default three (strong_metrics), not the chosen columns
    on = cv.recommendations(rated, cands, CUR, "Winger", 3.0, set(), {4: "League One"},
                            tag_metrics=["b", "d"], score_metrics=["b", "d"],
                            strong_metrics=["a", "b", "c"], strong2=True, **kw)
    assert [r["name"] for r in on["leagues"][0]["rows"]] == ["All closed"]


# --- owner 2026-11-13: measure a position against ANY of our rated players ----------------------
def _vs_ours():
    """Wingers: Best 3.0 and Second 2.5 rated this season in League One; Loan rated elsewhere,
    Old rated last season; a Centre Back 2.0."""
    rated = _cards([(20, 4, CUR, "Winger", 3.0, 3, 3, 900.0, "Leyton Orient", "Best"),
                    (21, 4, CUR, "Winger", 2.5, 3, 3, 900.0, "Leyton Orient", "Second"),
                    (22, 903, CUR, "Winger", 3.9, 3, 3, 900.0, "Somewhere U21", "Loan"),
                    (23, 4, PREV, "Winger", 3.8, 3, 3, 900.0, "Leyton Orient", "Old"),
                    (24, 4, CUR, "Centre Back", 2.0, 3, 3, 900.0, "Leyton Orient", "CB")])
    squad = pd.DataFrame({"player_id": [20, 21, 22, 23, 24],
                          "player_name": ["Best", "Second", "Loan", "Old", "CB"],
                          "position_group": ["Winger"] * 4 + ["Centre Back"]})
    return cv.our_players(squad, rated, CUR, PREV, {4: "League One", 903: "Premier League 2"})


def test_compared_player_is_the_chosen_rated_player_or_our_best():
    ours = _vs_ours()
    assert cv.compared_player(ours, "Winger")["name"] == "Best"               # default
    assert cv.compared_player(ours, "Winger", 21)["name"] == "Second"
    assert cv.compared_player(ours, "Winger", "21")["name"] == "Second"       # from the URL
    assert cv.compared_player(ours, "Winger", 20)["name"] == "Best"
    # invalid -> our best: rated elsewhere, last season only, another position, not ours, junk
    for bad in (22, 23, 24, 999, "abc", "", None, "21.5"):
        assert cv.compared_player(ours, "Winger", bad)["name"] == "Best", bad
    assert cv.compared_player(ours, "Full Back", 21) is None                  # nobody rated there


def test_gap_detail_is_his_shortfalls_and_profile_once():
    d = cv.gap_detail(GC_OURS, GC_BAR, ["a", "b", "c"], str)
    assert d["profile"] == cv.gap_profile(GC_OURS, GC_BAR, ["a", "b", "c"])
    assert d["all_shortfalls"] == cv.all_shortfalls(GC_OURS, GC_BAR, ["a", "b", "c"], str)
    assert d["shortfalls"] == cv.shortfalls(GC_OURS, GC_BAR, ["a", "b", "c"], str)
    # a weaker player: behind on c too, so his three biggest differ
    him = pd.Series({"a": 70.0, "b": 10.0, "c": 20.0})
    h = cv.gap_detail(him, GC_BAR, ["a", "b", "c"], str)
    assert [(s["metric"], s["ours"], s["top6"], s["short"]) for s in h["shortfalls"]] == [
        ("b", 10, 65, 55), ("c", 20, 75, 55), ("a", 70, 75, 5)]
    assert h["profile"] == {"a": (70.0, 75.0), "b": (10.0, 65.0), "c": (20.0, 75.0)}


def test_measure_against_a_non_best_player_sets_gap_and_shortfalls_from_him():
    ours = _vs_ours()
    best, second = cv.compared_player(ours, "Winger"), cv.compared_player(ours, "Winger", 21)
    row = {"group": "Winger", "level": best, "bar": {"median": 3.6}, "gap": 3.6 - 3.0,
           "players": [o for o in ours if o["group"] == "Winger"], "note": None,
           "shortfalls": ["best's"], "all_shortfalls": ["best's all"]}
    detail = {"shortfalls": ["his"], "all_shortfalls": ["his all"], "profile": {"a": (1.0, 2.0)}}
    out = cv.measure_against(row, second, detail)
    assert out["level"]["name"] == "Second" and out["best"]["name"] == "Best"
    assert out["gap"] == pytest.approx(3.6 - 2.5) and out["vs"] == 21
    assert out["shortfalls"] == ["his"] and out["all_shortfalls"] == ["his all"]
    assert row["level"]["name"] == "Best" and row["gap"] == pytest.approx(0.6)  # not mutated
    same = cv.measure_against(row, best, None)
    assert same["vs"] is None and same["best"]["name"] == "Best" and same["gap"] == pytest.approx(0.6)
    assert same["shortfalls"] == ["best's"]
    no_bar = cv.measure_against(dict(row, bar={"median": None}), second, detail)
    assert no_bar["gap"] is None


def test_recommendations_against_a_non_best_player_list_everyone_above_him():
    rated = _cards([(1, 4, CUR, "Winger", 2.8, 3, 3, 900.0, "T", "Between"),
                    (2, 4, CUR, "Winger", 3.4, 3, 3, 900.0, "T", "Above both"),
                    (3, 4, CUR, "Winger", 2.4, 3, 3, 900.0, "T", "Below him")])
    cands = rated[["player_id", "competition_id", "season_id"]].assign(age=24.0, contract_until=pd.NaT)
    pcts = pd.DataFrame({"player_id": [1, 2], "competition_id": 4, "season_id": CUR,
                         "position_group": "Winger", "b": [37.5, 65.0], "c": [20.0, 20.0]})
    him = pd.Series({"a": 70.0, "b": 10.0, "c": 20.0})
    prof = cv.gap_detail(him, GC_BAR, ["a", "b", "c"], str)["profile"]
    rec = cv.recommendations(rated, cands, CUR, "Winger", 2.5, set(), {4: "League One"}, pcts=pcts,
                             tag_metrics=["b", "c"], label=str, gap=prof, weights=GC_W)
    rows = rec["leagues"][0]["rows"]
    assert [r["name"] for r in rows] == ["Above both", "Between"]           # above 2.5, not 3.0
    assert [r["vs_best"] for r in rows] == [0.9, 0.3]                       # vs him
    # Between: a missing -> 0 of 5; b 27.5 of 55; c 0 of 55
    # 100 * (0.3*27.5) / (0.1*5 + 0.3*55 + 0.6*55) = 8.25 / 50 = 16.5 -> 17
    assert rows[1]["gap_closed"] == 17


def test_vs_terms_name_him():
    t = cv.vs_terms("James Morris")
    assert t["vs him"] == ("His rating minus James Morris's; the gap is closed when this reaches "
                           "the gap size.")
    # owner 2026-11-13: one sentence for both ("our player" covers the picked one)
    assert t["Gap closed"] == "How much of our player's shortfall vs the top 6 he would make up. 100% = all of it."


# --- owner 2026-11-13: Big picture physical by phase ----------------------------------------------
def _phase_setup():
    neutral = pd.DataFrame({
        "player_id": [1, 2, 3, 4, 5], "competition_id": 4, "season_id": [CUR, CUR, CUR, CUR, PREV],
        "team_name": ["A", "A", "Leyton Orient", "B", "Leyton Orient"],
        "minutes": [900.0, 300.0, 900.0, 900.0, 900.0],
        "sprint_count_p90": [10.0, 10.0, 20.0, 5.0, 8.0], "psv99_kmh": [30.0, 30.0, 31.0, 29.0, 30.0],
        "np_xg_p90": 0.2})
    detail = pd.DataFrame(
        [(1, 4, CUR, "phys_tip.sprint_count_p90", 6.0), (2, 4, CUR, "phys_tip.sprint_count_p90", 2.0),
         (3, 4, CUR, "phys_tip.sprint_count_p90", 3.0), (4, 4, CUR, "phys_tip.sprint_count_p90", 4.0),
         (5, 4, PREV, "phys_tip.sprint_count_p90", 9.0),
         (1, 4, CUR, "phys_otip.sprint_count_p90", 1.0), (3, 4, CUR, "phys_otip.sprint_count_p90", 9.0),
         (4, 4, CUR, "phys_otip.sprint_count_p90", 2.0),
         (1, 4, CUR, "phys_tip.distance_p90", 99.0)],          # a metric not on the page: ignored
        columns=["player_id", "competition_id", "season_id", "metric", "value_p90"])
    return neutral, detail


def test_phase_frame_is_neutral_with_the_phase_values():
    neutral, detail = _phase_setup()
    tip = cv.phase_frame(detail, neutral, "tip", ["sprint_count_p90", "psv99_kmh"])
    one = tip[(tip.player_id == 1) & (tip.season_id == CUR)].iloc[0]
    assert one["sprint_count_p90"] == 6.0 and one["minutes"] == 900.0 and one["team_name"] == "A"
    assert tip["psv99_kmh"].isna().all()                   # no possession split for top speed
    otip = cv.phase_frame(detail, neutral, "otip", ["sprint_count_p90"])
    assert otip[otip.player_id == 2]["sprint_count_p90"].isna().all()   # no figure -> not counted


def test_big_picture_physical_by_phase_same_club_calculation():
    neutral, detail = _phase_setup()
    rated = _cards([(1, 4, CUR, "Winger", 3.0, 3.0, 2.0, 900.0, "A", "a")])
    ms = ["sprint_count_p90", "psv99_kmh"]
    phases = {k: cv.phase_frame(detail, neutral, k, ms) for k in ("tip", "otip")}
    bp = cv.big_picture(rated, neutral, CUR, PREV, metrics=ms + ["np_xg_p90"], label=str,
                        sections={"sprint_count_p90": "Physical", "psv99_kmh": "Physical", "np_xg_p90": "Attack"},
                        phases=phases)
    rows = {r["measure"]: r for r in bp}
    # all phases: A (10*900+10*300)/1200 = 10, Orient 20, B 5 -> Orient 1st
    assert rows["sprint_count_p90"]["now"]["rank"] == 1
    # in possession: A (6*900+2*300)/1200 = 5, Orient 3, B 4 -> Orient 3rd of 3; last season 1st of 1
    tip = rows["sprint_count_p90"]["phases"]["tip"]
    assert tip["now"] == {"rank": 3, "of": 3, "text": "3rd of 3"} and tip["prev"]["rank"] == 1
    # out of possession: A 1 (player 2 has no figure), Orient 9, B 2 -> Orient 1st; no last season
    otip = rows["sprint_count_p90"]["phases"]["otip"]
    assert otip["now"] == {"rank": 1, "of": 3, "text": "1st of 3"} and otip["prev"] is None
    # top speed has no split: "—" in both phase views
    assert rows["psv99_kmh"]["phases"] == {"tip": {"now": None, "prev": None}, "otip": {"now": None, "prev": None}}
    # ratings and other sections carry no phases
    assert "phases" not in rows["Overall"] and "phases" not in rows["np_xg_p90"]


# --- owner 2026-11-13: Gap closed, a live step-by-step example ------------------------------------
GX_LEVEL = {"name": "Charlie Wellens", "rating": 2.38, "position": "Full Back", "player_id": 7}


def test_recommendations_carry_each_leagues_top_player_by_gap_closed():
    rated, cands, pcts, prof = _gc_setup()
    kw = dict(pcts=pcts, tag_metrics=["a"], label=str, gap=prof, weights=GC_W, n=2)
    rec = cv.recommendations(rated, cands, CUR, "Winger", 3.0, set(), {4: "League One"}, **kw)
    top = rec["leagues"][0]["top_gap"]
    # by Overall the list shows "None closed" and "Tie high"; the top by Gap closed is still found
    assert top["name"] == "All closed" and top["club"] == "T" and top["gap_closed"] == 100
    assert top["pcts"] == {"a": 80.0, "b": 80.0}            # his percentiles on our shortfalls
    none = cv.recommendations(rated, cands, CUR, "Winger", 3.0, set(), {4: "League One"},
                              pcts=pcts, tag_metrics=["a"], label=str)
    assert none["leagues"][0]["top_gap"] is None             # no shortfall -> no Gap closed


# ours / top 6: a 20/75, b 50/65, d 10/35, e 40/60, f 30/50; weighted gap a 5.5, d 5.0, b 4.5, f 2.0, e 1.0
GX_PROF = {"a": (20.0, 75.0), "b": (50.0, 65.0), "d": (10.0, 35.0), "e": (40.0, 60.0), "f": (30.0, 50.0)}
GX_W = {"a": 0.1, "b": 0.3, "d": 0.2, "e": 0.05, "f": 0.1}
# the target: a 47.5 (makes up 27.5), b 90 (40, capped at 15), d none, e 70 (30, capped 20), f 20 (-10 -> 0)
# Gap closed = 100 x (.1x27.5 + .3x15 + .05x20 + 0) / 18 = 45.8 -> 46 (the list's figure is passed in)
GX_TOP = {"name": "Sam Silvera", "club": "Milton Keynes Dons", "gap_closed": 46,
          "pcts": {"a": 47.5, "b": 90.0, "e": 70.0, "f": 20.0}}


def test_gap_example_mini_table_with_hand_numbers():
    ex = cv.gap_example("Full Back", GX_LEVEL, 3.67, GX_PROF, GX_TOP, GX_W, "League One",
                        label={"a": "Sprints", "b": "Distance", "f": "Crosses"}.get)
    assert ex["heading"] == "Gap closed: how much of our player's shortfall a target would make up."
    assert ex["scale"] == "Scores are out of 100 (100 = best at his position in his league)."
    assert ex["columns"] == ["Measure", "Ours (Wellens)", "Top 6", "Gap (Top 6 − Ours)", "Target (Silvera)",
                             "Target − Ours", "Counted"]
    # his 3 biggest weighted shortfalls the target has a figure for: a, b, f (d: no figure)
    # owner 2026-11-13: one decimal, so every row adds up exactly
    assert ex["rows"] == [
        {"label": "Sprints", "ours": "20.0", "top6": "75.0", "gap": "55.0", "target": "47.5", "diff": "27.5", "counted": "27.5"},
        {"label": "Distance", "ours": "50.0", "top6": "65.0", "gap": "15.0", "target": "90.0", "diff": "40.0", "counted": "15.0 (capped at the gap)"},
        {"label": "Crosses", "ours": "30.0", "top6": "50.0", "gap": "20.0", "target": "20.0", "diff": "−10.0", "counted": "0.0"}]
    assert ex["more"] == "…and 2 more measures"                          # d and e
    assert ex["total"] == ("Gap closed = total Counted ÷ total Gap = 46%. Measures that count more in "
                           "the Full Back rating count more.")
    assert ex["why"] == "Why: it ranks players by how much they fix our weaknesses, not just by how good they are."
    assert ex["candidate"] == {"name": "Sam Silvera", "club": "Milton Keynes Dons"} and ex["league"] == "League One"


def test_gap_example_one_decimal_rows_add_up_exactly():
    """Owner 2026-11-13: Ours, Top 6, Gap, Target, Target − Ours and Counted to one decimal;
    each row adds up exactly on the numbers shown (4.2 | 79.0 | 74.8 | 77.5 | 73.3 | 73.3)."""
    prof = {"a": (4.24, 79.04), "b": (33.35, 61.26)}
    top = dict(GX_TOP, pcts={"a": 77.46, "b": 12.05})
    ex = cv.gap_example("Winger", GX_LEVEL, 3.67, prof, top, {"a": 0.5, "b": 0.5}, "League One")
    a, b = ex["rows"]
    assert (a["ours"], a["top6"], a["gap"], a["target"], a["diff"], a["counted"]) == \
        ("4.2", "79.0", "74.8", "77.5", "73.3", "73.3")
    assert (b["ours"], b["top6"], b["gap"], b["target"], b["diff"], b["counted"]) == \
        ("33.4", "61.3", "27.9", "12.1", "−21.3", "0.0")
    for r in ex["rows"]:
        f = lambda k: float(r[k].replace("−", "-").split()[0])      # noqa: E731
        assert abs(f("gap") - (f("top6") - f("ours"))) < 1e-9
        assert abs(f("diff") - (f("target") - f("ours"))) < 1e-9
        assert f("counted") == min(max(f("diff"), 0.0), f("gap"))
    assert "= 46%." in ex["total"]                                   # the total keeps the whole %


def test_gap_example_no_more_row_and_one_more():
    two = {m: GX_PROF[m] for m in ("a", "b")}
    ex = cv.gap_example("Winger", GX_LEVEL, 3.67, two, GX_TOP, GX_W, "Championship")
    assert len(ex["rows"]) == 2 and ex["more"] is None
    assert "in the Winger rating" in ex["total"]
    four = {m: GX_PROF[m] for m in ("a", "b", "e", "f")}
    assert cv.gap_example("Winger", GX_LEVEL, 3.67, four, GX_TOP, GX_W, "L")["more"] == "…and 1 more measure"


def test_gap_example_chosen_columns_only():
    ex = cv.gap_example("Winger", GX_LEVEL, 3.67, GX_PROF, GX_TOP, GX_W, "League One", metrics=["b", "e", "x"])
    assert [r["label"] for r in ex["rows"]] == ["b", "e"] and ex["more"] is None


def test_gap_example_falls_back_to_none():
    for args in (("Winger", GX_LEVEL, 3.67, GX_PROF, None),                 # no candidate
                 ("Winger", None, 3.67, GX_PROF, GX_TOP),                   # no player of ours
                 ("Winger", GX_LEVEL, None, GX_PROF, GX_TOP),               # no bar
                 ("Winger", GX_LEVEL, 3.67, {}, GX_TOP),                    # no shortfall
                 ("Winger", GX_LEVEL, 3.67, GX_PROF, dict(GX_TOP, pcts={"c": 50.0})),     # no figure on any
                 ("Winger", GX_LEVEL, 3.67, GX_PROF, dict(GX_TOP, gap_closed=None))):
        assert cv.gap_example(*args, GX_W, "League One") is None, args


def test_gap_example_above_the_bar_says_remaining_shortfalls():
    """Owner 2026-11-13: when our player is already above the top-6 bar, the % is of his
    remaining shortfalls on these measures, not of a rating gap."""
    above = dict(GX_LEVEL, rating=3.76)
    ex = cv.gap_example("Centre Forward", above, 3.13, GX_PROF, GX_TOP, GX_W, "League One")
    assert ex["total"] == ("Gap closed = total Counted ÷ total Gap = 46% of his remaining shortfalls on "
                           "these measures. Measures that count more in the Centre Forward rating count more.")
    assert len(ex["rows"]) == 3
