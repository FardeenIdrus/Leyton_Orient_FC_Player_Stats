"""Per-match Impect scores (owner 2026-11-23, phase 4): parsing Impect's fixture list and match
player-scores, and each game's percentile within league + season + position (games of 45+
minutes), as raw match totals. Pure functions only -- no API call, no database."""
import pandas as pd
import pytest

from lofc.ingest import impect_matches as im

SCORE_IDS = {"IMPECT_SCORE_PACKING": 0, "OFFENSIVE_IMPECT_SCORE_PACKING": 1, "DEFENSIVE_IMPECT_SCORE_PACKING": 2}


def test_english_targets_are_the_five_leagues_this_season():
    from lofc.ingest.impect_matches import ENGLISH
    assert ENGLISH == {3, 4, 5, 65, 903}


def test_parse_matches_keeps_played_and_future_fixtures():
    raw = [{"id": 1, "homeSquadId": 10, "awaySquadId": 20, "scheduledDate": "2026-11-21T15:00:00Z",
            "lastCalculationDate": "2026-11-22T08:00:00.5Z", "available": True,
            "goals": {"home": {"fullTime": 2}, "away": {"fullTime": 1}}},
           {"id": 2, "homeSquadId": 20, "awaySquadId": 10, "scheduledDate": "2026-12-05T15:00:00Z",
            "lastCalculationDate": None, "available": False, "goals": None}]
    f = im.parse_matches(raw, iteration_id=2117, competition_id=4, season_id=319, names={10: "Orient", 20: "Bolton"})
    assert list(f["match_id"]) == [1, 2]
    a, b = f.iloc[0], f.iloc[1]
    assert (a["home_name"], a["away_name"], a["home_goals"], a["away_goals"], a["available"]) == ("Orient", "Bolton", 2, 1, True)
    assert a["scheduled_at"] == pd.Timestamp("2026-11-21 15:00") and b["available"] == False  # noqa: E712
    assert pd.isna(b["home_goals"]) and pd.isna(b["last_calculated_at"])


def _payload():
    def p(pid, pos, secs, i, o, d):
        return {"id": pid, "position": pos, "playDuration": secs,
                "playerScores": [{"playerScoreId": 0, "value": i}, {"playerScoreId": 1, "value": o},
                                 {"playerScoreId": 2, "value": d}, {"playerScoreId": 9, "value": 99.0}]}
    return {"matchId": 7, "squadHome": {"id": 10, "players": [
                p(100, "LEFT_WINGER", 3000.0, 1.0, 0.8, 0.2),
                p(100, "CENTER_FORWARD", 1800.0, 0.5, 0.5, 0.0),     # same player, a second position
                p(101, "GOALKEEPER", 5400.0, 0.3, 0.0, 0.3)]},
            "squadAway": {"id": 20, "players": [p(200, "CENTRAL_DEFENDER", 600.0, -0.1, 0.0, -0.1)]}}


def test_parse_player_scores_sums_positions_and_takes_the_longest():
    rows = im.parse_player_scores(_payload(), SCORE_IDS)
    by = rows.set_index("impect_player_id")
    w = by.loc[100]
    assert (w["squad_id"], w["position_group"], w["minutes"]) == (10, "Winger", 80.0)   # 50 + 30 min
    assert (w["impect"], w["offensive"], w["defensive"]) == pytest.approx((1.5, 1.3, 0.2))
    assert by.loc[200, "squad_id"] == 20 and by.loc[200, "position_group"] == "Centre Back"
    assert by.loc[200, "minutes"] == 10.0 and list(rows["match_id"].unique()) == [7]


def test_percentile_is_the_share_of_the_positions_45_minute_games_he_beats():
    f = pd.DataFrame({"competition_id": 4, "season_id": 319, "position_group": "Winger",
                      "minutes": [90, 90, 90, 90, 90, 30],
                      "impect": [1.0, 2.0, 3.0, 4.0, 5.0, 9.0],
                      "offensive": [5.0, 4.0, 3.0, 2.0, 1.0, 0.0],
                      "defensive": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0]})
    out = im.add_percentiles(f)
    # pool = the five 90-minute games; "better than X%" of the OTHER games in the pool
    assert list(out["impect_pct"]) == [0.0, 25.0, 50.0, 75.0, 100.0, 100.0]
    assert list(out["offensive_pct"][:5]) == [100.0, 75.0, 50.0, 25.0, 0.0]
    assert list(out["defensive_pct"][:5]) == [0.0] * 5                 # ties beat nobody
    # another league or position is its own pool
    g = pd.concat([f.head(2), f.head(2).assign(competition_id=5)], ignore_index=True)
    assert list(im.add_percentiles(g)["impect_pct"]) == [0.0, 100.0, 0.0, 100.0]


def test_a_pool_of_one_has_no_percentile():
    f = pd.DataFrame({"competition_id": [4], "season_id": [319], "position_group": ["Winger"], "minutes": [90],
                      "impect": [1.0], "offensive": [1.0], "defensive": [1.0]})
    assert im.add_percentiles(f)["impect_pct"].isna().all()


@pytest.mark.parametrize("pct,level", [(80.1, "Top"), (80.0, "Average"), (20.0, "Average"),
                                       (19.9, "Low"), (None, None)])
def test_level(pct, level):
    assert im.level(pct) == level


class _Resp:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"data": [1]}


class _Session:
    def __init__(self, fails, exc):
        self.fails, self.exc, self.headers, self.n = fails, exc, {}, 0

    def get(self, url, timeout):
        self.n += 1
        if self.n <= self.fails:
            raise self.exc("slow")
        return _Resp()


def _api(monkeypatch, fails, exc):
    monkeypatch.setattr(im.time, "sleep", lambda s: None)
    api = im.Api.__new__(im.Api)
    api.s, api.calls = _Session(fails, exc), 0
    return api


@pytest.mark.parametrize("exc_name", ["Timeout", "ConnectionError"])
def test_a_slow_or_dropped_answer_is_retried(monkeypatch, exc_name):
    import requests
    api = _api(monkeypatch, 3, getattr(requests, exc_name))
    assert api.get("/x") == [1] and api.s.n == 4


def test_gives_up_after_four_tries(monkeypatch):
    import requests
    api = _api(monkeypatch, 4, requests.Timeout)
    with pytest.raises(requests.Timeout):
        api.get("/x")
    assert api.s.n == 4
