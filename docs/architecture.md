# Architecture

> **What this is.** How the platform is built: data sources, the pipeline, the running
> services, the code layout, the database and where every metric comes from.
> **Current state (2026-11-16):** 25 leagues; the pipeline runs on the server Mon + Thu; the
> new web front end (FastAPI) serves staff; the old Streamlit dashboard is a fallback until it
> is retired. Scoring: `docs/methodology.md` · web front end: `docs/frontend.md` · server,
> schedules, deploys: `DEPLOY.md` · open work: `plan/TASKS.md`.

## What the system is

A decision platform. It turns Impect event data and SkillCorner physical tracking data
into a ranking of players on the club's own 1–5 recruitment framework, adds contract,
loan and injury facts from Transfermarkt and the club scouts' match reports from their
Google Sheet, and serves all of it through a web site behind the platform's own login. The
ranking model is the product; the infrastructure exists to make it reproducible and usable by
recruitment staff.

**Coverage.** 25 competitions (one line each in `src/lofc/leagues.py`): Championship, League
One, League Two, National League, Scottish Premiership, Scottish Championship, Premier League 2,
and 18 more added 2026-10-26 (Australia, Belgium, Czechia, Denmark, France ×2, Hungary, Northern
Ireland, Slovakia, South Africa, Finland, Ireland, Japan ×2, South Korea, Norway, Sweden, USA).
Seasons from 2024/25 (`FIRST_SEASON_ID = 317`); the live season is 2026/27
(`config.LIVE_SEASON_ID = 319`).

## Keys used everywhere

| Key | Values |
|---|---|
| `competition_id` | 3 Championship · 4 League One · 5 League Two · 65 National League · 901 Scottish Premiership · 902 Scottish Championship · 903 Premier League 2 · newer leagues `10000 + Impect competition id` (`NEW_ID_BASE`), e.g. 10189 Irish Premier Division |
| `season_id` | 317 = 2024/25 · 318 = 2025/26 · 319 = 2026/27, +1 a year (`leagues.season_id_for`). A calendar-year season ("2026") files under the season starting that year |
| `position_group` | Goalkeeper, Centre Back, Full Back, Defensive Mid, Central Mid, Attacking Mid, Winger, Centre Forward — one per player-season, the group he played most minutes in |

**The grain invariant.** Everything player-level downstream of ingest is keyed by
`(player_id, competition_id, season_id)`, not by player alone: a player who moves between
two covered leagues mid-season legitimately has two rows in one season. Any per-player view
must key on the full triple or deduplicate deliberately.

## Data sources

| Source | What it supplies | How it arrives | Cadence |
|---|---|---|---|
| **Impect** | On-ball event metrics (season averages per player per position), Impect's own player scores, KPI definitions, current club. Also the player identity spine: id, name, team, minutes, position | `impectPy` → `getPlayerIterationAverages`, `getPlayerIterationScores`; landed as parquet under `data/raw/impect/` | Mon + Thu (pipeline) |
| **SkillCorner** | Physical/tracking metrics (`get_physical`, `group_by=player`), in/out-of-possession splits for display, matches tracked (`count_match`) | `skillcorner` client; parquet under `data/raw/skillcorner/`. 14 editions: Championship, League One, League Two, National League, Premier League 2, Scottish Premiership (2025/26, 2026/27) and Irish Premier Division (2025, 2026) | Mon + Thu (pipeline) |
| **Transfermarkt** | Registered squads, market value, date of birth, contract expiry, height, foot, TM player id; loans (parent club, loan end); injury history | HTML scrape of squad, loan and injury pages (`transfermarkt_common.py`: polite client, fixed delay), CSVs pushed to the server | Manual, from the Mac (the server's IP is blocked — see `DEPLOY.md`) |
| **Club scouting sheet** | Scouts' match reports (filed via JotForm into a Google Sheet) and the form's player-name list with dates of birth | Google Sheets API, `spreadsheets.readonly` scope, one `batchGet` per run | Every minute (`scripts/scout_sync.sh`), separate from the pipeline |
| **Club SkillCorner export** | League One team benchmarks and the LOFC squad's physical data (xlsx) | `data/reference/skillcorner/*.xlsx` | Static; loaded only if the file is present |

Psychological and Medical judgements are entered by staff (the Assess page, today on the
Streamlit fallback only), not ingested. The modelled wage grid and the wage ceilings are
constructed reference data (`store/reference_data.py`), not a feed.

**Live vs finished seasons.** Impect and SkillCorner return season-to-date aggregates, so
the live season is re-pulled in full on every run. A finished season is skip-if-exists but is
re-pulled once its file is older than 30 days (`FINISHED_REFRESH_DAYS`, in `ingest/impect.py`
and `ingest/skillcorner_api.py`), because providers revise finished seasons — so corrections to
past matches reach the platform within about a month and are re-scored. A live season with no
matches yet is skipped, not an error, and an empty payload is never persisted.

## The pipeline

One command, `python -m lofc.pipeline`, runs every stage in order as a subprocess. Every stage
is idempotent and recorded in `pipeline_runs`. The stage list is built at run time by
`pipeline.build_steps()`; with `IMPECT_ONLY=true` (as on the server) it is:

| # | Stage | Module | Writes | Runs when |
|---|---|---|---|---|
| 1 | Apply schema | `alembic upgrade head` | schema | always |
| 2 | Load club SkillCorner export | `ingest.skillcorner` | `skillcorner_team_season`, `skillcorner_player_season` | export file present |
| 3 | Pull Impect player data | `ingest.impect` | `data/raw/impect/` | Impect credentials set |
| 4 | Pull Impect KPI definitions | `ingest.impect_definitions` | `impect_definitions` | Impect credentials set |
| 5 | Pull SkillCorner physical | `ingest.skillcorner_api` | `data/raw/skillcorner/` | SkillCorner credentials set |
| 6 | Build combined metric table | `model.build_neutral --write` | `player_metrics_neutral`, `player_detail_metrics`, `skillcorner_match_counts`, Impect-only rows in `players` | always |
| 7 | Position shares | `model.position_shares` | `player_position_shares` | always |
| 8 | Style signals | `model.style_run` | `player_style_signals` (labels only, never scoring) | always |
| 9 | Current club | `model.current_club` | `player_current_club` (+ `reference/current_club_overrides.csv`) | always |
| 9b | Squad minutes | `model.squad_minutes` | `impect_squad_minutes` (minutes per club, from the landed averages files; no API call) | always |
| 10 | Scrape squads + market values | `ingest.transfermarkt_efl` | `data/reference/transfermarkt/efl_values.csv` | EFL leagues configured and `SKIP_TRANSFERMARKT_SCRAPE` false (never on the server) |
| 11 | Scrape loans | `ingest.transfermarkt_loans` | `player_loans` + `loans.csv` | as stage 10 |
| 12 | Load squad snapshot | `store.squads` | `transfermarkt_squads` | EFL leagues configured |
| 13 | Load loans | `store.loans` | `player_loans` | EFL leagues configured |
| 14 | Percentiles + legacy scores | `model.run` | `player_percentiles`, `player_scores` | always |
| 15 | Style clusters (legacy) | `model.archetypes` | `archetypes` | always |
| 16 | Valuation | `model.valuation` | `valuations` | always |
| 17 | Identity | `model.identity` | `players.tm_player_id` and bio | always |
| 18 | Load injuries | `store.injuries` | `player_injuries` | always (no-op if `injuries.csv` absent) |
| 19 | Player bio | `model.player_bio` | `players.foot`, `players.nationality` (gap-fill only) | always |
| 20 | Club scorecard | `model.scorecard_run` | `player_scorecards` (incl. `peer_pool`, `peer_pool_size`) | always |
| 21 | Shortlists | `constrain.run` | `shortlists` | always |

"EFL leagues configured" means `SB_COMPETITIONS` in `.env` includes competition 3, 4, 5 or 65
(`settings.competitions` ∩ `valuation.EFL_LEAGUE_IDS`). The legacy `ingest.transfermarkt`
stage is only added for the old open-data league ids (2, 11, 12), so it never runs here.

Ordering constraints that matter: the combined table (6) must exist before anything that
scores; identity (17) must run before injuries (18) and player bio (19), which join on
`tm_player_id`; the scorecard (20) runs after valuation because Financial/Resale read
valuations and the wage tables, and before shortlists (21), which rank on its output.

**Not in the pipeline:**
- `ingest.transfermarkt_injuries` — the injury scrape. Run by hand on the Mac; stage 18 only loads its CSV.
- `store.scout_reports` — the scout-sheet sync (load + `model.scout_report_link` relink), run every minute by cron.
- `ingest.run`, `aggregate.run`, `store.reference_data`, `store.load` and the other legacy-provider ingest — **retired**. With `IMPECT_ONLY=true` they are skipped. Do not re-enable them to fill gaps: they would make thousands of paid API calls for data nothing reads.

`scripts/weekly_refresh.sh` wraps `docker compose exec -T app python -m lofc.pipeline` for
cron (Mon + Thu 04:15 UTC): a single-instance lock, timestamped logs (12 kept), and
`data/ops/last_success` / `data/ops/last_failure` markers. It never passes `--force` or
`--allow-shrink`, so a stage that judges its input too degraded fails the run and leaves the
previous data in place.

### Guards on scraped data

| Loader | Write mode | Guard |
|---|---|---|
| `store.squads` → `transfermarkt_squads` | snapshot, replaced wholesale | refuses a load under 70% of stored rows unless `--allow-shrink` |
| `ingest.transfermarkt_efl` | CSV | refuses to write if contract/height/foot fill rate < 20%, or rows fall under 70% of the previous CSV |
| `store.injuries` → `player_injuries` | scoped merge: only `source='transfermarkt'` rows for players present in the file are replaced | volume (shrink) guard |
| `store.loans` → `player_loans` | from `loans.csv` | a file far smaller than what is stored is refused unless `--allow-shrink` (end of May) |
| `ingest.transfermarkt_loans` → `player_loans` | clear-then-insert for one `season_id` | empty scrape leaves the table untouched |
| `store.scout_reports` → `scout_reports` | upsert on JotForm `submission_id`, never delete; a row gone from the sheet gets `missing_since` | truncated-read guard; unchanged sheet (same digest) writes nothing |

Check scraped tables with `GROUP BY season_id`, never a filter on one season: a wrong-key write
is invisible to a filtered query.

## Runtime components

| Service | Local (`docker-compose.yml`) | Production (`docker-compose.prod.yml`) |
|---|---|---|
| `db` | postgres:16, port 5432 published | postgres:16, no host port |
| `app` | Python 3.11 image; idle (`tail -f`), used via `exec` for the pipeline, tests and CLIs. Mounts `src/`, `tests/`, `alembic/`, `data/`, `secrets/` (ro) | same image; `data/` is the `appdata` named volume; `secrets/` (ro) |
| `web` / `web-blue` + `web-green` | `web`: uvicorn on :8600 with reload, same image, `src/` mounted, capped at 1.5 CPUs | two identical containers (`lofc.web.app`, one worker, :8600, no host port, `mem_limit 3g`, `cpus 2.0`, `/readyz` health check); only one serves at a time |
| `dashboard` | Streamlit on :8501 (old site) | Streamlit, no host port — the fallback address only |
| `caddy` | — | caddy:2.8, ports 80/443, automatic HTTPS. `DASHBOARD_DOMAIN` imports `caddy/web_upstream.caddy` (written by `scripts/web_switch.sh`: which web colour serves); `OLD_DASHBOARD_DOMAIN` → `dashboard:8501`; also routes a colleague's app on the same droplet |
| `pgadmin`, `metabase` | local conveniences on :5050 and :3000 | not deployed |

The image installs the package from `pyproject.toml` and runs as a non-root `appuser`. `data/`,
`docs/`, `plan/` and `.env` are excluded from the image. Configuration comes from `.env` via
pydantic-settings (`lofc.config.settings`); credentials never live in code. Access control is
the app's own login (scrypt-hashed passwords, lockout, signed session cookie via
`SESSION_SECRET`); there is no proxy-level auth. Every SQLAlchemy engine uses
`pool_pre_ping=True`, so the site recovers by itself after a database restart.

**Web caches.** The web process keeps each page's frames in memory until the data version
changes (`core/webcache.py`, `@webcache.versioned`; version from `dashboard/loaders.web_data_version()`),
warms every page at start-up (`/readyz` is 503 until done) and re-warms in the background when
the data changes.

## Code layout (`src/lofc/`)

**Top level**
- `config.py` — settings, Impect targets (derived from the registry + catalogue), SkillCorner targets, `LIVE_SEASON_ID`, feature flags (`IMPECT_ONLY`, `SCORING_SOURCE`, `SKIP_TRANSFERMARKT_SCRAPE`).
- `leagues.py` — the league registry: one line per competition, the season rule, id rules, names.
- `pipeline.py` — the ordered stage list and runner.
- `admin.py` — user-administration CLI (`create-user`, `set-password`, deactivate/reactivate, list); no self-service sign-up.

**`ingest/`** — getting data in
- `impect.py` — lands Impect averages and scores per iteration (live season always, finished every 30 days).
- `impect_definitions.py` — Impect's official KPI glossary → `impect_definitions`.
- `impect_map.py` — the 45 Impect metrics: our name → Impect column formula.
- `impect_translate.py` — Impect rows (one per position) → one per-90 row per player; sets `rankable` (≥ 450 minutes).
- `impect_detail.py` — display-only Impect detail (zones, lanes, receptions, Impect scores).
- `skillcorner_api.py` — lands SkillCorner physical data per edition (and possession splits).
- `skillcorner_map.py` — the 24 physical metrics → SkillCorner columns; lower-is-better set.
- `skillcorner.py` — loads the club's SkillCorner xlsx export.
- `transfermarkt_common.py` — shared rate-limited HTTP client for all scrapers.
- `transfermarkt_efl.py` — squad-page scrape (`LEAGUES` map).
- `transfermarkt_loans.py` — loan-page scrape → `player_loans` and `loans.csv`.
- `transfermarkt_injuries.py` — per-player injury-history scrape → `injuries.csv`.
- `scout_sheets.py` — read-only Google Sheets fetch and content hash.
- `scout_reports.py`, `scout_lookup.py` — pure normalisation of the report and player-name tabs.
- `retry.py` — retries with backoff for provider calls.
- `transfermarkt.py`, `run.py`, `landing.py` (file helpers, still used), and the legacy-provider modules — legacy ingest, not run in production.

**`aggregate/`** — legacy event aggregation; not run in production.

**`model/`** — everything derived
- `metric_registry.py` — every metric with its single source and derivation; generates the `player_metrics_neutral` columns. `python -m lofc.model.metric_registry` prints the inventory.
- `build_neutral.py` — merges the sources into `player_metrics_neutral`, `player_detail_metrics` and `skillcorner_match_counts` (`--match-counts` rebuilds only the last).
- `impect_spine.py` — player identity, minutes and position from Impect alone.
- `position_shares.py` — minutes/goals/assists per position group (display only).
- `styles.py`, `style_run.py` — the 24 playing-style labels (display only, never scoring).
- `current_club.py` — where each player is now (Impect `currentSquadId`), with a hand-kept corrections file `reference/current_club_overrides.csv`.
- `squad_minutes.py` — minutes per CLUB per league-season from the landed Impect averages files (a January mover has a row at each club); same linkage as `position_shares`. Display only (Squads & loans).
- `club_crosswalk.py` — Transfermarkt club name → Impect squad name for clubs whose names differ (`reference/club_crosswalk.csv`: normalised match, hand rows kept; a clash fails loudly). `--seed` rewrites the list.
- `club_framework.py` — the club's framework: dimension weights, per-position metric lists, archetype drops, metric successors, band formula.
- `performance_weights.py` — the club's High/Mid/Low per-metric weights inside Performance.
- `scorecard.py` — the 1–5 composite engine; `MIN_PEERS_FOR_RANKING = 10`, `pool_is_thin`, the midfield fallback pool (`pool_assignment`), `rank_in_pool`.
- `scorecard_run.py` — persists the composite to `player_scorecards`; `--reconcile-assessed` repair mode.
- `financial_resale.py` — modelled Financial Fit and Resale Potential bands.
- `report_categories.py` — groups each position's Performance metrics into report categories.
- `normalise.py`, `score.py`, `run.py` — within-league percentiles and the legacy 0–100 Quality/Fit scores.
- `archetypes.py` — k-means style clusters (hidden; superseded by `styles.py`).
- `valuation.py` — fair value and undervaluation (EFL 2025/26 only); `wage_check.py` — reconciles the wage grid against published payrolls.
- `identity.py` — links players to Transfermarkt on the stored `tm_player_id`, else name + date of birth.
- `player_bio.py` — fills foot and nationality from a per-field source order, never overwriting.
- `medical.py` — availability from injury history (evidence only, never a score).
- `club_criteria.py` — the club's Psychological and Medical criteria per position.
- `assessment_rules.py`, `scout_scores.py`, `assessment_status.py`, `assessed_refresh.py` — band rules, conflict resolution (signed-off wins), derived status, and recomputing `assessed_composite` after a save, sign-off or reject.
- `scout_report_link.py` — links scout reports to players (name + date of birth, with a tolerant second tier for wrong sheet dates).
- `metric_definitions.py` — resolves each metric to Impect's official wording.
- `impect_check.py`, `skillcorner_check.py` — read-only validation reports on landed data.
- `user_admin.py` — rules shared by the admin CLI and the Users page.

**`constrain/`** — `filters.py` (candidate pool, fee and wage gates, ranking on `objective_composite`, near-misses), `run.py` (writes the default `shortlists` snapshot).

**`store/`** — persistence
- `models.py` — SQLAlchemy schema (changes go through Alembic).
- `squads.py`, `loans.py`, `injuries.py`, `scout_reports.py` — loaders for scraped/synced data, with the guards above.
- `assessments.py` — insert-only scout assessments plus `sign_off` and `reject`.
- `users.py` — authentication and account management; `watchlist.py` — the watchlist.
- `runs.py` — the `pipeline_runs` record and per-league failure isolation; `integrity.py` — orphan / duplicate checks.
- `load.py` (engine helper; legacy loaders), `reference_data.py` (wage and identity reference CSVs).

**`core/`** — page logic shared by the web site (and Streamlit where both have the page): pure
functions per page — `players_pool.py`, `card.py`, `squad.py` ("Against our <position>", "vs
ours"), `compare.py`, `report_page.py`, `squads.py`, `scout_reports_page.py`, `watchlist_page.py`,
`physical_page.py`, `club_vs_league.py`, `similar.py` (Similar players: card section + page),
`infobar.py` (top-bar counts and pull dates),
`detail_store.py`, `webcache.py`.

**`web/`** — the web front end (`docs/frontend.md`)
- `app.py` — FastAPI app factory: login, sessions, `/healthz`, `/readyz`, static files, warm-up.
- `pages.py` — the navigation and page registry (every route is generated from it).
- `security.py` — `current_user`, `write_user` (session + `X-LOFC-Request: 1` header on writes).
- `api/` — one JSON module per page (players, card, similar, compare, report, squads, scout_reports, watchlist, physical, club_vs_league, reference, users).
- `templates/` (Jinja page shells), `static/` (one stylesheet + ES-module JS per page, no build step).

**`report/`** — `data.py` assembles one `ReportData` from stored scores and the assessment (used
by both sites); `svg.py`, `render.py` + `templates/` are the old Streamlit download (self-contained
HTML). The web Report builds its download in the browser from the preview sheet.

**`dashboard/`** — the old Streamlit app (fallback address only): `app.py` (login gate,
sidebar, `st.navigation`), `loaders.py` (cached DB reads; also `web_data_version()` used by the
web caches), `auth.py` / `session.py` / `cookie_auth.py` / `login_throttle.py` (roles, login,
throttle — the web site reuses `auth.can` and `login_throttle`), `tabs/` (one module per page:
Players, Squads & loans, Scout reports, Compare, Watchlist, Report, Assess, Sign-off, Physical,
reference pages, Users; Methodology hidden by `SHOW_METHODOLOGY = False`).

## Database (Postgres 16)

Schema source of truth: `src/lofc/store/models.py`; history in `alembic/versions/`
(34 migrations, head `a1d4f6b8c902` — scorecard peer pool — as of 2026-11-16).

### Scoring and metrics (pipeline-derived, rebuilt each run)

| Table | Grain | Holds |
|---|---|---|
| `player_metrics_neutral` | player × league × season | The combined metric table every score reads: identity, minutes, `rankable`, plus one nullable column per registry metric |
| `player_scorecards` | player × league × season × archetype | **The ranking.** 1–5 bands per dimension, `objective_composite` (Performance + Physical, the default ranking), `full_composite` (adds modelled Financial/Resale), `assessed_composite` (adds Psychological + Medical, NULL until both scout dimensions exist), weight-covered columns, advisory `veto` / `below_min_composite`, `peer_pool` (`position` / `midfield`) and `peer_pool_size` |
| `player_detail_metrics` | player × league × season × metric (long) | Display-only detail: Impect zones/receptions/scores, SkillCorner possession splits (`phys_tip.*`, `phys_otip.*`) |
| `player_position_shares` | player × league × season × position group | Share of minutes, goals and assists per position (display only) |
| `player_style_signals` | player × league × season × signal | Playing-style signals; percentiles taken at read time (labels only) |
| `skillcorner_match_counts` | player × league × season | Matches SkillCorner tracked (Physical page "Tracked matches") |
| `player_current_club` | one per player | His club today (Impect), for "… · now <club>" |
| `impect_squad_minutes` | player × club × league × season | Minutes at each club (Squads & loans; display only) |
| `player_percentiles` | player × league × season × metric | Within-position, within-league percentiles from `model.run` |
| `player_scores` | player × league × season | Legacy 0–100 Quality/Fit. Orders nothing, but is still the row source of the candidate pool and the wage-tier tercile |
| `archetypes` | player × league × season | Legacy style cluster id and label (hidden) |
| `valuations` | player × league × season | Market value, out-of-fold fair value, undervaluation (EFL 2025/26 only) |
| `shortlists` | player × league × season | Default fee/wage-gated snapshot ranked on `objective_composite` |
| `player_season_metrics` | player × league × season | Legacy historical table for the four EFL leagues, 2024/25–2025/26; no longer rebuilt and not read by the club composite. Comes from the database dump |

### Reference

| Table | Grain | Holds |
|---|---|---|
| `players` | one per player | Name, birth date, nationality, foot, height, contract expiry, `tm_player_id` |
| `wage_estimates` | league × position × age band × tier | Modelled weekly wage with low/high band |
| `wage_framework` | position × age band | Club wage-ceiling stand-in |
| `identity_profiles` | position × metric | Legacy Fit weights and floors |
| `impect_definitions` | one per Impect KPI column | Impect's official definitions for the glossary |
| `skillcorner_team_season` | club × season | League One team physical benchmarks (club export) |
| `skillcorner_player_season` | player × season | LOFC squad physical data (club export) |

### Scraped and synced

| Table | Grain | Holds |
|---|---|---|
| `transfermarkt_squads` | one per registered squad member | Snapshot of every club's squad: position, DOB, height, foot, contract, market value, `scraped_at` |
| `player_loans` | `tm_player_id` × club × season | Loans in, with parent club and `loan_ends`; `player_id` linked where known |
| `player_injuries` | one per injury spell | Season, raw wording, category, dates, days out, games missed, `source` |
| `scout_reports` | one per JotForm submission | Scout, fixture, positions (scout's own codes), grade, verdict, comments; `player_id` nullable |
| `scout_player_lookup` | one per sheet row | The form's player list with DOB, used for linking |
| `scout_sync` | one per sync that ran | Content digest, counts, `changed`; freshness record and cache key for scout data |

### Operations

| Table | Grain | Holds |
|---|---|---|
| `pipeline_runs` | one per step (and per league inside a league-by-league step) per run | Status (`success` / `partial` / `failed`), times, error, league. The top bar's pull dates come from here |

### User data (never written or cleared by the pipeline)

| Table | Grain | Holds |
|---|---|---|
| `users` | one per account | Username, name, role (`scout`/`medical`/`head_of_recruitment`/`admin`), scrypt hash, active flag, lockout state, `must_change_password`. Never deleted, only deactivated |
| `scout_assessments` | one per assessor × player × league × season × dimension | Band, status (`draft`/`submitted`/`signed_off`/`rejected`), reviewer, reason, narrative fields. Deliberately not unique on the player-dimension key |
| `scout_criterion_scores` | assessment × criterion | Per-criterion 1–5 score or pass/fail |
| `watchlist` | player × league × season | Status and note; foreign key to `players` |

Derived tables are clear-then-insert (whole table, or per league-season), so a re-run rebuilds
them exactly. User-data tables are read through LEFT JOINs so a rebuild never drops a watched or
assessed player.

## Metric provenance

`model/metric_registry.py` is the single list of metrics: 91 entries, each with exactly one
source. Populated today: **45 Impect** (`ingest/impect_map.py`, converted in
`impect_translate.py`) and **24 SkillCorner** (`ingest/skillcorner_map.py`). The other 22
registry columns belong to the retired legacy provider and are NULL in every row of
`player_metrics_neutral`.

**Impect derivation.** Impect gives per-match-equivalent averages, one row per position
played. A season total is `average × matchShare` summed over the player's position rows;
per-90 is total ÷ minutes × 90; ratios are computed from season totals. Players under 450
minutes are stored but not `rankable`.

**SkillCorner derivation.** Season per-appearance averages per player, converted to per 90
(`to_per90`); speeds and metres per minute are left as they are. Where SkillCorner has no
edition (2024/25, the Scottish Championship, the newer leagues except Ireland) there is no
Physical dimension; the composite renormalises over the dimensions present and records the
weight covered.

**What is scored** (`model/club_framework.py`, `model/performance_weights.py`):

| Dimension | Source | Metrics | Weight (outfield, normalised) |
|---|---|---|---|
| Performance | Impect | Per-position list (`PERFORMANCE_METRICS`), resolved through `CLUB_SUCCESSOR`; 32 distinct Impect metrics across all positions; weighted per metric (club's High/Mid/Low) | 41.4% (GK 50%) |
| Physical | SkillCorner | 7, same for every outfield position, equal weight: distance, HSR count and distance, sprint count and distance, average match top speed (PSV-99) and top speed best 5 matches (PSV-99 Top 5) | 22.3% (GK none) |
| Psychological | Scout assessment | Club criteria, 1–5 | 9.1% (GK 20%) |
| Medical Risk | Scout assessment | Band entered by a person; injury availability shown as evidence | 13.6% (GK 15%) |
| Financial Fit | Modelled | Fee, wage, contract | 9.1% (GK 10%) |
| Resale Potential | Modelled | Age curve, market value | 4.5% (GK 5%) |

So the objective ranking uses 39 metrics: 32 Impect + 7 SkillCorner. Each is a mid-rank
percentile within league + season + position group over rankable players (inverted for
lower-is-better metrics; a thin midfield group uses the league-season's combined midfield
pool), mapped to a band by `3 + (percentile − 50) / 20`, clamped to 1–5. Full Back and Winger
also have archetype rows that score Performance on a subset of the list. Details and rationale:
`docs/methodology.md`.

The other populated metrics are shown on player cards, Compare, Physical and the glossary but do
not move any score; nor do `player_detail_metrics`, `player_position_shares`,
`player_style_signals` and `skillcorner_match_counts`.

## Data flow into the web site

The web site reads Postgres (and, read-only, landed provider files for the glossary and
physical detail). It never runs a pipeline stage.

- **Players** — candidate pool from `constrain.filters.build_candidates(all_leagues=True)`
  (built on `player_scores`, left-joined to valuations, wage tables and names from
  `player_metrics_neutral`), merged with bio and styles; ranked on
  `player_scorecards.objective_composite` for the selected season, or optionally on
  `assessed_composite`. A pool with fewer than `MIN_PEERS_FOR_RANKING` (10) players is not
  rated (shown as "—" with one line saying why). `core/players_pool.py`.
- **Player card** — stored percentiles and bands, "vs ours" against Orient's players at the
  position, Strengths / Watch-outs, physical tables, scout reports, injuries. `core/card.py`, `core/squad.py`.
- **Squads & loans** — `transfermarkt_squads` + `player_loans`, with ratings carried across.
- **Scout reports** — `scout_reports`, keyed for freshness on `scout_sync.digest`. Its Refresh
  button reads the sheet directly, so the web containers also mount the read-only key.
- **Report** — `report.data` reads the same scorecard percentiles and assessment; it computes no
  new score. The download is made in the browser.
- **Physical** — SkillCorner metrics from `player_metrics_neutral` / `player_detail_metrics`,
  match counts, and the Orient squad's ratings. **Club vs League One** — stored ratings and
  percentiles, minutes-weighted (`core/club_vs_league.py`).
- **Glossary** — `impect_definitions` plus `glossary_data`; **Watchlist** — `watchlist` joined to
  scores, injuries and contracts.
- **Assess / Sign-off** (Streamlit fallback) — write `scout_assessments` /
  `scout_criterion_scores` through `store.assessments`, then `model.assessed_refresh` updates
  `assessed_composite`. `objective_composite` is never touched by scout input.

Caches refresh by themselves when the data version moves (any database write the pages read,
plus a daily rollover); no restart needed.

## Adding a league

1. **Event data** — add ONE line to `LEAGUES` in `lofc/leagues.py`:
   `Competition("<name>", <Impect competitionId>, NEW_ID_BASE + <Impect competitionId>)`.
   Its seasons (2024/25 on) come from Impect's catalogue on the next pull; ids, labels and
   names are derived from the registry. The competition must appear in the licence catalogue
   (`ip.getIterations`).
2. **Physical** — add a `SkillCornerTarget` per season to `config.DEFAULT_SKILLCORNER_TARGETS` if
   SkillCorner holds data for it (check it actually returns rows; the Scottish Championship
   lists editions but has none). Without it the league is scored on Performance alone.
3. **Transfermarkt** — add the league code, URL slug and `competition_id` to `LEAGUES` in
   `ingest/transfermarkt_efl.py`; the squad, loan and injury scrapes all iterate it. Confirm
   the squad-page headers match `REQUIRED_HEADERS` for the current season.
4. **Availability** — add the league's scheduled games to `SCHEDULED_GAMES` in
   `model/medical.py`, or availability is reported as unknown.
5. **Money** — valuation and the wage gate cover only `valuation.EFL_LEAGUE_IDS` and the
   leagues in `store/reference_data.WAGE_LEAGUE_ANCHORS`. A new league is ranked without
   Financial/Resale unless both are extended.
6. Re-run the pipeline. Percentiles, bands and peer pools are computed within whatever
   leagues exist; no scoring code changes.

A new season needs no change for Impect: the catalogue brings it in and the season rule gives
its id, label and age date. Update `LIVE_SEASON_ID` in `config.py`, and steps 2–3 for
SkillCorner and Transfermarkt.

## Failures and the run record

Every pipeline step, and every league inside a league-by-league step, writes a row to
`pipeline_runs` (`store/runs.py`; one `run_id` per run). In the Impect and SkillCorner pulls,
the combined table, position shares and style signals, a failing league is recorded and the
other leagues carry on (`runs.for_each_league`); the step exits 3 ("partial"), the run
continues and finishes partial, naming the failed leagues. A failed league keeps its previous
rows. Any other failure (migrations, ratings) stops the run. Provider calls retry transient
failures with backoff (`ingest/retry.py`). `python -m lofc.store.integrity` checks for orphan
rows, duplicate keys and possible duplicate player identities.

## Growth notes still relevant

- **One store is enough.** The working data is tens of thousands of structured rows;
  Postgres covers it. Raw provider files are reproducible from the APIs, so they stay on
  disk rather than in object storage.
- **Season aggregates only.** Both providers are pulled at season grain, so the platform
  cannot show what changed in a single match. Both expose per-match endpoints under the
  current licences; adding them means new player × match tables, for monitoring only — they
  must never feed the composite (register P11).
- **No cross-league ordering.** Percentiles are within league. Ranking players from
  different leagues on one list needs a league-strength adjustment that does not exist yet.
