"""Run the whole pipeline end to end, in order, to populate a fresh database.

  schema -> ingest -> aggregate -> reference data -> load -> score -> archetypes
        -> Transfermarkt download -> valuation -> identity -> injuries -> shortlists

Every step is idempotent, so re-running is safe. After it finishes, the dashboard at
http://localhost:8501 is fully populated.

Run with:  python -m lofc.pipeline
"""

from __future__ import annotations

import subprocess
import sys

def build_steps() -> list[tuple[str, list[str]]]:
    """The pipeline stages, with the market-value pull matched to the configured era."""
    from lofc.config import settings
    from lofc.model.valuation import EFL_LEAGUE_IDS, LEAGUE_CODE

    from lofc.ingest.skillcorner import source_file

    comp_ids = {c.competition_id for c in settings.competitions}

    # Dependency order matters: scoring + valuation read the metric table named by
    # SCORING_SOURCE (the neutral table by default), so the neutral table MUST be built
    # before the model steps — not after them (the pre-Phase-A order, which only worked
    # because scoring then read the StatsBomb spine directly).

    # 1. Spine: raw StatsBomb -> aggregated player-season metrics, loaded into Postgres.
    #
    # SKIPPED ENTIRELY UNDER `impect_only`. These three stages exist only to rebuild
    # `player_season_metrics` from raw StatsBomb events, and under impect_only every league
    # -- the EFL included -- is spined on Impect instead (see build_neutral's job list:
    # "so StatsBomb is not needed at all"). Verified: all 39 metrics the club composite uses
    # come from Impect (32) and SkillCorner (7), and the neutral table's EFL minutes match
    # the StatsBomb spine on 1 row in 2,940 -- they are Impect's numbers, not StatsBomb's.
    #
    # Leaving them in was invisible here, where data/raw already holds the files and the
    # ingest is skip-if-exists. On a machine without them -- a fresh server -- the ingest
    # would attempt ~8,900 paid API calls across 4,456 matches for 21 GB of events nothing
    # reads, and the aggregation raises FileNotFoundError if they are absent, halting the
    # whole run before the Impect pull, the scrapes or the scorecard rebuild.
    #
    # `player_season_metrics` itself is NOT dropped: archetypes, the profile's trajectory and
    # the methodology page still read that TABLE (register P3/P6). They read what is already
    # stored; none of them needs the raw events. This is the pipeline half of register R4.
    steps: list[tuple[str, list[str]]] = [
        ("Apply database schema", ["alembic", "upgrade", "head"]),
    ]
    if not settings.impect_only:
        steps += [
            ("Ingest raw StatsBomb data (slow on first run)",
             [sys.executable, "-m", "lofc.ingest.run"]),
            ("Aggregate to player-season metrics", [sys.executable, "-m", "lofc.aggregate.run"]),
            ("Generate club reference data", [sys.executable, "-m", "lofc.store.reference_data"]),
            ("Load metrics + reference data into Postgres", [sys.executable, "-m", "lofc.store.load"]),
        ]

    # 2. Club-provided SkillCorner squad export (feeds the Physical tab; independent).
    if source_file() is not None:
        steps.append(("Load SkillCorner tracking data (club-provided)",
                      [sys.executable, "-m", "lofc.ingest.skillcorner"]))

    # 3. Provider pulls for the neutral layer (each conditional on its credentials).
    # The StatsBomb advanced-stats pull is skipped in Impect-only mode: the EFL is then
    # Impect-spined, so its 12 advanced metrics are never joined (scoring uses Impect
    # successors). Base StatsBomb ingest above still runs — it seeds player IDENTITY
    # (stable ids, birth dates, league names) while the licence is live; only at licence
    # end does identity seeding move to Impect too (the final retirement step).
    if settings.statsbomb_authenticated and not settings.impect_only:
        steps.append(("Pull StatsBomb season stats (advanced metrics)",
                      [sys.executable, "-m", "lofc.ingest.statsbomb_season"]))
    if settings.impect_authenticated:
        steps.append(("Pull Impect player data",
                      [sys.executable, "-m", "lofc.ingest.impect"]))
        steps.append(("Pull Impect KPI definitions (official glossary)",
                      [sys.executable, "-m", "lofc.ingest.impect_definitions"]))
    if settings.skillcorner_authenticated:
        steps.append(("Pull SkillCorner physical data (platform)",
                      [sys.executable, "-m", "lofc.ingest.skillcorner_api"]))

    # 4. Build the combined neutral metric table (needs the spine + the provider pulls).
    steps.append(("Build the combined neutral metric table (87 metrics/player)",
                  [sys.executable, "-m", "lofc.model.build_neutral", "--write"]))
    # How each player's minutes split across position groups. Must run AFTER
    # build_neutral: it reuses that module's linkage, and its rows carry a foreign key to
    # `players`, where build_neutral registers the Impect-only (minted) identities.
    # DISPLAY ONLY -- the assigned position group and every score are untouched.
    steps.append(("Position shares: minutes per position group (display only)",
                  [sys.executable, "-m", "lofc.model.position_shares"]))
    # Playing-style signals (model/styles.py): attempts, shares and zones from the same
    # landed Impect files, linked through the same identities. LABELS ONLY -- never scoring.
    steps.append(("Style signals: playing-style labels (display only)",
                  [sys.executable, "-m", "lofc.model.style_run"]))
    # Each player's club NOW (Impect currentSquadId), for "Dundalk FC · now FC Portsmouth".
    # Same linkage as the two steps above. DISPLAY ONLY.
    steps.append(("Current club: where each player is now (display only)",
                  [sys.executable, "-m", "lofc.model.current_club"]))

    # 5. Transfermarkt market values (the valuation target).
    if comp_ids & set(LEAGUE_CODE):
        steps.append(("Download Transfermarkt market values",
                      [sys.executable, "-m", "lofc.ingest.transfermarkt"]))
    # The SCRAPE stages. Skipped on a server (`SKIP_TRANSFERMARKT_SCRAPE=true`): Transfermarkt
    # sits behind AWS WAF Bot Control and serves a datacentre IP a JavaScript challenge rather
    # than content -- see config.skip_transfermarkt_scrape for the full finding. The loaders
    # below (store.squads, store.injuries) are NOT skipped, so CSVs pushed from a workstation
    # are still ingested. Without this the pipeline halts here on a server and nothing after
    # it -- scoring, scorecards, shortlists -- ever runs.
    if comp_ids & EFL_LEAGUE_IDS and not settings.skip_transfermarkt_scrape:
        steps.append(("Pull squad bio + market values from Transfermarkt (7 leagues)",
                      [sys.executable, "-m", "lofc.ingest.transfermarkt_efl"]))
        # Who is on loan at each club, from whom, until when. Transfermarkt is the ONLY
        # source: Impect carries no registration data at all. Reads a different page per
        # club than the squad scrape, so it is its own stage; ~6 min for 147 clubs.
        steps.append(("Pull loan players from Transfermarkt (parent club + loan end)",
                      [sys.executable, "-m", "lofc.ingest.transfermarkt_loans"]))

    # The squad LOADER, deliberately outside the scrape block above: it reads the CSV rather
    # than fetching it, so it must still run on a server that cannot scrape -- that is how a
    # refresh pushed from a workstation reaches the database. Loads the snapshot into Postgres
    # so the DASHBOARD reads a table, not a file on this machine's disk. Must run after
    # transfermarkt_efl where that stage runs at all.
    if comp_ids & EFL_LEAGUE_IDS:
        steps.append(("Squads: load the Transfermarkt squad snapshot into Postgres",
                      [sys.executable, "-m", "lofc.store.squads"]))
        # Loans, the same way (TASKS 2.3): the Mac's loan scrape writes loans.csv, the file
        # is pushed with the squads file, and this loads it. Without it a re-scrape reached
        # only the Mac's database.
        steps.append(("Loans: load the Transfermarkt loan snapshot into Postgres",
                      [sys.executable, "-m", "lofc.store.loans"]))

    # 6. Model outputs — read the metric table per SCORING_SOURCE (neutral by default).
    steps += [
        ("Score: percentiles + performance/fit", [sys.executable, "-m", "lofc.model.run"]),
        ("Cluster playing-style archetypes", [sys.executable, "-m", "lofc.model.archetypes"]),
        ("Valuation: fair value + undervaluation", [sys.executable, "-m", "lofc.model.valuation"]),
        ("Identity: link players to Transfermarkt (independent of market value)",
         [sys.executable, "-m", "lofc.model.identity"]),
        # Loads the scraped Transfermarkt injury history (Medical dimension input). Must run
        # AFTER Identity: the loader joins on players.tm_player_id, which Identity populates.
        # Prints a clean message and returns without writing anything if injuries.csv has
        # never been scraped, so the pipeline stays runnable on a machine that has never run
        # lofc.ingest.transfermarkt_injuries.
        ("Injuries: load the Transfermarkt injury history (skipped if not scraped)",
         [sys.executable, "-m", "lofc.store.injuries"]),
        # foot + nationality, each from its own declared source order (foot: Transfermarkt
        # then Impect; nationality: Impect then Transfermarkt). Gap-fill only -- a stored
        # value is never overwritten. Must run AFTER Identity, which establishes the
        # tm_player_id the Transfermarkt side keys on.
        ("Player bio: fill foot + nationality from the best source for each",
         [sys.executable, "-m", "lofc.model.player_bio"]),
        # The club 1-5 composite (the live ranking). Must run AFTER valuation and the wage
        # reference data, because the Financial/Resale dimensions read them; and BEFORE the
        # shortlist, which now ranks on the stored objective composite.
        ("Club scorecard: the 1-5 recruitment composite",
         [sys.executable, "-m", "lofc.model.scorecard_run"]),
        ("Build ranked shortlists", [sys.executable, "-m", "lofc.constrain.run"]),
    ]
    return steps


def main() -> None:
    """Run every step. A step whose league-by-league work had a failing league exits
    runs.PARTIAL_EXIT: the run carries on (the failed league keeps last week's data) and
    finishes as partial, naming the leagues. Any other failure stops the run -- the steps
    after it would build on wrong data. Every step is recorded in `pipeline_runs`."""
    import datetime as dt
    import os
    from lofc.store import runs

    run_id = os.environ.get(runs.RUN_ID_ENV) or runs.new_run_id()
    env = {**os.environ, runs.RUN_ID_ENV: run_id}
    steps = build_steps()
    partial = False
    print(f"Pipeline run {run_id}", flush=True)
    for i, (label, command) in enumerate(steps, start=1):
        print(f"\n{'=' * 70}\n[{i}/{len(steps)}] {label}\n{'=' * 70}", flush=True)
        started = dt.datetime.utcnow()
        result = subprocess.run(command, env=env)
        if result.returncode == 0:
            runs.record(step=label, status="success", started_at=started, run_id=run_id)
        elif result.returncode == runs.PARTIAL_EXIT:
            partial = True
            runs.record(step=label, status="partial", started_at=started, run_id=run_id)
        else:
            runs.record(step=label, status="failed", started_at=started, run_id=run_id,
                        error=f"exit {result.returncode}")
            sys.exit(f"\nPipeline stopped: step '{label}' failed (exit {result.returncode}).")
    if partial:
        failed = runs.failed_leagues(run_id)
        print("\nPipeline finished with failed leagues (they keep last week's data):\n  "
              + "\n  ".join(failed or ["(see pipeline_runs for this run)"]))
        sys.exit(runs.PARTIAL_EXIT)
    print("\nPipeline complete. The dashboard at http://localhost:8501 is ready.")


if __name__ == "__main__":
    main()
