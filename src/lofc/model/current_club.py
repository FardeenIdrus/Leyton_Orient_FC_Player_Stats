"""Pipeline step: each player's CURRENT club, from Impect (`player_current_club`).

The club shown everywhere else is the club his stats are from: the squad he played most
minutes for in that league and season. A player who has moved -- in summer, in January, or
between a calendar-year league and a 2026/27 one (Eoin Kenny: rated at Dundalk FC, now at
Portsmouth) -- needs his club now as well. Impect's player list carries `currentSquadId`.

Players are linked to ours through the same route as `position_shares` (`_linked_ids`),
never by minting an id. A club Impect does not name in any season we can see is stored
without a name; the dashboard then adds nothing. Display only: nothing in scoring reads it.

Run with:  python -m lofc.model.current_club
"""

from __future__ import annotations

import json

import pandas as pd

COLUMNS = ["player_id", "impect_squad_id", "club_name"]


def resolve(frames, names: dict[int, str]) -> pd.DataFrame:
    """[(season_id, Impect player list, Impect id -> our player_id)] -> one row per player.

    Where a player appears in several seasons, the latest season's entry is kept (the
    field is the same club in each, but a later list is the fresher one)."""
    parts = []
    for season_id, players, ids in frames:
        if players is None or players.empty or ids is None or ids.empty:
            continue
        p = players.dropna(subset=["currentSquadId"]).copy()
        p["player_id"] = p["id"].map(ids)
        p = p.dropna(subset=["player_id"])
        p["season_id"] = season_id
        parts.append(p)
    if not parts:
        return pd.DataFrame(columns=COLUMNS)
    out = (pd.concat(parts, ignore_index=True)
             .sort_values("season_id", ascending=False)
             .drop_duplicates("player_id"))
    out["player_id"] = out["player_id"].astype("int64")
    out["impect_squad_id"] = out["currentSquadId"].astype("int64")
    out["club_name"] = out["impect_squad_id"].map(names)
    return out[COLUMNS].reset_index(drop=True)


def load_names() -> dict[int, str]:
    from lofc.ingest.impect import squad_names_path
    path = squad_names_path()
    if not path.exists():
        return {}
    return {int(k): v for k, v in json.loads(path.read_text()).items()}


def write(engine, frame: pd.DataFrame) -> int:
    """Replace the whole table: a current club is a fact about now, not about a season."""
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM player_current_club"))
        frame.assign(updated_at=pd.Timestamp.now("UTC").tz_localize(None)).to_sql(
            "player_current_club", conn, if_exists="append", index=False,
            chunksize=20_000, method="multi")
    return len(frame)


def main() -> None:
    from lofc.config import settings
    from lofc.ingest import impect as landing
    from lofc.model.position_shares import _linked_ids
    from lofc.store.load import get_engine

    from lofc.store import runs
    engine = get_engine()
    frames = []

    def one(target) -> int:
        path = landing.players_path(target.iteration_id)
        if not path.exists() or not landing.averages_path(target.iteration_id).exists():
            # The linkage reads the stats file too; without either there is nothing to link.
            print(f"{target.label}: no landed player list or stats; skipped")
            return 0
        ids = _linked_ids(engine, target)
        players = pd.read_parquet(path)
        frames.append((target.season_id, players, ids))
        return len(players)

    failures = runs.for_each_league("Current club", settings.impect_targets,
                                    label=lambda t: t.label,
                                    keys=lambda t: (t.competition_id, t.season_id), fn=one)
    out = resolve(frames, load_names())
    if out.empty:
        # Nothing landed (or every league failed): keep last week's clubs, never wipe them.
        print("Current clubs: nothing to write; previous clubs kept")
        runs.finish_step("Current club", failures)
        return
    n = write(engine, out)
    print(f"Current clubs: {n:,} players, {out['club_name'].notna().sum():,} named")
    runs.finish_step("Current club", failures)


if __name__ == "__main__":
    main()
