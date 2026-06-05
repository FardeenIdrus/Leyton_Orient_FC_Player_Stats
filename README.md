# Leyton Orient FC — Player Recruitment Intelligence Platform

Turns StatsBomb player data into a ranked shortlist of **affordable, on-profile,
undervalued** signings the Head of Recruitment can act on directly.

This is a *decision* intelligence platform, not a reporting dashboard: the core
deliverable is a valuation + ranking model that produces a judgement not already
in the data, with a thin Streamlit layer on top.

## Status

**Phase 0 (Scaffold) — in progress.** Reproducible skeleton that boots clean.
No business logic yet. Phase plan: Scaffold → Ingest → Aggregate → Store →
Normalise/Score → Archetypes → Valuation → Constrain/Rank → Dashboard → Package.

## Documentation map

- [`plan/LOFC_Recruitment_Platform_Build_Plan.md`](plan/LOFC_Recruitment_Platform_Build_Plan.md) — the brief/spec (**frozen**).
- [`CLAUDE.md`](CLAUDE.md) — project context, auto-loaded into each Claude Code session.
- [`plan/PROJECT_LOG.md`](plan/PROJECT_LOG.md) — living log: decisions, rationale, per-phase progress, AI-workflow note.

## Key decisions

- **Data source:** StatsBomb **free open data** (no credentials). LOFC's own data
  is not on the free tier; ingest is built so the paid API is a config swap later.
- **Demo competitions:** the three complete 2015/16 leagues — Premier League, La
  Liga, Serie A (the only complete men's-club seasons available free). Data vintage
  does not affect the methodology.
- **Cross-league fairness:** metrics are normalised within position **and** within
  league; raw cross-league comparison is a documented future extension.

## Tech stack

Python 3.11 · statsbombpy · pandas/numpy · scikit-learn · PostgreSQL 16 ·
SQLAlchemy + Alembic · Streamlit · Docker / docker-compose · pydantic-settings · pytest.

## Quick start

```bash
cp .env.example .env          # defaults work out of the box (open-data mode)
docker-compose up -d          # brings up Postgres 16 + the app container
docker-compose run --rm app alembic upgrade head   # apply migrations (empty baseline)
docker-compose run --rm app pytest                 # run tests
docker-compose run --rm app python -c "from lofc.config import settings; print(settings)"
```

The app container stays running (`docker-compose ps`); use
`docker-compose exec app ...` or `docker-compose run --rm app ...` to run commands inside it.
