"""Impect fixtures and per-match player scores for the English leagues (owner 2026-11-23, phase 4).

    python -m lofc.ingest.impect_matches            # this season, every English league
    python -m lofc.ingest.impect_matches --dry-run  # counts what would be pulled; no call made

For each of the five English leagues (Championship, League One, League Two, National League,
Premier League 2) in the season being played:

  1. the fixture list (one call per league): every match, played or not, into `impect_matches`;
  2. each played match not pulled yet, or recalculated by Impect since (one call per match):
     every player's IMPECT, Offensive and Defensive IMPECT (packing) as RAW MATCH TOTALS --
     Impect's default view, owner 2026-11-23 -- into `player_match_scores`;
  3. each game's percentile within league + season + position, over the games of 45+ minutes:
     "better than X% of the other games at that position" (Impect's own wording). Level: Top
     above 80, Low below 20, Average between.

Players are linked to OUR player_id with the same linkage every other Impect step uses
(`position_shares._linked_ids`); an unlinked player is kept with player_id NULL.
MONITORING ONLY: nothing in scoring reads these tables (register P11). First pull ~800 calls
(the matches played so far); then ~55 a week.
"""
from __future__ import annotations

import datetime
import time

import numpy as np
import pandas as pd

from lofc.ingest.impect_map import IMPECT_POSITION_GROUPS

HOST = "https://api.impect.com/v5/customerapi"
ENGLISH = {3, 4, 5, 65, 903}             # Championship, L1, L2, National League, PL2
SCORES = {"impect": "IMPECT_SCORE_PACKING", "offensive": "OFFENSIVE_IMPECT_SCORE_PACKING",
          "defensive": "DEFENSIVE_IMPECT_SCORE_PACKING"}
MIN_MINUTES = 45                          # games that count (owner 2026-11-23)
TOP, LOW = 80.0, 20.0
CALL_GAP = 0.15                           # seconds between calls (Impect allows 10 a second)
MATCH_COLUMNS = ["match_id", "iteration_id", "competition_id", "season_id", "scheduled_at", "home_squad_id",
                 "away_squad_id", "home_name", "away_name", "home_goals", "away_goals", "available",
                 "last_calculated_at"]
SCORE_COLUMNS = ["match_id", "impect_player_id", "squad_id", "position_group", "minutes",
                 "impect", "offensive", "defensive"]


# ---- pure parts ---------------------------------------------------------------------------------
def _ts(v):
    t = pd.to_datetime(v, errors="coerce", utc=True)
    return None if pd.isna(t) else t.tz_convert(None)


def _goals(g, side):
    try:
        v = g[side]["fullTime"]
        return None if v is None else int(v)
    except (TypeError, KeyError):
        return None


def parse_matches(raw: list, iteration_id: int, competition_id: int, season_id: int, names: dict) -> pd.DataFrame:
    """Impect's fixture list -> one row per match (played or not)."""
    rows = [{"match_id": int(m["id"]), "iteration_id": iteration_id, "competition_id": competition_id,
             "season_id": season_id, "scheduled_at": _ts(m.get("scheduledDate")),
             "home_squad_id": m.get("homeSquadId"), "away_squad_id": m.get("awaySquadId"),
             "home_name": names.get(m.get("homeSquadId")), "away_name": names.get(m.get("awaySquadId")),
             "home_goals": _goals(m.get("goals"), "home"), "away_goals": _goals(m.get("goals"), "away"),
             "available": bool(m.get("available")), "last_calculated_at": _ts(m.get("lastCalculationDate"))}
            for m in raw]
    return pd.DataFrame(rows, columns=MATCH_COLUMNS)


def parse_player_scores(payload: dict, score_ids: dict) -> pd.DataFrame:
    """One match's player-scores -> one row per player: the three scores and minutes summed over
    the positions he played; his position = the one he played longest."""
    want = {score_ids[name]: col for col, name in SCORES.items() if name in score_ids}
    recs = []
    for side in ("squadHome", "squadAway"):
        squad = payload.get(side) or {}
        for p in squad.get("players") or []:
            vals = {col: 0.0 for col in SCORES}
            got = set()
            for s in p.get("playerScores") or []:
                col = want.get(s.get("playerScoreId"))
                if col is not None and s.get("value") is not None:
                    vals[col] += float(s["value"])
                    got.add(col)
            recs.append({"impect_player_id": int(p["id"]), "squad_id": squad.get("id"),
                         "position": p.get("position"), "seconds": float(p.get("playDuration") or 0.0),
                         **{c: (vals[c] if c in got else None) for c in SCORES}})
    if not recs:
        return pd.DataFrame(columns=SCORE_COLUMNS)
    f = pd.DataFrame(recs)
    main = f.sort_values("seconds", ascending=False).drop_duplicates("impect_player_id").set_index("impect_player_id")
    agg = f.groupby("impect_player_id").agg(seconds=("seconds", "sum"),
                                            **{c: (c, lambda x: x.sum(min_count=1)) for c in SCORES})
    out = agg.join(main[["squad_id", "position"]]).reset_index()
    out["position_group"] = out["position"].map(IMPECT_POSITION_GROUPS)
    out["minutes"] = (out["seconds"] / 60.0).round(1)
    out["match_id"] = int(payload.get("matchId"))
    return out[SCORE_COLUMNS]


def add_percentiles(frame: pd.DataFrame) -> pd.DataFrame:
    """Each game's percentile per score: the share of the OTHER games of 45+ minutes at that
    position in that league season with a strictly lower score ("better than X%"). A game under
    45 minutes is measured against the same pool but is not part of it. A pool of one: none."""
    out = frame.copy()
    for col in SCORES:
        out[f"{col}_pct"] = float("nan")
    keys = ["competition_id", "season_id", "position_group"]
    for _k, idx in out.groupby(keys, dropna=False).groups.items():
        g = out.loc[idx]
        in_pool = pd.to_numeric(g["minutes"], errors="coerce").fillna(0) >= MIN_MINUTES
        for col in SCORES:
            pool = pd.to_numeric(g.loc[in_pool, col], errors="coerce").dropna().sort_values().to_numpy()
            n = len(pool)
            if n < 2:
                continue
            vals = pd.to_numeric(g[col], errors="coerce")
            for i, v in vals.items():
                if pd.isna(v):
                    continue
                lower = int(np.searchsorted(pool, v, side="left"))      # games strictly lower
                others = n - 1 if bool(in_pool.loc[i]) else n
                out.at[i, f"{col}_pct"] = round(100.0 * lower / others, 1) if others else float("nan")
    return out


def level(pct) -> str | None:
    """Impect's three levels: Top above 80%, Low below 20%, Average between."""
    if pct is None or pd.isna(pct):
        return None
    return "Top" if pct > TOP else "Low" if pct < LOW else "Average"


# ---- API + database ---------------------------------------------------------------------------
class Api:
    """A tiny Impect client: bearer token, a gap between calls, a retry on 429 / 5xx."""

    def __init__(self, token: str):
        import requests
        self.s = requests.Session()
        self.s.headers["Authorization"] = f"Bearer {token}"
        self.calls = 0

    def get(self, path: str):
        for attempt in range(4):
            time.sleep(CALL_GAP)
            r = self.s.get(HOST + path, timeout=60)
            self.calls += 1
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            body = r.json()
            return body.get("data", body) if isinstance(body, dict) else body
        raise RuntimeError(f"Impect {path}: gave up")


def targets(settings) -> list:
    """The English leagues in the season being played."""
    live = settings.live_season_id
    return [t for t in settings.impect_targets if t.competition_id in ENGLISH and t.season_id == live]


def _squad_names(engine) -> dict:
    f = pd.read_sql("SELECT DISTINCT impect_squad_id, team_name FROM impect_squad_minutes "
                    "WHERE impect_squad_id IS NOT NULL", engine)
    return dict(zip(f["impect_squad_id"].astype(int), f["team_name"]))


def write_matches(engine, f: pd.DataFrame) -> None:
    """Replace one league season's fixture rows, keeping when each match's scores were pulled."""
    from sqlalchemy import text
    if f.empty:
        return
    c, s = int(f["competition_id"].iloc[0]), int(f["season_id"].iloc[0])
    with engine.begin() as conn:
        pulled = dict(conn.execute(text("SELECT match_id, scores_pulled_at FROM impect_matches "
                                        "WHERE competition_id = :c AND season_id = :s"), {"c": c, "s": s}).all())
        conn.execute(text("DELETE FROM impect_matches WHERE competition_id = :c AND season_id = :s"), {"c": c, "s": s})
        f.assign(scores_pulled_at=f["match_id"].map(pulled)).to_sql(
            "impect_matches", conn, if_exists="append", index=False, method="multi", chunksize=2000)


def to_pull(engine, competition_id: int, season_id: int) -> list[int]:
    """Played matches whose scores are missing, or older than Impect's last recalculation."""
    q = pd.read_sql("SELECT match_id, last_calculated_at, scores_pulled_at FROM impect_matches "
                    "WHERE competition_id = %(c)s AND season_id = %(s)s AND available",
                    engine, params={"c": competition_id, "s": season_id})
    stale = q["scores_pulled_at"].isna() | (pd.to_datetime(q["last_calculated_at"]) > pd.to_datetime(q["scores_pulled_at"]))
    return [int(m) for m in q.loc[stale, "match_id"]]


def write_scores(engine, competition_id: int, season_id: int, new: pd.DataFrame, pulled_ids: list[int]) -> int:
    """Put the newly pulled matches in, then rework the whole league season's percentiles."""
    from sqlalchemy import text
    old = pd.read_sql("SELECT match_id, impect_player_id, player_id, competition_id, season_id, squad_id, "
                      "position_group, minutes, impect, offensive, defensive FROM player_match_scores "
                      "WHERE competition_id = %(c)s AND season_id = %(s)s",
                      engine, params={"c": competition_id, "s": season_id})
    old = old[~old["match_id"].isin(pulled_ids)]
    every = pd.concat([old, new], ignore_index=True) if len(new) else old
    every = add_percentiles(every)
    cols = ["match_id", "impect_player_id", "player_id", "competition_id", "season_id", "squad_id",
            "position_group", "minutes", "impect", "offensive", "defensive",
            "impect_pct", "offensive_pct", "defensive_pct"]
    now = datetime.datetime.now()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM player_match_scores WHERE competition_id = :c AND season_id = :s"),
                     {"c": competition_id, "s": season_id})
        if len(every):
            every[cols].to_sql("player_match_scores", conn, if_exists="append", index=False,
                               method="multi", chunksize=5000)
        if pulled_ids:
            conn.execute(text("UPDATE impect_matches SET scores_pulled_at = :t WHERE match_id = ANY(:ids)"
                              if conn.dialect.name == "postgresql" else
                              f"UPDATE impect_matches SET scores_pulled_at = :t WHERE match_id IN ({','.join(map(str, pulled_ids))})"),
                         {"t": now, "ids": pulled_ids} if conn.dialect.name == "postgresql" else {"t": now})
    return len(every)


def pull_league(engine, api: Api, target, score_ids: dict, names: dict, dry_run: bool = False) -> dict:
    from lofc.model.position_shares import _linked_ids
    raw = api.get(f"/iterations/{target.iteration_id}/matches")
    matches = parse_matches(raw, target.iteration_id, target.competition_id, target.season_id, names)
    if dry_run:
        stored = pd.read_sql("SELECT match_id, scores_pulled_at FROM impect_matches WHERE competition_id = %(c)s "
                             "AND season_id = %(s)s", engine, params={"c": target.competition_id, "s": target.season_id})
        done = set(stored.loc[stored["scores_pulled_at"].notna(), "match_id"])
        todo = [m for m in matches.loc[matches["available"], "match_id"] if m not in done]
        return {"league": target.label, "fixtures": len(matches), "to_pull": len(todo)}
    write_matches(engine, matches)
    todo = to_pull(engine, target.competition_id, target.season_id)
    ids = _linked_ids(engine, target)
    link = {} if ids is None else {int(k): int(v) for k, v in ids.dropna().items()}
    parts = []
    for mid in todo:
        f = parse_player_scores(api.get(f"/matches/{mid}/player-scores"), score_ids)
        parts.append(f)
    new = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=SCORE_COLUMNS)
    new["player_id"] = new["impect_player_id"].map(link)
    new["competition_id"], new["season_id"] = target.competition_id, target.season_id
    n = write_scores(engine, target.competition_id, target.season_id, new, todo)
    return {"league": target.label, "fixtures": len(matches), "pulled": len(todo), "rows": n,
            "linked": int(new["player_id"].notna().sum()), "unlinked": int(new["player_id"].isna().sum())}


def main(argv=None) -> None:
    import argparse
    from lofc.config import settings
    from lofc.ingest.impect import _token
    from lofc.store.load import get_engine

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="count what would be pulled (fixture lists only)")
    ap.add_argument("--iteration", type=int, default=None, help="one Impect iteration only")
    args = ap.parse_args(argv)
    engine = get_engine()
    api = Api(_token())
    defs = api.get("/player-scores")
    score_ids = {d["name"]: int(d["id"]) for d in defs if d.get("name") in SCORES.values()}
    missing = set(SCORES.values()) - set(score_ids)
    if missing:
        raise SystemExit(f"Impect no longer lists {sorted(missing)}; nothing pulled")
    names = _squad_names(engine)
    chosen = [t for t in (settings.impect_targets if args.iteration else targets(settings))
              if args.iteration is None or t.iteration_id == args.iteration]
    for t in chosen:
        print(pull_league(engine, api, t, score_ids, names, dry_run=args.dry_run), flush=True)
    print(f"Impect calls made: {api.calls}")


if __name__ == "__main__":
    main()
