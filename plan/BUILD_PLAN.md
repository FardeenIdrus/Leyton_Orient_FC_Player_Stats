# LOFC Recruitment Platform — BUILD PLAN

> **THIS FILE IS THE SINGLE SOURCE OF TRUTH.**
> It holds the full plan, every decision, and live progress. We update it and tick
> off tasks `[x]` as we go. Any new chat: **read this file first.**
>
> - `plan/LOFC_Recruitment_Platform_Build_Plan.md` = the original brief (frozen, never edited).
> - `CLAUDE.md` = a short auto-loaded pointer back to this file.
> - There is no other plan/progress file.

---

## ▶ STATUS AT A GLANCE

- **Current phase:** Phase 5 complete ✅ → **next up: Phase 6 (Valuation)**
- **Workflow rule:** I pause at the start of each phase, show the plan, and wait for
  your explicit go-ahead before building. After a phase passes its acceptance
  criteria, we checkpoint here before the next phase starts.
- **Last updated:** 2026-06-05

| Phase | Name | Status |
|---|---|---|
| 0 | Scaffold | ✅ Complete (verified) |
| 1 | Ingest | ✅ Complete (verified) |
| 2 | Aggregate | ✅ Complete (verified) |
| 3 | Store | ✅ Complete (verified) |
| 4 | Normalise & Score | ✅ Complete (verified) |
| 5 | Archetypes | ✅ Complete (verified) |
| 6 | Valuation | ⬜ Not started |
| 7 | Constrain & Rank | ⬜ Not started |
| 8 | Dashboard | ⬜ Not started |
| 9 | Package & Document | ⬜ Not started |

---

## 1. Context & objective

Build an end-to-end platform that turns StatsBomb player data into a ranked shortlist
of **affordable, on-profile, undervalued** signings for Leyton Orient FC. This is a
*decision* intelligence platform — the core IP is the **valuation + ranking model**,
not the infrastructure. Built phase-by-phase with Claude Code as a high-stakes
interview deliverable for an LOFC BI/recruitment internship.

Pipeline: StatsBomb data → Ingest → Aggregate → Store → Normalise/Score → Archetypes
→ Valuation → Constrain/Rank → Serve (Streamlit) → Deploy (Docker).

---

## 2. Locked decisions (verified — do not re-litigate without reason)

| # | Decision | Outcome | Why |
|---|---|---|---|
| 1 | **Data source** | StatsBomb **free open data** now; paid API is a config swap later (`USE_OPEN_DATA`, `SB_*`) | User has no paid creds. Verified: free tier has **no LOFC/EFL data** (24 comps, nothing below the PL). |
| 2 | **Demo competitions** | The **three complete 2015/16 leagues**: Premier League (2,27), La Liga (11,27), Serie A (12,27) — ~1,500 players | Verified: no complete *recent* men's club league is free (Bundesliga 23/24 = 34 matches). These are the only full 380-match seasons. Vintage doesn't affect methodology. |
| 3 | **Cross-league fairness** | Normalise within position **AND** within league; raw cross-league comparison is a documented future extension | Pooling leagues into one percentile ranking is wrong (90th pct Serie A ≠ PL) and a knowledgeable CEO would catch it. |
| 4 | **Wage framework** | Build our own, anchored in real EFL SCMP rules + LOFC finances; labelled as modelled, swappable for the real doc | No public LOFC wage doc exists. Real anchors are more defensible than guesses (see §3). |
| 5 | **Valuation target (market value)** | **Locked: Transfermarkt market values via the maintained Kaggle dataset** (`davidcariboo/player-scores`, CC0). Join Transfermarkt `players` (name, DOB, club) to `player_valuations` (dated value) on `player_id`, then to StatsBomb players by **name + date of birth + season** (club as tiebreaker) with fuzzy matching. Dataset lands in `data/reference/`. | StatsBomb has no fees/values. Verified: the Kaggle set covers PL/La Liga/Serie A 2015/16 with dated historical values and has the columns to join. **It does NOT cover League One**; for real LOFC data later, pull GB3 values with the same `dcaribou/transfermarkt-scraper` (identical schema, joins cleanly). Kaggle avoids scraping for the demo (rate limits / ToS). |
| 6 | **Docs** | This file = single source of truth; brief frozen; `CLAUDE.md` = auto-loaded pointer | Avoids the file-proliferation confusion. One living doc. |

---

## 3. Wage-framework anchors (for Phase 3 — recorded now)

- **Hard ceiling = EFL SCMP:** League One caps wages at **50% of turnover** (voted down
  from 60%, Dec 2024). LOFC turnover ~£7.7m (2023/24) → **~£3.5–4m** wage pool. *(FACT)*
- LOFC market position: top earners ~£6,000–6,500/wk, squad floor ~£200–1,000/wk. *(ESTIMATE — Capology/SalarySport)*
- Position multipliers (attackers highest → full-backs/squad GKs lowest); age band peaks ~27–31. *(ESTIMATE)*
- **U21 academy graduates are SCMP-exempt** — cheaper *and* outside the cap = the key value lever.
- **Honest caveat (write into `docs/methodology.md`):** filtering top-5-league players
  against League One ceilings means almost none are "affordable", so on demo data the
  affordability filter is *demonstrative* (slider-driven) while the
  performance/archetype/valuation engine is the valid output. The filter becomes binding
  on the club's real comparable-tier targets via the live API.
- **Design decision (Phase 7 + 8): the wage ceiling is adjustable, not a fixed number.**
  Provide BOTH a slider AND a number field where the user types an exact budget (the two
  stay in sync). On the free top-league demo data, raise it to show the filter working;
  on real lower-league data via the paid API, set it to LOFC's actual ceiling and it
  bites correctly. Default to LOFC's real ceiling so the limitation is honest, and let
  the user change it. The point of the tool for a small-budget club is the undervaluation
  engine: find cheap players who outperform their price (the Vardy case).
- **Design decision (Phase 7 + 8): never show a blank screen.** If a filter returns zero
  players, show the closest near-misses instead ("no exact matches; here are the 5
  closest"), so a demo or a tight budget never looks broken.

---

## 4. Tech stack

Python 3.11 (in Docker) · statsbombpy · pandas/numpy · scikit-learn · PostgreSQL 16 ·
SQLAlchemy + Alembic · Streamlit · Docker / docker-compose · pydantic-settings · pytest.
*Excluded from v1 (documented in `docs/scaling.md`): MongoDB, MinIO, Power BI/Tableau.*

---

## 5. Repo structure

```
lofc-recruitment/
├── CLAUDE.md                  auto-loaded pointer to this file
├── README.md                  run instructions
├── pyproject.toml · Dockerfile · docker-compose.yml · .env.example · .gitignore
├── alembic/                   migrations (env wired to DATABASE_URL)
├── src/lofc/
│   ├── config.py              pydantic-settings (target competitions live here)
│   ├── ingest/                statsbomb.py, landing.py            (Phase 1)
│   ├── aggregate/             events.py, player_season.py         (Phase 2)
│   ├── store/                 models.py, schema.sql, load.py      (Phase 3)
│   ├── model/                 normalise.py, score.py, valuation.py, archetypes.py (4–6)
│   ├── constrain/             filters.py                          (Phase 7)
│   └── dashboard/             app.py                              (Phase 8)
├── tests/                     pytest
├── data/{raw,reference}/      landed payloads (gitignored) / club docs
├── docs/                      architecture.md, methodology.md, scaling.md
└── plan/                      THIS FILE + the frozen brief
```

---

## 6. Coding conventions (apply to all phases)

These rules apply to every file we write. Add new rules here as they come up.

1. **Comments are clear and concise.** Write plain English. State the point directly.
   - No em dashes. Use a period, comma, colon, or parentheses instead.
   - No vague AI filler words (for example: robust, seamless, leverage, comprehensive,
     powerful, cutting-edge, elegant). Say the concrete thing instead.
   - Comment the "why", not the obvious "what". Skip comments that just restate the code.

## 7. The phased plan (tick off as we go)

> Each phase ends in a working, testable slice. **Do not start a phase until the
> previous one's acceptance criteria pass AND the user has approved starting the next.**

### Phase 0 — Scaffold ✅ COMPLETE (verified 2026-06-02)
- [x] Repo structure + stub modules (brief §5)
- [x] `pyproject.toml` (deps + dev group)
- [x] `config.py` (pydantic-settings; open-data default; the 2015/16 trio)
- [x] `Dockerfile` (python:3.11-slim, non-root)
- [x] `docker-compose.yml` (app + postgres:16, healthcheck, volume)
- [x] `.env.example`
- [x] Alembic (env wired to `DATABASE_URL`; empty `0001_baseline`)
- [x] `.gitignore`, `README.md`, `CLAUDE.md`
- [x] pytest smoke test
- **Acceptance — all passing:** ① `docker compose up` → both services, db healthy ✓
  ② config loads from `.env` (open-data mode) ✓ ③ `alembic upgrade head` clean, stamps
  `0001_baseline` (confirmed in Postgres) ✓ ④ `pytest` → 2 passed ✓ ⑤ `cp .env.example
  .env` + `up` reproduces ✓
- **Note:** pip resolved current majors (pandas 3.0, numpy 2.4, sklearn 1.9, statsbombpy
  1.18) vs lower-bound pins — no conflicts. Revisit a lock file at Phase 9.

### Phase 1 — Ingest ✅ COMPLETE (verified 2026-06-05)
- [x] `statsbombpy` open-data pulls for the three competitions (competitions, matches, events, lineups)
- [x] Land raw payloads idempotently under `data/raw/` (skip-if-exists; atomic temp+rename write)
- [x] Authenticated-API swap behind config (creds passed only in API mode; open data otherwise)
- [x] Documented, repeatable pull command (`python -m lofc.ingest.run`, flags `--competition` / `--limit` / `--force`)
- [x] Idempotency unit tests (no network)
- **Modules:** `ingest/statsbomb.py` (access), `ingest/landing.py` (idempotent JSON I/O), `ingest/run.py` (orchestrator).
- **Acceptance — all passing:** ① one command pulls a full league end to end ✓ ② re-run skips everything (PL: pulled=0 skipped=380) ✓ ③ raw files inspectable (nested events, lineups) ✓ ④ ingest unit tests pass (6) ✓
- **Result:** all 3 leagues landed — 1,140 matches (380 each), 1,140 events + 1,140 lineups files, 0 leftover temp files, 2.6 GB under `data/raw/` (gitignored). Events kept nested (`flatten_attrs=False`). Lineups pulled too (Phase 2 needs them for minutes). `raw_events` JSONB deferred (filesystem meets the goal).

### Phase 2 — Aggregate ✅ COMPLETE (verified 2026-06-05)
- [x] Event → player-match metrics; **minutes derived from lineup position spells**, period-aware (the clock resets to 45:00 each half, so spells crossing half-time use each period's real length)
- [x] Player-match → player-season per position group, carrying the league dimension; dominant position = most minutes
- [x] Per-90 for counting stats; pass% / dribble% / save% ratios; **non-penalty goals + xG**; **xA** via shot→key-pass link; basic GK set (saves, goals conceded, save%)
- [x] Minutes threshold: `rankable` flag at >= 450 min (small samples kept but flagged)
- [x] Unit tests on minutes, period reset, position map, metrics, xA (5 tests)
- [x] Spot-check vs known figures
- **Modules:** `aggregate/events.py` (per-match extraction), `aggregate/player_season.py` (season roll-up + per-90), `aggregate/run.py` (CLI → `data/processed/`).
- **Acceptance — all passing:** ① player-season table produced ✓ ② tests pass (11 total) ✓ ③ spot-checks match reality exactly ✓
- **Spot-check results (goals match real 2015/16 totals):** PL — Vardy 24, Kane 25, Agüero 24, Lukaku 18, Mahrez 17. La Liga — Suárez 40, Ronaldo 35, Messi 26. Serie A — Higuaín 36, Dybala 19. Pass-completion leaders are CBs / holding mids as expected.
- **Result:** `data/processed/player_season_metrics.{parquet,csv}` — 1,640 player-seasons, 47 columns, 3 leagues (PL 550, La Liga 539, Serie A 551). Gitignored (derived from raw).
- **Assumptions baked in:** minutes include stoppage time (a full ever-present season can exceed 3,420 min); one dominant position per player-season; per-90 scaling; age not present (arrives via Transfermarkt in Phase 6); progressive pass/carry use fixed metre thresholds (15 / 10).

### Phase 3 — Store ✅ COMPLETE (verified 2026-06-05)
- [x] SQLAlchemy models for the 4 tables we can fill now (players, player_season_metrics, wage_framework, identity_profiles); downstream tables added in their phases
- [x] Alembic migration (autogenerated from models, applied clean)
- [x] Idempotent upsert loaders (`store/load.py`); re-run gives identical counts
- [x] Constructed reference data built by `store/reference_data.py` with provenance, reviewed by user before loading
- [x] pgAdmin added (http://localhost:5050, LOFC server pre-listed, password `lofc`)
- [x] Tests (5): wage grid complete + peaks in prime, identity weights sum to 1.0, metrics reference real columns
- **Acceptance — all passing:** ① all 4 tables queryable in Postgres ✓ ② loaders idempotent (re-run = same counts) ✓ ③ reference data populated ✓ ④ SQL spot-check returns Vardy from the DB ✓
- **Result in Postgres:** players 1622, player_season_metrics 1640, wage_framework 40, identity_profiles 51. 16 tests total pass.
- **Reference data (constructed stand-ins, see `data/reference/README.md`):** wage ceilings anchored to the EFL 50%-of-turnover cap + LOFC accounts (fact) and Capology/SalarySport top-earner estimates (~£6.5k/wk), position/age shape assumed. Identity profiles are a football-reasoning construction (hard-working, progressive, press-resistant). Both swappable for the club's real files.

### Phase 4 — Normalise & Score ✅ COMPLETE (verified 2026-06-05)
- [x] Within-position **and** within-league percentiles (rankable players only), in `model/normalise.py`
- [x] **Two scores** in `model/score.py`: Performance (broad role-relevant stats, equal weight, data-only) and Fit (identity-weighted, focused, configurable). Both 0-100, ranked within position + league.
- [x] Persisted to `player_percentiles` + `player_scores` (idempotent), orchestrated by `model/run.py`
- [x] Tests (5): percentile ranking, rankable-only, NaN drop, performance mean, fit weighted sum, rank order
- **Why two scores:** a recruiter asks "is he good?" (performance, real) AND "does he fit us?" (fit, our identity). Bundling them hides the difference. Performance = objective; Fit = our constructed identity, clearly labelled and swappable.
- **Acceptance — all passing:** ① every rankable player has percentiles + both scores ✓ ② spot-checks sensible ✓
- **Spot-check results:** PL centre-forwards by performance topped by Iheanacho/Welbeck/Agüero/Kane; **Vardy ranks higher on fit than performance** (elite at goals+pressing, the identity we value). Defensive mids by fit: **Kanté 3rd** (7th by performance) alongside Coquelin, Lucas Leiva, Fernandinho — the fit score correctly surfaces ball-winners. The split works on real data.
- **Result in Postgres:** player_percentiles 32,285, player_scores 1,241 (rankable players across 3 leagues). 21 tests total pass.
- **Known characteristic:** per-90 + a 450-min floor can let a strong young sub (Iheanacho, Kevin Stewart) top a per-90 ranking. Defensible, worth surfacing minutes alongside scores in the dashboard.

### Phase 5 — Archetypes ✅ COMPLETE (verified 2026-06-05)
- [x] Standardise then PCA (~90% variance); k-means on the components, in `model/archetypes.py`
- [x] **Style not quality:** centre each player on their own average percentile first, so clusters capture relative strengths (style), not overall level
- [x] k-means per position (pooled across leagues); silhouette score per k logged; best k chosen automatically
- [x] Auto-generated label per cluster from its standout metrics; distance-to-centroid stored
- [x] Stability: fixed random_state, tested identical assignments across runs
- [x] Limitation + upgrade path documented (hard labels now, GMM soft assignment next) in the module docstring
- [x] Tests (4): within-player centering, two clear styles split, stability, label names the standout metric
- **Acceptance — all passing:** ① every rankable player has a cluster + readable label ✓ ② labels are football-sensible ✓
- **Validation (labels were auto-generated, not hand-written):** Centre Back split into ball-players (Fonte, Koscielny, Sakho) vs stoppers (Prödl, Ogbonna, Mbemba); Centre Forward into goalscorers (Vardy, Kane, Iheanacho) vs link/work forwards (Walters, Origi); Winger into creators (Willian, Redmond) vs goal-threat (Pedro, Arnautović). The classic positional archetypes, found by the data.
- **Result in Postgres:** archetypes 1,241; k=2-3 per position. Silhouettes 0.16-0.29 (modest, honest — styles are a continuum). 25 tests total pass.

### Phase 6 — Valuation ⬜
- [ ] Load Transfermarkt values (Kaggle `davidcariboo/player-scores`) from `data/reference/`; take each player's value at the 2015/16 season date
- [ ] Join values to players by **name + date of birth + season** (club as tiebreaker), fuzzy matching; log unmatched players, never fail silently
- [ ] Target = **log(market value)** (skew); back-transform for the fair-value estimate
- [ ] Features = normalised performance metrics PLUS age, position group, minutes (omitting age makes the model flag old players as "cheap")
- [ ] Model = Ridge regression (defensible coefficients); gradient boosting documented as an upgrade if the linear fit is poor
- [ ] Undervaluation score = residual (actual value below model-implied); persist with model version
- [ ] Report R² and MAE on a held-out split
- [ ] Test: a synthetic deliberately underpriced player gets flagged as undervalued
- [ ] Write up methodology in `docs/methodology.md`
- **Acceptance:** valuations stored; undervalued players surface sensibly; methodology documented.

### Phase 7 — Constrain & Rank ⬜
- [ ] Filter candidates vs wage ceiling + identity thresholds; rank into `shortlists`; persist
- [ ] Wage ceiling passed in as a parameter (not hardcoded), so the UI can drive it
- [ ] Near-misses fallback: if zero players pass, return the N closest instead of nothing
- **Acceptance:** every shortlisted player is affordable + on-profile; ranking reproducible from stored data; a too-low budget returns near-misses, never an empty result.

### Phase 8 — Dashboard ⬜
- [ ] Streamlit app: position selector, shortlist table, player profile (percentile bars),
      comparison view; wired to Postgres
- [ ] Budget control: a slider AND a typed number field, kept in sync, defaulting to LOFC's real ceiling
- [ ] Show closest near-misses when a filter returns zero players (no blank screen)
- **Acceptance:** a non-technical user selects a position and reads a shortlist; profile + comparison work; budget slider/number update live; zero-match shows near-misses.

### Phase 9 — Package & Document ⬜
- [ ] Finalise Docker so the whole stack deploys as one unit
- [ ] Complete `docs/architecture.md`, `methodology.md`, `scaling.md` (Mongo/MinIO/BI path)
- [ ] README run instructions; consider a dependency lock file
- **Acceptance:** fresh clone runs end-to-end with `docker compose up` + a documented ingest→dashboard sequence.

---

## 8. AI-native workflow note (brief §10 — interview evidence)

Running record of where Claude Code accelerated the build vs needed correction.

- **Planning:** verified data assumptions directly against the StatsBomb open-data repo
  rather than trusting the brief — caught that no LOFC/EFL data is free and that recent
  men's leagues are only partial samples, forcing the complete-2015/16 choice. Surfaced
  the cross-league normalisation trap and the affordability-filter caveat pre-code.
- **Phase 0:** scaffolded the full stack; self-corrected a `Competition`-as-BaseSettings
  slip before it could cause env-loading bugs. All acceptance checks passed first run.
- **Valuation source (planning):** verified the Transfermarkt Kaggle dataset before
  locking it. Confirmed it covers PL/La Liga/Serie A 2015/16 with dated historical values
  and the join columns, but caught that it does NOT cover League One, so the real-data
  path needs a separate GB3 scrape. Stopped an inaccurate assumption entering the plan.
- **Phase 1:** verified the statsbombpy API and network egress inside the container before
  writing the wrapper, so the ingest code was correct first run. Pulled all 1,140 matches;
  idempotent skip confirmed at full scale (re-run skipped 380/380). Two zsh gotchas hit and
  fixed in throwaway shell checks (`status`, `path` are reserved), no impact on code.
- **Phase 2:** inspected the real lineup/event files first and caught that the match clock
  resets at half-time, so minutes had to be period-aware (a naive subtraction undercounts
  cross-half spells by the first-half stoppage). Validated the whole pipeline by spot-check:
  goals matched the real 2015/16 totals exactly across all three leagues (Vardy 24, Suárez
  40, Higuaín 36, etc.), strong evidence the aggregation is correct, not just plausible.
- **Phase 3:** autogenerated the migration from the ORM models (no hand-written DDL). Built
  the constructed reference data as a documented generator (not hand-typed CSVs) with an
  assertion that identity weights sum to 1.0, and a test that every profile metric maps to a
  real column. Paused to show the user the wage/identity numbers before loading. Hit a pgAdmin
  first-boot error (`.local` is a reserved email domain) and fixed it. Was explicit about
  provenance throughout (which figures are fact vs estimate vs assumption).
- **Phase 4:** long user discussion clarified the design before building. Pushed back on a
  single bundled score and split it into Performance (objective) vs Fit (configurable, our
  identity), which is more honest and maps to the brief. Was repeatedly explicit that the fit
  score uses an invented identity, not real LOFC data. Validation by spot-check confirmed the
  split is real: Kanté ranks 3rd by fit vs 7th by performance among PL defensive mids.
- **Phase 5:** added a within-player centering step (not in the original plan) so clusters
  capture style rather than overall quality, pre-empting the "isn't this just good vs bad
  players?" critique. Auto-labelled clusters from standout metrics; the result reproduced the
  classic positional archetypes (ball-player vs stopper CB, poacher vs link forward) with no
  hand-labelling. Kept the modest silhouette scores honest rather than overstating separation.
- *(append per phase)*
