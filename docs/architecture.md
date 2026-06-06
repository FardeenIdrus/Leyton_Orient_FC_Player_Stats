# Architecture

## What this system is

A decision intelligence platform: it turns raw StatsBomb match data into a ranked
shortlist of affordable, on-profile, undervalued signings. The core deliverable is the
valuation and ranking model, not the infrastructure. The infrastructure exists only to
make that model reproducible and to put it in front of a non-technical recruiter.

## The pipeline

```
StatsBomb open data
  1 Ingest      raw events + line-ups, landed on disk, idempotent
  2 Aggregate   events -> one row per player-season, per-90 metrics, per position
  3 Store       metrics + reference data loaded into Postgres
  4 Score       within-position-and-league percentiles -> Performance + Fit scores
  5 Archetypes  k-means on playing style -> a labelled cluster per player
  6 Valuation   Transfermarkt values + Ridge regression -> fair value + undervaluation
  7 Shortlist   affordability (fee + wage) and profile gates -> ranked shortlist
  8 Dashboard   Streamlit app the recruiter actually uses
```

One command runs all of it: `python -m lofc.pipeline`.

## Runtime components (Docker Compose)

| Service | Image | Role |
|---|---|---|
| `db` | postgres:16 | single source of truth (player metrics, scores, reference data, model outputs) |
| `app` | built from `Dockerfile` | runs the pipeline and tests; the Python environment |
| `dashboard` | same image | the Streamlit app at http://localhost:8501 |
| `pgadmin` | dpage/pgadmin4 | optional visual database browser at http://localhost:5050 |
| `metabase` | metabase/metabase | optional BI / self-serve reporting layer at http://localhost:3000 (demonstrates the wider-BI path) |

Everything lifts onto a server as one unit with `docker compose up`.

## Code layout (`src/lofc/`)

- `config.py` — settings via pydantic-settings (database URL, data-source switch, target competitions).
- `ingest/` — `statsbomb.py` (API/open-data access), `landing.py` (idempotent raw I/O), `run.py` (pull orchestrator), `transfermarkt.py` (market-value download).
- `aggregate/` — `events.py` (per-match minutes + metrics), `player_season.py` (season roll-up + per-90), `run.py`.
- `store/` — `models.py` (SQLAlchemy schema), `load.py` (idempotent loaders), `reference_data.py` (builds the wage/identity/wage-estimate stand-ins).
- `model/` — `normalise.py` (percentiles), `score.py` (Performance + Fit), `archetypes.py` (clustering), `valuation.py` (fair value), `run.py` (scoring orchestrator).
- `constrain/` — `filters.py` (affordability + profile gates, ranking), `run.py`.
- `dashboard/app.py` — the Streamlit front end.
- `pipeline.py` — runs every stage end to end.

## Data model (Postgres)

| Table | Grain | Filled by |
|---|---|---|
| `players` | one per player | Phase 3 (+ birth date backfilled in Phase 6) |
| `player_season_metrics` | player x league x season | Phase 2/3 |
| `wage_framework` | position x age band | reference data |
| `wage_estimates` | position x age x performance tier | reference data |
| `identity_profiles` | position x metric | reference data |
| `player_percentiles` | player x metric | Phase 4 |
| `player_scores` | player x season | Phase 4 |
| `archetypes` | player x season | Phase 5 |
| `valuations` | player x season | Phase 6 |
| `shortlists` | player x season | Phase 7 |

Schema is defined in `store/models.py` and versioned with Alembic migrations.

## Data flow into the dashboard

The dashboard reads `player_scores`, `valuations`, `archetypes`, `player_percentiles`,
`wage_framework` and `wage_estimates`, then calls the Phase 7 filter (`constrain/filters.py`)
live with the budget and wage sliders. Nothing is precomputed for a fixed budget; moving a
slider re-runs the filter against the stored model outputs.

## Tech choices (and why)

- **Python + pandas/numpy/scikit-learn** — named in the brief; the right tools for aggregation, regression and clustering.
- **PostgreSQL** — structured player-season data is a few thousand rows; SQL is on the JD; one store is enough.
- **Streamlit** — ships the model and UI as one deployable app, readable by a non-technical user, no licensing tie to the club server.
- **Docker + Alembic + pydantic-settings** — reproducible, versioned, credentials out of code.

Tools deliberately left out of v1 (MongoDB, MinIO, Power BI/Tableau) and the conditions
that would justify adding them are documented in `scaling.md`.

## Reproducibility

- `docker compose up` brings up the whole stack.
- `python -m lofc.pipeline` populates a fresh database end to end (idempotent).
- Alembic migrations recreate the schema; `requirements.lock` pins exact dependency versions.
- Raw data and model outputs are reproducible from source, so they are gitignored.
