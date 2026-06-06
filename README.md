# Leyton Orient FC — Player Recruitment Intelligence Platform

Turns StatsBomb match data into a ranked shortlist of **affordable, on-profile,
undervalued** signings a Head of Recruitment can act on directly.

This is a *decision* intelligence platform, not a reporting dashboard. The core deliverable
is a valuation and ranking model that produces a judgement not already in the data, with a
clean Streamlit layer on top. It runs end to end as one Docker stack.

## What it does

Raw StatsBomb events in → for every player: per-90 metrics, a Performance score and a Fit
score (ranked within position and league), a playing-style archetype, a fair-value estimate
and undervaluation flag, filtered against a transfer budget and a wage ceiling → a ranked
shortlist a recruiter reads in a themed dashboard.

## Quick start

```bash
cp .env.example .env                 # defaults work out of the box (free open-data mode)
docker compose up -d                 # starts Postgres + app + dashboard + pgAdmin
docker compose exec app python -m lofc.pipeline   # populate the database end to end
```

Then open the dashboard at **http://localhost:8501**.

> The first `pipeline` run downloads the raw data (~2.6 GB of events plus Transfermarkt
> values) and takes roughly 20-40 minutes. It is idempotent, so re-running is fast and safe.
> Every command is also listed, with comments, in [`cli_commands.txt`](cli_commands.txt).

## The pipeline

`python -m lofc.pipeline` runs all stages in order, each idempotent:

```
schema → ingest → aggregate → reference data → load → score → archetypes
       → Transfermarkt download → valuation → shortlists
```

You can also run any stage on its own (see `cli_commands.txt`).

## Interfaces

- **Dashboard** — http://localhost:8501 (position selector, ranked shortlist, player profiles
  with percentile charts, side-by-side comparison, live budget/wage sliders, methodology tab).
- **pgAdmin** — http://localhost:5050 (visual database browser; the LOFC server is pre-listed,
  password `lofc`).
- **psql / SQL** — `docker compose exec db psql -U lofc -d lofc`.

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — components, pipeline, data model, tech choices.
- [`docs/methodology.md`](docs/methodology.md) — the modelling: normalisation, scoring, archetypes, valuation, and the honest assumptions.
- [`docs/scaling.md`](docs/scaling.md) — what was left out of v1 (MongoDB, MinIO, BI tools) and when to add it; the wider-BI growth path.
- [`plan/BUILD_PLAN.md`](plan/BUILD_PLAN.md) — the full phase-by-phase build plan and decisions.

## Tech stack

Python 3.11 · statsbombpy · pandas / numpy / scikit-learn · PostgreSQL 16 ·
SQLAlchemy + Alembic · Streamlit + Plotly · Docker / docker compose · pydantic-settings · pytest.

## Data and credentials

Runs on **free StatsBomb open data** (2015/16 Premier League, La Liga, Serie A) — the only
complete men's-club seasons on the free tier. Leyton Orient's own division is not free, so this
demonstrates the method; pointing it at the club's real, current data is a credentials and
config change (`USE_OPEN_DATA`, `SB_*` in `.env`, target competitions in `config.py`), not a
rewrite. Wages and the club identity profile are clearly-labelled modelled stand-ins, swappable
for the club's real documents in `data/reference/`.

## Tests

```bash
docker compose exec app pytest -q
docker compose exec app pytest --cov=lofc --cov-report=term-missing
```
