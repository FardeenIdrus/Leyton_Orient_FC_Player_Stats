"""Pipeline step: minutes per CLUB, per player, per league-season (`impect_squad_minutes`).

`player_metrics_neutral` holds one row per player per league-season: his minutes in the league
and the club he played MOST for. A January mover therefore shows at one club, with the minutes
of both. Impect's averages file -- already landed by `ingest.impect` -- holds one row per player
x squad x position with the `squadId`, so the minutes at each club are on disk. No API call.

Players are linked to ours through `position_shares._linked_ids`, the linkage build_neutral and
current_club use; an id is never minted here. DISPLAY ONLY: the Squads & loans page reads it,
nothing in scoring does.

Run with:  python -m lofc.model.squad_minutes              (every landed league-season)
           python -m lofc.model.squad_minutes --season 319 (one season)
"""

from __future__ import annotations

import pandas as pd

from lofc.ingest.impect_map import IMPECT_POSITION_GROUPS

COLUMNS = ["player_id", "impect_squad_id", "team_name", "competition_id", "season_id",
           "minutes", "position_group"]
_PER = ["playerId", "squadId", "squadName", "minutes", "position_group"]


def per_squad(frame: pd.DataFrame) -> pd.DataFrame:
    """One row per (Impect playerId, squadId): minutes there (playDuration / 60, summed over his
    positions) and the position group he played most minutes in AT THAT CLUB. A position
    Impect adds later, with no group mapping, counts towards minutes but names no group."""
    if frame.empty:
        return pd.DataFrame(columns=_PER)
    df = frame[["playerId", "squadId", "squadName", "position", "playDuration"]].copy()
    df["minutes"] = df["playDuration"] / 60.0
    df["group"] = df["position"].map(IMPECT_POSITION_GROUPS)
    keys = ["playerId", "squadId"]
    out = df.groupby(keys, as_index=False).agg(squadName=("squadName", "first"),
                                               minutes=("minutes", "sum"))
    by_group = (df.dropna(subset=["group"]).groupby(keys + ["group"], as_index=False)["minutes"]
                  .sum().sort_values("minutes", ascending=False).drop_duplicates(keys))
    out = out.merge(by_group[keys + ["group"]].rename(columns={"group": "position_group"}),
                    on=keys, how="left")
    return out[_PER]


def link(per: pd.DataFrame, ids: pd.Series, competition_id: int, season_id: int) -> pd.DataFrame:
    """`per_squad` keyed by OUR player_id (`ids`: Impect playerId -> player_id). Unlinked Impect
    players are dropped. Two Impect records of one player at one club are summed; the position
    is the one of the record with more minutes there."""
    if per.empty or ids is None or ids.empty:
        return pd.DataFrame(columns=COLUMNS)
    d = per.assign(player_id=per["playerId"].map(ids)).dropna(subset=["player_id"])
    if d.empty:
        return pd.DataFrame(columns=COLUMNS)
    d["player_id"] = d["player_id"].astype("int64")
    d = d.sort_values("minutes", ascending=False)
    out = d.groupby(["player_id", "squadId"], as_index=False, sort=False).agg(
        team_name=("squadName", "first"), minutes=("minutes", "sum"),
        position_group=("position_group", "first"))
    out = out.rename(columns={"squadId": "impect_squad_id"})
    out["impect_squad_id"] = out["impect_squad_id"].astype("int64")
    out["competition_id"] = int(competition_id)
    out["season_id"] = int(season_id)
    out = out.sort_values(["impect_squad_id", "minutes"], ascending=[True, False])
    return out[COLUMNS].reset_index(drop=True)


def collect(engine, target) -> pd.DataFrame:
    """Minutes per club for one landed Impect target, keyed by our player_id."""
    from lofc.ingest import impect as landing
    from lofc.model.position_shares import _linked_ids
    path = landing.averages_path(target.iteration_id)
    if not path.exists():
        return pd.DataFrame(columns=COLUMNS)
    ids = _linked_ids(engine, target)
    frame = pd.read_parquet(path, columns=["playerId", "squadId", "squadName", "position",
                                           "playDuration"])
    return link(per_squad(frame), ids, target.competition_id, target.season_id)


def write(engine, frame: pd.DataFrame, competition_id: int, season_id: int) -> int:
    """Clear-then-insert one league-season (the pattern of every derived table)."""
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM impect_squad_minutes WHERE competition_id = :c "
                          "AND season_id = :s"), {"c": competition_id, "s": season_id})
        if len(frame):
            frame[COLUMNS].assign(updated_at=pd.Timestamp.now("UTC").tz_localize(None)).to_sql(
                "impect_squad_minutes", conn, if_exists="append", index=False,
                chunksize=20_000, method="multi")
    return len(frame)


def pick_targets(targets, season_id: int | None):
    return [t for t in targets if season_id is None or t.season_id == season_id]


def main(argv=None) -> None:
    import argparse
    from lofc.config import settings
    from lofc.ingest import impect as landing
    from lofc.store import runs
    from lofc.store.load import get_engine

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--season", type=int, default=None, help="one season_id only (e.g. 319)")
    args = ap.parse_args(argv)
    engine = get_engine()
    totals = {"rows": 0}

    def one(target) -> int:
        if not landing.averages_path(target.iteration_id).exists():
            print(f"  {target.label}: no landed averages file; skipped (previous rows kept)")
            return 0
        frame = collect(engine, target)
        if frame.empty:
            # Nothing linked (or an empty file): keep the previous rows, never wipe them.
            print(f"  {target.label}: nothing linked; previous rows kept")
            return 0
        n = write(engine, frame, target.competition_id, target.season_id)
        movers = int((frame.groupby("player_id").size() > 1).sum())
        print(f"  {target.label}: {n:,} player-club rows, {frame['impect_squad_id'].nunique()} "
              f"clubs, {movers} players at two clubs or more")
        totals["rows"] += n
        return n

    failures = runs.for_each_league("Squad minutes", pick_targets(settings.impect_targets,
                                                                  args.season),
                                    label=lambda t: t.label,
                                    keys=lambda t: (t.competition_id, t.season_id), fn=one)
    print(f"impect_squad_minutes: {totals['rows']:,} rows written")
    runs.finish_step("Squad minutes", failures)


if __name__ == "__main__":
    main()
