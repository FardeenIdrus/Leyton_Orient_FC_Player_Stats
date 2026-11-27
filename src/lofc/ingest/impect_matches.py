"""Impect fixtures and per-match player scores for the UK and Irish leagues (owner 2026-11-23, phase 4;
Scottish, Northern Irish and Irish leagues added 2026-11-27, N28).

    python -m lofc.ingest.impect_matches            # this season, every UK and Irish league
    python -m lofc.ingest.impect_matches --dry-run  # counts what would be pulled; no call made

For each UK and Irish league (Championship, League One, League Two, National League, Premier
League 2, Scottish Premiership, Scottish Championship, NIFL Premiership, Irish Premier Division)
in the season being played:

  1. the fixture list (one call per league): every match, played or not, into `impect_matches`;
  2. each played match not pulled yet, or recalculated by Impect since (one call per match):
     every player's IMPECT, Offensive and Defensive IMPECT (packing) as RAW MATCH TOTALS --
     Impect's default view, owner 2026-11-23 -- into `player_match_scores`;
  3. each game's percentile within league + season + position, over the games of 45+ minutes:
     "better than X% of the other games at that position" (Impect's own wording). Level: Top
     above 80, Low below 20, Average between.

  4. the club's own per-game scoring (owner 2026-11-23, N21; `model.game_scoring`): each
     played match's player KPIs (one call per match, game totals) and SkillCorner's per-match
     physical rows (one call per league), rated on the club framework per game into
     `player_match_club`.

Players are linked to OUR player_id with the same linkage every other Impect step uses
(`position_shares._linked_ids`); an unlinked player is kept with player_id NULL.
MONITORING ONLY: nothing in scoring reads these tables (register P11). First pull ~800 calls
for the scores plus ~800 for the KPIs (the matches played so far); then ~110 a week.
"""
from __future__ import annotations

import datetime
import time

import numpy as np
import pandas as pd

from lofc.ingest.impect_map import IMPECT_POSITION_GROUPS

HOST = "https://api.impect.com/v5/customerapi"
# Championship, L1, L2, National League, PL2, Scottish Premiership, Scottish Championship,
# NIFL Premiership (10_000 + 305), Irish Premier Division (10_000 + 189) -- owner 2026-11-27 (N28)
UK_IRELAND = {3, 4, 5, 65, 903, 901, 902, 10305, 10189}
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


def add_percentiles(frame: pd.DataFrame, cols=SCORES) -> pd.DataFrame:
    """Each game's percentile per score: the share of the OTHER games of 45+ minutes at that
    position in that league season with a strictly lower score ("better than X%"). A game under
    45 minutes is measured against the same pool but is not part of it. A pool of one: none."""
    out = frame.copy()
    for col in cols:
        out[f"{col}_pct"] = float("nan")
    keys = ["competition_id", "season_id", "position_group"]
    for _k, idx in out.groupby(keys, dropna=False).groups.items():
        g = out.loc[idx]
        in_pool = pd.to_numeric(g["minutes"], errors="coerce").fillna(0) >= MIN_MINUTES
        for col in cols:
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
    """A tiny Impect client: bearer token, a gap between calls, a retry on 429 / 5xx and on a
    timed-out or dropped connection (owner 2026-11-23: one slow answer stopped the first pull)."""

    def __init__(self, token: str):
        import requests
        self.s = requests.Session()
        self.s.headers["Authorization"] = f"Bearer {token}"
        self.calls = 0

    def get(self, path: str):
        import requests
        for attempt in range(4):
            time.sleep(CALL_GAP)
            self.calls += 1
            try:
                r = self.s.get(HOST + path, timeout=60)
            except (requests.Timeout, requests.ConnectionError):
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)
                continue
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            body = r.json()
            return body.get("data", body) if isinstance(body, dict) else body
        raise RuntimeError(f"Impect {path}: gave up")


def targets(settings) -> list:
    """The UK and Irish leagues in the season being played."""
    live = settings.live_season_id
    return [t for t in settings.impect_targets if t.competition_id in UK_IRELAND and t.season_id == live]


def _squad_names(engine) -> dict:
    f = pd.read_sql("SELECT DISTINCT impect_squad_id, team_name FROM impect_squad_minutes "
                    "WHERE impect_squad_id IS NOT NULL", engine)
    return dict(zip(f["impect_squad_id"].astype(int), f["team_name"]))


def write_matches(engine, f: pd.DataFrame) -> None:
    """Replace one league season's fixture rows, keeping when each match's scores and KPIs were
    pulled (owner 2026-11-27: dropping kpis_pulled_at here re-pulled every match's KPIs on every
    run -- 1,766 calls where ~880 were due)."""
    from sqlalchemy import text
    if f.empty:
        return
    c, s = int(f["competition_id"].iloc[0]), int(f["season_id"].iloc[0])
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT match_id, scores_pulled_at, kpis_pulled_at FROM impect_matches "
                                 "WHERE competition_id = :c AND season_id = :s"), {"c": c, "s": s}).all()
        scores = {r[0]: r[1] for r in rows}
        kpis = {r[0]: r[2] for r in rows}
        conn.execute(text("DELETE FROM impect_matches WHERE competition_id = :c AND season_id = :s"), {"c": c, "s": s})
        f.assign(scores_pulled_at=f["match_id"].map(scores), kpis_pulled_at=f["match_id"].map(kpis)).to_sql(
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


def to_pull_kpis(engine, competition_id: int, season_id: int) -> list[int]:
    """Played matches whose per-match KPIs (for the club's per-game scoring) are missing, or
    older than Impect's last recalculation."""
    from sqlalchemy import text
    q = pd.read_sql(text("SELECT match_id, last_calculated_at, kpis_pulled_at FROM impect_matches "
                         "WHERE competition_id = :c AND season_id = :s AND available"),
                    engine, params={"c": competition_id, "s": season_id})
    stale = q["kpis_pulled_at"].isna() | (pd.to_datetime(q["last_calculated_at"]) > pd.to_datetime(q["kpis_pulled_at"]))
    return [int(m) for m in q.loc[stale, "match_id"]]


def physical_games(engine, competition_id: int, season_id: int):
    """SkillCorner's per-match physical rows for this league season (one call), with OUR
    player_id attached by the same birth-date + name match the season data uses. None when the
    league has no SkillCorner edition or the call fails (the stored physical is then kept)."""
    from lofc.config import settings
    from lofc.ingest import skillcorner_api
    from lofc.model.build_neutral import _league_name_index
    from lofc.model.skillcorner_check import match_to_ours
    target = next((t for t in settings.skillcorner_targets
                   if t.competition_id == competition_id and t.season_id == season_id), None)
    if target is None:
        return None
    try:
        rows = skillcorner_api._client().get_physical(params={"competition_edition": target.edition_id})
    except Exception as exc:                                   # keep what is stored; say so
        print(f"SkillCorner per-match physical not pulled for {target.label}: {exc}", flush=True)
        return None
    f = pd.DataFrame(rows)
    if f.empty:
        return None
    ours = pd.read_sql("SELECT player_id, player_name, birth_date FROM players", engine)
    m = match_to_ours(f, ours, league_name_index=_league_name_index(engine, competition_id, season_id))
    m = m.dropna(subset=["player_id_ours"]).copy()
    m["player_id"] = m["player_id_ours"].astype("int64")
    m["match_date"] = pd.to_datetime(m["match_date"]).dt.date
    return m


def _json(v):
    import json
    if isinstance(v, str):
        return json.loads(v)
    return v if isinstance(v, dict) else None


def write_club(engine, competition_id: int, season_id: int, new: pd.DataFrame, pulled_ids: list[int],
               physical, link: dict) -> int:
    """The club's per-game scoring for one league season (`model.game_scoring`): newly pulled
    games' KPIs replace their old rows, SkillCorner's per-match physical is joined on (our
    player, date) -- refreshed for every game when it was pulled, kept otherwise -- and the
    whole league season is re-rated (the pools change as games are added)."""
    import sqlalchemy as sa
    from sqlalchemy import text
    from lofc.model import game_scoring as gsc
    cols = ["match_id", "impect_player_id", "player_id", "competition_id", "season_id", "position_group",
            "minutes", "phys_minutes", "perf", "phys"]
    old = pd.read_sql(text("SELECT " + ", ".join(cols) + " FROM player_match_club "
                           "WHERE competition_id = :c AND season_id = :s"),
                      engine, params={"c": competition_id, "s": season_id})
    old = old[~old["match_id"].isin(pulled_ids)]
    old["perf"] = old["perf"].map(_json)
    old["phys"] = old["phys"].map(_json)
    fresh = pd.DataFrame(columns=cols)
    if new is not None and len(new):
        fresh = new.assign(
            player_id=new["impect_player_id"].map(link),
            competition_id=competition_id, season_id=season_id, phys_minutes=None, phys=None,
            perf=[gsc.impect_game_metrics(k, m) for k, m in zip(new["kpis"], new["minutes"])])[cols]
    every = pd.concat([x for x in (old, fresh) if len(x)], ignore_index=True) if (len(old) or len(fresh)) \
        else pd.DataFrame(columns=cols)
    if not len(every):
        return 0
    if physical is not None and len(physical):
        dates = pd.read_sql("SELECT match_id, scheduled_at FROM impect_matches", engine)
        day = dict(zip(dates["match_id"], pd.to_datetime(dates["scheduled_at"]).dt.date))
        by = {(int(r["player_id"]), r["match_date"]): r for r in physical.to_dict("records")}
        phys, pmins = [], []
        for pid, mid in zip(every["player_id"], every["match_id"]):
            r = by.get((int(pid), day.get(mid))) if pd.notna(pid) else None
            phys.append(gsc.physical_game_metrics(r) if r is not None else None)
            pmins.append(float(r["minutes_full_all"]) if r is not None and pd.notna(r.get("minutes_full_all")) else None)
        every["phys"], every["phys_minutes"] = phys, pmins
    every["player_id"] = every["player_id"].astype("Int64")
    scored = gsc.score_games(every)
    out_cols = cols + ["metric_pcts", "performance", "physical", "overall",
                       "performance_pct", "physical_pct", "overall_pct"]
    now = datetime.datetime.now()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM player_match_club WHERE competition_id = :c AND season_id = :s"),
                     {"c": competition_id, "s": season_id})
        scored[out_cols].to_sql("player_match_club", conn, if_exists="append", index=False, chunksize=2000,
                                dtype={c: sa.JSON(none_as_null=True) for c in ("perf", "phys", "metric_pcts")})
        if pulled_ids:
            if conn.dialect.name == "postgresql":
                conn.execute(text("UPDATE impect_matches SET kpis_pulled_at = :t WHERE match_id = ANY(:ids)"),
                             {"t": now, "ids": pulled_ids})
            else:
                conn.execute(text(f"UPDATE impect_matches SET kpis_pulled_at = :t "
                                  f"WHERE match_id IN ({','.join(map(str, pulled_ids))})"), {"t": now})
    return len(scored)


def pull_league(engine, api: Api, target, score_ids: dict, names: dict, dry_run: bool = False,
                kpi_names: dict | None = None) -> dict:
    from lofc.model.position_shares import _linked_ids
    raw = api.get(f"/iterations/{target.iteration_id}/matches")
    matches = parse_matches(raw, target.iteration_id, target.competition_id, target.season_id, names)
    if dry_run:
        stored = pd.read_sql("SELECT match_id, scores_pulled_at FROM impect_matches WHERE competition_id = %(c)s "
                             "AND season_id = %(s)s", engine, params={"c": target.competition_id, "s": target.season_id})
        done = set(stored.loc[stored["scores_pulled_at"].notna(), "match_id"])
        todo = [m for m in matches.loc[matches["available"], "match_id"] if m not in done]
        out = {"league": target.label, "fixtures": len(matches), "to_pull": len(todo)}
        if kpi_names is not None:
            kp = pd.read_sql("SELECT match_id, kpis_pulled_at FROM impect_matches WHERE competition_id = %(c)s "
                             "AND season_id = %(s)s", engine, params={"c": target.competition_id, "s": target.season_id})
            kdone = set(kp.loc[kp["kpis_pulled_at"].notna(), "match_id"])
            out["kpis_to_pull"] = sum(1 for m in matches.loc[matches["available"], "match_id"] if m not in kdone)
        return out
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
    out = {"league": target.label, "fixtures": len(matches), "pulled": len(todo), "rows": n,
           "linked": int(new["player_id"].notna().sum()), "unlinked": int(new["player_id"].isna().sum())}
    if kpi_names is not None:
        # The club's per-game scoring (N21): each new game's KPIs, SkillCorner's per-match
        # physical for the whole league (one call), then the league season re-rated.
        ktodo = to_pull_kpis(engine, target.competition_id, target.season_id)
        kparts = [gsc_parse(api.get(f"/matches/{mid}/player-kpis"), kpi_names) for mid in ktodo]
        knew = pd.concat(kparts, ignore_index=True) if kparts else None
        phys = physical_games(engine, target.competition_id, target.season_id)
        out["club_games_pulled"] = len(ktodo)
        out["club_rows"] = write_club(engine, target.competition_id, target.season_id, knew, ktodo, phys, link)
        out["physical_rows"] = 0 if phys is None else len(phys)
    return out


def gsc_parse(payload: dict, kpi_names: dict) -> pd.DataFrame:
    from lofc.model.game_scoring import parse_player_kpis
    return parse_player_kpis(payload, kpi_names)


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
    kpi_names = {int(k["id"]): k["name"] for k in api.get("/kpis")}
    chosen = [t for t in (settings.impect_targets if args.iteration else targets(settings))
              if args.iteration is None or t.iteration_id == args.iteration]
    for t in chosen:
        print(pull_league(engine, api, t, score_ids, names, dry_run=args.dry_run, kpi_names=kpi_names), flush=True)
    print(f"Impect calls made: {api.calls}")


if __name__ == "__main__":
    main()
