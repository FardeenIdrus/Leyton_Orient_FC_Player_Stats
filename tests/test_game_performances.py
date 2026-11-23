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
