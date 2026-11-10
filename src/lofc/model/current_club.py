"""Pipeline step: each player's CURRENT club, from Impect (`player_current_club`).

The club shown everywhere else is the club his stats are from: the squad he played most
minutes for in that league and season. A player who has moved -- in summer, in January, or
between a calendar-year league and a 2026/27 one (Eoin Kenny: rated at Dundalk FC, now at
Portsmouth) -- needs his club now as well. Impect's player list carries `currentSquadId`.

Players are linked to ours through the same route as `position_shares` (`_linked_ids`),
never by minting an id. A club Impect does not name in any season we can see is stored
without a name; the dashboard then adds nothing. Display only: nothing in scoring reads it.

Owner corrections: `src/lofc/reference/current_club_overrides.csv` overrides Impect where its
currentSquadId is stale (Jack Currie, 2026-11-09: "Leyton Orient" in every list, playing for
Oxford United). Applied after `resolve`; an unknown player or a duplicate row fails loudly. A
general "club he played for this season wins" rule was tried and rejected: it sent loanees
with no minutes yet at their new club back to their parent club.

Run with:  python -m lofc.model.current_club
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

COLUMNS = ["player_id", "impect_squad_id", "club_name"]
OVERRIDES = Path(__file__).resolve().parents[1] / "reference" / "current_club_overrides.csv"
OVERRIDE_COLUMNS = ["player_id", "club_name", "impect_squad_id", "note", "added"]


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


def load_overrides(path: Path = OVERRIDES) -> pd.DataFrame:
    """The owner's corrections file. A missing column, a blank club name or a player listed
    twice fails loudly: a correction must never be half-applied or silently ignored."""
    if not Path(path).exists():
        return pd.DataFrame(columns=OVERRIDE_COLUMNS)
    fixes = pd.read_csv(path, dtype={"club_name": str, "note": str, "added": str})
    missing = [c for c in OVERRIDE_COLUMNS if c not in fixes.columns]
    if missing:
        raise ValueError(f"{path}: missing column(s) {missing}")
    if fixes["club_name"].isna().any() or (fixes["club_name"].str.strip() == "").any():
        raise ValueError(f"{path}: every row needs a club_name")
    fixes["player_id"] = fixes["player_id"].astype("int64")
    dup = fixes.loc[fixes["player_id"].duplicated(), "player_id"].tolist()
    if dup:
        raise ValueError(f"{path}: player_id listed more than once: {dup}")
    fixes["club_name"] = fixes["club_name"].str.strip()
    return fixes[OVERRIDE_COLUMNS]


def apply_overrides(frame: pd.DataFrame, fixes: pd.DataFrame,
                    names: dict[int, str] | None = None) -> tuple[pd.DataFrame, int]:
    """Replace the club of each corrected player. A blank impect_squad_id takes Impect's id for
    that exact club name; a name Impect does not know then needs its id in the file. A
    player_id the step did not resolve fails loudly (a typo would otherwise do nothing)."""
    if fixes.empty:
        return frame, 0
    unknown = sorted(set(fixes["player_id"]) - set(frame["player_id"]))
    if unknown:
        raise ValueError(f"current club corrections: unknown player_id(s) {unknown}")
    by_name = {v: k for k, v in (names or {}).items()}
    out = frame.copy().set_index("player_id")
    for fix in fixes.itertuples(index=False):
        squad = fix.impect_squad_id
        if pd.isna(squad):
            if fix.club_name not in by_name:
                raise ValueError(f"current club corrections: no Impect squad named "
                                 f"{fix.club_name!r}; add its impect_squad_id (player {fix.player_id})")
            squad = by_name[fix.club_name]
        out.loc[fix.player_id, "impect_squad_id"] = int(squad)
        out.loc[fix.player_id, "club_name"] = fix.club_name
    out = out.reset_index()[COLUMNS]
    out["impect_squad_id"] = out["impect_squad_id"].astype("int64")
    return out, len(fixes)


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
    names = load_names()
    out, fixed = apply_overrides(resolve(frames, names), load_overrides(), names)
    if out.empty:
        # Nothing landed (or every league failed): keep last week's clubs, never wipe them.
        print("Current clubs: nothing to write; previous clubs kept")
        runs.finish_step("Current club", failures)
        return
    n = write(engine, out)
    print(f"Current clubs: {n:,} players, {out['club_name'].notna().sum():,} named")
    print(f"{fixed} club corrections applied")
    runs.finish_step("Current club", failures)


if __name__ == "__main__":
    main()
