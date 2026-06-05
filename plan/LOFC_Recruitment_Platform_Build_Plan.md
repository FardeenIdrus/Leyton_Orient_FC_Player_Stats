# Leyton Orient FC — Player Recruitment Intelligence Platform

## Build Plan and Claude Code Brief

This document is the build brief. It is written to be handed to Claude Code and executed phase by phase. Each phase has concrete tasks and acceptance criteria. Do not skip ahead: each phase produces a working, testable slice before the next begins.

---

## 1. Objective

Build an end-to-end platform that turns StatsBomb player data into a ranked shortlist of affordable, on-profile, undervalued signings that the Head of Recruitment can act on directly.

Input: raw StatsBomb match and event data.
Output: a dashboard giving ranked shortlists by position, archetype profiles, valuation flags, and player comparisons, with every recommendation filtered against a wage budget and an identity profile.

The hard deliverable is the valuation and ranking model, not the infrastructure. Build lean, document the scaling path, and keep the modelling honest (statistics where statistics is correct, machine learning only where it earns its place).

---

## 2. What this is, and what it is not

This is a decision intelligence platform, not a reporting dashboard. Traditional Business Intelligence describes what happened (goals, attendance, revenue). This system recommends a future action: which players to sign. That distinction drives every design choice below. The recruitment core is a model that produces a judgement that was not already in the data, with a presentation layer on top, not a presentation layer over data that already holds the answer.

---

## 3. Tech stack and reasoning

| Layer | Choice | Reason |
|---|---|---|
| Language | Python 3.11+ | Named in the JD. Ecosystem for data and modelling. |
| Data source | `statsbombpy` | Official StatsBomb Python library. Pulls competitions, matches, events. |
| Data handling | pandas, numpy | Aggregation of event data to player-season metrics. |
| Modelling | scikit-learn | Regression for valuation, k-means for archetypes, scaling and percentile logic. |
| Store | PostgreSQL 16 | Single source of truth. Structured player metrics, wage framework, identity profiles, model outputs. SQL is on the JD. JSONB column holds raw payloads where needed. |
| Dashboard | Streamlit | Ships model and interface as one deployable app. Fast to build, readable for a non-technical user, no licensing dependency on the LOFC server. |
| Packaging | Docker, docker-compose | Reproducible, lifts onto the LOFC server as one unit. JD calls out server deployment. |
| Migrations | Alembic | Versioned schema. Keeps the database reproducible alongside the code. |
| Config | pydantic-settings, .env | Credentials and parameters out of code. |
| Testing | pytest | Unit tests on aggregation and model logic. |

### Deliberately excluded from v1 (document, do not build)

- **MongoDB** — the working dataset is player-season metrics, a few thousand structured rows, not big data. StatsBomb returns JSON but it aggregates down to structured numbers. A Postgres JSONB column covers any raw-JSON need. A second database is operational cost for no v1 benefit.
- **MinIO / object storage** — solves a scaling problem not yet present. Raw pulls sit fine on the filesystem or in Postgres for a single-club build. This is a multi-league, multi-club decision, not a day-one one.
- **Power BI / Tableau / Metabase** — visualisation layers over an existing data model. They do not build the valuation model, which is the core deliverable. A BI tool is a later bolt-on for commercial reporting, not the recruitment engine.

The narrative for the interview: these tools are known and were used on a prior project; the judgement call was to keep v1 lean with a documented path to add them when data volume justifies it.

---

## 4. Pipeline (end to end)

```
StatsBomb API
  -> [1] Ingest        raw match + event JSON, landed and auditable
  -> [2] Aggregate     event data rolled up to player-season metrics, per position
  -> [3] Store         metrics + wage framework + identity profiles into Postgres
  -> [4] Normalise     each metric to percentile / z-score within position
  -> [5] Score + value performance/fit score AND fair-value estimate
  -> [6] Constrain     filter and rank vs wage budget + identity profile
  -> [7] Serve         Streamlit dashboard: shortlists, archetypes, comparisons
  -> [8] Deploy        Docker, one reproducible unit, onto LOFC server
```

One line: raw StatsBomb data in, a ranked list of affordable players who fit the brief out.

---

## 5. Repository structure

```
lofc-recruitment/
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── README.md
├── pyproject.toml
├── alembic/
│   └── versions/
├── src/
│   └── lofc/
│       ├── config.py            # settings, env loading
│       ├── ingest/
│       │   ├── statsbomb.py      # API pulls via statsbombpy
│       │   └── landing.py        # write/read raw payloads
│       ├── aggregate/
│       │   ├── events.py         # event -> player-match metrics
│       │   └── player_season.py  # -> player-season, per position
│       ├── store/
│       │   ├── models.py         # SQLAlchemy ORM
│       │   ├── schema.sql        # reference DDL
│       │   └── load.py           # upserts
│       ├── model/
│       │   ├── normalise.py      # within-position percentile / z-score
│       │   ├── score.py          # performance + archetype-fit score
│       │   ├── valuation.py      # fair-value regression, undervaluation flag
│       │   └── archetypes.py     # k-means clustering
│       ├── constrain/
│       │   └── filters.py        # wage + identity filtering and ranking
│       └── dashboard/
│           └── app.py            # Streamlit
├── tests/
│   ├── test_aggregate.py
│   ├── test_normalise.py
│   └── test_valuation.py
├── data/
│   ├── raw/                      # landed payloads (gitignored)
│   └── reference/                # wage framework, identity docs (provided by club)
└── docs/
    ├── architecture.md
    ├── methodology.md
    └── scaling.md                # Mongo/MinIO/BI path documented here
```

---

## 6. Data model (Postgres, v1 sketch)

Refine against the real StatsBomb fields and the club's provided documents during Phase 1. Indicative tables:

- `players` — player_id (PK), name, primary_position, age, current_club, nationality.
- `player_season_metrics` — player_id (FK), season, competition, minutes, per-90 metrics (goals, xG, assists, xA, progressive passes, pressures, tackles, etc.), position group. One row per player-season-position.
- `wage_framework` — position group, age band, wage band ceiling. Provided by club. Drives affordability.
- `identity_profiles` — position group, required attributes and thresholds. Provided by club. Drives fit.
- `valuations` — player_id, season, fair_value_estimate, undervaluation_score, model_version, run_timestamp.
- `archetypes` — player_id, season, cluster_id, cluster_label, distance_to_centroid.
- `shortlists` — generated output: position group, player_id, composite_score, affordable (bool), on_profile (bool), rank, run_timestamp.

Store raw StatsBomb payloads in a `raw_events` table with a JSONB column if a relational landing is preferred over filesystem.

---

## 7. Modelling methodology

This is the part the CEO is testing. Spell it out clearly in `docs/methodology.md`.

**Normalisation within position.** A metric is meaningless across positions. Convert each per-90 metric to a percentile rank (or z-score) within its position group. A striker is judged against strikers, a full-back against full-backs.

**Performance and archetype-fit score.** A weighted composite of the normalised metrics that matter for that position group, with weights informed by the club's identity profile rather than assumed uniformly. Output: a single comparable score per player within position.

**Archetypes.** k-means on the normalised metric set within a position group, producing clusters (e.g. for forwards: poacher, target man, pressing forward). Label clusters from their centroids. Lets recruitment search by playing style, not just raw output.

**Valuation.** Regress a value proxy on performance metrics to estimate a fair cost for a given performance level. Players whose performance sits well above their estimated cost (or market value) are the undervalued targets. The undervaluation score is the residual: actual value below model-implied value.

Keep it honest: percentile ranking and regression do the core work. scikit-learn earns its place on the valuation regression and the clustering. Do not reach for deep learning where regression and clustering are the correct tools, and say so if asked.

---

## 8. Dashboard specification (Streamlit)

The Head of Recruitment reads this directly, with no code knowledge.

- **Position selector.** Pick a position group, get a ranked shortlist of affordable, on-profile, undervalued players.
- **Shortlist view.** Table: player, club, age, composite score, fair-value vs market, affordable flag, on-profile flag. Sortable, filterable.
- **Player profile.** Single-player view: percentile bars per metric within position, archetype label, valuation flag.
- **Comparison view.** Two or three players side by side on the same percentile axes.
- **Constraint controls.** Adjustable wage ceiling and minimum thresholds so a recruiter can explore "what if" without touching code.

Design for clarity over decoration. The test is whether a non-technical recruiter can go from opening the app to a defensible shortlist in under a minute.

---

## 9. Phased build plan

Each phase ends in a working, testable state. Do not begin a phase before the previous one's acceptance criteria pass.

### Phase 0 — Scaffold
Tasks: repo structure, pyproject, Dockerfile, docker-compose (Python service + Postgres), .env.example, config loader, Alembic init, README skeleton.
Acceptance: `docker-compose up` brings up Python and Postgres; config loads from .env; `alembic upgrade head` runs clean on an empty schema.

### Phase 1 — Ingest
Tasks: connect via statsbombpy with provided credentials; pull competitions, matches, events for target leagues; land raw payloads under `data/raw/` (or `raw_events` JSONB). Make pulls repeatable and idempotent.
Acceptance: a documented command pulls one competition's events end to end; re-running does not duplicate; raw data is inspectable.

### Phase 2 — Aggregate
Tasks: event-to-player-match metrics, then player-season metrics per position group; per-90 normalisation of counting stats; handle minutes thresholds (exclude tiny samples).
Acceptance: a player-season metrics table is produced for the pulled competition; unit tests on aggregation logic pass; spot-check a known player against StatsBomb figures.

### Phase 3 — Store
Tasks: SQLAlchemy models, Alembic migration for the full schema, upsert loaders for metrics; load the club's wage framework and identity profiles from `data/reference/`.
Acceptance: metrics, wage framework and identity profiles are queryable in Postgres; loaders are idempotent; schema matches `docs/architecture.md`.

### Phase 4 — Normalise and score
Tasks: within-position percentile/z-score; position-weighted composite performance score; persist to tables.
Acceptance: every player has a within-position percentile per metric and a composite score; tests confirm a top performer scores near the top of its position group.

### Phase 5 — Archetypes
Tasks: k-means per position group; choose k with a defensible method (elbow/silhouette); label clusters from centroids; persist.
Acceptance: each player has a cluster and a human-readable label; labels are sensible on inspection.

### Phase 6 — Valuation
Tasks: fair-value regression on performance; undervaluation score as the residual; persist with model version.
Acceptance: model runs and stores valuations; undervalued players surface sensibly; methodology written up in `docs/methodology.md`.

### Phase 7 — Constrain and rank
Tasks: filter candidates against wage ceiling and identity thresholds; produce the final ranked shortlist per position; persist to `shortlists`.
Acceptance: every shortlisted player is affordable and on-profile; ranking is reproducible from stored data.

### Phase 8 — Dashboard
Tasks: build the Streamlit app per Section 8; wire to Postgres; add constraint controls.
Acceptance: a non-technical user can select a position and read a shortlist; profile and comparison views work; constraint sliders update results live.

### Phase 9 — Package and document
Tasks: finalise Docker so the whole stack deploys as one unit; complete `architecture.md`, `methodology.md`, `scaling.md` (Mongo/MinIO/BI path); README with run instructions.
Acceptance: a fresh clone runs end to end with `docker-compose up` plus a documented ingest-to-dashboard sequence; docs are complete.

---

## 10. AI-native workflow note

The JD states they test for fluent use of AI tools. Build this with Claude Code as the primary workflow and keep a short running note of where it accelerated the build and where it had to be corrected. That note is concrete evidence for the interview, worth more than any claim.

---

## 11. Build order summary

0 Scaffold → 1 Ingest → 2 Aggregate → 3 Store → 4 Normalise/Score → 5 Archetypes → 6 Valuation → 7 Constrain/Rank → 8 Dashboard → 9 Package/Document.

Start at Phase 0. Confirm each acceptance criterion before moving on.
