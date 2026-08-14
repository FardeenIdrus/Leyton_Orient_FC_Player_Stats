"""Pull player-season data from the Impect customer API.

Impect is the club's second event-data provider (and per the recruitment team the
intended future primary). This module lands one file per configured iteration
(an iteration = one league season) containing every player's season averages
across Impect's full KPI set, exactly as the API returns them. Nothing is
filtered here: curation to a modelling subset happens downstream, so the landed
file is the full-fidelity record.

Semantics that matter (verified empirically against known season totals):
  - The frame holds one row per player PER POSITION played, not one per player.
  - KPI columns are averages per full-match-equivalent. A season total is
    average * matchShare, summed over the player's position rows (e.g. Ballard,
    League One 25/26: 0.6131 * 37.52 = 23.00 goals, his real golden-boot total).

Idempotent: an iteration whose file exists is skipped; --force re-pulls.
Credentials come from IMPECT_USERNAME / IMPECT_PASSWORD in the environment
(.env), mirroring the StatsBomb setup. Rate limiting is handled by impectPy.

Run with:  python -m lofc.ingest.impect [--force] [--iteration N]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from lofc.config import ImpectTarget, settings
from lofc.ingest import landing


def impect_root() -> Path:
    return landing.raw_root() / "impect"


def iterations_catalogue_path() -> Path:
    return impect_root() / "iterations.json"


def averages_path(iteration_id: int) -> Path:
    return impect_root() / f"player_iteration_averages_{iteration_id}.parquet"


def write_parquet(path: Path, frame: pd.DataFrame, force: bool = False) -> bool:
    """Write a frame as parquet. Return True if written, False if skipped.

    Temp-file + rename, like landing.write_json: an interrupted write can never
    leave a half-written file that the skip check mistakes for complete.
    """
    if landing.exists(path) and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(tmp, index=False)
    tmp.replace(path)
    return True


def _token() -> str:
    """Authenticate against the Impect API, failing loudly if unconfigured."""
    if not settings.impect_authenticated:
        raise SystemExit(
            "Impect credentials missing: set IMPECT_USERNAME and IMPECT_PASSWORD "
            "in .env (containers read .env at start: `docker compose up -d`)."
        )
    import impectPy as ip
    return ip.getAccessToken(settings.impect_username, settings.impect_password)


def is_live(target: ImpectTarget) -> bool:
    """True if this target is the season currently being played (config.LIVE_SEASON_ID)."""
    return settings.live_season_id is not None and target.season_id == settings.live_season_id


def pull_iteration(target: ImpectTarget, token: str, force: bool = False) -> bool:
    """Land one iteration's player averages. Return True if pulled, False if skipped.

    Skip-if-exists is right for a FINISHED season (its data can never change), but wrong for
    the season being played: Impect returns season-to-date aggregates, so a landed file is
    stale as soon as the next round is played. The live season therefore always re-pulls --
    without this, the first in-season pull would silently be the only one.
    """
    path = averages_path(target.iteration_id)
    live = is_live(target)
    refresh = force or live                      # live seasons overwrite; finished ones don't
    if landing.exists(path) and not refresh:
        return False

    import impectPy as ip
    try:
        frame = ip.getPlayerIterationAverages(target.iteration_id, token)
    except Exception as exc:
        # A live season configured before kick-off legitimately has nothing yet: skip it
        # quietly and try again next run. Any other failure -- and any failure on a season
        # that should already have data -- still raises loudly.
        if live and not landing.exists(path):
            print(f"  [{target.label}] no data yet (season not started): {exc}")
            return False
        raise

    if frame.empty:
        # A transient API hiccup must not land an empty file that a re-run
        # would then skip forever (the same guard the StatsBomb ingest has).
        if live and not landing.exists(path):
            print(f"  [{target.label}] no data yet (season not started); nothing landed")
            return False
        raise RuntimeError(f"Impect returned no rows for {target.label} "
                           f"(iteration {target.iteration_id}); not persisting.")
    write_parquet(path, frame, force=refresh)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-pull even if files exist")
    parser.add_argument("--iteration", type=int, default=None,
                        help="pull one iteration id only (must be a configured target)")
    args = parser.parse_args()

    targets = settings.impect_targets
    if args.iteration is not None:
        targets = [t for t in targets if t.iteration_id == args.iteration]
        if not targets:
            raise SystemExit(f"iteration {args.iteration} is not a configured Impect target")

    token = _token()

    # Land the licence's iteration catalogue alongside the data for traceability
    # (which competitions/seasons the account could see at pull time).
    import impectPy as ip
    catalogue = ip.getIterations(token)
    landing.write_json(iterations_catalogue_path(),
                       catalogue.to_dict(orient="records"), force=True)

    pulled = skipped = 0
    for target in targets:
        if pull_iteration(target, token, force=args.force):
            pulled += 1
            frame = pd.read_parquet(averages_path(target.iteration_id))
            print(f"  [{target.label}] pulled: {frame['playerId'].nunique()} players, "
                  f"{len(frame)} position rows, {len(frame.columns)} columns")
        else:
            skipped += 1
            if not is_live(target):
                print(f"  [{target.label}] already present, skipped")
    live_ids = sorted({t.season_id for t in targets if is_live(t)})
    note = (f" | live season {settings.live_season_id} always re-pulled" if live_ids
            else " | no live season configured (all skip-if-exists)")
    print(f"Done: {pulled} pulled, {skipped} skipped "
          f"({len(targets)} iterations under {impect_root()}/){note}")


if __name__ == "__main__":
    main()
