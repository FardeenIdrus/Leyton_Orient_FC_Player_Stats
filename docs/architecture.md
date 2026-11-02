# Architecture

How the Leyton Orient FC recruitment platform is built: data sources, pipeline, runtime,
code layout, database and metric provenance. For the scoring method see
`docs/methodology.md`; for the server, cron jobs, backups and deploys see `DEPLOY.md`;
for current state and open work see `plan/BUILD_PLAN.md`.

## What the system is

A decision platform. It turns Impect event data and SkillCorner physical tracking data
into a ranking of players on the club's own 1–5 recruitment framework, adds contract,
loan and injury facts from Transfermarkt and the club scouts' match reports from their
Google Sheet, and serves all of it through a Streamlit app behind a login. The ranking
model is the product; the infrastructure exists to make it reproducible and usable by
recruitment staff.

**Coverage.** Seven leagues: Championship, League One, League Two, National League,
Scottish Premiership, Scottish Championship, Premier League 2. Three seasons:
2024/25, 2025/26 and the live 2026/27.

## Keys used everywhere

| Key | Values |
|---|---|
| `competition_id` | 3 Championship · 4 League One · 5 League Two · 65 National League · 901 Scottish Premiership · 902 Scottish Championship · 903 Premier League 2 |
| `season_id` | 317 = 2024/25 · 318 = 2025/26 · 319 = 2026/27 (the live season, `config.LIVE_SEASON_ID`) |
| `position_group` | Goalkeeper, Centre Back, Full Back, Defensive Mid, Central Mid, Attacking Mid, Winger, Centre Forward — one per player-season, the group he played most minutes in |

**The grain invariant.** Everything player-level downstream of ingest is keyed by
`(player_id, competition_id, season_id)`, not by player alone: a player who moves between
two covered leagues mid-season legitimately has two rows in one season. Any per-player view
must key on the full triple or deduplicate deliberately.

## Data sources

| Source | What it supplies | How it arrives | Cadence |
|---|---|---|---|
| **Impect** | On-ball event metrics (season averages per player per position), Impect's own player scores, KPI definitions. Also the player identity spine: id, name, team, minutes, position | `impectPy` → `getPlayerIterationAverages`, `getPlayerIterationScores`; landed as parquet under `data/raw/impect/` | Weekly (pipeline) |
| **SkillCorner** | Physical/tracking metrics (`get_physical`, `group_by=player`), plus in/out-of-possession splits for display | `skillcorner` client; parquet under `data/raw/skillcorner/` | Weekly (pipeline) |
| **Transfermarkt** | Registered squads, market value, date of birth, contract expiry, height, foot, TM player id; loans (parent club, loan end); injury history | HTML scrape of squad pages, loan pages and per-player injury pages (`transfermarkt_common.py`: polite client, fixed delay) | Manual, run from a workstation (the server's IP is blocked — see `DEPLOY.md`) |
| **Club scouting sheet** | Scouts' match reports (filed via JotForm into a Google Sheet) and the form's player-name list with dates of birth | Google Sheets API, `spreadsheets.readonly` scope, one `batchGet` per run | Every minute (`scripts/scout_sync.sh`), separate from the pipeline |
| **Club SkillCorner export** | League One team benchmarks and the LOFC squad's physical data (xlsx) | `data/reference/skillcorner/*.xlsx` | Static; loaded only if the file is present |

Psychological and Medical judgements are entered by staff in the app (the Assess page), not
ingested. The modelled wage grid and the wage ceilings are constructed reference data
(`store/reference_data.py`), not a feed.

**Live vs finished seasons.** Impect and SkillCorner return season-to-date aggregates, so
the live season is re-pulled on every run. A finished season is skip-if-exists but is
re-pulled once its file is older than 30 days (`FINISHED_REFRESH_DAYS`), because providers
revise finished seasons. A live season with no matches yet is skipped, not an error, and an
empty payload is never persisted.

## The pipeline

One command, `python -m lofc.pipeline`, runs every stage in order as a subprocess and stops
the whole run at the first failure. Every stage is idempotent. The stage list is built at
run time by `pipeline.build_steps()`; several stages are conditional:

| # | Stage | Module | Writes | Runs when |
|---|---|---|---|---|
| 1 | Apply schema | `alembic upgrade head` | schema | always |
| 2 | Load club SkillCorner export | `ingest.skillcorner` | `skillcorner_team_season`, `skillcorner_player_season` | export file present |
| 3 | Pull Impect player data | `ingest.impect` | `data/raw/impect/` | Impect credentials set |
| 4 | Pull Impect KPI definitions | `ingest.impect_definitions` | `impect_definitions` | Impect credentials set |
| 5 | Pull SkillCorner physical | `ingest.skillcorner_api` | `data/raw/skillcorner/` | SkillCorner credentials set |
| 6 | Build combined metric table | `model.build_neutral --write` | `player_metrics_neutral`, `player_detail_metrics`, Impect-only rows in `players` | always |
| 7 | Position shares | `model.position_shares` | `player_position_shares` | always |
| 8 | Scrape squads + market values | `ingest.transfermarkt_efl` | `data/reference/transfermarkt/efl_values.csv` | EFL leagues configured and `SKIP_TRANSFERMARKT_SCRAPE` false |
| 9 | Scrape loans | `ingest.transfermarkt_loans` | `player_loans` (directly) | as stage 8 |
| 10 | Load squad snapshot | `store.squads` | `transfermarkt_squads` | EFL leagues configured |
| 11 | Percentiles + legacy scores | `model.run` | `player_percentiles`, `player_scores` | always |
| 12 | Style clusters | `model.archetypes` | `archetypes` | always |
| 13 | Valuation | `model.valuation` | `valuations` | always |
| 14 | Identity | `model.identity` | `players.tm_player_id` and bio | always |
| 15 | Load injuries | `store.injuries` | `player_injuries` | always (no-op if `injuries.csv` absent) |
| 16 | Player bio | `model.player_bio` | `players.foot`, `players.nationality` (gap-fill only) | always |
| 17 | Club scorecard | `model.scorecard_run` | `player_scorecards` | always |
| 18 | Shortlists | `constrain.run` | `shortlists` | always |

"EFL leagues configured" means `SB_COMPETITIONS` in `.env` includes competition 3, 4, 5 or
65 (`settings.competitions` ∩ `valuation.EFL_LEAGUE_IDS`).

Ordering constraints that matter: the combined table (6) must exist before anything that
scores; identity (14) must run before injuries (15) and player bio (16), which join on
`tm_player_id`; the scorecard (17) runs after valuation because Financial/Resale read
valuations and the wage tables, and before shortlists (18), which rank on its output.

**Not in the pipeline:**
- `ingest.transfermarkt_injuries` — the injury scrape. Run by hand; stage 15 only loads its CSV.
- `store.scout_reports` — the scout-sheet sync (load + `model.scout_report_link` relink), run every minute by cron.
- `ingest.transfermarkt`, `ingest.run`, `aggregate.run`, `store.reference_data`, `store.load`, `ingest.statsbomb_season` — legacy stages. With `IMPECT_ONLY=true` (as in the current `.env`) they are skipped or their condition is never met.

`scripts/weekly_refresh.sh` wraps `docker compose exec -T app python -m lofc.pipeline` for
cron: a single-instance lock, timestamped logs (12 kept), and `data/ops/last_success` /
`data/ops/last_failure` markers. It never passes `--force` or `--allow-shrink`, so a stage
that judges its input too degraded fails the run and leaves the previous data in place.

### Guards on scraped data

| Loader | Write mode | Guard |
|---|---|---|
| `store.squads` → `transfermarkt_squads` | snapshot, replaced wholesale | refuses a load under 70% of stored rows unless `--allow-shrink` |
| `ingest.transfermarkt_efl` | CSV | refuses to write if contract/height/foot fill rate < 20%, or rows fall under 70% of the previous CSV |
| `store.injuries` → `player_injuries` | scoped merge: only `source='transfermarkt'` rows for players present in the file are replaced | volume (shrink) guard |
| `ingest.transfermarkt_loans` → `player_loans` | clear-then-insert for one `season_id` | empty scrape leaves the table untouched |
| `store.scout_reports` → `scout_reports` | upsert on JotForm `submission_id`, never delete; a row gone from the sheet gets `missing_since` | truncated-read guard; unchanged sheet (same digest) writes nothing |

## Runtime components

| Service | Local (`docker-compose.yml`) | Production (`docker-compose.prod.yml`) |
|---|---|---|
| `db` | postgres:16, port 5432 published | postgres:16, no host port |
| `app` | Python 3.11 image; idle (`tail -f`), used via `exec` for the pipeline, tests and CLIs. Mounts `src/`, `tests/`, `alembic/`, `data/`, `secrets/` (ro) | same image; `data/` is the `appdata` named volume; `secrets/` (ro) |
| `dashboard` | Streamlit on :8501; mounts `src/` live and `data/` read-only | Streamlit, no host port, no `data/` mount — reads Postgres only |
| `caddy` | — | caddy:2.8, ports 80/443, automatic HTTPS, `reverse_proxy dashboard:8501` for `$DASHBOARD_DOMAIN` |
| `pgadmin`, `metabase` | local conveniences on :5050 and :3000 | not deployed |

The image installs the package from `pyproject.toml` (`pip install -e ".[dev]"`) and runs as
a non-root `appuser`. `data/`, `docs/`, `plan/` and `.env` are excluded from the image.
Configuration comes from `.env` via pydantic-settings (`lofc.config.settings`); credentials
never live in code. Access control is the app's own login (scrypt-hashed passwords,
lockout, signed session cookie via `SESSION_SECRET`); there is no proxy-level auth.

The PDF export of the player report (`scripts/report_to_pdf.py`) runs on the host, not in
Docker: it drives headless Chromium through Playwright.

## Code layout (`src/lofc/`)

**Top level**
- `config.py` — settings, Impect targets (derived from the registry + catalogue), SkillCorner targets, `LIVE_SEASON_ID`, feature flags (`IMPECT_ONLY`, `SCORING_SOURCE`, `SKIP_TRANSFERMARKT_SCRAPE`).
- `leagues.py` — the league registry: one line per competition, the season rule, id rules, names.
- `pipeline.py` — the ordered stage list and runner.
- `admin.py` — user-administration CLI (`create-user`, `set-password`, deactivate/reactivate, list); no self-service sign-up.

**`ingest/`** — getting data in
- `impect.py` — lands Impect averages and scores per iteration.
- `impect_definitions.py` — Impect's official KPI glossary → `impect_definitions`.
- `impect_map.py` — the 45 Impect metrics: our name → Impect column formula.
- `impect_translate.py` — Impect rows (one per position) → one per-90 row per player; sets `rankable` (≥ 450 minutes).
- `impect_detail.py` — display-only Impect detail (zones, lanes, receptions, Impect scores).
- `skillcorner_api.py` — lands SkillCorner physical data per edition (and possession splits).
- `skillcorner_map.py` — the 24 physical metrics → SkillCorner columns; lower-is-better set.
- `skillcorner.py` — loads the club's SkillCorner xlsx export.
- `transfermarkt_common.py` — shared rate-limited HTTP client for all scrapers.
- `transfermarkt_efl.py` — squad-page scrape for all seven leagues (`LEAGUES` map).
- `transfermarkt_loans.py` — loan-page scrape, written straight to `player_loans`.
- `transfermarkt_injuries.py` — per-player injury-history scrape → `injuries.csv`.
- `scout_sheets.py` — read-only Google Sheets fetch and content hash.
- `scout_reports.py`, `scout_lookup.py` — pure normalisation of the report and player-name tabs.
- `transfermarkt.py`, `run.py`, `landing.py`, `statsbomb.py`, `statsbomb_season.py` — legacy ingest, not run in production.

**`aggregate/`** — legacy event aggregation (`events.py`, `player_season.py`, `run.py`); not run in production.

**`model/`** — everything derived
- `metric_registry.py` — every metric with its single source and derivation; generates the `player_metrics_neutral` columns. `python -m lofc.model.metric_registry` prints the inventory.
- `build_neutral.py` — merges the sources into `player_metrics_neutral` and `player_detail_metrics`.
- `impect_spine.py` — player identity, minutes and position from Impect alone.
- `position_shares.py` — minutes/goals/assists per position group (display only).
- `club_framework.py` — the club's framework: dimension weights, per-position metric lists, archetype drops, metric successors, band formula.
- `scorecard.py` — the 1–5 composite engine; `MIN_PEERS_FOR_RANKING`, `pool_is_thin`.
- `scorecard_run.py` — persists the composite to `player_scorecards`; `--reconcile-assessed` repair mode.
- `financial_resale.py` — modelled Financial Fit and Resale Potential bands.
- `report_categories.py` — groups each position's Performance metrics into report categories.
- `normalise.py`, `score.py`, `run.py` — within-league percentiles and the legacy 0–100 Quality/Fit scores.
- `archetypes.py` — k-means playing-style clusters.
- `valuation.py` — fair value and undervaluation (EFL only); `wage_check.py` — reconciles the wage grid against published payrolls.
- `identity.py` — links players to Transfermarkt on the stored `tm_player_id`, else name + date of birth.
- `player_bio.py` — fills foot and nationality from a per-field source order, never overwriting.
- `medical.py` — availability from injury history (evidence only, never a score).
- `club_criteria.py` — the club's Psychological and Medical criteria per position.
- `assessment_rules.py`, `scout_scores.py`, `assessment_status.py`, `assessed_refresh.py` — band rules, conflict resolution (signed-off wins), derived status, and recomputing `assessed_composite` after a save, sign-off or reject.
- `scout_report_link.py` — links scout reports to players on name + date of birth.
- `metric_definitions.py` — resolves each metric to Impect's official wording.
- `impect_check.py`, `skillcorner_check.py` — read-only validation reports on landed data.
- `user_admin.py` — rules shared by the admin CLI and the Users page.

**`constrain/`** — `filters.py` (candidate pool, fee and wage gates, ranking on `objective_composite`, near-misses), `run.py` (writes the default `shortlists` snapshot).

**`store/`** — persistence
- `models.py` — SQLAlchemy schema (changes go through Alembic).
- `squads.py`, `injuries.py`, `scout_reports.py` — loaders for scraped/synced data, with the guards above.
- `assessments.py` — insert-only scout assessments plus `sign_off` and `reject`.
- `users.py` — authentication and account management; `watchlist.py` — the watchlist.
- `load.py` (engine helper; legacy loaders), `reference_data.py` (wage and identity reference CSVs).

**`report/`** — the one-page player report: `data.py` (assembles one `ReportData` from stored scores and the assessment), `svg.py` (inline SVG charts), `render.py` + `templates/` (self-contained HTML, print CSS).

**`dashboard/`** — the Streamlit app
- `app.py` — entry point: login gate, sidebar, page registration and `st.navigation`.
- `loaders.py` — every cached DB read. Pipeline data: 24 h TTL keyed on `data_version()` (Postgres write counters + table file ids + server start + date, re-read every 30 s), so a cache is never older than the database; a background warm-up refills it when the version changes. User-written data (`assessed_composite`, watchlist, scout sync): 60 s TTL.
- `session.py`, `auth.py`, `cookie_auth.py`, `login_throttle.py` — login, roles/permissions, remembered-session cookie, password-spray throttle.
- `theme.py`, `labels.py`, `charts.py`, `formatting.py`, `units.py`, `badges.py` — presentation building blocks.
- `controls.py`, `sidebar_filters.py`, `metric_filters.py`, `search.py`, `search_target.py`, `seasons.py` — filters, global player search (and which row it opens), season helpers.
- `compare_tables.py` — the Compare page's tables, radar metrics and packing-zone pitch.
- `player_header.py`, `detail_section.py`, `evidence.py`, `assessment_detail.py`, `transparency.py` — player-card components.
- `glossary_data.py`, `rating_reference.py` — glossary content and the "What goes into each rating" page.
- `tabs/` — one module per page (below).

**Pages** (sidebar sections in `app.py`): **Scouting** — Players, Squads & loans, Scout
reports, Compare, Watchlist, Report · **Assessment** — Assess, Sign-off · **Analysis** —
Physical · **Reference** — What goes into each rating, Glossary, Methodology (currently hidden:
`SHOW_METHODOLOGY = False` in `app.py`) · **Admin** — Users (only for roles with `manage_users`).
`tabs/player_types.py` exists but is not registered.

## Database (Postgres 16)

Schema source of truth: `src/lofc/store/models.py`; history in `alembic/versions/`
(29 migrations, head `c7e2a1f4d903` as of 2026-10-22).

### Scoring and metrics (pipeline-derived, rebuilt each run)

| Table | Grain | Holds |
|---|---|---|
| `player_metrics_neutral` | player × league × season | The combined metric table every score reads: identity, minutes, `rankable`, plus one nullable column per registry metric |
| `player_scorecards` | player × league × season × archetype | **The ranking.** 1–5 bands per dimension, `objective_composite` (Performance + Physical, the default ranking), `full_composite` (adds modelled Financial/Resale), `assessed_composite` (Performance + Physical + Psychological + Medical, NULL until both scout dimensions exist), weight-covered columns, advisory `veto` / `below_min_composite` |
| `player_detail_metrics` | player × league × season × metric (long) | Display-only detail: Impect zones/receptions/scores, SkillCorner possession splits |
| `player_position_shares` | player × league × season × position group | Share of minutes, goals and assists per position (display only) |
| `player_percentiles` | player × league × season × metric | Within-position, within-league percentiles from `model.run` |
| `player_scores` | player × league × season | Legacy 0–100 Quality/Fit. Orders nothing, but is still the row source of the dashboard's candidate pool and the wage-tier tercile |
| `archetypes` | player × league × season | Style cluster id, label, distance to centroid |
| `valuations` | player × league × season | Market value, out-of-fold fair value, undervaluation (EFL leagues only) |
| `shortlists` | player × league × season | Default fee/wage-gated snapshot ranked on `objective_composite` |
| `player_season_metrics` | player × league × season | Legacy historical table for the four EFL leagues, 2024/25–2025/26 (the earlier event provider's figures); no longer rebuilt and not read by the club composite. Still read by the archetypes, valuation and some dashboard/methodology queries |

### Reference

| Table | Grain | Holds |
|---|---|---|
| `players` | one per player | Name, birth date, nationality, foot, height, contract expiry, `tm_player_id` |
| `wage_estimates` | league × position × age band × tier | Modelled weekly wage with low/high band |
| `wage_framework` | position × age band | Club wage-ceiling stand-in |
| `identity_profiles` | position × metric | Legacy Fit weights and floors (feed `on_profile` only) |
| `impect_definitions` | one per Impect KPI column | Impect's official definitions for the glossary |
| `skillcorner_team_season` | club × season | League One team physical benchmarks (club export) |
| `skillcorner_player_season` | player × season | LOFC squad physical data (club export) |

### Scraped and synced

| Table | Grain | Holds |
|---|---|---|
| `transfermarkt_squads` | one per registered squad member | Snapshot of every club's squad: position, DOB, height, foot, contract, market value, `scraped_at` |
| `player_loans` | `tm_player_id` × club × season | Loans in, with parent club and `loan_ends`; `player_id` linked where known |
| `player_injuries` | one per injury spell | Season, raw wording, category, dates, days out, games missed, `source` |
| `scout_reports` | one per JotForm submission | Scout, fixture, positions (scout's own codes), grade, verdict, comments; `player_id` nullable (non-league players are stored without a link) |
| `scout_player_lookup` | one per sheet row | The form's player list with DOB, used for linking |
| `scout_sync` | one per sync that ran | Content digest, counts, `changed`; the dashboard's freshness record and cache key for scout data |

### User data (never written or cleared by the pipeline)

| Table | Grain | Holds |
|---|---|---|
| `users` | one per account | Username, name, role (`scout`/`medical`/`head_of_recruitment`/`admin`), scrypt hash, active flag, lockout state, `must_change_password`. Never deleted, only deactivated |
| `scout_assessments` | one per assessor × player × league × season × dimension | Band, status (`draft`/`submitted`/`signed_off`/`rejected`), reviewer, reason, narrative fields. Deliberately not unique on the player-dimension key |
| `scout_criterion_scores` | assessment × criterion | Per-criterion 1–5 score or pass/fail |
| `watchlist` | player × league × season | Status and note; foreign key to `players` |

Derived tables are clear-then-insert (whole table, or per league-season for
`player_metrics_neutral`, `player_detail_metrics` and `player_position_shares`), so a re-run
rebuilds them exactly. User-data tables are read through LEFT JOINs so a rebuild never
drops a watched or assessed player.

## Metric provenance

`model/metric_registry.py` is the single list of metrics: 91 entries, each with exactly one
source. Populated today: **45 Impect** (`ingest/impect_map.py`, converted in
`impect_translate.py`) and **24 SkillCorner** (`ingest/skillcorner_map.py`). The other 22
registry columns belong to the legacy provider and are NULL in every row of
`player_metrics_neutral` (checked 2026-10-22).

**Impect derivation.** Impect gives per-match-equivalent averages, one row per position
played. A season total is `average × matchShare` summed over the player's position rows;
per-90 is total ÷ minutes × 90; ratios are computed from season totals. Players under 450
minutes are stored but not `rankable`.

**SkillCorner derivation.** Season per-match averages per player, mapped column-for-column.
SkillCorner covers 2025/26 and 2026/27 only, and has no Scottish Championship data, so
those league-seasons have no Physical dimension; the composite renormalises over the
dimensions present and records the weight covered.

**What is scored** (`model/club_framework.py`):

| Dimension | Source | Metrics | Weight (outfield, normalised) |
|---|---|---|---|
| Performance | Impect | Per-position list (`PERFORMANCE_METRICS`), resolved through `CLUB_SUCCESSOR`; 32 distinct Impect metrics across all positions | 36.4% (GK 50%) |
| Physical | SkillCorner | 7, same for every outfield position: distance, HSR count and distance, sprint count and distance, peak speed (p99 and top-5) | 27.3% (GK none) |
| Psychological | Scout assessment | Club criteria, 1–5 | 9.1% (GK 20%) |
| Medical Risk | Scout assessment | Band entered by a person; injury availability shown as evidence | 13.6% (GK 15%) |
| Financial Fit | Modelled | Fee, wage, contract | 9.1% (GK 10%) |
| Resale Potential | Modelled | Age curve, market value | 4.5% (GK 5%) |

So the objective ranking uses 39 metrics: 32 Impect + 7 SkillCorner. Within a dimension
metrics are equally weighted; each is a mid-rank percentile within league + season +
position group over rankable players (inverted for lower-is-better metrics), mapped to a
band by `3 + (percentile − 50) / 20`, clamped to 1–5. Full Back and Winger also have
archetype rows that score Performance on a subset of the list. Details and rationale:
`docs/methodology.md`.

The other 29 populated metrics are shown on player cards, Compare and the glossary but do
not move any score; nor do `player_detail_metrics` and `player_position_shares`.

## Data flow into the dashboard

The dashboard reads Postgres only. It never runs a pipeline stage.

- **Players** — candidate pool from `constrain.filters.build_candidates(all_leagues=True)`
  (built on `player_scores`, left-joined to valuations, wage tables and names from
  `player_metrics_neutral`), merged with `players` bio and `archetypes`; ranked on
  `player_scorecards.objective_composite` for the selected season, or optionally on
  `assessed_composite`. Sidebar filters and affordability gates run live on the cached
  frames; nothing is precomputed for a fixed budget. A pool with fewer than
  `MIN_PEERS_FOR_RANKING` (10) players is flagged as too thin to rank.
- **Squads & loans** — `transfermarkt_squads` + `player_loans`, with the last scored rating
  carried across.
- **Scout reports** — `scout_reports`, keyed for freshness on `scout_sync.digest`. Its
  Refresh button calls the sheet directly, so the dashboard container also mounts the
  read-only service-account key.
- **Assess / Sign-off** — write `scout_assessments` / `scout_criterion_scores` through
  `store.assessments`, then `model.assessed_refresh` updates `assessed_composite` on that
  player's scorecard rows. `objective_composite` is never touched by scout input.
- **Report** — `report.data` reads the same scorecard percentiles and assessment; it
  computes no new score.
- **Physical** — the club export tables; **Glossary** — `impect_definitions` plus
  `glossary_data`; **Watchlist** — `watchlist` joined to scores, injuries and contracts.

Pipeline-data caches refresh by themselves within ~30 s of any database write (the
`data_version()` token changes); user-written data within 60 s. No restart needed.

## Adding a league

1. **Event data** — add ONE line to `LEAGUES` in `lofc/leagues.py`:
   `Competition("<name>", <Impect competitionId>, new_competition_id(<Impect competitionId>))`.
   Its seasons (2024/25 on) come from Impect's catalogue on the next pull; ids, labels and
   names are derived from the registry. The competition must appear in the licence catalogue
   (`ip.getIterations`); calendar-year seasons ("2025") are skipped until a rule is agreed.
2. **Physical** — add a `SkillCornerTarget` per season if SkillCorner holds data for it
   (check it actually returns rows; the Scottish Championship lists editions but has none).
   Without it the league is scored on Performance alone.
3. **Transfermarkt** — add the league code, URL slug and `competition_id` to `LEAGUES` in
   `ingest/transfermarkt_efl.py`; the squad, loan and injury scrapes all iterate it. Confirm
   the squad-page headers match `REQUIRED_HEADERS` for the current season.
4. **Availability** — add the league's scheduled games to `SCHEDULED_GAMES` in
   `model/medical.py`, or availability is reported as unknown.
5. **Money** — valuation and the wage gate cover only `valuation.EFL_LEAGUE_IDS` and the
   leagues in `store/reference_data.WAGE_LEAGUE_ANCHORS`. A new league is ranked without
   Financial/Resale unless both are extended, and the wage reference tables are not
   rebuilt by the pipeline under `IMPECT_ONLY`; rebuild them deliberately and run
   `python -m lofc.model.wage_check` against published payrolls.
6. Re-run the pipeline. Percentiles, bands and peer pools are computed within whatever
   leagues exist; no scoring code changes.

A new season needs no change for Impect: the catalogue brings it in and the season rule
(`leagues.season_id_for`, 2024/25 = 317) gives its id, label and age date. Update
`LIVE_SEASON_ID` in `config.py`, and steps 2–3 for SkillCorner and Transfermarkt.

## Failures and the run record

Every pipeline step, and every league inside a league-by-league step, writes a row to
`pipeline_runs` (`store/runs.py`; one `run_id` per weekly run). In the Impect and SkillCorner
pulls, the combined table, position shares and style signals, a failing league is recorded
and the other leagues carry on (`runs.for_each_league`); the step exits 3 ("partial"), the run
continues and finishes partial, naming the failed leagues. A failed league keeps last week's
rows. Any other failure (migrations, ratings) stops the run. Provider calls retry transient
failures with backoff (`ingest/retry.py`). `python -m lofc.store.integrity` checks for orphan
rows, duplicate keys and possible duplicate player identities.

## Growth notes still relevant

- **One store is enough.** The working data is tens of thousands of structured rows;
  Postgres covers it. Raw provider files are reproducible from the APIs, so they stay on
  disk rather than in object storage.
- **Season aggregates only.** Both providers are pulled at season grain, so the platform
  cannot show what changed in a single match. Both expose per-match endpoints under the
  current licences; adding them means new player × match tables and must not feed the
  composite (see `plan/BUILD_PLAN.md`).
- **No cross-league ordering.** Percentiles are within league. Ranking players from
  different leagues on one list needs a league-strength adjustment that does not exist yet.
