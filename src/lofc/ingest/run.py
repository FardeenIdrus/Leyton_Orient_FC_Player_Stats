"""Pull raw StatsBomb data for the configured competitions and land it on disk.

Resumable and idempotent: matches whose events and lineups are already saved are
skipped, so an interrupted run continues where it stopped and a re-run is fast.

Usage:
  python -m lofc.ingest.run                  # all configured competitions
  python -m lofc.ingest.run --competition 2  # one competition only (by competition_id)
  python -m lofc.ingest.run --limit 5        # first 5 matches only (quick test)
  python -m lofc.ingest.run --force          # re-pull even if files already exist
"""

from __future__ import annotations

import argparse

from lofc.config import Competition, settings
from lofc.ingest import landing, statsbomb


def pull_competition(comp: Competition, limit: int | None = None, force: bool = False) -> tuple[int, int]:
    """Pull and land one competition. Return (matches_pulled, matches_skipped)."""
    cid, sid = comp.competition_id, comp.season_id

    matches = statsbomb.get_matches(cid, sid)
    landing.write_json(landing.matches_path(cid, sid), matches, force=force)

    matches = sorted(matches, key=lambda m: m["match_id"])
    if limit:
        matches = matches[:limit]

    pulled = skipped = 0
    total = len(matches)
    for i, match in enumerate(matches, start=1):
        mid = match["match_id"]
        ev_path = landing.events_path(cid, sid, mid)
        lu_path = landing.lineups_path(cid, sid, mid)

        # Only skip when both payloads are present, so a part-pulled match is redone.
        if landing.exists(ev_path) and landing.exists(lu_path) and not force:
            skipped += 1
        else:
            events = statsbomb.get_events(mid)
            # A transient API hiccup can return an empty list; saving it would make
            # the gap permanent (idempotent skip). Leave it missing so a re-run retries.
            if not events:
                print(f"  [{comp.label}] WARNING: match {mid} returned no events, will retry next run")
                continue
            landing.write_json(ev_path, events, force=force)
            landing.write_json(lu_path, statsbomb.get_lineups(mid), force=force)
            pulled += 1

        if i % 50 == 0 or i == total:
            print(f"  [{comp.label}] {i}/{total} matches (pulled={pulled} skipped={skipped})")

    return pulled, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="Pull raw StatsBomb data into data/raw/")
    parser.add_argument("--competition", type=int, help="only this competition_id")
    parser.add_argument("--limit", type=int, help="only the first N matches (quick test)")
    parser.add_argument("--force", action="store_true", help="re-pull even if files exist")
    args = parser.parse_args()

    print(f"Data source: {statsbomb.data_source()}")

    # Land the competitions list once (small, shared across competitions).
    landing.write_json(landing.competitions_path(), statsbomb.get_competitions(), force=args.force)

    comps = settings.competitions
    if args.competition:
        comps = [c for c in comps if c.competition_id == args.competition]
        if not comps:
            raise SystemExit(f"competition_id {args.competition} is not in the configured list")

    for comp in comps:
        print(f"Pulling {comp.label} (competition_id={comp.competition_id}, season_id={comp.season_id})")
        pulled, skipped = pull_competition(comp, limit=args.limit, force=args.force)
        print(f"Done {comp.label}: {pulled} pulled, {skipped} already present")


if __name__ == "__main__":
    main()
