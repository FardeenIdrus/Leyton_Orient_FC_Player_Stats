"""Pull season physical data from the SkillCorner platform API.

This replaces the single squad-only spreadsheet (`ingest/skillcorner.py`) as the
source of physical data. The platform licence covers every player in the covered
leagues, so physical output is available for recruitment TARGETS, not just our own
squad, which is what the club's archetype framework needs.

One file per configured edition (an edition = one league season) under
`data/raw/skillcorner/`, holding one row per player already aggregated to the
season (SkillCorner's group_by=player view: per-match averages plus match counts
and the top-3/top-5 timing benchmarks). Nothing is filtered here; curation to a
scoring subset happens downstream.

Covered leagues (2025/26): Championship, League One, League Two, National League,
PL2, Scottish Premiership, Irish Premier Division. Physical spans 2025/26 + 2026/27
only (no 2024/25), so it joins the 2025/26 rows of our event data.

Idempotent: an edition whose file exists is skipped; --force re-pulls. Credentials
come from SKILLCORNER_USERNAME / SKILLCORNER_PASSWORD in the environment (.env).

Run with:  python -m lofc.ingest.skillcorner_api [--force] [--edition N]
"""

from __future__ import annotations

import argparse

import pandas as pd

from lofc.config import SkillCornerTarget, settings
from lofc.ingest import landing
from lofc.ingest.impect import write_parquet  # shared atomic parquet writer


def skillcorner_root():
    return landing.raw_root() / "skillcorner"


def physical_path(edition_id: int):
    return skillcorner_root() / f"physical_player_season_{edition_id}.parquet"


def _client():
    """Authenticated SkillCorner client, failing loudly if unconfigured."""
    if not settings.skillcorner_authenticated:
        raise SystemExit(
            "SkillCorner credentials missing: set SKILLCORNER_USERNAME and "
            "SKILLCORNER_PASSWORD in .env (containers read .env at start: "
            "`docker compose up -d`)."
        )
    from skillcorner.client import SkillcornerClient
    return SkillcornerClient(username=settings.skillcorner_username,
                             password=settings.skillcorner_password)


def is_live(target: SkillCornerTarget) -> bool:
    """True if this edition is the season currently being played (config.LIVE_SEASON_ID).

    Shares the single definition of "the live season" with the Impect ingest, so the two
    providers can never disagree about which season is still accumulating.
    """
    return settings.live_season_id is not None and target.season_id == settings.live_season_id


def pull_edition(target: SkillCornerTarget, client, force: bool = False) -> bool:
    """Land one edition's season physical data. True if pulled, False if skipped.

    Skip-if-exists is right for a FINISHED season (its data can never change) but wrong for
    the season being played: these are season-to-date aggregates, so a landed file is stale
    as soon as the next round is played. The live season therefore always re-pulls.
    """
    path = physical_path(target.edition_id)
    live = is_live(target)
    refresh = force or live                      # live seasons overwrite; finished ones don't
    if landing.exists(path) and not refresh:
        return False

    # group_by=player returns one season-aggregated row per player.
    try:
        response = client.get_physical(params={"competition_edition": target.edition_id,
                                               "group_by": "player"})
    except Exception as exc:
        # A live edition configured before kick-off (or before SkillCorner has processed any
        # matches) legitimately has nothing yet: skip and try again next run. Every other
        # failure -- and any failure on a season that should already have data -- still raises.
        if live and not landing.exists(path):
            print(f"  [{target.label}] no data yet (season not started): {exc}")
            return False
        raise

    rows = response["results"] if isinstance(response, dict) and "results" in response else response
    frame = pd.json_normalize(rows)
    if frame.empty:
        # Do not persist an empty payload a re-run would then skip forever.
        if live and not landing.exists(path):
            print(f"  [{target.label}] no data yet (season not started); nothing landed")
            return False
        raise RuntimeError(f"SkillCorner returned no rows for {target.label} "
                           f"(edition {target.edition_id}); not persisting.")
    write_parquet(path, frame, force=refresh)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-pull even if files exist")
    parser.add_argument("--edition", type=int, default=None,
                        help="pull one edition id only (must be a configured target)")
    args = parser.parse_args()

    targets = settings.skillcorner_targets
    if args.edition is not None:
        targets = [t for t in targets if t.edition_id == args.edition]
        if not targets:
            raise SystemExit(f"edition {args.edition} is not a configured SkillCorner target")

    client = _client()
    pulled = skipped = 0
    for target in targets:
        if pull_edition(target, client, force=args.force):
            pulled += 1
            frame = pd.read_parquet(physical_path(target.edition_id))
            print(f"  [{target.label}] pulled: {frame['player_id'].nunique()} players, "
                  f"{len(frame.columns)} columns")
        else:
            skipped += 1
            if not is_live(target):
                print(f"  [{target.label}] already present, skipped")
    note = (f" | live season {settings.live_season_id} always re-pulled"
            if any(is_live(t) for t in targets)
            else " | no live season configured (all skip-if-exists)")
    print(f"Done: {pulled} pulled, {skipped} skipped "
          f"({len(targets)} editions under {skillcorner_root()}/){note}")


if __name__ == "__main__":
    main()
