"""How each player's minutes split across position groups, per league season.

The platform assigns ONE position group per player-season -- the group he played most --
and scores him against that group's peers. For most players that is the whole story. For a
utility player it is not: measured on the live Impect files, 668 of 6,575 rankable
player-seasons (10.2%) are assigned a group holding under half their minutes, and 219
(3.3%) under 40%. Luka Lynch reads as a Full Back on 38.6% of his minutes while 61.4% were
spent in attacking roles, split four ways.

Impect reports one row per player per position, so the split is a fact the platform
already held and threw away at aggregation. This module keeps it, so a report can show the
split instead of presenting one label as the whole truth.

DISPLAY ONLY. Nothing here feeds scoring, percentiles or the ranking -- the assigned
position group is unchanged and still comes from impect_translate.dominant_position.

Read-only except for `load`, which clear-then-inserts one league season at a time.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import text

from lofc.ingest.impect_map import IMPECT_POSITION_GROUPS

COLUMNS = ["playerId", "position_group", "minutes", "share", "goals", "assists"]
# Impect ships each KPI as a per-90 rate on the position row; count = rate x matchShare.
COUNT_COLUMNS = {"GOALS": "goals", "ASSISTS": "assists"}


def shares_from_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Minutes and share per position GROUP, one row per (playerId, group).

    Rows come out largest-share first: a report reads the first row as "his position", so
    the order carries meaning. An Impect position with no group mapping is kept as
    "Unknown" rather than dropped -- dropping it would renormalise the rest to sum to 1
    and hide the gap.
    """
    if frame.empty:
        return pd.DataFrame(columns=COLUMNS)

    df = frame[["playerId", "position", "playDuration"]].copy()
    df["position_group"] = df["position"].map(IMPECT_POSITION_GROUPS).fillna("Unknown")
    df["minutes"] = df["playDuration"] / 60.0

    # Counts per position, where the source carries them. A source WITHOUT the column
    # leaves the value NaN, never 0: "we do not know" and "he scored none here" are
    # different claims and a report must not print the second when it means the first.
    have = [c for c in COUNT_COLUMNS if c in frame.columns and "matchShare" in frame.columns]
    for src in have:
        df[COUNT_COLUMNS[src]] = frame[src] * frame["matchShare"]

    agg = ["minutes"] + [COUNT_COLUMNS[c] for c in have]
    out = (df.groupby(["playerId", "position_group"], as_index=False)[agg].sum())
    for name in COUNT_COLUMNS.values():
        if name not in out.columns:
            out[name] = pd.NA
    total = out.groupby("playerId")["minutes"].transform("sum")
    # A player with no recorded time has no split to report, and dividing would be a
    # zero-division rather than a 0% share.
    out = out[total > 0].copy()
    if out.empty:
        return pd.DataFrame(columns=COLUMNS)
    out["share"] = out["minutes"] / total[out.index]
    return (out.sort_values(["playerId", "share"], ascending=[True, False])
               [COLUMNS].reset_index(drop=True))


def _linked_ids(engine, target) -> pd.Series | None:
    """Impect playerId -> our player_id, for one target.

    The linkage is NOT re-derived here. It comes from the same two functions the metric
    build uses, so a player's position split can never attach to a different identity
    than his metrics did:

      - StatsBomb-spined leagues (the four English): build_neutral.load_impect, which
        matches through impect_check.match_to_ours.
      - Impect-spined leagues (Scottish x2, PL2, and every 2026/27 target):
        impect_spine.attach_identity, which REUSES an existing player_id where the player
        is already known and mints one only where he is not.

    Computing IMPECT_ID_OFFSET + playerId directly would be wrong -- it would invent a
    second identity for every Scottish player already held under a StatsBomb id.
    """
    from lofc.ingest.impect_translate import translate_target
    from lofc.model.build_neutral import load_impect
    from lofc.model.impect_check import load_overrides
    from lofc.model.impect_spine import attach_identity

    if target.sb_competition_id is not None:
        linked = load_impect(engine, target.sb_competition_id, target.sb_season_id)
    else:
        ours = pd.read_sql(
            "SELECT player_id, player_name, birth_date, tm_player_id FROM players", engine)
        linked = attach_identity(translate_target(target), ours, None, load_overrides())
    if linked is None or linked.empty:
        return None
    linked = linked.dropna(subset=["player_id"]).drop_duplicates("playerId")
    return linked.set_index("playerId")["player_id"].astype("int64")


def collect(engine, target) -> pd.DataFrame:
    """Position shares for one target, keyed by OUR player_id. Empty if unavailable."""
    from lofc.ingest import impect as impect_landing

    path = impect_landing.averages_path(target.iteration_id)
    if not path.exists():
        return pd.DataFrame()
    ids = _linked_ids(engine, target)
    if ids is None:
        return pd.DataFrame()

    shares = shares_from_frame(pd.read_parquet(path))
    shares["player_id"] = shares["playerId"].map(ids)
    shares = shares.dropna(subset=["player_id"])
    if shares.empty:
        return pd.DataFrame()

    # Two Impect records can map to one of our players (a duplicate in their feed). Sum
    # the minutes, then RENORMALISE -- otherwise the shares would sum above 1.
    out = (shares.groupby(["player_id", "position_group"], as_index=False)
                 [["minutes", "goals", "assists"]].sum(min_count=1))
    out["share"] = out["minutes"] / out.groupby("player_id")["minutes"].transform("sum")
    out["player_id"] = out["player_id"].astype("int64")
    out["competition_id"] = target.competition_id
    out["season_id"] = target.season_id
    return out.sort_values(["player_id", "share"], ascending=[True, False])


def load(engine, shares: pd.DataFrame, competition_id: int, season_id: int) -> int:
    """Clear-then-insert one league season, mirroring build_neutral.write_for."""
    cols = ["player_id", "competition_id", "season_id", "position_group", "minutes",
            "share", "goals", "assists"]
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM player_position_shares WHERE "
                          "competition_id = :c AND season_id = :s"),
                     {"c": competition_id, "s": season_id})
        if shares.empty:
            return 0
        shares[cols].to_sql("player_position_shares", conn, if_exists="append", index=False)
    return len(shares)


def main() -> None:
    from lofc.config import settings
    from lofc.store.load import get_engine

    engine = get_engine()
    total = 0
    for target in settings.impect_targets:
        shares = collect(engine, target)
        if shares.empty:
            print(f"  (skipped {target.label}: no data)")
            continue
        n = load(engine, shares, target.competition_id, target.season_id)
        players = shares["player_id"].nunique()
        print(f"  {target.label}: {players} players, {n} position rows")
        total += n
    print(f"position shares loaded: {total} rows")


if __name__ == "__main__":
    main()
