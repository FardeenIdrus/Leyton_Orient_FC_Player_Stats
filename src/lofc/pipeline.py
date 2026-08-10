"""Run the whole pipeline end to end, in order, to populate a fresh database.

  schema -> ingest -> aggregate -> reference data -> load -> score -> archetypes
        -> Transfermarkt download -> valuation -> shortlists

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
    steps: list[tuple[str, list[str]]] = [
        ("Apply database schema", ["alembic", "upgrade", "head"]),
        ("Ingest raw StatsBomb data (slow on first run)", [sys.executable, "-m", "lofc.ingest.run"]),
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

    # 5. Transfermarkt market values (the valuation target).
    if comp_ids & set(LEAGUE_CODE):
        steps.append(("Download Transfermarkt market values",
                      [sys.executable, "-m", "lofc.ingest.transfermarkt"]))
    if comp_ids & EFL_LEAGUE_IDS:
        steps.append(("Pull EFL market values from Transfermarkt",
                      [sys.executable, "-m", "lofc.ingest.transfermarkt_efl"]))

    # 6. Model outputs — read the metric table per SCORING_SOURCE (neutral by default).
    steps += [
        ("Score: percentiles + performance/fit", [sys.executable, "-m", "lofc.model.run"]),
        ("Cluster playing-style archetypes", [sys.executable, "-m", "lofc.model.archetypes"]),
        ("Valuation: fair value + undervaluation", [sys.executable, "-m", "lofc.model.valuation"]),
        ("Identity: link players to Transfermarkt (independent of market value)",
         [sys.executable, "-m", "lofc.model.identity"]),
        # The club 1-5 composite (the live ranking). Must run AFTER valuation and the wage
        # reference data, because the Financial/Resale dimensions read them; and BEFORE the
        # shortlist, which now ranks on the stored objective composite.
        ("Club scorecard: the 1-5 recruitment composite",
         [sys.executable, "-m", "lofc.model.scorecard_run"]),
        ("Build ranked shortlists", [sys.executable, "-m", "lofc.constrain.run"]),
    ]
    return steps


def main() -> None:
    steps = build_steps()
    for i, (label, command) in enumerate(steps, start=1):
        print(f"\n{'=' * 70}\n[{i}/{len(steps)}] {label}\n{'=' * 70}", flush=True)
        result = subprocess.run(command)
        if result.returncode != 0:
            sys.exit(f"\nPipeline stopped: step '{label}' failed (exit {result.returncode}).")
    print("\nPipeline complete. The dashboard at http://localhost:8501 is ready.")


if __name__ == "__main__":
    main()
