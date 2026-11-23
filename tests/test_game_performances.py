"""Game performances (owner 2026-11-23, phase 4): a player's last games with each game's
percentile and level, the Top / Average / Low counts, and the Watchlist's "Last 5" and "In
form". Plain frames in, plain data out."""
import pandas as pd

from lofc.core import game_performances as gp


def _games(n=12):
    d = pd.date_range("2026-08-09", periods=n, freq="7D")
    return pd.DataFrame({
        "match_id": range(1, n + 1), "scheduled_at": d, "squad_id": 10,
        "home_squad_id": [10 if i % 2 == 0 else 20 for i in range(n)],
        "home_name": ["Orient" if i % 2 == 0 else f"Opp {i}" for i in range(n)],
        "away_name": [f"Opp {i}" if i % 2 == 0 else "Orient" for i in range(n)],
        "competition_id": 4, "position_group": "Winger",
        "minutes": [90.0] * (n - 1) + [30.0],
        "impect": [1.0] * n, "offensive": [1.0] * n, "defensive": [1.0] * n,
        "impect_pct": [10, 50, 90, 85, 81, 20, 19.9, 80, 80.1, 99, 95, 70],
        "offensive_pct": [50] * n, "defensive_pct": [None] * n})


def test_last_ten_games_oldest_first_with_opponent_and_levels():
    out = gp.block(_games(), league_names={4: "League One"})
    g = out["games"]
    assert len(g) == 10 and [x["match_id"] for x in g] == list(range(3, 13))
    first = g[0]
    assert first["opponent"] == "Opp 2" and first["home"] is True and first["minutes"] == 90
    assert first["scores"]["impect"] == {"pct": 90, "level": "Top"}
    assert g[1]["opponent"] == "Opp 3" and g[1]["home"] is False
    assert g[-1]["counted"] is False                                    # 30 minutes: not counted
    assert g[0]["scores"]["defensive"] == {"pct": None, "level": None}


def test_counts_only_games_of_45_minutes():
    out = gp.block(_games(), league_names={4: "League One"})
    # last 10 = pcts 90, 85, 81, 20, 19.9, 80, 80.1, 99, 95 (90 min) + 70 (30 min, not counted).
    # Shown as whole numbers and levelled on what is shown: 19.9 -> 20 (Average), 80.1 -> 80
    # (Average), so a dot never reads "20%" in red.
    assert out["counts"]["impect"] == {"Top": 5, "Average": 4, "Low": 0}
    shown = [(x["scores"]["impect"]["pct"], x["scores"]["impect"]["level"]) for x in out["games"]]
    assert (20, "Average") in shown and (80, "Average") in shown and (81, "Top") in shown
    assert out["note"] == ("Match totals, as in Impect (not scaled to 90). Each game: better than X% of games "
                           "at the position he played, in League One this season (45+ minutes).")


def test_no_games_no_block():
    assert gp.block(_games().head(0), league_names={}) is None


def test_last_five_and_in_form():
    g = _games()
    # last five counted games (45+): 80.1, 99, 95 and before them 19.9, 80 -> newest last
    assert gp.last_five(g) == [20, 80, 80, 99, 95]                     # whole numbers, newest last
    assert gp.in_form(gp.last_five(g)) is False                         # 2 Top (99, 95)
    assert gp.in_form([81, 85, 90, 50, 60]) is True                     # 3 Top
    assert gp.in_form([81, 85, 20, 50, 60]) is False                    # 2 Top
    assert gp.last_five(g.head(0)) == []


# --- the club's per-game scoring on the player page (owner 2026-11-23, N21) -------------------
def test_block_carries_the_club_scores_beside_impects():
    g = _games().assign(overall=3.8, performance=3.6, physical=None,
                        overall_pct=78.4, performance_pct=71.0, physical_pct=None)
    out = gp.block(g, league_names={4: "League One"})
    s = out["games"][0]["scores"]
    assert s["overall"] == {"pct": 78, "level": "Average", "value": 3.8}
    assert s["physical"] == {"pct": None, "level": None, "value": None}
    assert list(out["labels"]) == ["overall", "performance", "physical", "impect", "offensive", "defensive"]
    assert out["counts"]["overall"]["Average"] == 9                    # 10 games, one under 45 min


def _club_row():
    perf = {"pass_completion_pct": {"v": 0.75, "n": 30.0, "d": 40.0},
            "aerial_win_pct": {"v": None, "n": 0.0, "d": 0.0},
            "ball_wins_p90": {"v": 6.0, "n": 6.0, "d": None},
            "turnovers_p90": {"v": 9.0, "n": 9.0, "d": None}}
    phys = {"distance_p90": {"v": 10400.0, "n": 10400.0, "d": None},
            "psv99_kmh": {"v": 31.2, "n": 31.2, "d": None}}
    return {"position_group": "Central Mid", "minutes": 90.0, "perf": perf, "phys": phys,
            "metric_pcts": {"pass_completion_pct": 71.0, "ball_wins_p90": 90.0, "turnovers_p90": 30.0,
                            "distance_p90": 60.0, "psv99_kmh": 85.0}}


def test_detail_lists_every_metric_with_value_percentile_band_and_source():
    d = gp.detail_tables(_club_row())
    perf = {r["metric"]: r for r in d["perf"]}
    pc = perf["pass_completion_pct"]
    assert (pc["label"], pc["game"], pc["per90"], pc["pct"], pc["band"]) == ("Pass accuracy", "30 of 40 (75%)", None, 71, 4.05)
    assert pc["source"] == "SUCCESSFUL_PASSES / (SUCCESSFUL_PASSES + UNSUCCESSFUL_PASSES)"
    assert pc["weight"] in ("High", "Mid", "Low")
    assert perf["aerial_win_pct"]["game"] == "none in this game" and perf["aerial_win_pct"]["out"] is True
    assert perf["turnovers_p90"]["lower_better"] is True and perf["ball_wins_p90"]["per90"] == 6.0
    # every Central Mid Performance metric is listed, in the club's order, even if the game lacks it
    from lofc.model import scorecard as sc
    assert [r["metric"] for r in d["perf"]] == sc._resolved_performance("Central Mid")
    phys = {r["metric"]: r for r in d["phys"]}
    assert phys["distance_p90"]["game"] == "10,400 m" and phys["distance_p90"]["source"] == "total_distance_full_all"
    assert phys["top5_psv99_kmh"]["game"] == "not available per game" and phys["top5_psv99_kmh"]["out"] is True
    assert phys["hsr_count_p90"]["game"] == "no SkillCorner data"


def test_games_workbook_has_one_row_per_game_and_a_sources_sheet():
    import io
    from openpyxl import load_workbook
    g = _games().head(3).assign(overall=3.8, performance=3.6, physical=4.1, overall_pct=78.0,
                         performance_pct=71.0, physical_pct=86.0, impect_pct=85.0,
                         perf=[_club_row()["perf"]] * 3, phys=[_club_row()["phys"]] * 3,
                         metric_pcts=[_club_row()["metric_pcts"]] * 3)
    wb = load_workbook(io.BytesIO(gp.games_xlsx(g, "Example Player", "League One")))
    ws = wb["Games"]
    head = [c.value for c in ws[1]]
    assert head[:6] == ["Date", "Opponent", "H/A", "Minutes", "Position", "Overall"]
    assert "Pass accuracy · game" in head and "Pass accuracy · %" in head and "Pass accuracy · band" in head
    assert ws.max_row == 4                                              # header + 3 games
    assert ws.cell(row=2, column=head.index("Pass accuracy · game") + 1).value == "30 of 40"
    src = {r[0].value: r[1].value for r in wb["Sources"].iter_rows(min_row=2)}
    assert src["Distance"] == "SkillCorner: total_distance_full_all"
