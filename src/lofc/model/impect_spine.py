"""Build a player-season identity spine from Impect data ALONE.

For leagues where we hold no StatsBomb data (Scottish Premiership/Championship, PL2),
Impect is the only source, so it must supply the identity the StatsBomb spine normally
provides: player_id, player_name, team, position_group, minutes, rankable. This module
produces that same schema from a translated Impect iteration, so build_neutral can treat
an Impect-spined league exactly like a StatsBomb-spined one — the whole point of the
source-neutral spine.

Player identity — the dangerous part, handled two ways:
  - REUSE: a player already in our database (a loanee/transfer we saw in the EFL, e.g.
    Adama Sidibeh appears in both a Scottish league and League One) is tied to their
    EXISTING player_id via the same six-stage matcher the metric layer uses. Getting
    this wrong splits one footballer into two (a first-name vs full-name mismatch, e.g.
    "Joe" vs "Joseph", at scale).
  - MINT: a genuinely new player gets a deterministic id in a reserved range
    (IMPECT_ID_OFFSET + Impect playerId). Deterministic so re-runs and multi-league
    appearances always resolve to the SAME id; offset so it can never collide with
    StatsBomb's id space (StatsBomb ids are < ~10^7).

Read-only: returns DataFrames; the caller decides what to persist.
"""

from __future__ import annotations

import pandas as pd

from lofc.ingest.impect_map import IMPECT_MAP
from lofc.model.impect_check import load_overrides, match_to_ours, unique_league_name_index

# Impect's 10 position codes -> our 8 position groups (dominant position by matchShare).
IMPECT_POSITION_GROUPS: dict[str, str] = {
    "GOALKEEPER": "Goalkeeper",
    "CENTRAL_DEFENDER": "Centre Back",
    "LEFT_WINGBACK_DEFENDER": "Full Back",
    "RIGHT_WINGBACK_DEFENDER": "Full Back",
    "DEFENSE_MIDFIELD": "Defensive Mid",
    "CENTRAL_MIDFIELD": "Central Mid",
    "ATTACKING_MIDFIELD": "Attacking Mid",
    "LEFT_WINGER": "Winger",
    "RIGHT_WINGER": "Winger",
    "CENTER_FORWARD": "Centre Forward",
}

# Reserved id range for players we hold ONLY via Impect (no StatsBomb identity).
IMPECT_ID_OFFSET = 2_000_000_000

IMPECT_METRIC_COLS = [m.name for m in IMPECT_MAP if m.kind != "none"]

SPINE_COLS = ["player_id", "competition_id", "season_id", "player_name",
              "team_name", "position_group", "minutes", "rankable"]


def attach_identity(translated: pd.DataFrame, ours: pd.DataFrame,
                    league_name_index: dict[str, int] | None = None,
                    overrides: pd.DataFrame | None = None) -> pd.DataFrame:
    """Add our player_id (reused or minted), position_group and matched_via.

    `translated` is a translate_target frame (Impect metrics + identity, keyed by the
    Impect `playerId`). Returns the same rows plus player_id / position_group.
    """
    result = match_to_ours(translated.assign(tm_player_id=pd.NA), ours,
                           league_name_index=league_name_index, overrides=overrides)
    minted = IMPECT_ID_OFFSET + result["playerId"].astype("int64")
    result["matched_via"] = result["matched_via"].where(result["player_id"].notna(), "minted")
    result["player_id"] = result["player_id"].fillna(minted).astype("int64")
    result["position_group"] = result["position"].map(IMPECT_POSITION_GROUPS).fillna("Unknown")
    return result


def build_spine(translated: pd.DataFrame, ours: pd.DataFrame,
                league_name_index: dict[str, int] | None = None,
                overrides: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(spine, impect_metrics) for one Impect-spined league season.

    spine: the identity schema (SPINE_COLS). impect_metrics: the 41 Impect metric
    columns keyed by our player_id, ready to merge like any other Impect frame. Both
    are de-duplicated to one row per player_id (dominant row = most minutes), so a
    player who somehow lands twice cannot fan out the join.
    """
    ident = attach_identity(translated, ours, league_name_index, overrides)
    ident = ident.sort_values("minutes", ascending=False).drop_duplicates("player_id")

    spine = ident[SPINE_COLS].copy()
    metrics = ident[["player_id"] + [c for c in IMPECT_METRIC_COLS if c in ident.columns]].copy()
    return spine, metrics


def new_players(spine: pd.DataFrame, translated: pd.DataFrame,
                ours_ids: set[int]) -> pd.DataFrame:
    """Rows to INSERT into the players table for minted (Impect-only) players.

    A minted player_id not already in `ours_ids` needs a players row so downstream
    joins (scores, dashboard names) resolve. Birth date comes from the translated frame.
    """
    minted = spine[~spine["player_id"].isin(ours_ids)][["player_id", "player_name"]].copy()
    if minted.empty:
        return minted.assign(birth_date=pd.NaT)
    # birth_date per minted id: recover the Impect playerId (id - offset) and look it up.
    bd = (translated.assign(_pid=IMPECT_ID_OFFSET + translated["playerId"].astype("int64"))
                    .drop_duplicates("_pid").set_index("_pid")["birth_date"])
    minted["birth_date"] = minted["player_id"].map(bd)
    return minted
