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

    comp_ids = {c.competition_id for c in settings.competitions}
    steps: list[tuple[str, list[str]]] = [
        ("Apply database schema", ["alembic", "upgrade", "head"]),
        ("Ingest raw StatsBomb data (slow on first run)", [sys.executable, "-m", "lofc.ingest.run"]),
        ("Aggregate to player-season metrics", [sys.executable, "-m", "lofc.aggregate.run"]),
        ("Generate club reference data", [sys.executable, "-m", "lofc.store.reference_data"]),
        ("Load metrics + reference data into Postgres", [sys.executable, "-m", "lofc.store.load"]),
        ("Score: percentiles + performance/fit", [sys.executable, "-m", "lofc.model.run"]),
        ("Cluster playing-style archetypes", [sys.executable, "-m", "lofc.model.archetypes"]),
    ]
    from lofc.ingest.skillcorner import source_file
    if source_file() is not None:
        steps.append(("Load SkillCorner tracking data (club-provided)",
                      [sys.executable, "-m", "lofc.ingest.skillcorner"]))
    if comp_ids & set(LEAGUE_CODE):
        steps.append(("Download Transfermarkt market values",
                      [sys.executable, "-m", "lofc.ingest.transfermarkt"]))
    if comp_ids & EFL_LEAGUE_IDS:
        steps.append(("Pull EFL market values from Transfermarkt",
                      [sys.executable, "-m", "lofc.ingest.transfermarkt_efl"]))
    steps += [
        ("Valuation: fair value + undervaluation", [sys.executable, "-m", "lofc.model.valuation"]),
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
