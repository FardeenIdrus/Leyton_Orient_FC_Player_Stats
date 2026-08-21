# Architecture

> **STATUS (2026-08-17): current.** Scoring runs on **Impect + SkillCorner** (91
> metrics/player, 7 leagues); StatsBomb is retired from scoring and now only seeds player
> identity for the historical EFL seasons. Players are ranked on the club's **1–5 composite**,
> computed by a pipeline stage and stored in `player_scorecards`. The Streamlit app has been
> split from one 2,560-line file into focused modules (see Code layout) and now sits behind a
> **login gate**, with a scout-assessment form, evidence panel, sign-off queue and an opt-in
> assessed-ranking mode (see the `dashboard/` bullet in Code layout and the `users` /
> `scout_assessments` rows in Data model). `objective_composite` — the default ranking — is
> unaffected by any of it. For the full metric layer and per-metric provenance see
> **`docs/DATA_ARCHITECTURE.md`**; for the scoring method, `docs/methodology.md` §3b; for the
> scout-assessment design, `docs/superpowers/specs/2026-08-10-scout-assessment-design.md`.

## What this system is

A decision intelligence platform: it turns raw StatsBomb match data into a ranked
shortlist of affordable, on-profile, undervalued signings for Leyton Orient FC. The
core deliverable is the valuation and ranking model, not the infrastructure. The
infrastructure exists only to make that model reproducible and to put it in front of
a non-technical recruiter.

It currently runs on the real paid StatsBomb feed: Championship, League One, League
Two and National League, seasons 2024/25 and 2025/26 (8 league-seasons, 4,456
matches), enriched with scraped Transfermarkt market values and bio data, a modelled
league-aware wage grid, and the club's SkillCorner tracking export.

## The pipeline

```
Impect event data (14 league-seasons: EFL + Scottish Prem/Champ + PL2) + SkillCorner physical
  1 Ingest        Impect + SkillCorner pulled to disk, idempotent (skip-if-exists) EXCEPT the
                  live season (config.LIVE_SEASON_ID), which BOTH providers always re-pull
                  because their season figures are cumulative; a season with no matches yet is
                  skipped cleanly, so future seasons can be configured before kick-off; player
                  identity still seeded from StatsBomb line-ups during the migration
  2 Aggregate     -> one row per player x league x season, per-90 metrics
  3 Store         metrics + reference data loaded into Postgres (idempotent upserts)
  4 TM values     Transfermarkt squad-page scrape: market value, DOB, contract,
                  foot, height, TM id (rate-limited, idempotent)
  5 Score         within-position-and-league percentiles -> the club 1-5 composite (the
                  live ranking; the old Quality/Fit in player_scores are retired)
  6 Archetypes    k-means on playing style -> a labelled style cluster per player
  7 Valuation     dual-era Ridge regression -> out-of-fold fair value + undervaluation;
                  bio backfill onto players
  8 Wages         league-aware modelled wage grid with uncertainty bands, reconciled
                  against published payrolls (model/wage_check.py)
  8b Scorecard    the club's 1-5 composite -> player_scorecards (one row per player-season
                  per archetype). Runs after valuation/wages, before the shortlist.
  9 Shortlist     fee gate + wage gate -> ranked on the club objective composite
                  (the retired Style-fit no longer orders anything)
 10 SkillCorner   club tracking export -> squad physical identity + league benchmarks
                  (conditional step: runs when an export exists)
 11 Dashboard     the Streamlit app the recruiter actually uses
```

One command runs all of it: `python -m lofc.pipeline` (11 idempotent steps, safe to
re-run at any point). Per-stage commands are in `cli_commands.txt`.

## Runtime components (Docker Compose)

| Service | Image | Role |
|---|---|---|
| `db` | postgres:16 | single source of truth (metrics, scores, model outputs, reference data, user data) |
| `app` | built from `Dockerfile` | runs the pipeline and tests; the Python 3.11 environment |
| `dashboard` | same image | the Streamlit app at http://localhost:8501 (mounts `./data` read-only) |
| `pgadmin` | dpage/pgadmin4 | visual database browser at http://localhost:5050 |
| `metabase` | metabase/metabase | self-serve BI layer at http://localhost:3000 (the wider-BI growth path) |

Everything lifts onto a server as one unit with `docker compose up`. Target
competitions come from the `SB_COMPETITIONS` env var (`.env`), parsed at startup with
loud failure on malformed input; compose injects `.env` at container start, so re-up
after editing it.

## Code layout (`src/lofc/`)

- `config.py` — settings via pydantic-settings: database URL, open-data/paid switch
  (`USE_OPEN_DATA`, `SB_USERNAME/PASSWORD`), target competitions (`SB_COMPETITIONS`).
  Credentials never live in code.
- `ingest/`
  - `statsbomb.py` — API/open-data access (one code path, config decides).
  - `landing.py` — idempotent raw JSON I/O (atomic temp+rename writes; skip-if-exists).
  - `run.py` — pull orchestrator (`--competition`, `--limit`, `--force`); refuses to
    persist transient empty API payloads so a re-run retries them.
  - `transfermarkt.py` — demo-era market values (dcaribou dataset).
  - `transfermarkt_efl.py` — the EFL scraper: detailed club squad pages
    (kader/plus/1) for the four covered leagues; market value, date of birth,
    contract end, preferred foot, height, TM player id; 2.5s request delay,
    idempotent, `--force` to re-pull. Output is licensed data: gitignored.
  - `skillcorner.py` — loads the club's tracking export (xlsx) into Postgres.
- `aggregate/` — `events.py` (per-match minutes from lineup spells, period-aware;
  per-match metrics), `player_season.py` (season roll-up, per-90, rankable flag),
  `run.py`.
- `store/` — `models.py` (SQLAlchemy schema, versioned by Alembic), `load.py`
  (idempotent loaders; derived tables are clear-then-insert), `watchlist.py`
  (user-data persistence, plain Core so it runs on Postgres and the sqlite used in
  tests), `reference_data.py` (builds the wage/identity stand-ins with provenance),
  `injuries.py` (Transfermarkt injury CSV → `player_injuries`, clear-then-insert on
  `source='transfermarkt'` only, so hand-entered rows survive a re-scrape), `users.py`
  (account creation/authentication reads used by the dashboard and `lofc.admin`;
  password rules and hashing live in `dashboard/auth.py`, not here), `assessments.py`
  (reads and writes `scout_assessments`/`scout_criterion_scores` — one submitted or
  signed-off row per assessor per player-season-dimension; drafts and prior submissions
  are never overwritten, only superseded per Decision 17).
- `model/` — `normalise.py` (percentiles), `score.py` (Quality + Fit),
  `archetypes.py` (style clustering), `valuation.py` (dual-era fair value + bio
  backfill), `wage_check.py` (squad-bill reconciliation vs published payrolls),
  `run.py`.
- `model/medical.py` — injury-evidence math for the Medical dimension: `availability_with_evidence()`
  returns an explicit `MEASURED` / `CONFIRMED_BY_MINUTES` / `UNKNOWN` status alongside the value
  (an unknown record is never a confident 1.0), `games_missed_in_window()` merges overlapping
  injury spells before counting. Feeds the evidence panel only — Medical itself is a
  human-entered band (Decision 12), never computed from this.
- `model/club_criteria.py` — the club's per-position Psychological and Medical criteria,
  transcribed verbatim from the club document. `model/scout_scores.py` — `resolve_bands()`:
  the Decision 17 conflict rule (a signed-off assessment always wins; two or more unsigned
  assessments disagreeing on the same dimension score nothing, status `CONFLICT`, until
  someone signs one off). `model/assessment_rules.py` — the 1–5 band labels and screening-warn
  logic (Decision 13: a failed criterion warns, never overrides the entered band).
  `model/assessment_status.py` — derives one aggregate status (`Not assessed` / `Awaiting
  sign-off` / `Assessments conflict` / `Signed off`) per player-season for the watchlist and
  Players list, so the two can never disagree by reading different sources.
  `model/assessed_refresh.py` — recomputes `assessed_composite` on `player_scorecards` after an
  assessment is saved or signed off.
- `constrain/` — `filters.py` (fee/wage/profile gates, ranking, near-misses),
  `run.py`.
- `model/scorecard_run.py` — the pipeline stage that **persists** the composite to
  `player_scorecards` (clear-then-insert, idempotent), so the dashboard, the offline shortlist
  and the BI layer all read the same numbers instead of the dashboard computing its own.
- `model/club_framework.py` + `model/scorecard.py` + `model/financial_resale.py` — the
  club's own recruitment framework (per-position metric lists, dimension weights, the five
  objective decisions) and the 1–5 composite scorecard engine (two composites: objective =
  Performance + Physical from real data; full = adds modelled Financial + Resale). Computed
  live in the dashboard from stored data; gates are advisory (never exclude). See
  `docs/methodology.md` §3b.
- `dashboard/` — the Streamlit app, split into focused modules (was one 2,560-line file):
  `app.py` (entry point: page setup, sidebar, page wiring) · `theme.py` (brand colours, CSS,
  header) · `labels.py` (metric names, provenance, glossary text) · `charts.py` (Plotly
  builders) · `seasons.py` (season identity + contract horizons) · `loaders.py` (every cached
  DB read) · `controls.py` (synced sidebar widgets) · `auth.py` (password hashing/verification,
  role permissions via `can(role, action)`, login-throttle and session-expiry logic — pure
  functions, unit-tested without Streamlit) · `session.py` (the login gate `require_login`, the
  logged-in `CurrentUser`, and the `CarriedPlayer` handoff that lets "Assess this player"
  navigate to the Assess page with the player already selected) · `badges.py` (one status-badge
  renderer used everywhere an assessment's state appears, so a watchlist row and a profile row
  can never disagree) · `evidence.py` (the injury/availability evidence panel, rendered
  identically on the player profile and the assessment form) · `transparency.py` (the
  "what this covers, and what it doesn't" disclosure panel, spec §10) · `tabs/` (one module per
  page: players, compare, watchlist, assess, signoff, player_types, physical, glossary,
  methodology).
  **Dependencies run one way** — theme/labels → charts → loaders → controls → session → tabs →
  app (documented in `app.py`'s module docstring) — so the layers cannot form import cycles;
  `st.switch_page` needs a live `st.Page`, which only `app.py` builds, so `session.py` exposes
  `register_pages`/`switch_to` for a tabs/ module to navigate without importing `app.py` back.
  Navigation runs on **`st.navigation` pages, not `st.tabs`** — the login gate returns before
  `st.navigation(...)` is even constructed, so an unauthenticated visitor sees the sign-in form
  and nothing else. The pages are **Players**, Compare, Watchlist, **Assess**, **Sign-off**,
  Player types, Physical, **Glossary**, Methodology. **Assess** is the scout-assessment form
  (the club's per-position criteria, Psychological scored 1–5 per criterion, Medical entered as
  a band with the evidence panel beside it); **Sign-off** is the approval queue, which also
  surfaces and resolves conflicts (Decision 17) — any user with `sign_off` permission
  (`head_of_recruitment`/`admin`) can sign off one of two disagreeing assessments, enter and
  sign off their own, or leave it contested. **Compare** charts players on the club's Performance metrics
  (archetype-aware, from the scorecard percentiles) — the same stats as the composite, not the
  retired role metrics — plus a **raw physical output table** (SkillCorner per-90) that, being
  raw, is directly comparable across leagues (unlike the within-league percentile radar). Age is
  derived from `players.birth_date` at the season midpoint (all leagues, ~99% coverage), not the
  EFL-only valuations table. A **Contract expiry** selector (`CONTRACT_HORIZONS` + the testable
  `contract_mask()`) filters the free-transfer market; contract dates come only from the
  Transfermarkt scrape, so the UI shows the snapshot date and the count of players hidden for
  having no known expiry. **Affordability is opt-in** (a sidebar toggle): the transfer-budget and
  wage-ceiling controls, the affordability KPI, and money columns appear only when it is on, and
  they never reorder the default ranking (which is the objective composite). The **Players** workspace (master-detail) merged the former
  Shortlist + Club scorecard + Player profile tabs: a composite-ranked list (objective
  composite, within-season) with, on click or search, a full player detail — dimension scores
  + the club-framework grand table (Source · Season total · Per-90 · Percentile · Band) +
  charts on the club per-position (archetype) metrics. **Every ranking uses the club's 1–5
  composite** (`model/scorecard.py`); the invented Style-fit is retired. **Money is an opt-in
  layer** (off by default). Players also carries an opt-in **"Rank on assessed composite"**
  toggle (off by default): switches the ranking column to `assessed_composite`, filtered to
  players with both scout dimensions assessed, with the status badge shown beside every row.
  The **Glossary** tab is the single searchable home for metric
  definitions (each with its exact definition and, for a substitute, the StatsBomb stat it
  stands in for); definitions no longer sit on the player card.
- `pipeline.py` — runs every stage end to end.

## Data model (Postgres)

| Table | Grain | Filled by | Notes |
|---|---|---|---|
| `players` | one per player | aggregate; bio backfilled by valuation | carries `birth_date`, `foot`, `contract_until`, `height_cm`, `tm_player_id` |
| `player_season_metrics` | player × league × season | aggregate | ~47 metric columns + `rankable` (≥450 min) |
| `player_percentiles` | player × league × season × metric | score | within-position AND within-league |
| `player_scores` | player × league × season | score | Quality + Fit, 0–100 — **retired**, ranks nothing |
| `player_scorecards` | player × league × season × **archetype** | scorecard_run; `assessed_composite` updated by `model/assessed_refresh.py` | **the live ranking model**: the club's 1–5 bands + `objective_composite` (real data, the default ranking) and `full_composite` (adds modelled money), advisory veto flags. Also carries `assessed_composite`/`assessed_weight_covered`/`psychological_band`/`medical_band` — Performance + Physical + Psychological + Medical, 86% of outfield weight, populated once both scout dimensions are assessed for that player; NULL until then, and never read by `objective_composite` |
| `archetypes` | player × league × season | archetypes | cluster id + auto-generated label + centroid distance |
| `valuations` | player × league × season | valuation | market value, out-of-fold fair value, undervaluation, age, model version. 2025/26 EFL rows only (see methodology) |
| `wage_framework` | position × age band | reference data | the club ceiling stand-in |
| `wage_estimates` | league × position × age band × tier | reference data | modelled weekly wage + low/high band (×0.7/×1.4) |
| `identity_profiles` | position × metric | reference data | the old Fit weights + floors — **retired** from the live ranking (superseded by the club framework in `club_framework.py`) |
| `shortlists` | player × league × season | constrain | rank (**on `objective_composite`**), gate flags, near-miss flag |
| `skillcorner_team_season` | club × season | skillcorner | all 24 League One clubs, physical per-90s |
| `skillcorner_player_season` | player × season | skillcorner | LOFC squad only (21 players, DOB+name matched to StatsBomb ids) |
| `watchlist` | player × league × season | **the user** | status, free-text note, timestamps. USER DATA — see below |
| `users` | one per account | `lofc.admin` CLI only (`create-user`/`set-password`) | username, full_name, role, scrypt `password_hash`, `is_active`, failed-login/lockout state. No email column — there is no self-service or email password reset by design |
| `player_injuries` | one per injury spell | `store/injuries.py` (Transfermarkt scrape) or entered by hand via the evidence panel | `source` (`transfermarkt`/`manual`), `entered_by` (null when scraped), category, dates, days out, matches missed. Feeds `model/medical.py`'s availability evidence — never a score on its own |
| `scout_assessments` | player × league × season × dimension × **assessor** | `store/assessments.py`, written by the Assess page | not unique on that key — several assessors may hold `submitted` rows for the same player-dimension; at most one may be `signed_off`. `status` (`draft`/`submitted`/`signed_off`), `band`, `approved_by`, `approved_at`. Resolved by `model/scout_scores.resolve_bands()` (Decision 17) into what actually scores |
| `scout_criterion_scores` | one per assessment × criterion | `store/assessments.py` | the per-criterion 1–5 score (Psychological) or pass/fail (Medical screening) behind each assessment's band |

Schema lives in `store/models.py`; every change goes through an Alembic migration.

### The grain invariant (learned the hard way)

Everything downstream of aggregation is keyed by **(player_id, competition_id,
season_id)** — not by player alone — because a mid-season mover between tracked
leagues legitimately holds two rows in the same season (e.g. a January transfer from
League Two to the National League). Any per-player view must either key by the full
triple or dedupe deliberately. Three separate production bugs (a profile crash, an
on-profile gate miscount, duplicated rows in the Physical tab) were all this one
pattern violated in different places; all are fixed at the root and regression-tested.

### Derived data vs user data

Pipeline outputs (`percentiles`, `scores`, `archetypes`, `valuations`, `shortlists`)
are **clear-then-insert**: a re-run rebuilds them exactly, and re-targeting leagues
leaves no orphan rows. The `watchlist` table is the opposite: it is **user data**,
never touched by any pipeline step, protected by a foreign key (a watched player
cannot be swept), and read via LEFT JOINs so a watched player survives a rebuild with
blanks rather than vanishing. This guarantee is tested and was verified in the wild
(a real entry survived a full end-to-end rebuild).

### The two data eras

The valuation layer runs two eras that never mix: the original 2015/16 demo trio
(dcaribou dataset values) and the live EFL era (our own scrape, current-snapshot
values, priced against 2025/26 output only). Each era trains its own model, because
price levels a decade apart would poison a shared fit. The rest of the pipeline is
era-agnostic: whatever `SB_COMPETITIONS` targets flows through identically.

## Data flow into the dashboard

The dashboard reads the stored model outputs (`player_scores`, `valuations`,
`archetypes`, `player_percentiles`, wage tables, SkillCorner tables, `watchlist`) and
calls the constrain filter (`constrain/filters.py`) **live** with the sidebar
controls (transfer budget, wage ceiling, minutes, max age, leagues, contract status,
foot). Nothing is precomputed for a fixed budget; moving a slider re-runs the filter
against stored outputs. The candidate pool is the inner join of scores and
valuations — which is why an unvalued player is invisible to the shortlist (the
cross-league loanee fix of 2026-07-06 exists because of exactly this).

Loaders are cached (`st.cache_data`) — restart the dashboard container after a
pipeline re-run to pick up fresh data.

## Tech choices (and why)

- **Python + pandas/numpy/scikit-learn** — named in the brief; the right tools for
  aggregation, regression and clustering.
- **PostgreSQL** — structured player-season data at this scale is thousands of rows;
  SQL is on the JD; one store is enough (see `scaling.md` for what would change that).
- **Streamlit** — ships the model and UI as one deployable app, readable by a
  non-technical user, no licensing tie to the club server.
- **Docker + Alembic + pydantic-settings** — reproducible, versioned, credentials out
  of code.
- **beautifulsoup4/lxml** — the TM scraper; **openpyxl** — the SkillCorner export.

Tools deliberately left out of v1 (MongoDB, MinIO, Power BI/Tableau) and the
conditions that would justify adding them are documented in `scaling.md`.

## Verification approach

- **60 pytest tests**, no network, sqlite standing in where a DB is needed.
- The dashboard is verified headlessly with Streamlit's **AppTest** (the full script
  must run with zero exceptions) after every UI change — there is no browser in the
  automated loop.
- Aggregates are spot-checked against external reality (published golden-boot tables:
  exact in the Championship and League One).
- The wage grid is reconciled in aggregate against published squad payrolls
  (`python -m lofc.model.wage_check`).
- Before the demo freeze, a sweep held 10 SQL invariants at zero (no duplicate rows,
  no null ages, no negative fair values, no inverted wage bands, no out-of-range
  scores, no unlabelled archetypes, no unmatched SkillCorner players, every
  shortlisted player linked to TM, no qualifying row off-profile).

## Reproducibility

- `docker compose up` brings up the whole stack.
- `python -m lofc.pipeline` populates a fresh database end to end (idempotent; certified
  full runs are recorded in the frozen build log, `plan/HISTORY.md`).
- Alembic migrations recreate the schema; `requirements.lock` pins exact versions.
- Raw data and model outputs are reproducible from source, so they are gitignored —
  as are the scraped Transfermarkt values and the SkillCorner export (licensed data,
  never public).
