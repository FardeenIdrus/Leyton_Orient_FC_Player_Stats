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

- **Current phase:** 🎉 **PHASE 10 COMPLETE (Stages A + B) — at final checkpoint.** Real paid-feed EFL data (8 league-seasons) + SkillCorner physical layer live. Next: club's real wage framework + identity profiles when provided (CSV drop-ins); prep for the Scott/Joe/Steve Tait demo. Dashboard at http://localhost:8501.
- **Workflow rule:** I pause at the start of each phase, show the plan, and wait for
  your explicit go-ahead before building. After a phase passes its acceptance
  criteria, we checkpoint here before the next phase starts.
- **Last updated:** 2026-06-09 — phases 0–9 done; **dashboard v2 + Metabase added**; **the interview advanced to the COO stage and real data (paid StatsBomb credentials + Skills Corner 2026) is now in hand.** See "▶ CURRENT FOCUS" below.

| Phase | Name | Status |
|---|---|---|
| 0 | Scaffold | ✅ Complete (verified) |
| 1 | Ingest | ✅ Complete (verified) |
| 2 | Aggregate | ✅ Complete (verified) |
| 3 | Store | ✅ Complete (verified) |
| 4 | Normalise & Score | ✅ Complete (verified) |
| 5 | Archetypes | ✅ Complete (verified) |
| 6 | Valuation | ✅ Complete (verified) |
| 7 | Constrain & Rank | ✅ Complete (verified) |
| 8 | Dashboard | ✅ Complete (verified) |
| 9 | Package & Document | ✅ Complete (verified) |
| 10 | Real data + enrichment | ✅ Complete (Stage A: 8 EFL league-seasons live · Stage B: SkillCorner physical layer) |

---

## ▶ CURRENT FOCUS (post-interview) — updated 2026-06-09

Phases 0–9 are complete. Everything below happened after that and is the live state.

### Interview progress
- The platform was built as an interview deliverable. **CEO interview with David Gandler (Zoom) is done; the demo landed well; the process has advanced to a meeting with the COO, Steve Tait** (Maddy is connecting us). Strong signal it may convert to a paid role.
- **2026-06-09: David has provided real resources** — **paid StatsBomb API credentials** and **Skills Corner 2026 tracking data** — to refine the model before the Steve Tait meeting. (Credentials go in `.env` only, never in a tracked file.)

### Dashboard v2 (built on top of Phase 8 `dashboard/app.py`, all verified headless, live at :8501)
- Click a shortlist row → that player's full profile opens **inline** below the table. Shared `_render_profile_body` powers both the inline view and the Player profile tab, so they never drift.
- **Player-type filter** + "group by type" toggle above the shortlist (per-position archetypes).
- New **"Player types" tab**: cluster scatter; axes chosen as two *different* trait families (e.g. shot threat vs driving forward, not xG vs goals) via `METRIC_FAMILY` in `_cluster_axes`; zoom/pan on; a player-search box to ring a dot.
- **Wage budget is now a £/week** synced slider + number (`synced_wage_budget`), converted to the internal multiplier via the position's prime-age ceiling (≈£150k makes top-flight players signable for the demo).
- League names as on-brand **pills** in the KPI strip; age to 1 dp; **"Quality"** label unified (was "Performance"); goals/assists tiles + npxG/xA caption on the profile; **Full stats** expander (season total, per-90, percentile); strengths/watch-outs line; signable rows tinted green/amber.
- **Metabase** connected on the same Postgres DB (port 3000); built a bargain map + goals-by-team on a "Recruitment overview" dashboard. This is the wider-BI growth path the brief wants.

### Interview demo (locked, lives in chat — do NOT create a script file)
Walkthrough as a recruiter would use it: **Centre Forward · transfer €15m · wage ≈£150k · min minutes 1500 · signable on · player type = "High driving forward & pressing, low shot threat"** → 31 strikers → 5 creative forwards → **Lucas Pérez (Deportivo)** at #1 (Quality 79, +38% undervalued, vindicated by his ~€19m Arsenal move months later). Recruiter framing, no colons, "I"/"Leyton Orient" voice, plain language.

### Phase 10 — Real data + enrichment (IN PROGRESS — Stage A approved & building, 2026-06-09)

**Audience note:** the demo is now to the **Director of Football (Scott), Head of Recruitment
Analysis (Joe) and COO (Steve Tait)** — validation rigour and honest caveats outrank polish.
Wage framework + identity profiles stay modelled until the club provides real ones (after
the meeting). Checkpoints: after A1 (targets agreed ✅), after A7, after B5.

**Stage A — Real StatsBomb data (8 EFL league-seasons)**
- [x] **A1 Licence discovery** — paid licence verified live: full EFL pyramid 2018/19→2025/26
  (Championship, League One, League Two; National League from 20/21) + scouting leagues
  (Ligue 2, Scot. Premiership, Eliteserien, Allsvenskan, Irish PD) + PL2 + Euro 2020.
  **League One 2025/26 is complete** (557 matches incl. playoffs, season ended 24 May 2026).
  **Targets approved: League One + League Two + National League + Championship × 2025/26 + 2024/25.**
  Continental leagues deferred (calendar-season mismatch).
- [x] **A2 Configurable competitions** — `SB_COMPETITIONS` env var (`cid:sid:label,...`) overrides
  the demo trio (default unchanged); parsing fails loudly; tests env-isolated (container env
  no longer breaks them). The 8 targets live in `.env`. NOTE: compose injects `.env` at container
  start → `docker compose up -d` after editing it.
- [x] **A3 Ingest** — all 8 league-seasons landed: 4,456 matches, 24 GB. Paid-feed payload
  validated against the aggregator field-by-field before the full pull. **Paid lineups carry
  `birth_date`** (open data did not) → carried through aggregate → `players` table. Two
  paid-feed quirks found and fixed: lineup clocks carry milliseconds (parser updated), and
  transient API hiccups can return an empty events list (ingester now refuses to persist
  empties so a re-run retries; aggregator skips them loudly). 19 fixtures (0.4%, almost all
  National League) are genuinely uncollected on the feed — documented in methodology.
- [x] **A4 Aggregate + spot-check** — 5,994 player-season rows, 4,568 rankable.
  **League One exact:** Ballard (LOFC) 23 = the real golden boot; Wareham 19, Tolaj 18,
  Leonard 16 exact; Wootton +1 = his playoff goal (we include playoffs). **Championship
  exact:** Vipotnik 23, McBurnie 18, Wright 17, Clarke 16. League Two 3/4 exact (Drinan 21
  vs 22 published, one-goal records variance). National League variances fully explained by
  the 14 missing fixtures + playoff inclusion. Scores pass the football-sense check
  (Ballard top-5 CF both ways; Lincoln's forwards high; Wing/Norwood lead DMs).
- [x] **A5 EFL market values** — dcaribou dataset confirmed to have **zero EFL coverage** (as
  decision #5 predicted), so built `ingest/transfermarkt_efl.py`: scrapes TM club-squad pages
  (4 leagues, ~100 requests, rate-limited 2.5s, idempotent). **Done: 2,620 players, 96 clubs.**
  Coverage: Championship 97% valued, League One 91%, League Two 90%, **National League 2.5%**
  → CNAT stays in scores/archetypes but drops out of valuation (labelled). Valuation rewritten
  dual-source: demo era (name match, league-scoped) + EFL era (**DOB+name match**, current-snapshot
  values, **2025/26 rows only** — 24/25 keeps scores/archetypes for trajectory, no valuation:
  current prices must not price last season's output). Eras train as separate models. A
  maintained-dataset fallback (rows with values still updated this season) catches loanees
  from outside the four leagues. **Full-data result: 1,525 valued; ~85% match in the valued
  leagues; CV R² 0.748 (log) — the league feature carries real signal across 4 price tiers.**
- [x] **A5b Wage model re-anchor** — `wage_estimates` now **league-aware** (competition_id ×
  position × age band × tier) with **low/high bands** (×0.7/×1.4); league anchors sourced
  (League One £4.1k/wk avg — Capology n=640; League Two ~£2k; National League ~£1–1.5k;
  sources in `reference_data.py`). Gate semantics: pass on the low band, `wage_marginal`
  flags band-straddles-ceiling for human judgement. Tiers computed **within league** as well
  as position. Alembic migration applied. `model/wage_check.py` reconciles modelled squad
  bills vs published payrolls. **Validation: Championship anchors flagged +57% → re-anchored
  down 30% (the calibration loop working); all 8 league-seasons now within tolerance
  (−2%…+31%); LOFC's own modelled bill +9% vs its published Capology figure.**
- [x] **A6 Full pipeline on real data** — players 3,636 / metrics 5,994 / percentiles 118,815 /
  scores+archetypes 4,568 / valuations 1,525 / shortlists 429 qualifying. **The wage gate
  bites:** the CF shortlist at LOFC's real ceiling spans the pyramid — #1 Andy Dallas
  (Southend, NL, €100k, +90% undervalued), #2 Kabia (Grimsby, +51%), Leonard/Fink/Taylor
  (League One) — genuinely affordable, on-profile, undervalued. Derived tables are now
  clear-then-insert so re-targeting leagues leaves no orphan rows; 1,542 stale demo player
  rows swept.
- [x] **A7 Verify + dashboard** — 44 tests green; image rebuilt with the new deps
  (beautifulsoup4, lxml, openpyxl) + requirements.lock regenerated; headless AppTest on the
  full 8-league DB: **zero exceptions** in the fresh container. Dashboard fixes shipped:
  multi-season-safe loaders (latest-season pinning), minutes slider (step 90→10, data-driven
  max, 450 floor + caption), season-aware KPI/footer (no more hard-coded "2015/16").
  Methodology doc rewritten for the real-data era (valuation scope, NL exclusion, fixture
  gaps, wage validation). **CHECKPOINT: user reviews real shortlists before Stage B.**

**Stage B — SkillCorner ✅ COMPLETE (2026-06-10): squad-only physical data → identity + benchmarks, NOT candidate scores**
File: `data/reference/skillcorner/SkillCorner-2026-04-27.xlsx` — League One 2025/26, 4 sheets;
player-level = LOFC squad only; team-level = all 24 clubs.
- [x] **B1 Ingest** — `ingest/skillcorner.py` + Alembic migration: `skillcorner_team_season`
  (24 clubs) + `skillcorner_player_season` (21 LOFC players, **21/21 matched** to StatsBomb
  ids by DOB+name). Curated per-90 metric set + peak speed. Clear-then-insert; wired into
  the pipeline as a conditional step (runs when an export exists). 'null' strings handled;
  dates as ISO through the JSON round-trip.
- [x] **B2 Measured physical identity** — "Physical" dashboard tab shows the measured squad
  profile (per-player table: who drives running/sprint output) and a league-rank summary
  per dimension, framed explicitly as **a draft for the DoF to confirm** (describes how the
  team currently plays). The caption states plainly that candidates are never physically
  scored (no tracking data exists for them); once confirmed, the identity informs which
  on-ball traits the Fit score weights.
- [x] **B3 League One physical benchmarking** — metric selector + 24-club bar chart, LOFC
  highlighted in club red, rank + league-median caption (e.g. Orient: below-mid on total
  distance, mid-pack on sprints/high accelerations). Metabase: tables queryable on the
  same DB; tile SQL added to `cli_commands.txt`.
- [x] **B4 Honest scoping note** — methodology section 7: what SkillCorner is used for
  (benchmarking, draft identity) and what it refuses (candidate physical scores).
- [x] **B5 Verified** — 47 tests green (3 new SkillCorner tests: parsing, 'null' handling,
  DOB+name matching); headless AppTest zero exceptions with the new tab. Bonus fix: player
  pickers (Profile/Compare) now use "Name — Club" labels with an explicit row map, so
  genuine namesakes (two Cameron Humphreys) can't be conflated.

Then: swap in the club's **real wage framework + identity profiles** when provided (drop-in
CSVs, no logic change) and prep the **Steve Tait (COO)** meeting.

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
- **Decision (affordability, amended): the wage gate ships live, not dormant.** Phase 7
  runs **two gates**: real market value vs a transfer budget, AND a **modelled weekly wage**
  vs the wage-framework ceiling. The wage is from an anchored lookup
  (`data/reference/wage_estimates.csv`, position group x age band x performance tier, source
  flagged `modelled`, anchored to Capology/SalarySport orders of magnitude for the demo
  leagues), NOT derived from market value (a flat % of value is rejected: it underestimates
  cheap players and inflates their affordability). Wages are labelled "modelled estimate"
  wherever shown; real club wage data dropped into `data/reference/` replaces the table with
  no logic change. Honest caveats: on demo data the two gates largely overlap (wage and value
  both track performance/age), so the wage gate is mainly demonstrative here and earns its
  keep on real data (cheap-to-sign-but-high-wage cases); the Capology anchors are present-day,
  consistent with the present-day ceiling. Performance tier = terciles of performance score
  within position.

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

### Phase 6 — Valuation ✅ COMPLETE (verified 2026-06-06)
- [x] Transfermarkt data via auth-free R2 bucket (`ingest/transfermarkt.py`); also gives age + appearances (gitignored). Kaggle/data.world are documented fallbacks.
- [x] Take each player's latest 2015/16-era market value; backfill **age** (which StatsBomb lacked) into `players.birth_date`
- [x] Match by **name, scoped per league via real appearance records** (the TM valuation league tag is unreliable). Exact + token + fuzzy; **98.4% matched** (1,221/1,241), 20 unmatched logged
- [x] Target = **log(market value)**; back-transformed for fair value
- [x] Features = performance percentiles + age + minutes + position + **league** (league added: it genuinely affects value and removes league bias from undervaluation)
- [x] Model = **RidgeCV** (auto-tuned regularisation); **cross-validation** so every fair value is out-of-fold (no player priced by a model that trained on them) — this is the answer to "what's the test set": held-out players, every player held out once
- [x] Undervaluation = fair value − market value; persisted to `valuations` (clear-then-insert, fully idempotent) with model version + timestamp
- [x] Reported **CV R² 0.51 (log), MAE €4.4m, median AE €1.9m** — honest: on-ball stats + age + position + league explain ~half of market value
- [x] Tests (4): name normalise, exact/token/fuzzy match, collision keeps higher value, **synthetic underpriced player flagged** (fair 10.6× actual)
- **Data-quality guard:** name matching across nickname vs full legal names leaves rare mismatches (e.g. "Juanfran"), visible as implausible ages; we reject ages outside 16-38 and log them. Club-level disambiguation is the documented upgrade.
- **Result:** valuations 1,221; ~half undervalued. Sensible bargains (newly-promoted Bournemouth squad, young talents priced below output). 29 tests pass.
- [ ] Write up methodology in `docs/methodology.md` (deferred to Phase 9 docs)

### Phase 7 — Constrain & Rank ✅ COMPLETE (verified 2026-06-06)
- [x] **Two affordability gates** (`constrain/filters.py`): real market value vs transfer budget AND **modelled wage vs wage-framework ceiling** (wage from `wage_estimates`, position x age x performance tier, source-flagged, never value-derived)
- [x] On-profile = clears the identity min-percentile floors for the position (no-floor positions auto-pass)
- [x] Budget + wage-ceiling multiplier are **parameters**, so Phase 8 sliders drive them live
- [x] Near-misses fallback: if nobody passes, return the closest on-profile players, flagged `is_near_miss`
- [x] Ranked into `shortlists` (clear-then-insert), via `constrain/run.py`
- [x] Tests (4): age band, on-profile threshold + no-floor pass, qualifying path, near-miss fallback
- **Two bugs found and fixed during validation:** `min_percentile` stored as a fraction (0.55) vs percentiles on 0-100 (made everyone on-profile); and no-floor positions were wrongly excluded instead of auto-passing.
- **Acceptance — all passing:** ① shortlisted players are affordable + on-profile ✓ ② reproducible from stored data ✓ ③ too-low budget returns near-misses, never empty ✓
- **Result (honest):** at LOFC's real ceiling, **0 qualify / all near-misses** — top-league modelled wages (£58k-130k/wk) dwarf the £2.5-6.5k ceiling, so even fee-affordable players (Iheanacho, €5m) fail the wage gate. The wage gate adds independent signal. Relaxing the ceiling to real lower-league levels yields 300+ qualifying players, proving the engine. 33 tests pass.

### Phase 8 — Dashboard ✅ COMPLETE (verified 2026-06-06)
- [x] Streamlit app (`dashboard/app.py`): branded header, position selector, Shortlist + Player profile + Compare tabs; wired to Postgres; calls the Phase 7 filter live
- [x] Budget control: a slider AND a typed number field, **kept in sync** (`synced_budget`); plus wage-budget and minimum-minutes sliders
- [x] Shortlist table with fit/performance progress bars, market value, undervaluation, archetype, and fee/wage/on-profile tick columns; near-miss banner when nothing qualifies
- [x] Player profile: percentile chart with a **Bars / Radar toggle** (plotly), scores, value vs fair value, modelled-wage caption
- [x] Compare: 2-3 players overlaid on a radar + a side-by-side table
- [x] **Methodology tab:** a graphviz pipeline diagram + a clickable stage selector that reveals each stage's plain-English what-it-does, key assumption, and how it extends with more data (built for technical + non-technical readers)
- [x] Polish: KPI strip (players analysed / leagues / season / matches-this-filter), club-red metric + tab accents, transparent header; **fixed the collapsed-sidebar reopen** (the earlier CSS hid the header that holds the toggle)
- [x] **Leyton Orient themed:** club red theme (`.streamlit/config.toml`) + custom CSS (hides default chrome); crest loads from `assets/logo.png` (user-supplied) with a styled wordmark fallback
- [x] Runs as a Docker service at http://localhost:8501 (up with `docker compose up`)
- [x] Verified headlessly with Streamlit AppTest: full script runs with **zero exceptions**, all tabs/widgets render
- **Acceptance — all passing:** non-technical user picks a position and reads a shortlist; profile + compare work; budget slider/number sync and update live; zero-match shows near-misses.
- **Design intent:** clean and professional (restrained palette, whitespace, no emoji/animation clutter), not the default-Streamlit look.

### Phase 9 — Package & Document ✅ COMPLETE (verified 2026-06-06)
- [x] **One-command end-to-end runner** `lofc/pipeline.py` (schema → ingest → ... → shortlists), each step idempotent
- [x] Whole stack deploys with `docker compose up` (db + app + dashboard + pgAdmin)
- [x] `docs/architecture.md`, `docs/methodology.md`, `docs/scaling.md` written (methodology covers the modelling + honest assumptions; scaling covers the Mongo/MinIO/BI path)
- [x] `README.md` finalised (quick start, pipeline, interfaces, docs map); `requirements.lock` pins exact versions
- **Acceptance — all passing:** `docker compose up` + `python -m lofc.pipeline` runs all 10 stages clean (exit 0) and fully populates the database (players 1622, metrics 1640, scores 1241, archetypes 1241, valuations 1221, shortlists, reference tables); dashboard live at :8501.

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
- **Phase 6:** found an auth-free public source for the Transfermarkt data (no Kaggle login).
  Caught two data traps by inspecting first: the valuation league tag is unreliable (Jordi Alba
  tagged "MLS1"), so matching is scoped by real appearance records instead; and short-name vs
  full-legal-name mismatches (Juanfran) survive even league scoping, so implausible ages are
  rejected and logged. Used cross-validation for out-of-fold fair values after the user asked
  the right question about the test set. R² 0.51 reported honestly, not inflated. Fixed a
  stale-row bug (upsert left rejected matches behind) by switching valuations to clear-then-insert.
- **Phase 7:** adopted the user's amendment to ship the wage gate live (anchored synthetic
  wages, not value-derived), and pushed back on the flat-% approach for bias. Built both gates
  with everything editable (CSV + config). Caught two bugs by validating before trusting:
  a 0-1 vs 0-100 scale mismatch that made everyone on-profile, and no-floor positions being
  excluded instead of auto-passing. Kept the demo result honest (all near-misses at LOFC's real
  ceiling) and demonstrated the qualifying path separately rather than faking a populated default.
- **Phase 8:** built a clean, club-themed Streamlit app (restrained red/white palette, custom
  CSS over the default look) rather than a generic dashboard. Verified the whole script
  headlessly with Streamlit's AppTest (zero exceptions) since there is no browser here, and
  fixed a real deprecation (`use_container_width` -> `width="stretch"`, now past its removal
  date). Crest is user-supplied via assets/ with a styled fallback, so no copyrighted asset is
  bundled. Reused the Phase 7 filter live behind the sliders rather than duplicating logic.
- **Phase 9:** packaged the whole pipeline behind one idempotent command, wrote the three docs
  (architecture, methodology, scaling) honestly including the assumptions and limitations, and
  verified the full `docker compose up` + `python -m lofc.pipeline` flow runs all ten stages
  clean and populates the database. Pinned dependencies for reproducibility.
