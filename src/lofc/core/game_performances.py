"""Game performances (owner 2026-11-23, phase 4): a player's last games -- each game's IMPECT,
Offensive and Defensive IMPECT percentile and level, as in Impect's "Game performances" -- for
the player page, and "Last 5" / "In form" for the Watchlist.

Each percentile is shown as a whole number and the level is worked out from that shown number
(Top above 80, Low below 20), so a dot never reads "20%" while coloured Low. Only games of 45+
minutes are counted; a shorter one is shown hollow. Raw match totals, as in Impect (owner
2026-11-23). MONITORING ONLY: never part of a rating (P11)."""
from __future__ import annotations

import math

import pandas as pd

LAST = 10
MIN_MINUTES = 45
SCORES = ("impect", "offensive", "defensive")
LABELS = {"impect": "IMPECT", "offensive": "Offensive", "defensive": "Defensive"}


def _whole(p):
    return None if p is None or pd.isna(p) else int(math.floor(float(p) + 0.5))


def level(p) -> str | None:
    """On the SHOWN whole number: Top above 80, Low below 20, Average between."""
    p = _whole(p) if isinstance(p, float) else p
    if p is None:
        return None
    return "Top" if p > 80 else "Low" if p < 20 else "Average"


def block(games: pd.DataFrame, league_names: dict) -> dict | None:
    """The player page's section from his game rows (player_match_scores joined to
    impect_matches): the last LAST games oldest first, the counts per level over the counted
    ones, and one line saying what the numbers are."""
    if games is None or games.empty:
        return None
    g = games.sort_values("scheduled_at").tail(LAST)
    rows = []
    for r in g.to_dict("records"):
        home = r.get("home_squad_id") == r.get("squad_id")
        mins = r.get("minutes")
        rows.append({"match_id": int(r["match_id"]),
                     "date": pd.Timestamp(r["scheduled_at"]).strftime("%-d %b"),
                     "opponent": r["away_name"] if home else r["home_name"], "home": bool(home),
                     "minutes": None if mins is None or pd.isna(mins) else int(round(mins)),
                     "counted": bool(mins is not None and not pd.isna(mins) and mins >= MIN_MINUTES),
                     "position": r.get("position_group"),
                     "scores": {s: {"pct": _whole(r.get(f"{s}_pct")), "level": level(_whole(r.get(f"{s}_pct")))}
                                for s in SCORES}})
    counts = {s: {"Top": 0, "Average": 0, "Low": 0} for s in SCORES}
    for x in rows:
        if x["counted"]:
            for s in SCORES:
                if x["scores"][s]["level"]:
                    counts[s][x["scores"][s]["level"]] += 1
    league = league_names.get(int(g.iloc[-1]["competition_id"]), "his league")
    # each game is measured at the position he played in THAT game
    return {"games": rows, "counts": counts, "labels": LABELS,
            "note": (f"Match totals, as in Impect (not scaled to 90). Each game: better than X% of games "
                     f"at the position he played, in {league} this season ({MIN_MINUTES}+ minutes).")}


def last_five(games: pd.DataFrame, score: str = "impect") -> list:
    """His last five counted games' percentiles (whole numbers), oldest first."""
    if games is None or games.empty:
        return []
    g = games[pd.to_numeric(games["minutes"], errors="coerce").fillna(0) >= MIN_MINUTES]
    g = g.sort_values("scheduled_at").tail(5)
    return [_whole(v) for v in g[f"{score}_pct"]]


def in_form(last: list) -> bool:
    """Top level in 3 or more of his last five counted games."""
    return sum(1 for p in last if level(p) == "Top") >= 3


def load(engine, player_ids, season_id: int) -> pd.DataFrame:
    """Every game row of `player_ids` in `season_id` (any English league), with the fixture."""
    ids = [int(i) for i in player_ids]
    if not ids:
        return pd.DataFrame()
    return pd.read_sql(
        "SELECT s.player_id, s.match_id, s.squad_id, s.competition_id, s.position_group, s.minutes, "
        "s.impect, s.offensive, s.defensive, s.impect_pct, s.offensive_pct, s.defensive_pct, "
        "m.scheduled_at, m.home_squad_id, m.home_name, m.away_name "
        "FROM player_match_scores s JOIN impect_matches m USING (match_id) "
        "WHERE s.season_id = %(s)s AND s.player_id = ANY(%(i)s)",
        engine, params={"s": int(season_id), "i": ids})
