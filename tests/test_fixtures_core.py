"""Fixtures page (owner 2026-11-27, phase 5): which games to watch and which players in them,
and why. Pure functions: each player's signals, the region of a club, a past game's scout
reports, and suggested links for reports not attached to a player (never linked automatically).
"""
import pandas as pd

from lofc.core import fixtures as fx


def test_form_flags_top_in_3_of_last_5_and_6_of_last_10():
    f = fx.form_flags([10, 20, 30, 40, 50, 90, 85, 50, 81, 20])
    assert (f["t5"], f["f5"]) == (3, True)
    assert fx.form_flags([90, 90, 90, 90, 10, 90, 90, 10, 10, 10])["f10"] is True     # 6 of 10
    assert fx.form_flags([90, 90, 90, 90, 10, 90, 10, 10, 10, 10])["f10"] is False    # 5 of 10
    assert fx.form_flags([90, 90, 90])["f10"] is False                               # needs 10 games
    # a game under 45 minutes (None) is not a rated game: it is skipped, not counted as Low
    assert fx.form_flags([None, 90, None, 90, 90, None])["t5"] == 3


def test_rising_is_20_points_up_on_the_5_games_before():
    f = fx.form_flags([30, 45, 50, 35, 40, 60, 70, 55, 75, 65])       # 40 -> 65
    assert (f["rise"], f["rise_by"], f["rise_from"], f["rise_to"]) == (True, 25, 40, 65)
    assert fx.form_flags([30, 45, 50, 35, 40, 50, 55, 55, 60, 60])["rise"] is False   # +16
    assert fx.form_flags([60, 70, 55, 75, 65])["rise_by"] is None                     # under 10 games


def test_breaking_through_under_23_minutes_doubled_to_200_plus():
    before, after = [0, 12, 0, 25, 0], [90, 78, 90, 0, 85]
    b = fx.breaking_through(19, before + after)
    assert b == {"on": True, "before": 37, "after": 343}
    assert fx.breaking_through(23, before + after)["on"] is False                     # not under 23
    assert fx.breaking_through(19, [90] * 5 + [90] * 5)["on"] is False                # no jump
    assert fx.breaking_through(19, [0] * 5 + [45, 45, 45, 45, 0])["on"] is False      # 180 < 200
    assert fx.breaking_through(None, before + after)["on"] is False                   # age unknown
    assert fx.breaking_through(19, after)["on"] is False                              # needs 10 club games


def test_region_by_league_or_club_list_unknown_never_dropped():
    table = {"leyton orient": "London & South East", "port vale": "Midlands & East"}
    assert fx.region("Aberdeen FC", 901, table) == "Scotland"
    assert fx.region("Linfield FC", 10305, table) == "Northern Ireland"
    assert fx.region("Shamrock Rovers", 10189, table) == "Ireland"
    assert fx.region("Leyton Orient FC", 4, table) == "London & South East"
    assert fx.region("FC Port Vale", 5, table) == "Midlands & East"
    assert fx.region("Somewhere Town", 65, table) is None


def test_verdicts_any_report_and_scouts_disagree():
    reps = [{"verdict": "Don't sign"}, {"verdict": "Sign"}]
    v = fx.verdict_flags(reps)
    assert v == {"priority": True, "disagree": True, "seen": True}
    assert fx.verdict_flags([]) == {"priority": False, "disagree": False, "seen": False}
    assert fx.verdict_flags([{"verdict": "Monitor"}])["priority"] is False


def test_team_names_match_across_sources():
    assert fx.same_team("Dundee Utd", "Dundee United FC")
    assert fx.same_team("Rangers", "Glasgow Rangers")
    assert fx.same_team("Man City U21", "Manchester City U21")
    assert not fx.same_team("St. Mirren", "St. Johnstone FC")
    assert not fx.same_team("Dundee", "Dundee United FC")
    assert not fx.same_team("Man City U21", "Manchester City")


def test_suggested_links_need_the_club_and_the_surname_and_are_only_suggestions():
    players = pd.DataFrame({"player_id": [1, 2, 3], "player_name": ["Jordan Lawrence-Gabriel", "Jack Smith", "Joe Smith"],
                            "team_name": ["Port Vale FC", "Port Vale FC", "Port Vale FC"]})
    reps = pd.DataFrame({"submission_id": ["a", "b", "c"], "player_name": ["Jordan Gabriel", "J. Smith", "Jordan Gabriel"],
                         "club_name": ["Port Vale", "Port Vale", "Crewe"], "verdict": ["Monitor"] * 3,
                         "submitted_at": pd.to_datetime(["2026-08-10"] * 3)})
    s = fx.suggest_links(reps, players)
    assert s == {1: ["a"]}            # one clear candidate at his club; J. Smith = Jack or Joe -> none; Crewe -> none


def test_every_english_and_pl2_club_has_a_region():
    """The 2026/27 club names as our data holds them (Impect); a new club shows "Region
    unknown" on the page, but these must all be in the list."""
    table = fx.load_regions()
    assert set(table.values()) <= set(fx.REGIONS)
    names = ("AFC Wrexham|FC Burnley|FC Millwall|Queens Park Rangers|Leyton Orient|Milton Keynes Dons|"
             "FC Port Vale|AFC Rochdale|FC Altrincham|Tamworth FC|Aston Villa U21|"
             "Brighton & Hove Albion U21|AFC Bournemouth U21|AFC Sunderland U21|Manchester United U21")
    missing = [n for n in names.split("|") if fx.region(n, 4, table) is None]
    assert missing == []
    assert fx.region("Aston Villa U21", 903, table) == "Midlands & East"


def _frames():
    T = pd.Timestamp
    games = [(100 + i, T("2026-09-01") + pd.Timedelta(days=7 * i)) for i in range(10)]
    matches = pd.DataFrame({"match_id": [g for g, _ in games] + [200], "competition_id": 4, "season_id": 319,
                            "scheduled_at": [d for _, d in games] + [T("2026-11-29 15:00")],
                            "home_squad_id": [10] * 10 + [10], "away_squad_id": [20] * 10 + [30],
                            "home_name": ["Leyton Orient"] * 11, "away_name": ["Bolton"] * 10 + ["Port Vale"],
                            "available": [True] * 10 + [False]})
    # player 1 (Orient, 19): minutes 0 x5 then 90 x5 -> breaking through; player 2 (Orient): in form
    rows = pd.DataFrame({"player_id": [1] * 5 + [2] * 10, "match_id": [105, 106, 107, 108, 109] + list(range(100, 110)),
                         "squad_id": 10, "competition_id": 4, "minutes": [90.0] * 15, "position_group": "Winger"})
    club = pd.DataFrame({"player_id": [2] * 10, "match_id": list(range(100, 110)), "minutes": 90.0,
                         "overall_pct": [10, 20, 30, 40, 50, 90, 85, 50, 81, 20]})
    squadmin = pd.DataFrame({"player_id": [1, 2, 3], "impect_squad_id": [10, 10, 30], "team_name": ["Leyton Orient", "Leyton Orient", "Port Vale"],
                             "position_group": ["Winger", "Winger", "Centre Back"], "minutes": [450, 900, 800], "competition_id": 4})
    people = pd.DataFrame({"player_id": [1, 2, 3], "player_name": ["Young One", "Form Man", "Big Back"],
                           "birth_date": [T("2007-05-01"), T("1998-01-01"), T("2000-01-01")]})
    cards = pd.DataFrame({"player_id": [2, 3], "competition_id": 4, "position_group": ["Winger", "Centre Back"],
                          "objective_composite": [3.2, 3.8]})
    return dict(matches=matches, rows=rows, club=club, squadmin=squadmin, people=people, cards=cards)


def test_players_get_their_squad_signals_and_rank():
    P, squads = fx.players(_frames(), today=pd.Timestamp("2026-11-27"))
    assert P[1]["br"] == {"on": True, "before": 0, "after": 450} and P[1]["age"] == 19
    assert P[2]["f5"] is True and P[2]["sq"] == 10 and P[2]["ov"] == 3.2 and P[2]["rk"] == 1 and P[2]["of"] == 1
    assert P[3]["sq"] == 30 and P[3]["pos"] == "Centre Back" and P[3]["f"] == []   # no games: from squad minutes
    assert squads[30]["name"] == "Port Vale"


def test_not_seen_yet_and_reports_attach_fresh():
    P, _ = fx.players(_frames(), today=pd.Timestamp("2026-11-27"))
    reps = pd.DataFrame({"submission_id": ["a"], "player_id": [2.0], "verdict": ["Sign"], "scout": ["Ann"],
                         "submitted_at": pd.to_datetime(["2026-11-12"]), "home_team": ["Orient"], "away_team": ["Bolton"],
                         "fixture_date": pd.to_datetime(["2026-11-10"]), "player_name": ["Form Man"],
                         "club_name": ["Leyton Orient"], "linkable": [True]})
    out = fx.attach(P, reps, watch={3: "Watching"})
    assert out[2]["rep"] == [{"v": "Sign", "d": "2026-11-12", "s": "Ann", "g": "Orient v Bolton"}]
    assert out[2]["pri"] is True and out[2]["ns"] is False
    assert out[3]["ns"] is True and out[3]["watch"] == "Watching"     # 3.8, never scouted
    assert P[2].get("rep") is None                                     # the cached players are not changed


def test_past_game_lists_the_reports_filed_at_it():
    reps = pd.DataFrame({"player_name": ["A", "B", "C"], "verdict": ["Sign", "Monitor", "Monitor"], "scout": ["Ann"] * 3,
                         "player_id": [1.0, None, 2.0], "home_team": ["Leyton Orient", "Orient", "Bolton"],
                         "away_team": ["Bolton", "Bolton Wanderers", "Leyton Orient"],
                         "fixture_date": pd.to_datetime(["2026-11-21", "2026-11-21", "2026-11-21"])})
    got = fx.reports_at(reps, pd.Timestamp("2026-11-21 15:00"), "Leyton Orient", "Bolton Wanderers")
    assert [r["p"] for r in got] == ["A", "B"]
