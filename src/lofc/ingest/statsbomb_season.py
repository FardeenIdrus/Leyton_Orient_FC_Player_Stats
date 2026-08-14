"""Pull StatsBomb Season Player Stats for the metrics Impect does not have.

Impect covers most of the club's framework, but a handful of StatsBomb-specific
metrics have no Impect equivalent (confirmed via Impect's KPI-definitions API):
possession-adjusted tackles/interceptions and pressures, aggressive actions,
pressures in the opposition half, xG buildup, pressured-pass %, box-cross %,
dribble volume/success, goalkeeper claims, goalkeeper aggressive distance, and
long-ball %. Impect has dribble VALUE (PxT) but no dribble count, and has no
goalkeeper positioning or claims KPIs at all.

These live in StatsBomb's Season Player Stats endpoint (the `API SB Helper.pdf`
) as ready-made per-90 values. Unlike our event-based aggregate, we do
not compute these; we take them from the endpoint. This is the StatsBomb side of
the provider-neutral layer: it fills only the gaps Impect leaves.

Two things make this simple: the endpoint returns one row per player already
per-90, and its player_id IS our player_id (both are StatsBomb ids), so there is
no matching step. Landed one file per league season under
`data/raw/statsbomb_season/`.

Idempotent: an existing file is skipped; --force re-pulls. Needs the paid
StatsBomb API (USE_OPEN_DATA=false + SB_USERNAME/PASSWORD).

Run with:  python -m lofc.ingest.statsbomb_season [--force]
"""

from __future__ import annotations

import argparse

import pandas as pd

from lofc.config import Competition, settings
from lofc.ingest import landing

# our internal name -> the StatsBomb Season-Player-Stats column. All are already
# per-90 (or a 0..1 ratio), so translation is a straight rename.
STATSBOMB_GAP_MAP: dict[str, str] = {
    "pressures_opp_half_p90": "player_season_fhalf_pressures_90",
    "aggressive_actions_p90": "player_season_aggressive_actions_90",
    "padj_tackles_interceptions_p90": "player_season_padj_tackles_and_interceptions_90",
    "padj_pressures_p90": "player_season_padj_pressures_90",
    "xg_buildup_p90": "player_season_xgbuildup_90",
    "pressured_pass_pct": "player_season_pressured_passing_ratio",
    "successful_box_cross_pct": "player_season_box_cross_ratio",
    "dribbles_p90": "player_season_total_dribbles_90",
    "dribble_success_pct": "player_season_dribble_ratio",
    "gk_claims_pct": "player_season_clcaa",
    "gk_aggressive_distance": "player_season_da_aggressive_distance",
    "long_ball_pct": "player_season_long_ball_ratio",
}


def statsbomb_season_root():
    return landing.raw_root() / "statsbomb_season"


def stats_path(competition_id: int, season_id: int):
    return statsbomb_season_root() / f"player_season_stats_{competition_id}_{season_id}.parquet"


def pull_competition(comp: Competition, force: bool = False) -> bool:
    """Land one league season's player-season stats. True if pulled, False if skipped."""
    from lofc.ingest.impect import write_parquet  # shared atomic parquet writer
    path = stats_path(comp.competition_id, comp.season_id)
    if landing.exists(path) and not force:
        return False
    if not settings.statsbomb_authenticated:
        raise SystemExit("The Season Player Stats endpoint needs the paid StatsBomb API "
                         "(USE_OPEN_DATA=false + SB_USERNAME/PASSWORD in .env).")
    from statsbombpy import sb
    frame = sb.player_season_stats(competition_id=comp.competition_id,
                                   season_id=comp.season_id,
                                   creds={"user": settings.sb_username,
                                          "passwd": settings.sb_password})
    if frame.empty:
        raise RuntimeError(f"StatsBomb returned no season stats for {comp.label}; not persisting.")
    write_parquet(path, frame, force=force)
    return True


def translate_frame(frame: pd.DataFrame, competition_id: int, season_id: int) -> pd.DataFrame:
    """Select + rename the gap metrics, one row per player, keyed by league + season.

    player_id is the StatsBomb id, which is our players.player_id, so this joins
    downstream with no matching. The endpoint splits a mid-season mover into one
    row per club, whereas we hold one combined row per player-league-season, so
    per-90 values are recombined as a MINUTES-WEIGHTED mean across a player's rows
    (exact for per-90 counts; a fair approximation for the two ratios). Missing
    columns (older endpoint payloads) fill NaN.
    """
    frame = frame.copy()
    frame["_min"] = pd.to_numeric(frame["player_season_minutes"], errors="coerce").fillna(0.0)
    pid = frame["player_id"]

    out = pd.DataFrame({"player_id": frame["player_id"].drop_duplicates().to_numpy()})
    out = out.set_index("player_id")
    for internal, sb_col in STATSBOMB_GAP_MAP.items():
        if sb_col in frame.columns:
            value = pd.to_numeric(frame[sb_col], errors="coerce")
            weighted = (value * frame["_min"]).groupby(pid).sum()      # skips NaN
            weight = frame["_min"].where(value.notna()).groupby(pid).sum()
            out[internal] = weighted / weight.replace(0, pd.NA)
        else:
            out[internal] = pd.NA
    out = out.reset_index()
    out["competition_id"] = competition_id
    out["season_id"] = season_id
    return out


def translate_competition(comp: Competition) -> pd.DataFrame:
    frame = pd.read_parquet(stats_path(comp.competition_id, comp.season_id))
    return translate_frame(frame, comp.competition_id, comp.season_id)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-pull even if files exist")
    args = parser.parse_args()

    pulled = skipped = 0
    for comp in settings.competitions:
        if pull_competition(comp, force=args.force):
            pulled += 1
            n = len(pd.read_parquet(stats_path(comp.competition_id, comp.season_id)))
            print(f"  [{comp.label}] pulled: {n} players")
        else:
            skipped += 1
            print(f"  [{comp.label}] already present, skipped")
    print(f"Done: {pulled} pulled, {skipped} skipped "
          f"({len(settings.competitions)} league seasons under {statsbomb_season_root()}/)")


if __name__ == "__main__":
    main()
