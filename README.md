# Leyton Orient FC — Player Recruitment Intelligence Platform

Turns event and physical data into a ranked shortlist of **affordable, undervalued** signings,
scored on **Leyton Orient's own recruitment framework**. It is a *decision* intelligence
platform, not a reporting dashboard: the core deliverable is a scoring and ranking model that
produces a judgement not already in the data, with a clean Streamlit layer on top. It runs end
to end as one Docker stack.

> **New to the project?** Read [`plan/BUILD_PLAN.md`](plan/BUILD_PLAN.md) first — it is the
> master plan and documentation map (current state, where every doc lives, what's next).

## What it does

For every player, across 7 leagues, the platform computes per-90 metrics, ranks them into
percentiles within position and league, and scores each player **1–5 on the club's framework**
(the metrics, thresholds and dimension weights come straight from the club's own documents).
Each player gets a **composite** score; the shortlist ranks by it and layers on market value,
modelled wages, and affordability gates. A themed dashboard lets a recruiter drill into
profiles, compare players, and see exactly how every score is built.

- **Performance** data → **Impect** · **Physical** data → **SkillCorner** · **Market values** →
  **Transfermarkt**.
- Leagues: the EFL (Championship, League One, League Two, National League), the Scottish
  Premiership & Championship, and Premier League 2.

## Quick start

```bash
cp .env.example .env                 # then add the provider credentials (see below)
docker compose up -d                 # starts Postgres + app + dashboard + pgAdmin + Metabase
docker compose exec app python -m lofc.pipeline   # populate the database end to end
```

Then open the dashboard at **http://localhost:8501**.

> The first `pipeline` run downloads the data and takes a while; it is idempotent, so
> re-running is fast and safe (data already on disk is skipped). Every command is also listed,
> with comments, in [`cli_commands.txt`](cli_commands.txt).

## Signing in

The dashboard sits behind a login gate. Accounts are created by an administrator:

```bash
docker compose exec app python -m lofc.admin create-user --username fi --name "..." --role scout
```

There is **no self-service sign-up**. A forgotten password is reset by an administrator in
person (`python -m lofc.admin set-password --username fi`) — the accounts table holds no email
address, so there is no email-based reset link to send. `list-users` shows every account and
whether it is currently locked out, and `deactivate-user`/`reactivate-user` block or restore
sign-in. **Accounts are never deleted** — every assessment stays attributed to whoever made it.
An administrator can do all of this from the browser too, on the **Users** page (Admin section
of the sidebar, visible only to the `admin` role) — the CLI and the page call the same
underlying code, so the two can never disagree on the rules.

## The pipeline

`python -m lofc.pipeline` runs all stages in order, each idempotent:

```
schema → ingest (Impect + SkillCorner) → aggregate → reference data → load
       → build combined 91-metric table → Transfermarkt values → score
       → archetypes → valuation → shortlists
```

Players are then ranked on the club **1–5 composite**, computed by a pipeline stage and stored
in `player_scorecards`, so the dashboard, the offline shortlist and the BI layer all read the
same numbers. You can run any stage on its own (see `cli_commands.txt`).

## Dashboard tabs

The sidebar groups the ten pages into **Scouting**, **Assessment**, **Analysis**,
**Reference**, and — for administrators only — **Admin**.

- **Players** — the one decision workspace: a composite-ranked list and, on click or search,
  the full player detail (bio, dimension scores, the club-framework grand table of
  metric → percentile → 1–5 band, charts on the club's own metrics, and a **"Current form"**
  section showing the live season's minutes/goals/assists as plain facts once it exists, never
  as a rating). Merged from the former Shortlist + Club scorecard + Player profile tabs.
  **Money is opt-in** — market value, modelled wages and the affordability gates appear only
  when "Show affordability" is ticked, and never reorder the default ranking. An opt-in
  **"Rank on assessed composite"** toggle (off by default) switches the ranking to the
  scout-assessed composite for players who have one.
- **Compare** — two or three players head-to-head on the club's Performance metrics, plus a
  raw physical table (raw because physical output *is* comparable across leagues).
- **Watchlist · Player types · Physical** — saved targets, playing-style groups, tracking data.
- **Assess** — the scout-assessment form: the club's own criteria for that player's position,
  Psychological scored 1–5 per criterion, Medical entered as a band with an injury and
  availability evidence panel beside it. Injury data informs the judgement; it never becomes
  the score.
- **Sign-off** — the approval queue for the Head of Recruitment/admin: sign off an assessment,
  **reject** one (an optional reason — it stays on the record and the scout can resubmit),
  enter and sign off your own, or leave it. Where two scouts' assessments disagree, none of
  them scores until one of those actions resolves it.
- **Users** *(Admin only)* — list every account, create one, reset a password, clear a
  lockout, or deactivate/reactivate. Accounts are never deleted, so every past assessment
  stays attributed.
- **Glossary** — searchable definitions for every metric (Impect's own wording; substitutes
  labelled honestly).
- **Methodology** — how the pipeline works, step by step, including a worked example of the
  1–5 composite.

## Interfaces

- **Dashboard** — http://localhost:8501
- **pgAdmin** — http://localhost:5050 (visual database browser; password `lofc`)
- **Metabase (BI)** — http://localhost:3000 (self-serve reporting over the same database)
- **psql / SQL** — `docker compose exec db psql -U lofc -d lofc`

## Documentation

The master plan and full documentation map is [`plan/BUILD_PLAN.md`](plan/BUILD_PLAN.md).
Key deep-dives:

- [`docs/architecture.md`](docs/architecture.md) — the system: pipeline stages, which file
  does what, data flow, dashboard tabs.
- [`docs/methodology.md`](docs/methodology.md) — the scoring method: percentiles, the club
  1–5 composite, and the design decisions.
- [`docs/DATA_ARCHITECTURE.md`](docs/DATA_ARCHITECTURE.md) — the 91-metric layer: the four data
  sources and per-metric provenance.
- [`docs/scaling.md`](docs/scaling.md) — scaling considerations and the wider-BI growth path.
- [`plan/HISTORY.md`](plan/HISTORY.md) — the frozen build log (the rationale behind past
  decisions).

## Deployment

`docker compose up` is the whole stack, so deploying is running it on a server. See
[`DEPLOY.md`](DEPLOY.md) for a production setup (Caddy for HTTPS, database and admin tools
kept internal — the dashboard's own login gate handles authentication) and a quick tunnel
option for a demo link. **Deployment has not happened yet** — the platform has only run
locally so far. This branch (with the login gate) is well ahead of `main`, which has none; do
not deploy `main` as-is.

## Tech stack

Python 3.11 · Impect / SkillCorner / Transfermarkt clients · pandas / numpy / scikit-learn ·
PostgreSQL 16 · SQLAlchemy + Alembic · Streamlit + Plotly · Docker / docker compose ·
pydantic-settings · pytest.

## Data and credentials

The platform runs on **licensed data** — Impect (event), SkillCorner (physical) and
Transfermarkt (market values). Provider credentials go in `.env`; target leagues/seasons are
configured in `src/lofc/config.py`. **Licensed feeds and the club's confidential documents
(`docs/*.xlsx`, `*.docx`) are gitignored and never published.** Modelled inputs (wages, and —
until the club's real files land — parts of the framework) are clearly labelled and swappable
for real club data via drop-in CSVs in `data/reference/`.

## Tests

```bash
docker compose exec app python -m pytest -q
docker compose exec app python -m pytest --cov=lofc --cov-report=term-missing
```
