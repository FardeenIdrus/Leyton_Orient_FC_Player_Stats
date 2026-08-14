# Build history — FROZEN LOG (do not edit)

> **This is the append-only build history: every phase, decision, and its rationale, in the
> order it happened.** It is preserved verbatim so no past decision has to be re-derived from
> memory. **It is NOT the current state** — for what the platform is *today* and what's next,
> read `plan/BUILD_PLAN.md` (the master). Read this file only when you need the *why* behind a
> past decision.
>
> Frozen 2026-07-27 from the former `BUILD_PLAN.md`. Anything below reflects the state at the
> time it was written, not necessarily now.

---

# LOFC Recruitment Platform — BUILD PLAN
<!-- ============================================================================ -->
> ## ⭐ CURRENT STATE — READ THIS FIRST (updated 2026-07-27)
>
> **This file is the single source of truth: the full plan, every decision with its
> rationale, and the live build log. The log is append-only — the LIVE state is this
> box plus the last dated section of Part 2; everything between is history (how we got
> here), kept so no decision has to be re-litigated from memory.**
>
> **Goal (unchanged):** real event data → a ranked shortlist of **affordable,
> on-profile, undervalued** signings for Leyton Orient FC. A *decision* platform (the
> IP is the valuation + ranking model), not a reporting dashboard.
>
> **Progress:** Phases 0–9 (demo build) ✅ · Phase 10 (real EFL data + SkillCorner) ✅ ·
> recruiter-workflow batch ✅ · panel demo ✅ **went well** · cross-league loanee valuation
> fix ✅ · **Phase 11 (Impect migration) — sub-phases A/A2/B1/B2/C/D DONE; scoring is now
> 100% Impect + SkillCorner (zero StatsBomb in scoring).**
>
> **LATEST (2026-07-27) — WE ARE HERE.** The club's REAL recruitment framework is now the
> scoring model:
> - **Club scorecard** (`model/club_framework.py` + `model/scorecard.py`): each player scored
>   **1–5** on the club's dimensions, per-position metric lists + weights taken directly from
>   the club files (see below), combined into a composite. Two composites: **objective**
>   (Performance + Physical, real data — the DEFAULT ranking) and **full** (adds MODELLED
>   Financial + Resale). Psychological + Medical are scout inputs (not yet collected).
> - **The invented Style-fit is RETIRED** from every live surface. The Shortlist, Player
>   profile, Compare, Player-types and Watchlist now rank/show the **club composite**, not Fit.
>   Affordability gates are fee + wage only (no quality-threshold exclusion; nothing is
>   excluded automatically — advisory flags only).
> - **91 metrics** per player (87 + 4 club-framework additions: keeper catches, defensive
>   touches outside box, cross bypassed-opponents, dribble count).
> - **Physical (SkillCorner)** now covers the EFL + Premier League 2 + Scottish Premiership
>   (Scottish Championship has no edition). 2025/26 only.
> - **149 tests pass.** Dashboard renders clean.
> - **STILL SEPARATE, deliberately:** Shortlist (composite + affordability) vs Club scorecard
>   (composite + per-player dimension/metric detail). Both rank by the same composite.
> - **Deferred:** persist scorecards to a DB table (then retire Fit in the constrain/stored
>   `shortlists` path too); archetype sub-profiles; scout-entry for Psych/Medical; load the
>   club's real wage framework CSV; full StatsBomb identity-seed retirement; app.py refactor.
>
> **The Impect direction (decided with the user, 2026-07-07):** the club is moving to
> Impect as its single event-data provider within ~a year, so Impect becomes our PRIMARY
> source, StatsBomb is kept as a frozen validation baseline (not deleted), and the tool
> is being rebuilt around a provider-neutral metric layer so the source is swappable.
> The club provided the files (in `docs/`) that now define the scoring: **`Impect Data -
> Positional Metrics.xlsx`** (the per-position metric lists — its `Input` sheet →
> `PERFORMANCE_METRICS` in `club_framework.py`) and **`LOFC - Position Archetype.docx`**
> (the 7 dimensions, their per-position weights → `DIMENSION_WEIGHTS`, the 1–5 scoring and
> the median/70th thresholds). These replaced our made-up identity/Fit stand-ins. Full
> plan: the "Phase 11" section at the foot of Part 2.
>
> **SkillCorner platform (2026-07-10):** the club gave paid SkillCorner PLATFORM/API access
> (not just the squad xlsx). Coverage confirmed = the covered leagues at PLAYER level for
> ALL teams, so physical data is now available for RECRUITMENT TARGETS, not just our
> squad — this closes the one gap in the club's framework (its physical dimension). API
> ingest built + validated (see Phase 11 log). Impect (performance) + SkillCorner
> (physical) are the two halves of the club framework, both joined per player.
>
> **Phase 11 metric layer — where it stood (2026-07-20; SUPERSEDED — now LIVE in the DB,
> 91 metrics, see LATEST above):** the provider-neutral metric
> set is DEFINED and verified across four source files (nothing wired into the live DB
> yet). **87 metrics/player: 36 Impect + 12 StatsBomb-advanced + 15 StatsBomb-original +
> 24 SkillCorner-physical.** Each source now has ONE explicit definition file
> (`impect_map.py`, `statsbomb_season.py`, `skillcorner_map.py`, `models.py`). Full
> per-metric provenance + file map: **`docs/DATA_ARCHITECTURE.md`** (the presentable
> reference). Two things settled this session: (a) added 12 metrics (club-file gaps +
> Impect extras: off-ball receiving, finishing quality, shot threat), caught + fixed a
> real GK mapping bug (Impect "shots saved" is shooter-context, not keeper-context); (b)
> investigated consolidating the 15 StatsBomb-original into the endpoint — **rejected: the
> pre-computed feed is missing 6 of them (progressive passes/carries, blocks count, GK
> saves count, all-passes, all-shots xG), so the split is a real capability line
> ("computed by us from events" vs "StatsBomb-proprietary pre-computed"), not an
> accident.**
>
> **Next (Phase 11):** Step 1 (merge) ✅ **DONE 2026-07-20** — unified in-code registry
> (`model/metric_registry.py`: 87 metrics, one source each, explicit derivations, overlap
> resolution, invariants asserted at import) + the combiner (`model/build_neutral.py`),
> coverage verified across all 8 league seasons (Impect 95–99%, physical 88–91% on 25/26)
> · **NEXT: Step 2** = wire into the DB (extend `models.py` schema via Alembic + pipeline
> loader) · Step 3 = re-score + compare shortlists · Step 4 = apply the club's real
> per-position metrics/thresholds/weights (Joe's files) · Step 5 = physical into scoring ·
> Steps 6–8 = valuation retrain, dashboard, make Impect primary. Also open: club's real
> wage framework CSV; FMDB features; deployment.
>
> **Live numbers:** StatsBomb build unchanged + LIVE (3,636 players · 1,643 valued · CV R²
> 0.745) — the tool still runs entirely on the original StatsBomb pipeline; nothing
> switched. **Impect:** 14 iterations landed, ~1,480 KPIs/player; EFL goal agreement vs
> StatsBomb 93–99.7% exact, xG corr 0.987–0.992. **SkillCorner platform:** 7 editions,
> all teams, EFL candidate match 91.6–96.1%. **86 tests green.**
>
> **WHERE TO READ FOR DETAIL:** the metric inventory + file architecture is
> **`docs/DATA_ARCHITECTURE.md`**. Build history: the last sections of Part 2
> ("Phase 11 — Impect migration"). Decisions: Part 1 §2 (19–22 for Impect).
> Reader-facing docs: `docs/architecture.md`, `docs/methodology.md`, `docs/scaling.md`.
>
> **CODEBASE MAP** (`src/lofc/`) — Phase-11 metric-source files marked ★:
> ```
> config.py        env targets for all providers (SB_COMPETITIONS, IMPECT_ITERATIONS,
>                  SKILLCORNER_EDITIONS) + credentials
> ingest/          statsbomb.py (events API) · landing.py (idempotent raw I/O) · run.py
>                  transfermarkt.py + transfermarkt_efl.py (market values, bio)
>                  skillcorner.py (OLD squad xlsx loader — being retired)
>                  impect.py (Impect API pull → data/raw/impect/)
>                ★ impect_map.py       = the 36 Impect metric definitions
>                  impect_translate.py = Impect raw → our names (per-90 + minutes floor)
>                ★ statsbomb_season.py = the 12 StatsBomb-advanced metric defs + pull
>                  skillcorner_api.py  = SkillCorner platform pull → data/raw/skillcorner/
>                ★ skillcorner_map.py  = the 24 physical metric definitions
> aggregate/       events.py + player_season.py = compute the 15 StatsBomb-original metrics
>                  from raw events (their names ★ live in store/models.py PER90_COLUMNS)
> store/         ★ models.py (DB schema + the 15 original metric names) · load.py ·
>                  watchlist.py (USER data) · reference_data.py (wage/identity)
> model/           normalise.py (percentiles) · score.py (Quality + Fit) · archetypes.py
>                  · valuation.py · wage_check.py · impect_check.py (Impect validation)
>                  · skillcorner_check.py (physical coverage check)
> constrain/       filters.py (fee/wage/profile gates + ranking) · run.py
> dashboard/       app.py (Streamlit: shortlist, profile, compare, types, watchlist,
>                  physical, methodology tabs)
> pipeline.py      one-command end-to-end runner (11 idempotent steps)
> ```
> Companion files: `plan/LOFC_Recruitment_Platform_Build_Plan.md` = the original brief
> (**frozen, never edited**) · `CLAUDE.md` = auto-loaded pointer here ·
> `cli_commands.txt` = the command for every stage · Alembic migrations in `alembic/` ·
> `docs/` also holds the three club-provided reference files (Impect/positional/archetype).
<!-- ============================================================================ -->

---

<!-- ───────────────────────────────────────────────────────────────────────────
     PART 1 — REFERENCE (static): objective, decisions, anchors, conventions.
     Not dated. Changes here are rare and deliberate.
     ─────────────────────────────────────────────────────────────────────────── -->

## 1. Context & objective

Build an end-to-end platform that turns StatsBomb player data into a ranked shortlist
of **affordable, on-profile, undervalued** signings for Leyton Orient FC. This is a
*decision* intelligence platform — the core IP is the **valuation + ranking model**,
not the infrastructure. Built phase-by-phase as a high-stakes interview deliverable
for an LOFC BI/recruitment role; the interviews are now complete and the platform is
in post-demo refinement.

Pipeline: StatsBomb data → Ingest → Aggregate → Store → Normalise/Score → Archetypes
→ Valuation → Constrain/Rank → Serve (Streamlit) → Deploy (Docker).

## 1.5 Working philosophy

The rules that shaped every phase; they are why the build log below looks the way it
does.

- **Pause at each phase boundary:** show the plan, wait for explicit go-ahead, build,
  validate against acceptance criteria, checkpoint here, only then move on.
- **Validate before trusting.** Every stage is spot-checked against external reality
  (real golden-boot tables, published payrolls, known transfer outcomes) before its
  output feeds the next stage. Several real bugs were caught exactly this way.
- **Honesty over polish.** Modelled numbers are labelled modelled; accuracy is reported
  as measured, never inflated (R² 0.51 on the demo era, 0.745 on EFL, and the ±40%
  in-league point-estimate caveat are all stated in the docs and in the dashboard).
- **Stand-ins are swappable data, not code.** Wage framework and identity profiles are
  CSVs in `data/reference/`; the club's real documents drop in with zero logic change.
- **User data is sacred.** The watchlist is never touched by pipeline rebuilds
  (verified in the wild: a real entry survived a full end-to-end rebuild).
- **Everything runs in Docker** (host Python is 3.14; the container is 3.11). Postgres
  is the single store. Schema changes go through Alembic. Credentials live in `.env`
  only.
- **Append-only log.** Superseded sections are marked, not deleted; bugs are recorded
  with root cause and fix, not scrubbed.

## 2. Locked decisions (verified — do not re-litigate without new evidence)

Each entry records what was decided, why, and what was rejected. Numbers 1–6 date from
the original demo build; 7 onward from Phase 10 (real data).

| # | Decision | Outcome | Why / rejected alternative |
|---|---|---|---|
| 1 | **Data source (demo era)** | StatsBomb **free open data** first; paid API behind a config swap (`USE_OPEN_DATA`, `SB_*`) | No paid creds at the start. Verified: free tier has **no LOFC/EFL data** (24 comps, nothing below the PL). |
| 2 | **Demo competitions** | The three complete 2015/16 leagues: PL, La Liga, Serie A (~1,500 players) | The only full 380-match seasons on the free tier. Vintage doesn't affect methodology. |
| 3 | **Cross-league fairness** | Percentiles within position **AND** within league; raw cross-league comparison is a documented extension | Pooling leagues into one percentile ranking is wrong (90th pct Serie A ≠ PL). The dashboard warns when Compare mixes leagues; valuation is where league level is accounted for (league is a model feature). |
| 4 | **Wage framework** | Build our own, anchored in real EFL SCMP rules + LOFC finances; labelled modelled, swappable for the real doc | No public LOFC wage doc exists. Real anchors beat guesses (§3). |
| 5 | **Valuation target** | Transfermarkt market values. Demo era: the maintained dcaribou dataset (CC0). EFL era: our own squad-page scrape (decision 9) | StatsBomb has no fees/values. Verified early that the dcaribou set does NOT cover League One — which is exactly what forced decision 9 when real data arrived. |
| 6 | **Docs** | This file = single source of truth; brief frozen; `CLAUDE.md` = pointer; `docs/` = reader-facing | One living doc; avoids file proliferation. |
| 7 | **Configurable competitions** | `SB_COMPETITIONS` env var (`cid:sid:label,...`) overrides the demo trio; malformed input fails loudly at startup | Retargeting leagues must be config, not code. Rejected: silently falling back to defaults on a typo (would ingest the wrong league without anyone noticing). |
| 8 | **Dual-era valuation** | Demo era and EFL era train as **separate models**; scraped EFL values price **2025/26 rows only** | Price levels a decade apart must never mix. Scraped values are a current snapshot: pricing 2024/25 output with 2026 prices would be dishonest. 2024/25 keeps scores + archetypes (trajectory) but no fair value. |
| 9 | **EFL value matching** | **Birth date + name**, four stages: in-league DOB+name → in-league name-only (DOB-contradiction guard) → **cross-league DOB+name (loanees, added 2026-07-06)** → maintained-dataset fallback (out-of-pyramid loanees, January movers) | DOB from the paid lineups makes namesakes safe (two Cameron Humphreys). League-scoping alone silently dropped loanees whose TM value sits under the parent club in another division (the Josh Stokes case, +122 players when fixed). Name cutoff 0.55 with identical DOB; 0.80 without. |
| 10 | **National League valuation** | CNAT stays in scores/archetypes; **excluded from valuation** (labelled); its rare valued players carry an uncertainty caption | TM maintains values for ~2.5% of fifth-tier players. Post-demo error analysis vindicated this: NL log-correlation ≈ 0.06 (no signal). |
| 11 | **Wage model** | League-aware grid (league × position × age band × tier) with **±bands (×0.7/×1.4)**; gate passes on the LOW band; `wage_marginal` flags band-straddles-ceiling; validated vs published payrolls (`wage_check.py`) | Rejected: wage as a flat % of market value (underestimates cheap players, inflates their affordability). Bands keep borderline cases with humans ("call the agent"), not silently dropped. The Championship anchor was corrected −30% when reconciliation flagged it: the calibration loop working. |
| 12 | **Two scores, not one** | **Quality** (broad role-relevant percentiles, equal weight, objective) + **Fit** (identity-weighted) | A single blended score conflates "is he good?" with "does he fit us?". Kanté: 3rd by Fit vs 7th by Quality among PL DMs — the split is real. |
| 13 | **Row grain invariant** | Everything is keyed by **(player_id, competition_id, season_id)**; every per-player view must key or dedupe by it | Mid-season movers legitimately hold two same-season rows (Kacurri: Grimsby L2 + Morecambe NL). Violating this caused three separate bugs (profile crash, gate bug, physical-tab duplicates) — all fixed by re-keying, all logged in Part 2. |
| 14 | **SkillCorner scope** | Squad physical identity + league benchmarks only; **never candidate physical scores** | No tracking data exists for non-LOFC players; a per-candidate "physical score" would be invented. Physical assessment of targets stays with scouts. |
| 15 | **Watchlist = user data** | Own table, FK to players, never cleared by pipeline runs; loads via LEFT JOIN so watched players survive rebuilds with blanks | A recruiter's tracked list must outlive every data refresh. Single-user by design for now; multi-user = user_id + auth (roadmap). |
| 16 | **Playing-style k** | k-means k = the largest k within 0.02 silhouette of the best | Widened CF and AM to 3 football-sensible styles where the data tolerates it; other positions honestly stay at 2. Rejected: forcing k=3 everywhere (fabricates structure). |
| 17 | **Freeze discipline** | Code frozen before the demo (2026-06-11 → post-demo); only user-found bugs fixed within the freeze; **lifted 2026-07-06** | A moving build cannot be rehearsed. Feature requests during the freeze (extra leagues, similar-player search) were parked, not built: adding leagues reopens the scraper, wage anchors and re-validation. |
| 18 | **Fair value framing** | Fair value is a **screening/ranking signal**, not a price. In-league point estimates carry ±40% typical error; stated wherever the number appears | Post-demo error analysis (Part 2). The pooled R² 0.745 is flattered by the league feature; within-league ordering is real (log-corr ~0.6) but point accuracy is not. More data won't fix it — the ceiling is feature relevance (contract length, potential, reputation are absent), not sample size. |
| 19 | **Impect becomes primary; StatsBomb kept as baseline** | Migrate to Impect as the primary event-data source; keep the working StatsBomb build as a **frozen validation baseline**, not deleted | The club is moving to Impect as its single provider within ~a year. Rejected "disregard/delete StatsBomb now": (a) the club's own recruitment framework is written in StatsBomb metrics, so we can't drop it until the mapping is agreed; (b) everything is validated on StatsBomb; (c) with a provider-neutral layer, keeping StatsBomb as a cross-check costs ~nothing. Switch only after Impect is proven (decision 22 gate) and the framework is translated. |
| 20 | **Provider-neutral metric layer** | A fixed internal metric set that scores/valuation/dashboard read from; one translator per provider (StatsBomb→neutral, Impect→neutral) feeds it | Makes the data source swappable (Joe's steer: don't lean on one provider). The pipeline already separates ingest from model/dashboard, so we are structurally close. Switching provider becomes changing a translator, not a rebuild. |
| 21 | **Follow the club's real framework** | Replace the made-up identity/Fit stand-ins with the club's `LOFC - Position Archetype.docx` (per-position metrics, thresholds league-median=min / 70th-pct=elite, scorecard weights) + `Data - Positional Metrics.xlsx` | These are the real version of what we faked. Our within-league percentile engine already supports the median/70th-pct bars directly. The tool computes the DATA-DRIVEN dimensions (performance, part of financial/resale); physical (candidates), medical, psychological stay explicit manual scout inputs — honest, matches how the club decides. |
| 22 | **Validate Impect before trusting it** | Read-only gate (`impect_check.py`): match players (TM id, then DOB+name) and compare goal totals + xG vs the StatsBomb data we already validated | "Prove it before switching." Gate PASSED 2026-07-07 for the EFL (93–99.7% exact goals, xG corr ≥0.987). NOTE: the Transfermarkt-id bridge did NOT work at the averages endpoint (column present but null) — DOB+name carried the match at 92–98%; a TM id may exist on another Impect endpoint (Phase B check). Scottish/PL2 low match (6–32%) is expected: those are new players not yet in our DB. |

## 3. Wage-framework anchors (recorded for Phase 3; still the live anchors)

- **Hard ceiling = EFL SCMP:** League One caps wages at **50% of turnover** (voted down
  from 60%, Dec 2024). LOFC turnover ~£7.7m (2023/24) → **~£3.5–4m** wage pool. *(FACT)*
- LOFC market position: top earners ~£6,000–6,500/wk, squad floor ~£200–1,000/wk.
  *(ESTIMATE — Capology/SalarySport)*
- Position multipliers (attackers highest → full-backs/squad GKs lowest); age band
  peaks ~27–31. *(ESTIMATE)*
- **U21 academy graduates are SCMP-exempt** — cheaper *and* outside the cap = the key
  value lever.
- League anchors (League One £4.1k/wk avg, Capology n=640; League Two ~£2k; National
  League ~£1–1.5k; Championship re-anchored −30% after payroll reconciliation) are
  sourced in `store/reference_data.py`.
- **The wage ceiling is adjustable, not fixed** (slider + synced number field), so the
  gate is honest on any data. **Never show a blank screen:** zero matches returns the
  closest near-misses, flagged.

## 4. Tech stack

Python 3.11 (in Docker) · statsbombpy · pandas/numpy · scikit-learn · PostgreSQL 16 ·
SQLAlchemy + Alembic · Streamlit · beautifulsoup4/lxml (TM scraper) · openpyxl
(SkillCorner xlsx) · Docker / docker-compose · pydantic-settings · pytest.
*Excluded from v1 (with reasons + triggers in `docs/scaling.md`): MongoDB, MinIO,
Power BI/Tableau.*

## 5. Repo structure

```
lofc-recruitment/
├── CLAUDE.md                  auto-loaded pointer to this file (local-only)
├── README.md                  run instructions
├── pyproject.toml · Dockerfile · docker-compose.yml · .env.example · .gitignore
├── alembic/                   migrations (env wired to DATABASE_URL)
├── src/lofc/                  see the CODEBASE MAP in the READ-FIRST box
├── tests/                     pytest (60 tests, no network, sqlite where DB needed)
├── data/
│   ├── raw/                   landed payloads (gitignored, 24 GB EFL)
│   └── reference/             transfermarkt/ (scraped values, gitignored),
│                              skillcorner/ (club export, gitignored),
│                              wage/identity CSVs (the swappable stand-ins)
├── docs/                      architecture.md, methodology.md, scaling.md
└── plan/                      THIS FILE + the frozen brief
```

## 6. Coding conventions (apply to all files)

1. **Comments are clear and concise.** Plain English, state the point directly.
   - No em dashes in code comments. Use a period, comma, colon, or parentheses.
   - No vague AI filler words (robust, seamless, leverage, comprehensive, powerful,
     cutting-edge, elegant). Say the concrete thing.
   - Comment the "why", not the obvious "what".
2. **Idempotency everywhere:** ingest skips what exists; derived tables are
   clear-then-insert; re-running any stage is always safe.
3. **Fail loudly** on malformed config or unexpected data; never silently fall back.

---

<!-- ───────────────────────────────────────────────────────────────────────────
     PART 2 — BUILD LOG (chronological, append-only: OLDEST at the top → NEWEST at
     the bottom). The LAST dated section is the live state. Superseded content is
     marked, never deleted. Dates run 2026-06-02 → 06-06 (Phases 0–9) → 06-09/10
     (Phase 10 A+B) → 06-11 (freeze) → 06-14 (demo prep) → late June (demo) →
     2026-07-06 (post-demo + loanee fix).
     ─────────────────────────────────────────────────────────────────────────── -->

## 7. The phased plan — Phases 0–9 (the demo build, all complete)

> Each phase ends in a working, testable slice. **No phase starts until the previous
> one's acceptance criteria pass AND the user has approved starting the next.**

| Phase | Name | Status |
|---|---|---|
| 0 | Scaffold | ✅ Complete (verified 2026-06-02) |
| 1 | Ingest | ✅ Complete (verified 2026-06-05) |
| 2 | Aggregate | ✅ Complete (verified 2026-06-05) |
| 3 | Store | ✅ Complete (verified 2026-06-05) |
| 4 | Normalise & Score | ✅ Complete (verified 2026-06-05) |
| 5 | Archetypes | ✅ Complete (verified 2026-06-05) |
| 6 | Valuation | ✅ Complete (verified 2026-06-06) |
| 7 | Constrain & Rank | ✅ Complete (verified 2026-06-06) |
| 8 | Dashboard | ✅ Complete (verified 2026-06-06) |
| 9 | Package & Document | ✅ Complete (verified 2026-06-06) |
| 10 | Real data + enrichment | ✅ Complete (2026-06-10; A = 8 EFL league-seasons, B = SkillCorner) |

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
  1.18) vs lower-bound pins — no conflicts. Lock file added at Phase 9.

### Phase 1 — Ingest ✅ COMPLETE (verified 2026-06-05)
- [x] `statsbombpy` open-data pulls for the three competitions (competitions, matches, events, lineups)
- [x] Land raw payloads idempotently under `data/raw/` (skip-if-exists; atomic temp+rename write)
- [x] Authenticated-API swap behind config (creds passed only in API mode; open data otherwise)
- [x] Documented, repeatable pull command (`python -m lofc.ingest.run`, flags `--competition` / `--limit` / `--force`)
- [x] Idempotency unit tests (no network)
- **Modules:** `ingest/statsbomb.py` (access), `ingest/landing.py` (idempotent JSON I/O), `ingest/run.py` (orchestrator).
- **Acceptance — all passing:** ① one command pulls a full league end to end ✓ ② re-run skips everything (PL: pulled=0 skipped=380) ✓ ③ raw files inspectable (nested events, lineups) ✓ ④ ingest unit tests pass (6) ✓
- **Result:** all 3 leagues landed — 1,140 matches (380 each), 1,140 events + 1,140 lineups files, 0 leftover temp files, 2.6 GB under `data/raw/` (gitignored). Events kept nested (`flatten_attrs=False`). Lineups pulled too (Phase 2 needs them for minutes).

### Phase 2 — Aggregate ✅ COMPLETE (verified 2026-06-05)
- [x] Event → player-match metrics; **minutes derived from lineup position spells**, period-aware (the clock resets to 45:00 each half, so spells crossing half-time use each period's real length)
- [x] Player-match → player-season per position group, carrying the league dimension; dominant position = most minutes
- [x] Per-90 for counting stats; pass% / dribble% / save% ratios; **non-penalty goals + xG**; **xA** via shot→key-pass link; basic GK set (saves, goals conceded, save%)
- [x] Minutes threshold: `rankable` flag at >= 450 min (small samples kept but flagged)
- [x] Unit tests on minutes, period reset, position map, metrics, xA (5 tests)
- [x] Spot-check vs known figures
- **Modules:** `aggregate/events.py`, `aggregate/player_season.py`, `aggregate/run.py`.
- **Acceptance — all passing:** ① player-season table produced ✓ ② tests pass (11 total) ✓ ③ spot-checks match reality exactly ✓
- **Spot-check results (goals match real 2015/16 totals):** PL — Vardy 24, Kane 25, Agüero 24, Lukaku 18, Mahrez 17. La Liga — Suárez 40, Ronaldo 35, Messi 26. Serie A — Higuaín 36, Dybala 19. Pass-completion leaders are CBs / holding mids as expected.
- **Assumptions baked in:** minutes include stoppage time; one dominant position per player-season; per-90 scaling; age not present (arrives via Transfermarkt in Phase 6); progressive pass/carry use fixed metre thresholds (15 / 10).

### Phase 3 — Store ✅ COMPLETE (verified 2026-06-05)
- [x] SQLAlchemy models for the 4 tables fillable then (players, player_season_metrics, wage_framework, identity_profiles); downstream tables added in their phases
- [x] Alembic migration (autogenerated from models, applied clean)
- [x] Idempotent upsert loaders (`store/load.py`); re-run gives identical counts
- [x] Constructed reference data built by `store/reference_data.py` with provenance, reviewed by user before loading
- [x] pgAdmin added (http://localhost:5050, LOFC server pre-listed, password `lofc`)
- [x] Tests (5): wage grid complete + peaks in prime, identity weights sum to 1.0, metrics reference real columns
- **Result in Postgres:** players 1622, player_season_metrics 1640, wage_framework 40, identity_profiles 51. 16 tests total pass.
- **Reference data (constructed stand-ins, see `data/reference/README.md`):** wage ceilings anchored to the EFL 50%-of-turnover cap + LOFC accounts (fact) and Capology/SalarySport top-earner estimates (~£6.5k/wk); position/age shape assumed. Identity profiles are a football-reasoning construction (hard-working, progressive, press-resistant). Both swappable for the club's real files.

### Phase 4 — Normalise & Score ✅ COMPLETE (verified 2026-06-05)
- [x] Within-position **and** within-league percentiles (rankable players only), in `model/normalise.py`
- [x] **Two scores** in `model/score.py`: Quality (broad role-relevant stats, equal weight, data-only; shown as "Quality" in the UI, previously "Performance") and Fit (identity-weighted, focused, configurable). Both 0-100, ranked within position + league.
- [x] Persisted to `player_percentiles` + `player_scores` (idempotent), orchestrated by `model/run.py`
- [x] Tests (5): percentile ranking, rankable-only, NaN drop, performance mean, fit weighted sum, rank order
- **Why two scores:** decision 12. **Spot-check:** Vardy ranks higher on Fit than Quality (elite at goals+pressing, the constructed identity); Kanté 3rd by Fit vs 7th by Quality among PL DMs. The split works on real data.
- **Result in Postgres:** player_percentiles 32,285, player_scores 1,241. 21 tests pass.
- **Known characteristic:** per-90 + a 450-min floor can let a strong young sub (Iheanacho) top a per-90 ranking. Defensible; minutes are surfaced alongside scores in the dashboard.

### Phase 5 — Archetypes ✅ COMPLETE (verified 2026-06-05)
- [x] Standardise then PCA (~90% variance); k-means on the components, in `model/archetypes.py`
- [x] **Style not quality:** centre each player on their own average percentile first, so clusters capture relative strengths (style), not overall level
- [x] k-means per position (pooled across leagues); silhouette per k logged; k chosen automatically
- [x] Auto-generated label per cluster from its standout metrics; distance-to-centroid stored
- [x] Stability: fixed random_state, tested identical assignments across runs
- [x] Limitation + upgrade path documented (hard labels now, GMM soft assignment next)
- [x] Tests (4)
- **Validation (labels auto-generated, not hand-written):** CB split into ball-players (Fonte, Koscielny) vs stoppers (Prödl, Ogbonna); CF into goalscorers (Vardy, Kane) vs link/work forwards (Walters, Origi); Winger into creators vs goal-threat. The classic archetypes, found by the data.
- **Result:** archetypes 1,241; k=2–3 per position; silhouettes 0.16–0.29 (modest, honest — styles are a continuum). 25 tests pass.

### Phase 6 — Valuation ✅ COMPLETE (verified 2026-06-06)
- [x] Transfermarkt data via auth-free R2 bucket (`ingest/transfermarkt.py`); also gives age + appearances. Kaggle/data.world documented fallbacks.
- [x] Latest 2015/16-era market value per player; **age backfilled** into `players.birth_date` (StatsBomb open data lacked it)
- [x] Match by **name, scoped per league via real appearance records** (the TM valuation league tag is unreliable — Jordi Alba tagged "MLS1"). Exact + token + fuzzy; **98.4% matched** (1,221/1,241), 20 unmatched logged
- [x] Target = **log(market value)**; features = performance percentiles + age + minutes + position + **league**; model = **RidgeCV**; **cross-validated out-of-fold fair values** (no player priced by a model that trained on them — the honest answer to "what's the test set")
- [x] Undervaluation = fair value − market value; persisted clear-then-insert with model version + timestamp
- [x] Reported **CV R² 0.51 (log), median AE €1.9m** — honest: on-ball stats + age + position + league explain ~half of market value
- [x] Tests (4), incl. a synthetic underpriced player flagged (fair 10.6× actual)
- **Data-quality guard:** short-name vs full-legal-name mismatches (Juanfran) survive league scoping; implausible ages (outside 16–38) are rejected and logged.
- **Result:** valuations 1,221; sensible bargains (newly-promoted Bournemouth squad, young talents priced below output). 29 tests pass.

### Phase 7 — Constrain & Rank ✅ COMPLETE (verified 2026-06-06)
- [x] **Two affordability gates** (`constrain/filters.py`): market value vs transfer budget AND **modelled wage vs ceiling** (wage from the grid, never value-derived — decision 11)
- [x] On-profile = clears the identity min-percentile floors for the position (no-floor positions auto-pass)
- [x] Budget + wage-ceiling multiplier are **parameters**, so the dashboard sliders drive them live
- [x] Near-misses fallback (never a blank screen); ranked into `shortlists` (clear-then-insert)
- [x] Tests (4)
- **Two bugs found and fixed during validation:** `min_percentile` stored as a fraction (0.55) vs percentiles on 0–100 (made everyone on-profile); and no-floor positions wrongly excluded instead of auto-passing.
- **Result (honest):** at LOFC's real ceiling on top-league demo data, **0 qualify / all near-misses** — modelled top-league wages (£58k–130k/wk) dwarf the £2.5–6.5k ceiling. The gate adds independent signal; relaxing the ceiling proves the engine (300+ qualify). 33 tests pass.

### Phase 8 — Dashboard ✅ COMPLETE (verified 2026-06-06)
- [x] Streamlit app: branded header, position selector, Shortlist + Player profile + Compare tabs; wired to Postgres; calls the Phase 7 filter live (nothing precomputed for a fixed budget)
- [x] Budget slider + typed number **kept in sync**; wage-budget + minimum-minutes sliders
- [x] Shortlist with fit/quality bars, value, undervaluation, archetype, fee/wage/profile ticks; near-miss banner
- [x] Profile: percentile chart with Bars/Radar toggle; Compare: 2–3 players on a radar + table
- [x] **Methodology tab** (pipeline diagram + per-stage plain-English explainer)
- [x] Club-red theme, custom CSS, crest via `assets/` (user-supplied, no bundled copyright asset)
- [x] Verified headlessly with Streamlit **AppTest** (zero exceptions) — the standing verification method for every dashboard change since
- **Acceptance — all passing:** a non-technical user picks a position and reads a shortlist; sliders update live; zero-match shows near-misses.

### Phase 9 — Package & Document ✅ COMPLETE (verified 2026-06-06)
- [x] **One-command runner** `lofc/pipeline.py` (schema → ingest → … → shortlists), each step idempotent
- [x] Whole stack deploys with `docker compose up` (db + app + dashboard + pgAdmin)
- [x] `docs/architecture.md`, `docs/methodology.md`, `docs/scaling.md` written; `README.md` finalised; `requirements.lock` pins versions
- **Acceptance — all passing:** `docker compose up` + `python -m lofc.pipeline` runs all stages clean and fully populates the database; dashboard live at :8501.

---

## Interview arc + dashboard v2 (2026-06-07 → 06-09)

- The platform was built as an interview deliverable. **CEO demo (David Gandler, Zoom)
  landed well** — walkthrough: CF · €15m · ~£150k/wk · 1500 min · signable ·
  type "high driving forward & pressing" → 31 strikers → 5 creative forwards →
  **Lucas Pérez (Deportivo) #1** (Quality 79, +38% undervalued — vindicated by his
  real ~€19m Arsenal move months later). Process advanced to the club's football/data
  panel.
- **2026-06-09: David provided real resources** — paid StatsBomb API credentials and
  SkillCorner 2026 tracking data — to refine the model before the panel meeting.
  (Credentials in `.env` only; the SkillCorner export and scraped TM data are
  licensed/commercial → gitignored, never public.)
- **Dashboard v2** (all AppTest-verified): inline profile under the shortlist row
  (shared `_render_profile_body` so inline and tab never drift); player-type filter +
  group-by-type; "Player types" cluster scatter (axes = two *different* trait families
  via `METRIC_FAMILY`); wage budget as a synced £/week control; KPI league pills;
  goals/assists tiles; Full-stats expander (total, per-90, percentile);
  strengths/watch-outs; signable-row tinting. **Metabase** added on the same Postgres
  (port 3000) as the wider-BI demonstration.

---

## Phase 10 — Real data + enrichment ✅ COMPLETE (2026-06-09 → 06-10)

**Audience note:** the demo audience became the **Director of Football (Scott), Head
of Recruitment Analysis (Joe) and COO (Steve Tait)** — so validation rigour and honest
caveats outrank polish. Wage framework + identity profiles stay modelled until the
club provides real ones. Checkpoints honoured: after A1 (targets agreed), after A7,
after B5.

### Stage A — Real StatsBomb data (8 EFL league-seasons)

- [x] **A1 Licence discovery** — paid licence verified live: full EFL pyramid
  2018/19→2025/26 (Championship, League One, League Two; National League from 20/21)
  + scouting leagues (Ligue 2, Scot. Premiership, Eliteserien, Allsvenskan, Irish PD)
  + PL2 + Euro 2020. **League One 2025/26 complete** (557 matches incl. playoffs).
  **Targets approved: League One + League Two + National League + Championship ×
  2025/26 + 2024/25.** Continental leagues deferred (calendar-season mismatch).
- [x] **A2 Configurable competitions** — `SB_COMPETITIONS` env var (decision 7);
  parsing fails loudly; tests env-isolated. NOTE: compose injects `.env` at container
  start → `docker compose up -d` after editing it.
- [x] **A3 Ingest** — all 8 league-seasons landed: **4,456 matches, 24 GB**. Paid-feed
  payload validated field-by-field against the aggregator before the full pull.
  **Paid lineups carry `birth_date`** (open data did not) → carried through to
  `players`. Two paid-feed quirks found and fixed: lineup clocks carry milliseconds
  (parser now uses `float()`), and transient API hiccups can return an empty events
  list (ingester refuses to persist empties so a re-run retries; aggregator skips
  them loudly). **19 fixtures (0.4%, almost all National League) genuinely
  uncollected on the feed** — documented in methodology.
- [x] **A4 Aggregate + spot-check** — 5,994 player-season rows, 4,568 rankable.
  **League One exact:** Ballard (LOFC) 23 = the real golden boot; Wareham 19, Tolaj
  18, Leonard 16 exact; Wootton +1 = his playoff goal (we include playoffs).
  **Championship exact:** Vipotnik 23, McBurnie 18, Wright 17, Clarke 16. League Two
  3/4 exact. National League variances fully explained by the 14 missing fixtures +
  playoff inclusion. Scores pass the football-sense check (Ballard top-5 CF both
  ways; Wing/Norwood lead DMs).
- [x] **A5 EFL market values** — dcaribou dataset confirmed **zero EFL coverage** (as
  decision 5 predicted) → built `ingest/transfermarkt_efl.py`: scrapes TM club-squad
  pages (4 leagues, ~100 requests, 2.5s rate limit, idempotent). **2,620 players,
  96 clubs.** Coverage: Championship 97% valued, League One 91%, League Two 90%,
  **National League 2.5%** → decision 10. Valuation rewritten dual-era (decision 8)
  with DOB+name matching (decision 9). **Result then: 1,525 valued; CV R² 0.748
  (log)** — the league feature carries real signal across 4 price tiers.
- [x] **A5b Wage model re-anchor** — `wage_estimates` now league-aware with bands
  (decision 11); Alembic migration applied; `model/wage_check.py` reconciles modelled
  squad bills vs published payrolls. **Validation: Championship anchors flagged +57%
  → re-anchored −30%; all 8 league-seasons within tolerance (−2%…+31%); LOFC's own
  modelled bill +9% vs its published Capology figure.**
- [x] **A6 Full pipeline on real data** — players 3,636 / metrics 5,994 / percentiles
  118,815 / scores+archetypes 4,568 / valuations 1,525 / shortlists 429 qualifying
  (later corrected to 357 by the gate-bug fix, then 400 by the loanee fix). Derived
  tables clear-then-insert so re-targeting leagues leaves no orphans; 1,542 stale
  demo player rows swept.
- [x] **A7 Verify + dashboard** — tests green; image rebuilt (beautifulsoup4, lxml,
  openpyxl) + lock regenerated; headless AppTest on the full 8-league DB: **zero
  exceptions**. Multi-season-safe loaders (latest-season pinning), minutes slider
  reworked (step 10, data-driven max, 450 floor + caption), season-aware KPI/footer.
  Methodology doc rewritten for the real-data era. **CHECKPOINT passed.**

### Stage B — SkillCorner ✅ (squad-only physical data → identity + benchmarks, NOT candidate scores)

File: `data/reference/skillcorner/SkillCorner-2026-04-27.xlsx` — League One 2025/26;
player-level = LOFC squad only; team-level = all 24 clubs. Scope = decision 14.

- [x] **B1 Ingest** — `ingest/skillcorner.py` + migration: `skillcorner_team_season`
  (24 clubs) + `skillcorner_player_season` (21 LOFC players, **21/21 matched** to
  StatsBomb ids by DOB+name). Clear-then-insert; conditional pipeline step (runs when
  an export exists). 'null' strings handled; dates ISO through the JSON round-trip.
- [x] **B2 Measured physical identity** — "Physical" tab: per-player squad table +
  league-rank summary per dimension, framed explicitly as **a draft for the DoF to
  confirm**. Caption states candidates are never physically scored.
- [x] **B3 League benchmarking** — metric selector + 24-club bar chart, LOFC in club
  red, rank + league-median caption (Orient: below-mid on total distance, mid-pack on
  sprints/high accels). Metabase tile SQL in `cli_commands.txt`.
- [x] **B4 Honest scoping note** — methodology §7: what SkillCorner is used for and
  what it refuses.
- [x] **B5 Verified** — 3 new tests (parsing, 'null' handling, DOB+name matching);
  AppTest zero exceptions. Bonus fix: player pickers use "Name — Club" labels so
  namesakes (two Cameron Humphreys) can't be conflated.

### Post-checkpoint polish (2026-06-10, user-approved batch)

- [x] Methodology tab rebuilt for the panel: **live funnel** (last stage reacts to the
  sidebar), 7 plain-language step cards with live DB numbers + per-step charts,
  "For the analyst" footnotes. Dashboard container now mounts `./data` read-only.
- [x] Minutes filter: synced slider + typed box (450 floor, data-driven max, clamped).
- [x] **Max-age filter** + help text (the veteran-bargain skew: TM floor-values older
  players regardless of output).
- [x] **Cross-league caveat** on Compare when players are from different leagues.
- [x] **Playing styles widened** where the data tolerates it (decision 16): CF and AM
  split into 3 football-sensible styles; others honestly stay at 2. Conflation test
  rewritten to assert the real invariant (opposite styles never share a cluster).
- [x] **Season-by-season trajectory** on profiles (the visible payoff of the 24/25
  ingest): minutes/goals/assists/npxG/xA per season with league-change caveat.
  Example: Ballard 24/25 = 6 goals (Cambridge + Sunderland) → 25/26 = 23-goal golden
  boot.
- [x] **User-found bug batch (2026-06-10 evening):** profile tiles + trajectory now
  position-aware (GK: save%/saves; defenders: tackles/interceptions). **Centre-back
  profile crash fixed at the root:** every profile lookup re-keyed by player+league
  (decision 13 — mid-season movers hold two same-season rows; Kacurri: Grimsby L2 +
  Morecambe NL is correct data, now two disambiguated entries). Pre-existing display
  bug found: save%/pass% stored 0–1 but formatted as 0–100 ("1%"). Verification
  sweep: all 8 positions + filter extremes exception-free; 8 SQL sanity checks zero.
- [x] **User-found gate bug (fixed):** the on-profile check pooled floor passes across
  ALL a player's season rows and demanded count == floor count — a second passing
  season flipped a player off-profile (Tolaj: npxG 95 + 63, both ≥ 55 → count 2 ≠ 1 →
  wrongly amber), and a last-season pass could mask a failing current season. Fixed:
  each (player, league, season) row judged alone (`compute_on_profile` re-keyed;
  regression test). Stored qualifying count corrected 429 → 357 (the bug corrupted
  both directions). Amber legend reworded: "fails at least one check".

### Recruiter-workflow batch ✅ (2026-06-10)

- [x] **Contract expiry + preferred foot + height:** scraper moved to TM's detailed
  squad pages (kader/plus/1, same request count + rate limit). 2,619 players:
  contract dates 82%, foot 93%, height 94%; **840 out of contract by summer 2026**
  (the free-transfer market). New `players` columns via migration; bio rides the
  valuation match. Sidebar: out-of-contract checkbox + foot selector; Contract column;
  profile header shows foot · height · contract. Demo gift: **Andy Dallas (shortlist
  #1) out of contract June 2026.**
- [x] **League column + league filter** (multiselect, feeds the live funnel too).
- [x] **CSV export** — the on-screen shortlist exactly (lists travel to scouts).
- [x] **NL fair-value caption** on National League profiles with a valuation.
- [x] **Watchlist — the workflow layer** (decision 15). `watchlist` table (player+
  league+season key, FK to players, status + note, timestamps; migration
  `e3f9ffc5dff5`). `store/watchlist.py`: Core-only persistence (sqlite-testable),
  idempotent add, LEFT-JOIN load. Profile button (☆ Add / ★ On watchlist + Remove) on
  both render sites. Watchlist tab: read-only table, click a row → **popup dialog**
  (st.dialog) with full note + status dropdown (Watching / Scout sent / Contact agent
  / Dropped) — redesigned after user UX feedback (data_editor cells truncated notes).
  CSV export with full notes; ignores sidebar filters by design. 7 new sqlite tests
  incl. left-join survival + mid-season mover; live Postgres round-trip verified;
  **a real watchlist entry survived a full pipeline rebuild** (the user-data
  guarantee proven in the wild).
- [x] **Transfermarkt profile links:** `players.tm_player_id` (migration
  `8298a17dd305`), backfilled via the valuation match + fallback ids. "View on
  Transfermarkt ↗" on profiles; LinkColumn on the Watchlist tab. Id-based
  (DOB-matched), so namesakes cannot cross-wire.
- [x] **Full pipeline certification:** `python -m lofc.pipeline` end to end after all
  Phase-10 changes — 11 steps, exit 0; ingest fully idempotent (0 pulled, 4,456
  skipped); 19 known uncollected fixtures skipped loudly.

---

## Code freeze → demo prep (2026-06-11 → 06-14)

- [x] **Watchlist dialog bug (user-found, fixed within the freeze):** every tab
  re-runs on interaction, so a persisted row selection re-opened the dialog on any
  click anywhere. Fixed: the dialog opens only when the selection CHANGES (session
  marker, reset on deselect); verified with a populated watchlist + cross-tab smoke.
- [x] **🧊 CODE FREEZE (2026-06-11) — final QA sweep passed.** All 8 positions render
  exception-free; filter extremes clean (age 18, minutes 4,900, budget €0, stacked
  contract+foot+league); **10 SQL invariants all zero** (incl. every shortlisted
  player has a TM link; no qualifying row off-profile); 57 tests green.
- [x] **Physical-tab duplicate bug (user-found 2026-06-13, fixed within the freeze):**
  4 players shown twice. Cause: `load_sc_players()` joined 21 SkillCorner rows to a
  position lookup; four mid-season movers hold two same-season rows, fanning 21→25.
  Fix: `positions.drop_duplicates("player_id")` before the merge. **Third instance of
  the decision-13 pattern; all per-player views now keyed or deduped.**
- **Demo prep (2026-06-14):** walkthrough script lives in chat only (user preference —
  no script files). Structure: intro → set the brief (sidebar) → ranked list +
  out-of-contract reveal (Andy Dallas, Southend, free in June) → profile (Dallas →
  Wareham as the firm-ground valuation, NL uncertainty caveat) → player types (3
  striker styles, Ballard surfaced by the data) → compare (cross-league warning fires
  itself) → watchlist → physical (SkillCorner, squad-only) → methodology funnel +
  forward close. Verified demo facts: budget €1m, age ≤28, 1500 min, contract filter
  ON → Dallas + Taylor only; valuation R² ≈ 0.75 on EFL.
- **Decided NOT to add features pre-demo** (decision 17): rejected adding leagues
  (reopens scraper + wage anchors + re-validation; continental calendar mismatch);
  similar-player search scoped but parked.

---

## Demo to the panel + post-demo work (late June → 2026-07-05)

**The demo to Scott (DoF), Joe (Head of Recruitment Analysis) and Steve Tait (COO)
went well.** Follow-ups agreed/offered: continued availability over the summer
(part-time until 1 Sept, full-time from September — proposed by email), and **Joe
granted access to the FM Database (FMDB) and Impect data** as candidate future inputs.

### Valuation reliability analysis (honest findings — the basis of decision 18)

Trigger: Joe asked for Dominic Ballard's fair value, which forced the question "how
reliable is a single fair-value number?". Method: the out-of-fold predictions vs
actual values, per league (out-of-fold = every player priced by a model that did not
train on them, so this is honest held-out error, not training fit).

Measured on the current build (2026-07-06, n = players valued in that league):

| League | n | median abs error | median abs % error | log-correlation |
|---|---|---|---|---|
| Championship | 554 | €940k | 49% | 0.75 |
| League One | 531 | €140k | 43% | 0.60 |
| League Two | 500 | €60k | 37% | 0.62 |
| National League | 58 | €92k | 75% | **0.06** |
| Cheap players (<€300k, pooled) | 681 | — | 45% | — |

**Interpretation (stated plainly, also to Joe):**
- The pooled CV R² (0.745) is **flattered by the league feature** — much of it is the
  model correctly knowing a Championship player outprices a League Two one.
- **Within a league the ordering signal is real** (log-correlation ~0.6–0.75): "this
  player is priced below peers with his output" is trustworthy.
- **The point estimate is not a price**: typical error ~±40% within a league, worst
  for cheap players (TM values are coarse at the bottom — €25k steps, floor values)
  and no signal at all in the National League (vindicating decision 10).
- **More data will not fix this.** The ceiling is feature relevance, not sample size:
  contract length, potential/age-curve expectations, reputation and selling-club
  leverage drive prices and are absent from the features. FMDB + Impect are the
  candidate sources for exactly those features — to be interrogated first, then
  integrated across iterations (owner: the user).
- Framing shipped: fair value is a **screening/ranking signal**. Use it to order the
  queue and spot mispricing, not to quote a fee.

---

## 2026-07-06 — Cross-league loanee valuation fix (freeze lifted) — LIVE STATE

**Trigger:** the panel asked to look at **Josh Stokes** (Stockport County, AM). He was
invisible in the tool despite strong numbers.

**Diagnosis (root cause, established from the data):**
- Stokes IS in the DB and fully scored: player_id 405034, born 2004-04-29, 1,533 min,
  Quality 66, Fit 73.9, style "high passing into the box & chance creation, low goals".
- He had **no valuation row**: he is a **Bristol City loanee**, so his Transfermarkt
  value (€400k) is listed under the parent club — in the **Championship** — while his
  metrics row is League One. The value match was league-scoped (decision 9 as then
  built), so the DOB+name pass looked only inside League One and found nothing; the
  fallback dataset covers out-of-pyramid loanees, not cross-league ones.
- `build_candidates()` inner-joins valuations, so unvalued players drop out of the
  shortlist pool, profile picker and compare entirely. **Every parent-club loanee
  playing in a different division was silently missing.**

**Fix (surgical, ~10 lines + tests):** a fourth matching stage in
`match_players_efl()` — a league-agnostic DOB+name pass over the whole scrape,
running **only after both in-league passes fail**, same 0.55 name cutoff. In-league
priority is preserved by construction (the new pass cannot fire when an in-league
match exists); exact-DOB + fuzzy-name across four leagues makes false positives
vanishingly unlikely, and a name-agreement test guards the DOB-coincidence case.

**Results:**
- **+122 loanees matched** (Stokes was far from alone). 1,643/2,291 rankable 2025/26
  players valued (**71.7%**, up from ~66%).
- Model quality unchanged: CV R² 0.745 (was 0.748), median abs error €160k.
- Qualifying shortlist rows 357 → **400**. Stokes now: €400k market vs **€802k fair
  value (+50% undervalued)**, on-profile, visible in shortlist/profile/compare.
- **3 new tests** (cross-league catch; same-DOB-different-name rejected; in-league
  priority wins) → **60 green**. Valuation + constrain re-run; dashboard restarted.
- **Freeze formally lifted** (its purpose — a stable build to rehearse — ended with
  the demo).

**Documentation overhaul (same day):** this file restructured to the read-first +
append-only-log format; `docs/architecture.md`, `docs/methodology.md` and
`docs/scaling.md` rewritten in full detail (current data model incl. SkillCorner/
watchlist/bio tables, the four-stage value matching, the reliability findings, the
add-a-league and deployment playbooks).

**Open items (not started):**
- Club's real wage framework + identity profiles (CSV drop-ins when provided).
- FMDB + Impect interrogation → valuation feature upgrades (contract length,
  potential). Owner: the user, over multiple iterations.
- Roadmap candidates discussed, awaiting a decision: similar-player search;
  availability % (matches played ÷ team matches); "does he improve us" benchmark vs
  LOFC's own players; height filter (data already in `players.height_cm`).
- Deployment when wanted (see `docs/scaling.md`).

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
  idempotent skip confirmed at full scale (re-run skipped 380/380).
- **Phase 2:** inspected the real lineup/event files first and caught that the match clock
  resets at half-time, so minutes had to be period-aware (a naive subtraction undercounts
  cross-half spells by the first-half stoppage). Validated by spot-check: goals matched
  the real 2015/16 totals exactly across all three leagues.
- **Phase 3:** autogenerated the migration from the ORM models. Built the constructed
  reference data as a documented generator with assertions (identity weights sum to 1.0)
  and provenance flags (fact vs estimate vs assumption). Paused for user review before
  loading.
- **Phase 4:** pushed back on a single bundled score and split it into Quality vs Fit,
  which is more honest and maps to the brief. Repeatedly explicit that the fit identity
  is invented, not real LOFC data. Spot-check confirmed the split is real (Kanté).
- **Phase 5:** added within-player centering (not in the original plan) so clusters
  capture style rather than quality, pre-empting the "isn't this just good vs bad?"
  critique. Kept the modest silhouettes honest rather than overstating separation.
- **Phase 6:** found an auth-free source for the Transfermarkt data. Caught two data
  traps by inspecting first: the valuation league tag is unreliable (matching scoped by
  real appearance records instead), and short-name mismatches survive scoping
  (implausible ages rejected and logged). Used cross-validation for out-of-fold fair
  values after the user asked the right question about the test set. R² 0.51 reported
  honestly.
- **Phase 7:** adopted the user's amendment to ship the wage gate live (anchored
  synthetic wages, not value-derived) and pushed back on the flat-% approach for bias.
  Caught two bugs by validating before trusting (0–1 vs 0–100 scale; no-floor positions
  excluded instead of auto-passing). Kept the demo result honest (all near-misses at the
  real ceiling) rather than faking a populated default.
- **Phase 8:** club-themed Streamlit app verified headlessly with AppTest (zero
  exceptions) since there is no browser in the loop; fixed a real deprecation past its
  removal date. Crest user-supplied so no copyrighted asset is bundled.
- **Phase 9:** packaged the pipeline behind one idempotent command; wrote the three docs
  honestly including assumptions and limitations; verified the full compose + pipeline
  flow end to end; pinned dependencies.
- **Phase 10:** validated the paid-feed payload field-by-field before the 24 GB pull;
  found and fixed two feed quirks (millisecond clocks, transient empty payloads) without
  corrupting the landing zone; spot-checked aggregates against real golden-boot tables
  (exact in two leagues); predicted and confirmed the dcaribou EFL gap and built the
  scraper instead; reconciled the wage grid against published payrolls and corrected an
  anchor the loop flagged. Three user-found bugs (gate pooling, profile crash, physical
  duplicates) all traced to one root pattern (the multi-row mid-season mover) and fixed
  at the root with regression tests, not patched per-symptom.
- **Post-demo:** answered "how reliable is fair value?" with a measured per-league error
  analysis rather than reassurance, and reframed the number as a screening signal.
  Diagnosed the invisible-loanee report (Stokes) to its root cause in the league-scoped
  match and fixed it for the whole class (+122 players), with tests proving in-league
  priority and false-positive guards.

---

## Phase 11 — Impect migration (IN PROGRESS) — decided + Phase A executed 2026-07-07

**Why this phase exists.** The club is standardising on **Impect** as its single
event-data provider within ~a year. Joe (Head of Recruitment Analysis) gave the user
paid Impect access and its API, and shared three club files (now in `docs/`):
`API SB Helper.pdf` (StatsBomb season-stats spec), `Data - Positional Metrics.xlsx`
(the metrics that matter per position), and `LOFC - Position Archetype.docx` (the
club's real Feb-2026 recruitment operating model: per-position profiles, thresholds,
scorecard weights). Joe also asked to add the **Scottish leagues and PL2**. Strategy
locked with the user: **Impect primary, StatsBomb frozen baseline, provider-neutral
layer** (decisions 19–22).

**The four-phase plan (see also the READ-FIRST box):**
- **A — Impect in cleanly + proven correct** ✅ DONE (this session).
- **B — provider-neutral layer + map the club's metrics to Impect.** Needs Joe's Friday
  sign-off on the concepts with no clean Impect twin (on-ball value especially).
- **C — apply the club's real framework** (per-position metrics, median/70th-pct
  thresholds, scorecard weights); re-point valuation at Impect features; re-validate.
- **D — dashboard + make Impect primary.**

### Phase A — DONE + GATE PASSED (2026-07-07)

- **Config (`config.py`):** `ImpectTarget` model + `DEFAULT_IMPECT_TARGETS` (14
  iterations: EFL×4 + Scottish Premiership/Championship + PL2, both 2024/25 & 2025/26,
  iteration ids verified against the licence catalogue). `IMPECT_USERNAME/PASSWORD`
  and `IMPECT_ITERATIONS` env (fails loudly on a malformed override). The four EFL
  targets carry their StatsBomb (competition_id, season_id) mapping so validation can
  compare like-for-like; the added leagues carry none (we hold no StatsBomb for them).
- **Ingest (`ingest/impect.py`):** idempotent pull via the official `impectPy` package
  (pinned in pyproject + baked into the image + lock regenerated). One parquet per
  iteration under `data/raw/impect/` (gitignored — licensed data), plus the licence's
  iteration catalogue for traceability. Atomic temp+rename writes; refuses to persist an
  empty payload (same guard as the StatsBomb ingest); `--force` / `--iteration N`.
- **Validation gate (`model/impect_check.py`, read-only):** reconstructs season totals
  from Impect's averages (KPI × matchShare summed over a player's position rows —
  verified: Ballard 0.6131 × 37.52 = 23.00, his real golden boot), matches Impect
  players to ours (TM id then birth-date+name at the 0.55 cutoff), and compares goals +
  xG against the StatsBomb data we already validated.
- **Tests:** `tests/test_impect.py` (11) — target parsing, the average×matchShare
  reconstruction, TM-id-first matching, DOB+name fallback, and the same-birthday-
  different-name rejection. **71 green total.**

**GATE RESULT (the checkpoint that earns the switch) — PASS for the EFL:**

| Iteration | Goals exact | Within one | xG corr | Matched to our DB |
|---|---|---|---|---|
| Championship 24/25 | 99.7% | 100% | 0.992 | 98.1% |
| Championship 25/26 | 98.8% | 100% | 0.991 | 96.8% |
| League One 25/26 | 99.0% | 100% | 0.990 | 93.7% |
| League Two 24/25 | 99.1% | 100% | 0.988 | 95.4% |
| League Two 25/26 | 98.7% | 100% | 0.988 | 96.4% |
| National League 24/25 | 96.6% | 99.6% | 0.987 | 94.1% |
| National League 25/26 | 93.1% | 98.6% | 0.991 | 92.1% |

The residual goal gaps are exactly the expected **playoff-inclusion tail** (our
StatsBomb totals include playoffs; the Impect league iteration does not), e.g. Nick
Haughton 16 vs 19 (three playoff goals). Impect is trustworthy for the EFL.

**Two honest findings recorded:**
1. **The Transfermarkt-id bridge did NOT work at the averages endpoint** — the
   `transfermarktId` column is present but null there, so the clean id-join I expected
   didn't fire; **birth-date+name carried the match at 92–98%**. A TM id may live on a
   different Impect endpoint (player master data / profiles) — check in Phase B; DOB+name
   is adequate regardless.
2. **Scottish + PL2 match rates are low (6–32%) and that is expected**, not a failure:
   our `players` table only holds EFL players, so a Scottish/PL2 player matches only if
   they also appeared in the EFL. These become NEW player records when integrated (Phase
   C). Landed counts: Scottish Prem ~369–385, Scottish Champ ~274–284, PL2 ~999–1,141.

**Data landed:** 14 iterations, ~1,480 KPIs/player (Impect's packing family: opponents/
defenders bypassed by zone and action type, packing-xG, expected-threat, ball win/loss,
zonal duels/shots). EFL player counts track StatsBomb almost exactly (League One 25/26:
Impect 749 vs our 748).

**NEXT (Phase B, some gated on Friday):** confirm whether a usable player id/TM id lives
on another Impect endpoint; define the neutral metric set from the club's positional
file; build the Impect→neutral translator + a StatsBomb→neutral translator; produce the
club-metric→Impect mapping table and flag the no-clean-twin cases for Joe. **StatsBomb
build stays the live baseline throughout — nothing switched yet.**

### SkillCorner platform migration — DONE + coverage validated (2026-07-10)

**Why:** Joe gave paid SkillCorner PLATFORM/API access, replacing the squad-only xlsx
(`ingest/skillcorner.py`). The decisive question was coverage, and it landed the right
way: the licence covers the leagues at PLAYER level for ALL teams, so physical data is
available for RECRUITMENT TARGETS. This closes the physical dimension of the club's
framework, which the squad-only file (decision 14) could never do for candidates.

- **Config:** `SkillCornerTarget` + `DEFAULT_SKILLCORNER_TARGETS` (7 editions:
  Championship/L1/L2/NL + PL2 + Scottish Premiership + Irish Premier, 2025/26; edition
  ids verified against the licence catalogue). `SKILLCORNER_USERNAME/PASSWORD` +
  `SKILLCORNER_EDITIONS` env (fails loudly). EFL editions map to our (competition_id,
  season_id); the others carry none (pulled, but only join players we already hold).
- **Ingest (`ingest/skillcorner_api.py`):** pulls `get_physical(group_by=player)` — one
  season-aggregated row per player (per-match averages + match counts + the top-3/top-5
  timing benchmarks the club doc names). Landed parquet per edition under
  `data/raw/skillcorner/` (gitignored, licensed); idempotent; `--force`/`--edition`.
  `skillcorner` package pinned + baked into the image + lock regenerated.
- **Coverage check (`model/skillcorner_check.py`, read-only):** matches SkillCorner
  players to ours (birth date + name) and reports the rate. **Tests:**
  `tests/test_skillcorner_api.py` (5) → **76 green total.**

**COVERAGE RESULT (the checkpoint):** all metrics the club's archetype sheets demand are
present (PSV-99 + top-5, sprint distance/count, HSR distance/count, running distance,
total distance, m/min, high-intensity, explosive-accel-to-sprint/HSR, top-3 time to
HSR/sprint, change-of-direction, 505 agility). Candidate match to our DB:
Championship 96.1%, League One 93.6%, League Two 95.1%, National League 91.6% —
**physical data now available for ~92–96% of EFL candidates.** PL2/Scottish/Irish match
low (12–20%), expected until those players are ingested.

**Honest caveats:** (1) physical covers **2025/26 + 2026/27 only, not 2024/25** — it
joins the 2025/26 rows of our event data; a 2024/25 row has performance but no physical
(handled as blank, never cross-season, per the grain invariant). (2) The old xlsx loader
+ its `skillcorner_player_season`/`_team_season` tables (squad-only) are still in place;
**fully retiring them (loading the all-league physical into the DB + updating the
Physical tab)** is the next step, done with the neutral-layer/scoring work so the schema
change is made once.

### Impect metric map + translator — DONE + verified (2026-07-10)

Building the provider-neutral layer. First the Impect half.

- **The map (`ingest/impect_map.py`, single source of truth):** 41 internal metric
  names, each with its Impect source and a confidence tier. Verified: every referenced
  Impect column exists. Exported to `data/reference/impect_metric_map.csv` for Joe to
  review/override. Tiers: **10 direct · 10 derived · 4 analogue · 4 native · 13 none.**
- **THE KEY FINDING (structural, not a mapping oversight):** the 13 "none" are the
  StatsBomb-only defensive/pressing metrics (tackles, interceptions, clearances,
  pressures, counterpressures, PAdj tackles/pressures, deep progressions, xG buildup).
  Impect has **no equivalent by name** — it measures defending through duels + on-ball
  value (PxT), not event counts. So Impect covers 28 of the club's target metrics; the
  13 come from StatsBomb (per-metric hybrid, which the neutral layer allows). Eventually
  Joe's framework is either re-expressed in Impect's duel/value language or those 13 are
  dropped — a club decision, flagged.
- **The translator (`ingest/impect_translate.py`):** landed Impect file -> one row per
  player with our internal names. Two corrections it exists for: (a) **per-90** — Impect
  KPIs are averages per full match (~100 min), so we rebuild season totals (value x
  matchShare) and divide by real minutes (playDuration/60) x90; (b) the **450-min floor**
  (same as StatsBomb), since a cameo scorer otherwise reads 14/90.
- **SANITY CHECK vs StatsBomb (548 rankable matched League One players):** `goals_p90`
  **corr 1.000, means identical** — the per-90 conversion is exactly right. `np_xg` 0.96,
  `xa` 0.84, `assists` 0.85 — strong, with small mean gaps = expected provider-model
  differences. The check **caught two mapping bugs** (xa was on EXPECTED_SHOT_ASSISTS, a
  count 9x too big -> fixed to EXPECTED_GOAL_ASSISTS; np_xg's SHOT_XG includes penalties
  -> documented). Both preserved in the map notes.
- **Tests:** `tests/test_impect_translate.py` (6: per-90, minutes floor, ratio,
  multi-position aggregation, none-metrics-absent) -> **82 green total.**

**Impect gaps re-verified (2026-07-10, user pushed back — correctly):** my first "13
gaps" was overstated. Re-searched all 1,482 columns (Impect names presses "PRESSES" not
"PRESSURES") AND pulled Impect's **official KPI definitions** from the metadata API
(`https://api.impect.com/v5/customerapi/kpis`, saved `data/reference/impect_definitions.csv`;
human glossary `https://glossary.impect.com/`, login-gated). Result — RECOVERED: pressures
(`NUMBER_OF_PRESSES`, corr 0.91), counterpressures (`NUMBER_OF_PRESSES_COUNTER_PRESS`,
spot-checked on known pressers), deep progressions (`BYPASSED_OPPONENTS_TO...FINAL_THIRD`,
corr 0.81). CONFIRMED NO EQUIVALENT (defn + magnitude): ball recoveries (`BALL_WIN_NUMBER`
is packing-weighted regains, corr 0.14 — refuted), interceptions, clearances, aggressive
actions, PAdj (no possession adjustment), xG buildup, pressures-in-opp-half, pressured-pass%,
box-cross%. **Map now 31 mappable / 11 gaps** (10 direct, 10 derived, 7 analogue, 4 native).

**StatsBomb gap wiring — DONE (2026-07-10):** of the 11 gaps, 4 are already in
`player_season_metrics` from our event aggregate (tackles, interceptions, clearances, ball
recoveries); the 7 advanced ones come from the **StatsBomb Season-Player-Stats endpoint**
(`ingest/statsbomb_season.py`). This is trivial vs Impect: the endpoint returns ready-made
per-90 values and its player_id IS our player_id (no matching). Pulled all 8 EFL
league-seasons; the endpoint splits mid-season movers per club, so the translator
**minutes-weights** them back to one row per player-league-season (fixed a 782->748
fan-out; regression-tested). 100% of our League One players enriched; xG-buildup top-5 are
deep creators (sane). Tests `tests/test_statsbomb_season.py` (4) -> **86 green total.**

**NEXT (Phase B remainder):** the per-metric SOURCE SWITCH + wiring the neutral layer into
the pipeline (combine Impect-translated 31 + StatsBomb 4-existing + StatsBomb-endpoint 7).
**Nothing switched live yet; StatsBomb still runs the tool.**

### Map expanded to 49 metrics + a real bug caught and fixed (2026-07-20)

User asked for the club-file gap metrics + high-value Impect extras to be added before
assembly. Added 12: 4 club-gaps Impect covers (turnovers, open-play assists, combined
NP xG+xA, save%), 5 club-gaps only StatsBomb has (dribbles, dribble%, GK claims, GK
aggressive distance, long ball%, -> added to `statsbomb_season.py`'s gap map), 3 Impect-only
extras (off-ball receiving `BYPASSED_OPPONENTS_RECEIVING`, finishing quality `POSTSHOT_XG`,
shot threat `PXT_SHOT`). All columns verified present. **Map now 49 total, 36 mappable from
Impect / 13 from StatsBomb** (13, not 11: the two GK bugs below moved from Impect to the
"none" tier).

**Also generalised `ratio` to support signed terms** (same `(col, sign)` pair format as
`rate`), needed for `gk_shot_stopping_pct`'s GSAA/post-shot-xG formula (a subtraction in
the numerator) -- every existing ratio entry + `impect_columns_used()` + the translator's
ratio branch updated to match; regression-tested.

**A real bug, caught by the user asking for a spot-check, not by me:** `gk_saves_p90` and
the new `save_pct` were mapped to `SHOT_AT_GOAL_NUMBER_SAVED`/`_ON_TARGET`. Checked these
against real goalkeepers (Sam Walker, Sam Tickle, Josh Keeley, all near-full seasons) and
both read **exactly zero for every one of them**. Root cause: those Impect columns are
**shooter-context** (a player's OWN shots saved by the opposing keeper), not keeper-context
(shots a goalkeeper faced) -- confirmed against Impect's own KPI definition ("intention to
score a goal... ball ends up saved by the OPPONENT goalkeeper"). A second finding this
exposed: `gk_saves_p90` and `save_pct` are not new metrics at all -- they are ALREADY
produced correctly by our original event-based aggregate (`aggregate/events.py` ->
`player_season.py`), predating this whole Impect project. **Fix:** both moved to the "none"
tier (documented as already-correct via the existing pipeline, not a live gap); the
already-fixed `gk_shot_stopping_pct` (GSAA / post-shot xG faced, both genuinely
keeper-context "CONCEDED_" columns) verified sane on the same three keepers (small
positive/negative values around zero, as a GSAA-style ratio should be). A broader sweep
found 14 OTHER same-name overlaps between the map and the existing pipeline (goals_p90,
np_xg_p90, assists_p90, pressures_p90, etc.) -- all confirmed correct: these are the
INTENDED design (same internal name, deliberately re-sourced from a verified Impect
column, each already magnitude-checked earlier in Phase 11). Only the two GK metrics were
a genuine mapping error. Tests + CSV regenerated; **86 green throughout.**

### Metric layer finalised across four source files + consolidation investigated (2026-07-20)

Session focused on making the metric provenance clear and consistent (the user needed a
presentable, unambiguous "what comes from where"). Outcomes:

- **SkillCorner got its own definition file** (`ingest/skillcorner_map.py`): the 24
  physical metrics listed explicitly (name → raw SkillCorner column → description),
  matching how Impect and StatsBomb-advanced are defined. Previously SkillCorner had NO
  curated list — the new API loader just took whatever columns came back. 6 timing/agility
  metrics flagged `LOWER_IS_BETTER` (faster = better, inverted in scoring). All 24 columns
  verified against real data.
- **`docs/DATA_ARCHITECTURE.md` created** — the presentable reference: all 87 metrics
  listed by source, a "what each file does" table, and the honest source split. This is
  the doc to show the recruitment team.
- **Consolidation of the 15 StatsBomb-original metrics into the endpoint: INVESTIGATED and
  REJECTED (with evidence).** I had earlier claimed the season-stats endpoint contained all
  15 (checked only 12, extrapolated — wrong). Exhaustive search found the pre-computed feed
  is **missing 6**: progressive passes, progressive carries, blocks COUNT (only
  blocks-per-shot ratio), GK saves COUNT (only save ratio), all-passes count (only
  open-play), all-shots xG (only non-penalty). So full consolidation is impossible, and a
  partial move (9 to endpoint, 6 stay) would create a worse three-way split. **Decision:
  keep the 15 in the event-aggregation pipeline.** The two StatsBomb files are a real
  capability line, not an accident: `models.py`+`aggregate/*` = "metrics we compute
  ourselves from raw events (incl. ones the feed can't give)"; `statsbomb_season.py` =
  "advanced stats StatsBomb pre-computes that we cannot replicate". Documented in
  `DATA_ARCHITECTURE.md`.
- **Reader-facing docs** (`architecture.md`, `methodology.md`, `scaling.md`) given a
  Phase-11 status banner pointing at `DATA_ARCHITECTURE.md`; they still describe the LIVE
  StatsBomb-only tool because nothing is switched yet.

**Final metric tally (defined, not yet in the DB): 87/player** = 36 Impect + 12
StatsBomb-advanced + 15 StatsBomb-original + 24 SkillCorner-physical. **86 tests green.**

**NEXT = Step 1 (the merge):** combine the four defined sources into one table per player,
one source per metric (Impect wins the ~10 overlaps), in memory. Then Step 2 wires it into
the database. Nothing switched live yet.

### Step 1 DONE — unified metric registry + the neutral-layer merge (2026-07-20, later)

The user required metric provenance to be explicit IN CODE (not only in markdown), and
every derived metric's computation to be explicitly stated. Both delivered:

- **`model/metric_registry.py` — the unified registry.** ONE `MetricSpec` entry per final
  metric (87), each with its single `source` and an explicit `derivation` string: the raw
  column for renames, the exact formula for everything we derive (e.g. tackles_p90 =
  'count of Duel events with duel type "Tackle" (events.py:192-194); count / minutes x 90
  (player_season.py:134)'). Assembled FROM the four per-source definition files (they stay
  the truth for their own source); **`OVERLAP_RESOLUTION`** makes the 12 cross-source
  conflicts explicit in code (10 -> Impect, 2 -> the advanced endpoint). Invariants
  (87 total, 36/12/15/24 per source, no duplicates, winners consistent) are **asserted at
  import time**, so a bad edit fails loudly everywhere. `python -m lofc.model.metric_registry`
  prints the full inventory.
- **`model/build_neutral.py` — the merge (Step 1 of the wiring plan).** Pure
  registry-driven combine: spine = player_season_metrics (identity + the 15 computed),
  left-joined with Impect (translated + DOB/name-matched), the advanced endpoint
  (player_id-keyed), and SkillCorner (matched + renamed via skillcorner_map). Each source
  contributes ONLY its registry-assigned columns, so no collisions by construction; no
  fan-out (asserted). Read-only — nothing written to the DB yet.
- **RESULT (all 8 EFL league-seasons):** ~740-770 players each; source coverage on
  rankable players: Impect 95-99%, advanced 100%, computed 100%, SkillCorner 88-91% for
  2025/26 (0% for 2024/25 by design — no physical before 25/26). Spot-check: Ballard's
  single combined row carries all four sources (goals 0.54/90 x 42.5 nineties = his real
  23; packing-xG + off-ball receiving from Impect; xG-buildup + PAdj from the endpoint;
  tackles + progressive passes computed; PSV-99 29.53 from SkillCorner).
- **Docs now generated FROM the registry:** `docs/DATA_ARCHITECTURE.md` §3 (all 87 with
  exact derivations + the overlap table) is produced by the registry itself, so docs
  cannot drift from code. Tests: `tests/test_metric_registry.py` (7: counts, uniqueness,
  derivation completeness incl. computed-metrics-must-cite-code, overlap consistency,
  merge no-fan-out/fill-by-source/dedupe) -> **93 green total.**

**NEXT = Step 2:** wire the combined table into the database (extend `models.py` schema
via Alembic + a loader step in the pipeline), then Step 3 re-score + compare shortlists.
Nothing switched live yet; the dashboard still runs on the original StatsBomb build.

### Step 2 DONE — the combined table is in the database (2026-07-20, later still)

- **Schema:** `PlayerMetricNeutral` (`player_metrics_neutral`) added to `store/models.py`
  with its 87 metric columns **generated from the registry** (a loop over REGISTRY), so
  schema and definitions cannot drift — locked by a test that asserts table columns ==
  identity + the 87. Unique on (player_id, competition_id, season_id).
- **Migration:** Alembic `71204e85d2fb` (autogenerated, inspected: creates ONLY the new
  table — no alters/drops of live tables), applied clean.
- **Loader:** `build_neutral --write` — clear-then-insert per league season, the same
  idempotent pattern as every derived table. Object-dtype NA columns coerced to float so
  absent-source values land as SQL NULLs.
- **Loaded + validated:** **5,994 rows** across all 8 league seasons — exactly one per
  player_season_metrics row, keys unique, idempotency proven (re-run → still 5,994).
  Ballard's DB row spot-checked: values from all four sources present and correct.
- **Pipeline wired:** steps 12–15 appended (pull advanced StatsBomb / Impect / SkillCorner
  — each conditional on its credentials — then rebuild the combined table). The pipeline
  is now 15 steps; the LIVE tables and dashboard remain untouched.
- **Stale files refreshed:** `data/reference/impect_definitions.csv` regenerated to cover
  ALL 32 Impect columns the map references (was a 21-column subset predating the added
  metrics); `docs/DATA_ARCHITECTURE.md` updated (status + the unified-layer file map).
  **94 tests green.**

**NEXT = Step 3:** re-score on the neutral table and compare shortlists vs the live build
(a checkpoint with the user), then Step 4 = the club's real per-position framework.

### User-found data issue -> day/month-swap rescue in matching (2026-07-20, evening)

The user, browsing `player_metrics_neutral`, spotted players with whole blocks of NULL
columns (e.g. **Luke Harris**: StatsBomb metrics filled, every Impect + SkillCorner
column NULL). Diagnosis: our players table (from StatsBomb lineups) has him born
**2005-04-03**, while Impect AND SkillCorner both carry **2005-03-04** — a **day/month
swap** in a provider's data entry. Exact-birth-date matching therefore failed in both
sources, despite the identical name. Quantified: 277 unmatched Impect player-rows across
the 8 EFL iterations, of which **7 are provable swap cases** (identical normalised name +
exactly swapped date): Luke Harris x3, Adam Fairclough x2, Jaxon Brown, Cody Johnson.

**Fix:** a swap-rescue stage in BOTH matchers (`impect_check.match_to_ours`, shared by
`skillcorner_check`): if DOB+fuzzy-name fails, try the day/month-swapped date, but ONLY
with an **exact normalised-name match** (date evidence is weaker, so the name bar is
raised from fuzzy to exact; guarded to days <= 12 where a swap is possible). Tagged
`matched_via="dob_swap"`. 4 new tests (rescue works in both matchers; different name
rejected; impossible swaps skipped). Table rebuilt: Harris now carries all four sources.
**98 tests green.**

**NULL-vs-fallback policy recorded (user question):** the four legitimate causes of NULL
(identity mismatch; source doesn't cover the season, e.g. no physical before 25/26;
zero-denominator ratios; genuine zeros are 0 not NULL) — and there is deliberately **NO
metric-level cross-source fallback** (one source per metric keeps every player measured
by the same instrument; per-player source-mixing would silently bias comparisons).
Match-level rescues (like this swap fix) are the right lever and the only one used.

### NULL diagnosis round 2: provider DOB disagreements + the zeros verified (2026-07-20, night)

User flagged still-many NULLs and asked whether the 0s are genuine. Two findings:

**NULLs — provider birth-date DISAGREEMENTS (not swaps).** 24 rankable regular starters
in League One 25/26 (Ethan Pye 4,892 min, Oliver Casey 4,247 min) had ALL Impect columns
NULL. Cause: StatsBomb and Impect genuinely disagree on their birth dates (Pye: ours
2002-11-07 vs Impect 2003-11-27 — different year AND day, not a swap). Exact-DOB matching
therefore failed despite identical names. Measured: of ~277 unmatched, **201 are exact
name, same league season, unique on both sides** (only 1 ambiguous). **Fix:** Stage-4
EXACT-NAME-WITHIN-LEAGUE rescue in both matchers — when a name is unique among OUR
league-season players AND unique among the still-unmatched rows, match on exact
normalised name with no date requirement (two different footballers, identical full name,
same division + season is not credible; ambiguous names refused). Wired via
`build_neutral._league_name_index` (built from the spine). Impect coverage 95–99% ->
**98–100%**; residual missing 0.2–1.6% per league (~35 players) are genuine Impect
absences. Ethan Pye now carries all four sources. 6 new tests (rescue works both matchers;
ambiguous refused; off by default). **101 tests green.**

**Zeros — VERIFIED genuine, not errors.** Among the 549 rankable players WITH Impect data:
metrics where 0 is impossible (passes_completed, pass_completion_pct, pressures,
packing_bypassed_opponents) have **exactly 0 zeros**; zeros appear only where role-plausible
(186 with 0 goals, 162 with 0 assists — defenders/keepers). So a 0 is a real measurement
(a centre-back's 0 goals/90), never a failed computation. NULL and 0 mean different things
by design (missing vs genuinely none). Recorded for the write-up.

### Step 3 DONE — shadow re-score on the neutral table vs live (2026-07-20, checkpoint)

Read-only shadow comparison (`scratchpad/step3_compare.py` + diagnostics). Scores AND
shortlists recomputed from BOTH `player_season_metrics` (live) and `player_metrics_neutral`
with the SAME scorer (normalise + score) and SAME filter (constrain/filters), in memory.
**No live table touched.** Faithfulness proven: recomputed-live == stored `player_scores`
to max |gap| 0.000, so every difference is the DATA, not the code path. 11 of 27 scored
metrics change source (9 -> Impect, 2 -> SB advanced).

**Two effects, separated:**
- **Genuine signal (99.2% Impect covers, 4,533 players):** performance corr 0.966
  (mean|Δ| 2.5), fit corr 0.955 (mean|Δ| 2.9); ~32% of players move >=10 rank places
  within position-league. Model not overturned, but moves for real — the intended effect.
- **Artifact (0.8%, 35 rankable players, 7 in League One):** ALL 10 Impect-scored metrics
  NULL -> those weighted terms silently drop from the fit sum -> score COLLAPSES for a data
  reason (fit corr 0.45, max|Δ| 58). Every scary "big mover" (A.Sidibeh -58, Apter -53,
  Tutierov -50, Olaofe -48) is one of these 35. This is the NULL-handling flaw the
  checkpoint exists to catch — a bug, not a re-rating.

**Biggest genuine driver = pressing definition.** `pressures_p90` StatsBomb->Impect
"PRESSES": Spearman only 0.73, mean percentile move 15.8 — genuinely RE-ORDERS players
(Keillor-Dunn 71st->1st pct). Does a lot of the fit work because pressing is central to
LOFC identity. Whether Impect's definition is "right" is a football call for Joe.

**Shortlist churn (League One 25/26, EUR5m):** moderate; concentrated at Centre Forward
(9 in / 6 out, partly contaminated by the artifact). Report: `scratchpad/STEP3_REPORT.md`.

**CHECKPOINT DECISION — did NOT flip live scoring. Two gates before the switch:**
1. Handle the 35 fully-uncovered players. Options: (a, recommended) whole-player fallback
   to StatsBomb when a player has NO Impect data at all (flagged; NOT the per-metric mixing
   we ruled out); (b) flag-and-exclude from neutral ranking; (c) normalise fit sum by
   present-weight. Awaiting user choice.
2. Validate the Impect pressing definition with Joe (largest single mover, a football call).

**NEXT = resolve gate 1 (uncovered-player policy) + gate 2 (Joe on pressing), then re-run
this comparison; after that Step 4 = the club's real per-position framework.**

### Step 3 CORRECTION + matcher fixes — "uncovered" was a MATCHING failure (2026-07-20, late)

User pushed back: they could see metrics for the "uncovered" players. Investigation
(analysis/step3/, all gitignored — carries licensed Impect names) overturned the earlier
framing. Objective finding: the 35 rankable players with all-NULL Impect columns are NOT
absent from Impect — **all 35 exist in Impect raw data; our matcher failed to link them.**
Root causes + fixes (both implemented, 106 tests green):

1. **`_norm` apostrophe bug** — curly U+2019 was dropped by NFKD+ascii while straight
   U+0027 became a space, so O'Mahony/O'Leary normalised differently and failed to match
   despite identical DOBs. FIX: drop apostrophe glyphs uniformly before normalising.
   Test: `test_norm_apostrophe_glyphs_normalise_identically`.
2. **DOB-exact + surname rescue** (new Stage 4 in `impect_check.match_to_ours`, shared by
   `skillcorner_check`) — recovers nickname/known-as/abbreviation cases (Tanto=Isaac
   Olaofe, Femi=Oluwafemi Ilesanmi) where an exact DOB agrees but the forename sinks the
   fuzzy score. GUARDED on both-side uniqueness of (DOB, surname): SIBLINGS share both
   (verified: Craig/Lisbie/Cadden/Fletcher/Powell/Palmer/Williams twin pairs in the data),
   so a twin pair is refused, never merged. Tests: nickname match; our-side twin refused;
   provider-side duplicate refused; DOB-disagreement not fired.

Deliberately NOT done: a loose surname+fuzzy rule for DOB-disagreement cases — a wrong
merge silently corrupts real data (worse than a visible NULL). Those go to a curated
override list instead.

Rebuilt player_metrics_neutral: **unmatched 35 -> 16**, Impect coverage now 99-100%/league.
Mark O'Mahony flipped from a FALSE -19 fit collapse to a GENUINE +20 rise on real data.
Remaining 16 = override-list candidates (DOB disagreements: Apter, Sidibeh, Neil, Nkeng,
Aderoju, Hmami; different-surname PT/BR names: Castro/Pereira, Gomes/Nunes; transliteration:
Tutierov/Tuterov; nickname: Henrique/Esquerdinha) + ONE spine duplicate (Joe Rye 346685 ==
Joseph Rye 520286, same DOB — a players-table dedup issue, not an Impect miss).

Corrected score movement (covered players dominate): perf corr 0.965, fit corr 0.946;
~32% of rankable players move >=10 rank places. Biggest genuine driver still the Impect
pressing definition (pressures_p90 Spearman 0.73 vs StatsBomb). Report:
analysis/step3/STEP3_REPORT.md.

**NEXT = build the curated override list for the remaining ~15 (plus dedup Joe/Joseph Rye),
re-run the comparison for a fully clean shortlist, THEN the checkpoint decision on flipping
scoring + Joe's read on the pressing definition. Step 4 (club framework) after that.**

### Curated override list — the residual 16 closed to 1 (2026-07-20, later still)

Built the human-verified override list for the 16 players the automatic matcher stages
correctly declined to link. Evidence gathered per player: BOTH birth dates, AND — the
decisive addition — **club affiliation** pulled from Impect's squad_name field, since
several cases have surname mismatches a birth date alone can't resolve (Joel Castro vs
Joel Pereira; João Henrique vs Esquerdinha, which also had a same-DOB decoy "Keenan
Gough" at a DIFFERENT club, ruled out by the club check). Confirmed Impect's internal
playerId is stable across iterations for the same real player, so the override keys
globally (our_player_id <-> impect_player_id), not per league-season.

**11 players confirmed and added** to `data/reference/impect_player_overrides.csv`
(gitignored — licensed player names): Tutierov/Tuterov (transliteration), Sidibeh
(club+surname), Nkeng (club+surname), Castro/Pereira (club+dob+forename, medium
confidence flagged for the surname mismatch), Apter (club matches across 3 separate
season-rows — strongest case), James/Taylor (club+dob only, no name overlap at all —
flagged medium, recommend a human sanity check), Hmami (club+surname), Aderoju
(club+surname), Neil (club matches both rows), Henrique/Esquerdinha (club resolves a
same-DOB ambiguity), Gomes/Nunes (club+dob+forename).

**1 excluded, NOT an override case:** Joseph Rye (player_id 520286, Tamworth 2025/26) is
our OWN players table's DUPLICATE of Joe Rye (player_id 346685, Barnet 2024/25) — same
person, split into two player_ids across a transfer, confirmed because Impect correctly
carries ONE "Joe Rye" spanning both clubs/seasons while our spine has two. This is a
StatsBomb-spine identity issue, not a Impect-matching gap — flagged for future player-
identity dedup work, NOT wired into the override (would violate the one-row-per-
player-season grain).

**Implementation:** new Stage 2 in `impect_check.match_to_ours` (`overrides` param,
`load_overrides()` reads the CSV, empty-safe if missing) — checked early, only applied
where a row is still unmatched; existing stages renumbered 3-6 in the docstring. Wired
into `build_neutral.load_impect`. 5 new tests (override matches; unlisted playerId falls
through; absent-by-default; missing-file returns empty frame). **110 tests green.**

**Result:** rebuilt `player_metrics_neutral` — Impect coverage now **100% in ALL 8
league-seasons** (League One was 99%, now 100%). Unmatched rankable rows: **16 -> 1**
(only the Rye spine-duplicate remains, correctly left NULL rather than force-matched).
Verified all 11 curated players now carry 36/36 Impect columns.

**NEXT = the two checkpoint decisions (uncovered-player policy is now moot — coverage is
100% modulo the 1 known duplicate; Joe's read on the Impect pressing definition remains),
then flip live scoring to the neutral table. Step 4 (club framework) after that.**

### PROPOSED PLAN — Impect as the primary IDENTITY spine (2026-07-20, awaiting go-ahead)

User asked to refactor the spine around Impect being primary, and flagged that the 6
non-EFL Impect leagues (Scottish Prem/Champ, PL2 — sb_competition_id=None) are currently
SKIPPED. Confirmed true: `data/raw/` holds StatsBomb data for comp_ids {2,3,4,5,11,12,65}
only; `player_season_metrics` has ZERO rows outside {3,4,5,65}; `build_neutral` loops
`settings.competitions` (the 4 EFL leagues), so the 6 Impect-only targets can never be
reached. They exist today ONLY for impect_check coverage QA.

**KEY DISTINCTION (source of the confusion):** two different "spines" —
  - METRIC spine = which numbers describe a player = `player_metrics_neutral`. Multi-source
    now, 100% Impect coverage. DONE (Steps 1-3 + overrides).
  - IDENTITY spine = who exists / minutes / position / which leagues = `players` +
    `player_season_metrics`. STILL 100% StatsBomb, EFL-only. UNCHANGED. This is the actual
    "refactor the spine" work and what unlocks the 6 leagues + StatsBomb retirement.

**Dependency facts (verified 2026-07-20):**
  - `player_id` == StatsBomb's id; Impect-only players have none -> must MINT ids.
  - Impect carries playerId, playerName, birthdate, squadName, position (10 codes),
    matchShare, playDuration -> enough to build identity + minutes/rankable natively.
  - CORRECTION to an earlier claim: Impect's `transfermarktId` is **0% filled across ALL
    14 iterations** — so valuation for new leagues still needs a Transfermarkt scrape
    matched by DOB+name, NOT a TM-id join. (Also means impect_check stage-1 TM match never
    fires from the Impect side today; matches come from DOB+name + the rescues + overrides.)
  - For an Impect-spined league the 27 StatsBomb-sourced metrics (15 event-computed + 12
    advanced-endpoint) are NULL — there is no StatsBomb data there at all.

**DECISION LOGGED (Phase B3, user chose): EXPAND THE IMPECT MAPPING** — re-derive the 15
event-computed + relevant advanced metrics (tackles, interceptions, progressive passes,
packing, etc.) FROM Impect, so StatsBomb becomes redundant and every league is scored on
the same instrument. This is the only path that enables Phase C (retire StatsBomb). NOT
chosen: an Impect-only smaller scoring profile (rejected — weakens cross-league comparison,
dead-ends the endgame).

**Phased plan:**
  - **Phase A — flip EFL scoring onto the neutral table.** Point score/valuation/filters at
    `player_metrics_neutral`. Small; gated on (a) Joe's read on the Impect pressing
    definition, (b) the flip decision. Identity spine stays StatsBomb here.
  - **Phase B — source-neutral identity spine (the refactor):**
    B1 per-league `spine_source` + a source-agnostic spine builder (same identity schema
       from StatsBomb OR Impect).
    B2 Impect-native identity: deterministic id-minting (reserved offset, no collision with
       StatsBomb ids), `players`-row creation, Impect-position -> position_group map,
       minutes/rankable from playDuration/matchShare.
    B3 EXPAND Impect metric mapping to cover the 27 currently-StatsBomb metrics (the logged
       decision) — re-resolve the registry so Impect wins where it now supplies them.
    B4 turn on the 6 new leagues (Scottish Prem/Champ, PL2) as Impect-spined.
    B5 Transfermarkt scrape + valuation for the new leagues; wire into scoring/dashboard.
  - **Phase C — retire StatsBomb for the EFL too (endgame):** switch EFL identity to Impect,
    validate Impect-spine-EFL vs StatsBomb-spine-EFL player-by-player, then StatsBomb is
    droppable when the licence lapses.

**NEXT = confirm sequencing/entry point with user (recommendation: finish Phase A flip since
it's nearly done + demoable, and in parallel start the Phase B3 Impect mapping expansion,
which is the long pole and is NOT blocked on Joe). No building until explicit go-ahead.**

### Phase D — Impect's EXACT definitions, pulled + displayed (2026-07-20, late)

Joe said proceed with the Impect migration and set a hard requirement: every metric must
carry Impect's own exact definition, surfaced in the system. Built end-to-end:

- **D1 ingest (`ingest/impect_definitions.py`):** pulls the full KPI glossary from Impect's
  authoritative endpoint (`/v5/customerapi/kpis`, ~1,458 KPIs, each with label / definition /
  meaning / inverted). Lands raw JSON under the gitignored data/raw/impect/, rebuilds
  `data/reference/impect_definitions.csv`. Pitch-position/phase VARIANTS carry no definition
  of their own — they inherit the base KPI via the nested `parentKpi` record; `_flatten`
  resolves that and records `parent_kpi` so the display can say "Successful Passes, scoped to
  the opponent box". Licensing: the full glossary is Impect IP — CSV + raw are GITIGNORED
  (displayable in our licensed tool, not republishable). Wired into the pipeline after the
  Impect pull.
- **D2 resolver (`model/metric_definitions.py`):** `describe(metric)` joins registry (metric
  -> source) + impect_map (metric -> underlying KPI columns via numer/denom) + the glossary,
  returning Impect's exact wording per underlying column for Impect metrics (numerator AND
  denominator for ratios), or the LOFC derivation for non-Impect metrics. Coverage: **36/36
  Impect metrics resolve to full glossary definitions** (was 32/36 before the parent-KPI
  inheritance fix).
- **D3 display (`dashboard/app.py`):** the player-profile "Full stats" table gained a
  **Source** column (Impect / StatsBomb / SkillCorner), and a **"Metric definitions"** block
  renders each shown metric's exact Impect wording (StatsBomb/SkillCorner show our documented
  derivation, clearly labelled). `metric_glossary()` cached.
- **Tests:** `tests/test_metric_definitions.py` (own-vs-parent definition, ratio numerator+
  denominator, non-Impect fallback, scoped_from). **116 tests green.** Dashboard verified
  serving HTTP 200 with no render errors (fixed a mid-edit function-split bug).

**NEXT = Phase A (flip EFL scoring onto the neutral table) + Phase B (source-neutral Impect
identity spine incl. re-deriving the AMBER/RED metrics from Impect per B3 findings).**

### Phase A DONE — EFL scoring flipped onto the neutral table (2026-07-20, late)

Joe approved proceeding; flipped scoring from the StatsBomb-only spine to the
provider-neutral 87-metric table. Made REVERSIBLE via a config toggle rather than a
one-way rewrite:

- **config:** `SCORING_SOURCE` (default "neutral") + `settings.scoring_metrics_table`
  -> "player_metrics_neutral" | "player_season_metrics". Validated; rejects unknown values.
- **model/run.py:** reads `settings.scoring_metrics_table`. `competition_name` (absent from
  the neutral table) is joined from the spine only for the cosmetic spot-check, never scoring.
- **Ran the flip:** re-scored 4,568 rankable players + 118,805 percentiles from the neutral
  table; rebuilt shortlists. Dashboard reads player_scores live -> now Impect-informed.
- **Before/after verified** (League One CF fit): Ryan One 1st(86.7) -> 7th(74.6); Justin
  Obikwu, Aribim Pepple enter — the exact genuine re-rating validated in Step 3, now live.
- 3 config tests added. **119 tests green.** Dashboard HTTP 200, clean.

**Scope note — valuation NOT yet flipped.** `model/valuation.py` still reads
`player_season_metrics` for its performance FEATURES (valuation.py:419-420, 494-495). So
today scores/percentiles/shortlist-fit are Impect-based, but fair-value / undervaluation
still train on StatsBomb features. That is the next sub-step (Phase A2) and is bigger
(Ridge retrain, era models, fair-value + undervaluation shift) so it gets its own
before/after validation checkpoint.

**NEXT = Phase A2 (flip valuation onto the neutral table, validate fair-value shift), then
Phase B (source-neutral Impect identity spine + re-derive AMBER/RED metrics from Impect).**

### Phase A2 DONE — valuation flipped onto the neutral table + pipeline reordered (2026-07-20)

- **valuation.py:** feature source now follows `settings.scoring_metrics_table` (same toggle
  as scoring), so fair value is built from the SAME metrics the scores use. `competition_name`
  (absent from the neutral table) joined from the spine for the unmatched-report display only.
- **Validated — model quality preserved:** StatsBomb-feature vs Impect-feature valuation,
  apples-to-apples via the toggle: cross-validated R2 (log) **0.742 -> 0.744**, MAE within
  0.5% (EUR 862k vs 866k), match rate **identical (1,644)** — matching keys on identity, not
  metrics. Per-player fair values shift as expected (Impect features), but the model is equally
  trustworthy. Re-ran valuation + shortlists on neutral (final DB state).
- **Pipeline REORDERED (bug fix):** scoring + valuation now READ the neutral table, so
  build_neutral had to move BEFORE them. New order: spine(1-5) -> club SkillCorner(6) ->
  provider pulls(7-10) -> build_neutral(11) -> Transfermarkt(12) -> score/archetypes/
  valuation/shortlists(13-16). Previously build_neutral ran last, which would have fed an
  EMPTY neutral table to scoring on a fresh run.
- **Known remaining inconsistency:** `model/archetypes.py` (playing-style clustering, step 14)
  still reads `player_season_metrics`, so style groups are StatsBomb-based while scores are
  Impect-based. Low priority (grouping, not ranking) but flagged for full consistency.

**Live EFL system is now Impect-based for: metric definitions, scoring/percentiles/fit,
valuation/undervaluation, shortlists. StatsBomb still supplies: the identity spine, 17/27
scored metrics, and archetype clustering. 119 tests green; dashboard HTTP 200.**

**NEXT = Phase B (source-neutral Impect identity spine + re-derive the AMBER/RED metrics from
Impect), which is what actually lets StatsBomb be switched off and unlocks the 6 new leagues.**

### Phase B1 DONE — 5 metrics migrated StatsBomb -> Impect, each empirically validated (2026-07-20)

Method: for every candidate mapping, computed the Impect per-90 from raw columns for League
One 25/26, matched to our players, and CORRELATED against the StatsBomb value on the same
players (472 with >=900 Impect minutes). Adopt only on strong correlation or an identical
concept; a wrong mapping silently corrupts scores.

**MIGRATED (registry: IMPECT wins over SB_COMPUTED; counts now 41/12/10/24, total 87):**
- passes_p90 = SUCC+UNSUCC+NEUTRAL_PASSES (corr 0.984, same scale)
- np_goals_p90 = GOALS - GOALS_BY_ACTION_PENALTY_KICK (corr 0.999)
- xg_p90 = SHOT_XG incl. penalties (corr 0.984)
- blocks_p90 = DEFENSIVE_TOUCHES_BY_ACTION_BLOCK (corr 0.885; reads ~30% lower, percentiles absorb)
- clearances_p90 = the three BY_ACTION_CLEARANCE pass outcomes summed (corr 0.74, identical
  scale -- Impect's own clearance coding, same concept)
**FIXED:** np_xg_p90 -> SHOT_XG - SHOT_XG_BY_ACTION_PENALTY_KICK (corr 0.981): removes the
documented penalties-included flaw. Verified live: David Kamara (all goals penalties) now
np_goals 0.000 / np_xg 0.296 vs xg 0.544.

**REFUSED after validation (the honest half of the result):**
- ball_recoveries: BALL_WIN_NUMBER corr 0.12, LOOSE_BALL_REGAIN corr 0.24 -> Impect does not
  measure the concept; successor = ball_wins_p90 (already in registry).
- gk_saves/save_pct: BALL_WIN_BY_SAVE keeper-only corr 0.62/0.58 (a save is only a ball WIN
  if the keeper keeps it -- parried saves missed); successors = gk_gsaa_p90 /
  gk_shot_stopping_pct (already in registry).
- tackles/interceptions: corr 0.72 / 0.68 at 2x / 5x scale = different instruments; the map
  already carries honestly-named successors (ground_duels_won_p90, ball_wins_p90) --
  deliberately NOT masquerading duels as "Tackles".
- progressive_passes/carries: BYPASSED_OPPONENTS already mapped as packing_bypassed_opponents
  _p90 (corr 0.856) -- remapping would duplicate one column under two names; packing/deep_
  progressions are the successors.
- The earlier overall gk_saves corr of 0.986 was an outfielder-zeros illusion; keeper-only
  told the truth. (Same class of trap as the original SHOT_AT_GOAL_NUMBER_SAVED GK bug.)

No schema migration needed (column names unchanged; sources move inside the registry).
Rebuilt neutral table (100% coverage held), re-scored, re-valued (R2 0.745, steady),
shortlists rebuilt. impect_map "none" notes now carry the validation evidence per refusal.
**119 tests green** (registry count assertions updated 36->41, 15->10).

**Scored-metric sources now: 15 Impect / 12 SB (10 computed + 2 advanced) of the 27.**
**NEXT = Phase B2: the source-neutral identity spine (Impect-native player identity, minutes,
position mapping, id-minting) -> unlock the 6 non-EFL leagues; then Phase C validation.**

### Phase B2 DONE — source-neutral identity spine + 6 new leagues switched on (2026-07-20)

The structural piece: the player universe (who exists, minutes, position, rankable) can
now be built from Impect ALONE, so (a) leagues with no StatsBomb data enter the system and
(b) the EFL identity can later move off StatsBomb (Phase C).

- **`model/impect_spine.py` (new):** builds the identity schema from a translated Impect
  iteration. player_id REUSED via the six-stage matcher when the player is already ours
  (loanees/transfers), else MINTED at IMPECT_ID_OFFSET (2e9) + Impect id — deterministic,
  collision-free with StatsBomb's id space. Impect's 10 position codes -> our 8 groups.
- **VALIDATED vs ground truth (League One 25/26, where StatsBomb IS truth):** minutes corr
  **1.000** (mean abs diff 3 min), rankable agreement **100%**, universe **100%** (0
  rankable players missing), position-group agreement **91.8%** (all disagreements adjacent
  roles, DM<->CM etc). The 3 minted were all sub-450-min fringe players. Green light.
- **config:** ImpectTarget gained competition_id/season_id/spine_source (+ competition_name).
  EFL targets default keys to the StatsBomb ids (spine_source=statsbomb); the 6 added
  leagues get minted ids (Scottish Prem 901, Scottish Champ 902, PL2 903; season 317/318)
  and spine_source=impect.
- **build_neutral is now source-neutral:** `build_for_impect_league` builds the spine from
  Impect, blanks the StatsBomb-sourced columns, joins SkillCorner if mapped, and REGISTERS
  minted players in `players` (ON CONFLICT DO NOTHING) so scoring's FKs resolve. main() runs
  both StatsBomb-spined (EFL) and Impect-spined (new) jobs. Table grew **5,994 -> 9,444 rows
  across 14 league-seasons**; 1,848 new players inserted. New leagues: 100% Impect, 0%
  StatsBomb by design. Reused ids spot-checked ALL genuine (Iheanacho, Nisbet, Dowell... 75
  Scottish players who also appear in our EFL data, exact DOB + name).
- **Fit-score fix (`score.py`):** fit renormalised by PRESENT identity-metric weight, scaled
  to the full profile weight — so a player missing StatsBomb-sourced metrics (every new-
  league player) is not deflated. Proven a NO-OP for fully-covered EFL players (fit scores
  byte-identical before/after: 11.6/41.1/48.7/66.3/39.6). New leagues now scored (avg fit
  ~50, correct for percentile scores); player_scores 4,568 -> 6,565.
- **Valuation/shortlists correctly EXCLUDE the new leagues** (no market values): 0 valuations
  for 901/902/903, EFL 1,644 unchanged, R2 0.747. Dashboard HTTP 200, unaffected (new leagues
  not yet surfaced in its EFL-only filter -- see below).
- **Tests:** test_impect_spine.py (6) + config assertions (3). **128 green.**

**KNOWN / NEXT:** the 6 new leagues are SCORED and in the system but NOT yet surfaced in the
dashboard (league filter reads player_season_metrics = EFL only; no market value so excluded
from shortlists by design). Surfacing them (browse/scout view, cross-league compare, "no
market value" handling) is a dashboard task. Also pending: archetypes still on the StatsBomb
spine; Phase C = move EFL identity onto Impect + validate, then StatsBomb is removable.

### Dashboard — the 6 new leagues made scoutable (2026-07-20)

The B2 leagues were scored but invisible in the UI (the affordability shortlist is EFL-only,
and Impect-only leagues carry no market value). Added a way to browse them:

- **New "Scouting (all leagues)" tab** (`_scouting`): browses EVERY scored player across all
  7 leagues by Quality + Style fit, with its own position / league / min-minutes filters and
  no budget gates. Click-to-profile like the shortlist. 3,338 players, incl. 1,047 from the
  Scottish/PL2 leagues, now scoutable. CSV export included.
- **`load_scouting`**: scores + identity from player_metrics_neutral only (no valuations), so
  it spans leagues with no market data. `_competition_name_by_id` names EFL + Impect leagues.
- **`load_metric_values` now reads the combined table** (was player_season_metrics) so player
  profiles render for ALL leagues and match exactly the values scoring uses.
- **`_render_profile_body` made source-tolerant**: market value / fair value / wage / age /
  raw goal-assist totals are all optional now — an Impect-only player shows a quality-and-
  style profile with an explicit "no market-value data for this league" note instead of
  crashing. EFL profiles unchanged (raw totals still used when present).
- **Verified:** Streamlit AppTest renders the full app incl. the Scouting tab table + filters
  with no exception (exit 0); dashboard HTTP 200; 128 tests green. (A second AppTest rerun
  segfaults in pyarrow — an AppTest infra issue, not app logic; the live app is unaffected.)

The shortlist / valuation / KPI strip stay EFL-only by design (affordability needs market
values). Scouting is the cross-league quality/style browser.

### Phase C validation DONE — checkpoint reached, NOT yet flipped (2026-07-20)

The go/no-go evidence for making the EFL Impect-only (so StatsBomb can be dropped). Read-only
shadow; nothing live changed. Two questions:

**1. Does the Impect IDENTITY spine reproduce StatsBomb across ALL 8 EFL leagues? YES.**
minutes corr 0.997-1.000 (mean abs diff 2-8 min, National League up to 45), rankable agreement
98.8-100%, universe 98-99.6%, position 89-94% (adjacent roles). 0-7 rankable players per league
get a minted id instead of reusing (residual matcher gap, small/fixable). Identity is a faithful
reproduction.

**2. Does scoring on Impect SUCCESSORS (losing the StatsBomb-only metrics) change the ranking?
MODERATELY, and unevenly.** Isolated the metric-set change on the same EFL players (C4 successors:
tackles->ground_duels_won, interceptions/ball_recoveries->ball_wins, progressive_passes->
packing_bypassed_opponents, passes_into_final_third->deep_progressions, progressive_carries->
dribble_carry_value, gk_saves->gk_gsaa, save_pct->gk_shot_stopping). Performance score:
- overall corr **0.886**, mean|Δ| 5.2, median rank move **12 places**, 45% move >=15.
- attacker corr 0.928 (stable — attacking metrics were already Impect), defender 0.871
  (median 20-place move — defenders lean hardest on the swapped metrics), midfielder 0.870, GK 0.829.
- League One CF top-10 by quality: **5/10 overlap** between the two methods.

**INTERPRETATION (honest):** the switch is TECHNICALLY ready — identity faithful, successors ~100%
populated. But it MATERIALLY re-ranks defenders/midfielders, because Impect measures tackling
(duels), ball-winning, and progression (packing) as related-but-different concepts. Not wrong —
arguably richer — but a **football-judgment call for Joe**, not a technical one: does the club
accept Impect's defensive/progression definitions as the scoring basis? Attackers barely move.

**DECISION: did NOT flip (C5) or retire StatsBomb (C6).** Awaiting Joe's sign-off on the defensive
metric swap. C1 (EFL spine toggle), C5, C6 are built-ready but gated on that. Analysis:
scratchpad c3a/c3b scripts.

### Phase C DONE — EFL flipped to Impect-only; StatsBomb retired from scoring (2026-07-20)

The platform now runs its scoring on Impect (+ SkillCorner) with ZERO StatsBomb metrics.
Reversible via one flag.

- **config `IMPECT_ONLY`** (default false, set true in .env): when on, the EFL is built from
  the Impect identity spine (not StatsBomb) and scoring maps StatsBomb-only metrics to Impect
  successors. Restart-to-rollback.
- **C4 successor map (`score.py IMPECT_SUCCESSOR`)** applied to BOTH quality role sets and fit
  identity profiles, once up front, when impect_only: tackles->ground_duels_won,
  interceptions & ball_recoveries->ball_wins (collapse to one, weights summed / strictest floor
  kept), progressive_passes->packing_bypassed_opponents, passes_into_final_third->
  deep_progressions, progressive_carries & dribbles_completed->dribble_carry_value,
  gk_saves->gk_gsaa, save_pct->gk_shot_stopping. `normalise` now ranks these successors too
  (skips any column absent from the StatsBomb-only table).
- **build_neutral:** with impect_only, ALL 14 leagues (incl. EFL) built [impect spine].
  Rebuilt: 9,451 rows, EFL now 100% Impect / 0% StatsBomb, EFL 25/26 gains SkillCorner physical.
- **Rescored + revalued + reshortlisted** in impect_only: 6,573 scores; valuation R2 0.748
  (steady, matched 1,630). Verified: EFL percentiles now carry the successors (ball_wins,
  ground_duels_won, packing, deep_progressions), the StatsBomb-only tackles/interceptions
  percentiles are GONE. **Audit: StatsBomb metrics used in scoring = NONE.**
- **C6 (partial):** the StatsBomb ADVANCED-stats pull is skipped when impect_only (unused).
  Base StatsBomb ingest still runs as the identity SEED (stable player ids, birth dates, league
  names) while the licence is live — deliberately kept so watchlists/TM links don't churn; the
  final identity cutover to Impect happens at licence end.
- **Dashboard** made impect-only aware: charts/profile use successor role metrics
  (`role_metrics_for`). AppTest renders clean (exit 0); HTTP 200.
- **Tests:** +3 (successor map dedup, weight-collapse, impect-only fit); an autouse fixture pins
  the default so the suite is independent of the deployment's IMPECT_ONLY. **131 green.**

**PHASE C VALIDATION (from the checkpoint, now live):** identity faithful (minutes corr
0.997-1.000, rankable 98.8-100%); the metric swap re-ranks defenders/mids most (perf corr
~0.87, attackers ~0.93) — a football consequence Joe accepted. Now shipped.

**REMAINING to fully drop StatsBomb (final step, at licence end):** seed player identity +
league names from Impect (all-minted ids) instead of StatsBomb lineups, so the base StatsBomb
ingest can be removed entirely. Also: move archetypes off the StatsBomb spine (still reads
player_season_metrics). Both mechanical; deferred until the licence actually lapses.

### Dashboard — Scouting folded into Shortlist; one league-complete tab (2026-07-20)

User feedback: the separate "Scouting (all leagues)" tab was confusing, and the Shortlist
sidebar only offered the 4 EFL leagues. Merged into ONE league-complete Shortlist:

- **filters.build_candidates(all_leagues=True)**: LEFT-joins valuations (was INNER), so ALL
  scored players are kept (EFL + Scottish/PL2), not just valued ones. Names then come from
  player_metrics_neutral (all leagues). Default (all_leagues=False) unchanged, so the snapshot
  generator + tests are untouched.
- **dashboard**: load_candidates(all_leagues=True); league_names() now returns all 7 (from the
  combined table); removed the separate Scouting tab + load_scouting/_scouting/scouting_league_
  names. Non-EFL players carry NaN market value/wage -> can't pass affordability gates but are
  browsable/rankable by Quality + Style. "Show only signable" isolates the affordable EFL list.
- **Bug fixed by the merge**: non-EFL players have no playing-style cluster (NaN); the default
  Player-type filter would have silently dropped them -> now NaN-cluster players are always kept.
- Footer caption corrected (Impect + SkillCorner, not StatsBomb). Verified: candidates span all
  7 leagues (6,573; 1,630 with market value, 4,943 scout-only); AppTest renders clean (exit 0),
  HTTP 200, 131 tests green.
