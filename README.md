# Leyton Orient FC — Player Recruitment Intelligence Platform

> **What this is.** A decision platform for the club's recruitment staff: Impect event data and
> SkillCorner physical data → every player rated **1–5 on Leyton Orient's own framework**, plus
> Transfermarkt contracts, squads, loans and injuries, and the club's scouting sheet.
> **Live** at https://lofc-recruitment.duckdns.org (the new web front end) and in daily use.
> **Current focus:** correctness and clarity of the live site; retiring the old Streamlit site
> (still on a fallback address). What is open: [`plan/TASKS.md`](plan/TASKS.md).

## What it does

For every player in **25 leagues** (the EFL, Scotland, Premier League 2, Ireland and 18 more
licensed Impect competitions; registry in `src/lofc/leagues.py`) the platform computes per-90
metrics, ranks them into percentiles **within league, season and position**, and turns them into
a 1–5 rating on the club's metrics, thresholds and weights. The ranking is
`objective_composite` (Performance + Physical); scout input never changes it.

| Data | Provider | How it arrives |
|---|---|---|
| Event (Performance) | **Impect** | API, weekly refresh |
| Physical (tracking) | **SkillCorner** | API, weekly refresh |
| Contracts, squads, loans, injuries, market values | **Transfermarkt** | Scraped on the Mac only (the server is blocked), pushed to the server |
| Scout reports | Club's scouting Google Sheet | Read-only sync every minute |

How the rating works: [`docs/methodology.md`](docs/methodology.md).

## The site

Sign in at the live address. Pages, as grouped in the navigation rail:

| Group | Page | What it is |
|---|---|---|
| Find | **Players** | The ranked list (season, position, leagues, Rank as, more filters, metric filters) and the player card |
| Find | **Squads & loans** | Every registered squad member: contract, loan, minutes, rating |
| Assess a player | **Compare** | Up to three players of one position, side by side; remembers the last comparison; download |
| Assess a player | **Scout reports** | The club's scouting sheet beside each player's rating; Data vs scout and Squad role filters |
| Decide | **Watchlist** | Tracked targets with form, injury, contract and rating |
| Decide | **Report** | One-page player report: one wide sheet, downloads made in the browser (authored or data-only), photo, availability rows, scout verdicts, drafts kept in that browser; search lists every player A–Z |
| Decide | Assess · Sign-off | Show "Currently building" on the new site; still on the old site |
| Analysis | **Physical** | SkillCorner leaders, Two metrics chart, Leyton Orient squad (Physical \| Performance, Excel download) |
| Analysis | **Club vs League One** | Where Orient fall short of a top-6 League One side, and who could close the gap |
| Reference | What goes into each rating · How playing styles work · Glossary | The rules and definitions, in the providers' words |
| Admin | **Users** | Accounts (admins only) |

Every list page remembers its last settings in that browser; the top bar shows when Impect and
SkillCorner were last pulled.

## Signing in

Real accounts only: scrypt-hashed passwords (12-character minimum), lockout after 5 failed
attempts, a throttle against password-spraying, 12-hour sessions in a signed cookie
(`SESSION_SECRET` is required; the web app refuses to start without it). No self-service
sign-up or email reset; an administrator creates and resets accounts, from the Users page or:

```bash
docker compose exec app python -m lofc.admin create-user --username <name> --name "..." --role scout
docker compose exec app python -m lofc.admin set-password --username <name>
```

Roles: `scout`, `medical`, `head_of_recruitment`, `admin`. Accounts are never deleted, only
deactivated, so every assessment stays attributed.

## Run it locally (Mac)

```bash
cp .env.example .env                   # provider credentials + SESSION_SECRET
docker compose up -d db app web        # Postgres, the pipeline/test container, the web site
```

Open **http://localhost:8600** (the web site; reloads on save). The old Streamlit dashboard is
the `dashboard` service on :8501, kept only while the fallback address exists.

**Do not build the local database from the providers.** Resync it from the server first
(command in [`DEPLOY.md`](DEPLOY.md) → "Two machines"): the server refreshes twice a week, the
Mac never does. Mac load limits, tests and the browser harness: [`DEPLOY.md`](DEPLOY.md) →
"Working on the Mac".

## The pipeline

`python -m lofc.pipeline` runs every stage in order; each is idempotent and recorded in
`pipeline_runs`. On the server it runs from cron (Monday and Thursday 04:15 UTC). The live
season is re-pulled in full each run; finished seasons are re-pulled once their files are 30
days old, so provider corrections to past matches are picked up.

```
schema → Impect pull + KPI definitions → SkillCorner pull
       → combined metric table → position shares → style signals → current club
       → Transfermarkt squad + loan loaders → percentiles → valuation → identity
       → injuries → player bio → club scorecard (1–5) → shortlists
```

Stage by stage: [`docs/architecture.md`](docs/architecture.md). Commands:
[`cli_commands.txt`](cli_commands.txt).

## Tests

```bash
docker compose exec -T app nice -n 15 python -m pytest -q     # Python suite, in Docker
node --test tests/js/                                          # JS rule tests, on the Mac
```

Browser harness for the web pages: `scripts/web_check.py` (see [`docs/frontend.md`](docs/frontend.md)).

## Documentation

| File | Purpose |
|---|---|
| [`plan/TASKS.md`](plan/TASKS.md) | What is open, in order (Now / Next / Parked / Done) |
| [`plan/BUILD_PLAN.md`](plan/BUILD_PLAN.md) | Register of known problems + dated work log |
| [`docs/architecture.md`](docs/architecture.md) | How the system is built: sources, pipeline, code, tables |
| [`docs/methodology.md`](docs/methodology.md) | How players are scored |
| [`docs/frontend.md`](docs/frontend.md) | How the web front end is built and tested |
| [`DEPLOY.md`](DEPLOY.md) | The live server, schedules, backups, deploying, the Mac workflow |
| [`cli_commands.txt`](cli_commands.txt) | The command for each stage |
| [`plan/HISTORY.md`](plan/HISTORY.md) | Frozen log of earlier decisions (the *why*) |

## Tech stack

Python 3.11 · FastAPI + Jinja2 + plain JavaScript (ES modules, no build step) · pandas / numpy /
scikit-learn · PostgreSQL 16 · SQLAlchemy + Alembic · Docker Compose · Caddy (HTTPS) ·
pytest, Playwright (browser harness), node:test. The old site: Streamlit + Plotly.

## Data and credentials

Licensed data (Impect, SkillCorner, Transfermarkt pulls) and the club's documents (`club_docs/`)
are gitignored and never published. Credentials live in `.env`, read through
`lofc.config.settings`; never in code. Modelled inputs (wages, Financial Fit, Resale Potential)
are labelled as modelled, appear only behind "Show affordability (modelled)", and never change
the ranking.
