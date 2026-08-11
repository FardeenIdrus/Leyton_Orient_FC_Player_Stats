# BUILD PLAN — master plan & documentation hub

> **Read this first.** This file is the single, always-current map of the platform: what it
> is, where every other document lives, the state today, and what's next. It is kept small
> and up to date. It is the file to read on a fresh session or when onboarding.
>
> - **The current state and roadmap** are in this file (below).
> - **The rationale/history** of every past decision is in `plan/HISTORY.md` (frozen log —
>   read only when you need the *why* behind something).
> - **Technical deep-dives** are in `docs/` (see the Documentation map below).
>
> _Last updated: 2026-08-11._

---

## What this is (one paragraph)

The Leyton Orient FC **Player Recruitment Intelligence Platform** turns event and physical
data into a ranked shortlist of **affordable, undervalued** signings, scored on **the club's
own recruitment framework**. It is a *decision* platform (the IP is the scoring + ranking
model), not a reporting dashboard. It runs end to end via `docker compose up` +
`python -m lofc.pipeline`; the dashboard is at http://localhost:8501.

---

## Documentation map

| Document | What it covers | Read it when… |
|---|---|---|
| **`plan/BUILD_PLAN.md`** (this file) | Current state, doc index, roadmap | Always first — the entry point |
| `plan/HISTORY.md` | Frozen append-only build log: every phase + decision + rationale | You need *why* a past decision was made |
| `plan/LOFC_Recruitment_Platform_Build_Plan.md` | The original client brief (frozen, never edited) | You want the original scope/requirements |
| `README.md` | Human front door: what it is, how to run it, repo layout | You're a new team member getting started |
| `docs/architecture.md` | System map: the pipeline stages, which file does what, data flow, dashboard tabs | You want to understand or change the code |
| `docs/DATA_ARCHITECTURE.md` | The 91-metric layer: the four data sources, per-metric provenance, the club→Impect mapping; §5 the Medical-dimension injury source and availability formula | You're working with metrics / data sources |
| `docs/methodology.md` | The scoring method: percentiles, the club 1–5 composite, the design decisions | You want to understand how players are scored |
| `docs/scaling.md` | Scaling considerations | You're planning growth / more leagues |
| `DEPLOY.md` | Deployment and operations | You're deploying or running in production |
| `data/reference/README.md` | The drop-in reference CSVs (wages, identity) | You're replacing a modelled input with real club data |
| `CLAUDE.md` | AI session pointer + working rules (local-only, not in git) | (Claude reads this automatically) |

`analysis/step*/` holds one-off working notes from the build — **historical, not living docs.**

---

## Current state (2026-08-11)

> **2026-08-03 — audit + fixes.** A full metric audit (club-document fidelity, API pull, computation)
> confirmed the framework is faithful to the club files and the composite maths is correct. It found
> and we **fixed**: (1) `np_xg_xa_p90` was penalty-inclusive though labelled "NP xG + xA" — now strips
> penalty xG to match `np_xg_p90` (neutral table rebuilt from landed data, no re-fetch); (2)
> Financial/Resale percentiles pooled both seasons — now ranked **within season**; (3) `metric_percentiles`
> made season-safe (groups by season) and a stray `id` column excluded from ranking. **UI fixes:** the
> advisory veto/minimum flag is now a styled amber callout; the Transfer-budget & Wage-budget controls
> (and the affordability KPI) are shown **only when "Show affordability" is on** (Option A — they gate
> nothing in the default view, so hiding them removes a misleading control); the **Compare** tab now
> charts the club's Performance metrics (archetype-aware, from the scorecard percentiles) instead of the
> retired Quality/Fit role metrics, and its Market column is money-gated; the cross-league name lookup now
> covers Scottish/PL2 (fixed "league 903" → "Premier League 2"). **Season split verified end-to-end** — every
> scoring path filters/groups by `season_id`, a both-season player holds two independent rows (unique
> `(player, competition, season)` triples), percentile peer groups are same-season only, and selecting a
> season yields scorecards from that season alone. 301 tests pass. *Known, non-scoring:* the playing-style **clusters** pool both seasons
> (and still read the StatsBomb-era table) — a style label only, it does not touch the composite (roadmap).
>
> **2026-08-03 (b) — more fixes.** (1) **Age** is now derived from `players.birth_date` at the season
> midpoint for **all** leagues (was read from `valuations`, EFL-valued only) — coverage jumped from
> ~35% to **~99.9%** (Scottish/PL2 went from 0 to full). (2) **Compare** gained a **raw physical
> comparison table** (SkillCorner per-90 output) — deliberately *raw*, because physical output is
> genuinely comparable across leagues (unlike the within-league percentile radar); mixed units, so a
> table not a radar. (3) The cross-league name lookup covered the last two spots (fixed "league 903").
> **Identity audit:** the 54 names sharing multiple player-ids are **all genuine namesakes** (distinct
> birth dates) — **zero split identities**; one unconfirmable case (a birth-date-less PL2 youth vs a
> senior L2/NL player) is a namesake by age. The Impect↔player-id matcher is sound.


**Scoring is 100% Impect + SkillCorner — zero StatsBomb in scoring.** (StatsBomb still runs
only to seed player identity — stable IDs, birth dates, league names — during the migration.)

- **Data:** **91 metrics** per player, **7 leagues** — the EFL (Championship, League One,
  League Two, National League), the Scottish Premiership & Championship, and Premier League 2
  — across **14 league-seasons** (2024/25 + 2025/26).
- **Physical (SkillCorner):** covers the EFL + Premier League 2 + Scottish Premiership.
  **2025/26 only.** The **Scottish Championship has no physical layer** — SkillCorner lists the
  competition and even a 2025/26 edition (id 1210), but holds **zero** physical/tracking data for
  it (verified against the live API: 0 players vs 358 for the Scottish Premiership). It is a
  SkillCorner data gap, not a config omission — so that league scores on Performance alone.
- **The scoring model is the club's real framework** (`model/club_framework.py` +
  `model/scorecard.py`), encoded from the club files in `docs/`:
  - `Impect Data - Positional Metrics.xlsx` → the per-position metric lists (`PERFORMANCE_METRICS`).
  - `LOFC - Position Archetype.docx` → the seven dimensions, their per-position weights
    (`DIMENSION_WEIGHTS`), the 1–5 scoring, and the median/70th thresholds.
- **Every player gets a 1–5 composite.** Two composites: **objective** (Performance +
  Physical, real data — the default ranking) and **full** (adds the *modelled* Financial +
  Resale). Psychological + Medical are scout inputs (not yet collected).
- **The old invented "Style-fit" is retired** from every live surface. The Shortlist, Player
  profile, Compare, Player-types and Watchlist all rank/show the club composite.
- **Nobody is excluded automatically.** The club's "< 3.0 = do not proceed" / "< 2.0 = veto"
  rules are advisory flags only; affordability gates (fee + wage) are opt-in.
- **Scored WITHIN one season** (a sidebar **Season** selector; latest, 2025/26, is the
  default). Each player appears once, ranked against that season's peers with that season's
  coverage (physical is ~90% within 2025/26; 2024/25 has none). Earlier seasons stay fully
  available and power the profile **trajectory** chart. This fixed the earlier season-mixing
  (duplicate players + last-season-vs-this-season comparisons).
- **Archetype lens (opt-in)** for **Full Back** (Attacking / Progressive) and **Winger**
  (Direct & 1v1 / Crossing & Creative): the sidebar **Archetype** re-scores the Performance
  dimension on that archetype's metric subset and re-ranks, with the **all-round composite kept
  visible** alongside on both the Shortlist and the Club scorecard. Midfield archetypes are
  deferred (workbook doesn't fully specify their lists).
- **One "Players" workspace** (master-detail) — the former Shortlist + Club scorecard + Player
  profile tabs are merged into a single composite-ranked list with, on click or search, a full
  player detail: dimension scores + the club-framework **grand table** (Source · Season total ·
  Per-90 · Percentile · 1–5 Band) + charts on the club per-position (archetype) metrics.
  **Money is an opt-in secondary layer** (off by default — the default ranking is 100% real
  football data; market value/wages/affordability appear only when "Show affordability
  (modelled)" is ticked). Tabs now: Players · Compare · Watchlist · Player types · Physical ·
  Glossary · Methodology.
- **The composite is persisted** to `player_scorecards` (a pipeline stage), so the dashboard, the
  offline `shortlists` table and the BI layer all read the *same* numbers. The `shortlists` table
  now ranks on `objective_composite` — **the retired Style-fit no longer orders anything anywhere.**
- **Contract-expiry filter (the free-transfer market)** — a sidebar **Contract expiry** selector
  (*Any* · *summer 2027* · *summer 2028* · *already expired*) plus **Contract** and **Months left**
  columns in the Players table. A forward horizon means "still under contract today, expiring by
  the cutoff", so lapsed deals never pad the list; players with no known expiry are excluded **and
  counted on screen**. **The filter works again following the B1 recovery** (see below): **702**
  players expiring by summer 2027, **1,110** by summer 2028, **35** already expired. The contract
  snapshot date is now **11 Aug 2026** (it was a 10 Jun 2026 snapshot before the incident). These
  figures reflect **2026/27 squads**, so a player who featured in 2025/26 but has since left the
  four English leagues will have no contract date — that is correct for recruitment (you want live
  contract positions), and it is why the numbers do not match the pre-incident 542 expiring summer
  2027, 822 by 2028, 447 already expired exactly. **There is deliberately no "January" option**: of
  those pre-incident dates, 1,377 of 1,381 were in June and none in January, so the January
  question was answered by *Months left ≤ 6* on a summer horizon — unaffected by the incident.
  **B1 — Transfermarkt contract/market-value refresh: ✅ DONE (11 Aug 2026).** The 11 Aug 2026
  scrape initially destroyed contract/foot/height data via a parsing bug; the bug was fixed and a
  recovery scrape ran successfully the same day. The database now holds **1,363** contract dates,
  **1,606** feet and **1,635** heights, against 5,626 players. Market values were unaffected
  throughout (**2,526** present — that field is located by CSS selector, not by column position).
  Full incident record and recovery outcome in the Pending work register below.
- **301 tests pass.** The dashboard renders clean.

Full detail on the scoring: `docs/methodology.md` §3b. Full metric provenance:
`docs/DATA_ARCHITECTURE.md`.

---

## Pending work register (nothing here is dropped)

**Blocked on an outside party — recheck, do not forget:**

| # | Item | Blocked by | What to do when unblocked |
|---|---|---|---|
| B1 | ✅ **DONE (11 Aug 2026)** — recovery scrape completed; contract/foot/height data restored | — (resolved) | Database now holds 1,363 contract dates, 1,606 feet, 1,635 heights (was 20 / 23 / 24 immediately after the incident). Full incident record and recovery outcome directly below. |
| B2 | **Midfield archetypes** (DM / Box-to-Box / AM) | needs the club's per-archetype metric lists | encode into `ARCHETYPE_DROPS`; deliberately not fabricated |
| B3 | **Real financial models** | needs the club's real wage framework CSV | drop-in replaces the modelled wage grid; makes the money layer decision-grade |

**B1 incident — contract/foot/height data destroyed, 11 Aug 2026 — RESOLVED, recovered the same day:**

- **Cause:** the 11 Aug scrape ran `transfermarkt_efl --force` against a **stale hard-coded
  season** (`TM_SEASON = 2025`). That season had already ended, so Transfermarkt served the squad
  page as *history* — a page layout that replaces the `Contract` column with `Current club` and
  shifts every later column one position right. The parser read fields by **fixed cell position**
  rather than by column header, so it silently produced **blanks** for `contract_until`, `foot`
  and `height_cm` on all 4,014 rows scraped — and still printed a success line, because nothing
  checked fill rate at the time. `identity.py` and `valuation.py` then wrote those blanks straight
  over the database (there was no COALESCE protection on those writers at the time).
- **Effect:** **1,381 contract expiry dates were destroyed**, along with `foot` and `height_cm`,
  dropping the database to **20** contract dates, **23** feet and **24** heights against 5,626
  players. Market values were unaffected (**2,526** present), because that field is located by
  CSS selector rather than by cell position.
- **Backup:** a full database backup was taken before any repair —
  `data/backups/lofc-20260811-103912.sql.gz`.
- **Code status: fixed and reviewed.** The scraped season is now derived from today's date
  instead of hard-coded; the squad-page parser reads columns by header name instead of position;
  a fill-rate/volume guard aborts a degraded pull before it touches the CSV; and every writer to
  `players` (`identity.py`, `valuation.py`, `store/load.py`) now uses COALESCE so a blank incoming
  value can never overwrite a value already on file.
- **Data status: ✅ RESTORED.** The recovery scrape ran successfully on 2026-08-11 using the fixed
  code. It pulled **2,437** players with **1,882** contract dates, **2,187** feet and **2,199**
  heights. `valuation` matched **1,380** players; `identity` linked **1,346**. The database now
  holds **1,363** contract dates, **1,606** feet and **1,635** heights, against 5,626 players — up
  from the incident's 20 / 23 / 24. These figures reflect **2026/27 squads**: a player who featured
  in 2025/26 but has since left the four English leagues will have no contract date, which is why
  the recovered totals do not match the pre-incident 542 / 822 / 447 contract-band figures exactly
  — correct behaviour for recruitment (you want live contract positions), not a shortfall.
- **Recovery procedure, three commands in order (as run):**
  1. `transfermarkt_efl --force --allow-degraded`
  2. `valuation`
  3. `identity`

  `--allow-degraded` was required because the volume guard compared the recovery run's **2,437**
  current-squad rows against the corrupt 4,014-row file, which was still its comparison baseline.
  That corrupt baseline is now replaced by the clean recovery CSV, so the flag should not be needed
  on future runs.

**Injury scrape capability — landed and complete (11 Aug 2026):**

The Transfermarkt injury-history scraper, categoriser, `player_injuries` table, CSV→Postgres
loader (`lofc.store.injuries`) and the Medical-dimension `availability()` calculation are all
built, tested and wired into the pipeline (runs immediately after the Identity step, since the
loader joins on `players.tm_player_id`). **The real scrape has finished and is loaded:**

- **Scrape (final run, against the refreshed player list):** 3,930 injury rows written to
  `data/reference/transfermarkt/injuries.csv`, **0 failed**, 3,507 player pages fetched.
- **Loaded into Postgres:** **3,766 rows for 1,176 players** (the gap to 3,930 is rows whose
  Transfermarkt id matches no player we hold metrics for — dropped, not guessed). All rows
  carry `source = 'transfermarkt'` (the loader always clears existing `source = 'transfermarkt'`
  rows before inserting, so the earlier 5-player smoke-test load has been replaced).
- **Coverage stays EFL only** (Championship, League One, League Two, National League — the four
  leagues with a `SCHEDULED_GAMES` constant), and only players carrying a `tm_player_id`.
- **`tm_player_id` coverage, 2025/26 season** (this is what makes a Medical figure computable):

  | League | Coverage | % |
  |---|---|---|
  | Championship | 730 / 748 | 98% |
  | League Two | 714 / 745 | 96% |
  | League One | 715 / 749 | 95% |
  | National League | 711 / 769 | 92% |
  | Premier League 2 | 182 / 1,141 | 16% |
  | Scottish Premiership | 28 / 385 | 7% |
  | Scottish Championship | 8 / 284 | 3% |

  The last three rows are not usable for injuries today (no `SCHEDULED_GAMES` constant either —
  see R6); they are recorded here because the same `tm_player_id` link also feeds B1's contract
  data.
- **Completeness check:** of 2,701 linked EFL players in 2025/26, **2,701 had their injury page
  fetched — zero were never fetched.** An unfetched player would otherwise silently read as 100%
  available; there is now no such ambiguity for the EFL.
- **Injury category distribution** (3,766 rows), with average matches missed / average days out:

  | Category | Rows | Avg matches missed | Avg days out |
  |---|---|---|---|
  | other | 1,534 | 7.0 | 53 |
  | knee_ligament | 634 | 17.4 | 135 |
  | hamstring | 494 | 10.2 | 69 |
  | ankle | 371 | 9.6 | 70 |
  | muscular | 303 | 6.8 | 45 |
  | groin | 195 | 7.0 | 52 |
  | calf | 162 | 7.6 | 51 |
  | hip | 73 | 9.3 | 64 |

  The clinical ordering is a sanity signal — knee-ligament injuries cost by far the most time,
  as expected if parsing is correct. The `other` bucket is dominated by phrasings genuinely
  outside the club's named categories ("unknown injury" 301, "Knock" 153, "Ill" 85, "Corona
  virus" 68, "Foot injury" 66, "Shoulder injury" 61) — honestly uncategorised, not mis-parsed;
  category does **not** affect availability, which counts matches missed regardless of category.
- **Availability, validated end to end on real data:** computed for **2,870** player-season rows
  across the four EFL leagues; **77 fall below the club's stated 60% bar**; the most affected are
  recognisable long-term-injured players (e.g. Charlie Wyke, 128 matches missed, availability
  0.0).
- **Open design question, not yet answered:** under the design spec's band formula
  `band = 3 + 5 × (availability − 0.60)`, **2,201 of 2,870 (77%)** would score the maximum
  Medical band of 5.0, because they had no injuries in the two-season window. Medical carries
  13.6% of the outfield composite weight. Whether a *risk* dimension that awards three-quarters
  of players an identical maximum is the intended behaviour is an open question for the
  scout-assessment plan (R3) — recorded here, not decided. **Medical is not wired into scoring
  yet**; this branch delivers the injury data and the availability calculation only.

Full detail: `docs/DATA_ARCHITECTURE.md` §5.

**Task 0 identity fix (landed 2026-08-10):** `load_efl_values()` was discarding a player's
Transfermarkt id, birth date, foot and contract date whenever he had no market value on file.
A separate identity matcher (`model/identity.py`) now runs over the full scrape instead,
matching on birth date + name, league-scoped. **National League `tm_player_id` coverage rose
from 60 of 769 players to 567 of 769** (8% → ~74%) on that fix alone; combined with the
refreshed scrape above, National League now stands at **711 / 769 (92%)**. The three EFL
divisions above it improved too, not fallen (they were already matched via market value, and now
also pick up players the value-filtered path missed). This is what made the injury scrape usable for the National League —
previously only 8% of that league could be joined at all. (The same `tm_player_id` link also
carries B1's contract/foot/height data — see the B1 incident above, now recovered.)

**In-season operating model (2026/27 — LIVE from August 2026):**

The 2026/27 iterations for all seven leagues are configured (`DEFAULT_IMPECT_TARGETS`,
season_id **319**), and `config.LIVE_SEASON_ID = 319` makes the ingest **always re-pull** that
season — Impect returns season-to-date aggregates, so skip-if-exists (correct for a finished
season) would have frozen the data after the first in-season pull. A season with no matches yet
is skipped cleanly, not treated as an error. **Update `LIVE_SEASON_ID` each August.**

- **Refresh cadence: weekly** (both endpoints are cumulative, so per-match polling buys nothing):
  `python -m lofc.ingest.impect` → `python -m lofc.ingest.skillcorner_api` →
  `python -m lofc.model.build_neutral --write` → `python -m lofc.pipeline`.
- **The live-season rule covers both providers** (Impect events + SkillCorner physical) from the
  single `LIVE_SEASON_ID`, so they can never disagree about which season is still accumulating.
- **Verified live on 2026-08-04:** the Scottish Premiership + Championship 2026/27 are already
  underway (184 / 151 players, **1 matchweek**, **0 rankable**); the English leagues and PL2
  correctly reported "no data yet" and skipped.
- **Expect an empty-looking 2026/27 until ~October.** `rankable` needs 450 minutes (5 full
  matches), so early-season players are stored and visible but not ranked. **Keep 2025/26 as the
  default scouting season** (complete, 46 games) and switch when 2026/27 matures.

| # | Pending in-season item | Note |
|---|---|---|
| S1 | **Weekly refresh** — manual for now | a cron container in `docker-compose` is the unattended option |
| S2 | **Build season 319 into the DB** | deliberately NOT done yet: only the two Scottish leagues have data, so a 2026/27 view would be Scotland-only. Run `build_neutral --write` once the English leagues kick off |
| S3 | ✅ **SkillCorner 2026/27 editions (DONE 2026-08-10)** | six editions added (Championship 1569, League One 1574, League Two 1575, National League 1576, PL2 1578, Scottish Premiership **1683** — SkillCorner labels it just "Premiership"). The **Scottish Championship is deliberately excluded**: the competition exists but holds **zero** physical data (0 rows for 24/25 and 25/26 vs 358 for the Scottish Prem), so configuring it would emit a false "no data" warning every week. The live-season rule now covers **both** providers off one `LIVE_SEASON_ID`. Verified live: Scottish Prem 26/27 already returning **146 players**; the English leagues skipped cleanly (they would have **crashed** the run before this fix) |
| S4 | **Show "current club"** | the Players list shows the club a player played for *in that season* (by design). A transferred player therefore shows his old club until he plays for the new one. The Transfermarkt scrape carries current club (`club_name`) and is not used — adding it would resolve the confusion |

**Ready to do (not blocked):**

| # | Item | Why |
|---|---|---|
| R1 | **Full pipeline re-run** (`python -m lofc.pipeline`) | a clean end-to-end recompute; now covers the new scorecard stage. NB it *fetches nothing* — every ingest step skips existing files, so it is a recompute, not a refresh |
| R2 | ✅ **Refactor `dashboard/app.py` (DONE 2026-08-10)** | 2,560 lines → **191**, split into 15 focused modules (`theme` · `labels` · `charts` · `seasons` · `loaders` · `controls` + `tabs/` one per tab), dependencies strictly one-way so there are no import cycles. **337 lines of dead code deleted** (`_club_scorecard`, `_scorecard_player_detail`, `_profile`, `_render_score_composition`, `percentile_vector`, `_dimension_metric_labels`) plus the retired Style-fit helpers `score_composition`/`load_fit_profiles` and their 3 tests. Done in verified phases against a captured behaviour snapshot: **the final output is byte-for-byte identical to before the refactor**; 191 tests passed at the time (301 now, after later branches added tests) |
| R3 | **Scout-entry fields** for Psychological + Medical (roadmap #4) | completes the club's 7-dimension framework — the biggest remaining gap vs the club document |
| R4 | **Full StatsBomb retirement** (roadmap #6) | seed identity from Impect, delete the ingest + ~21 GB raw events + 22 dead all-NULL columns |
| R5 | **Playing-style clusters: season split + move onto Impect** (roadmap #8) | the last season-mixing and last StatsBomb read; style label only, never touches the composite |
| R6 | **Extend the Transfermarkt squad scrape to Scottish Premiership, Scottish Championship and Premier League 2** | those three leagues carry **low Transfermarkt coverage today** — 2025/26 `tm_player_id` coverage is **Premier League 2 182/1,141 (16%), Scottish Premiership 28/385 (7%), Scottish Championship 8/284 (3%)** — so almost no market value, contract-expiry data, or injury history (the injury loader only ever sees players with a `tm_player_id`, and none of the three has a `SCHEDULED_GAMES` constant for availability either way). Needs a squad-page scrape built for those competitions (`transfermarkt_efl`-equivalent); not started |
| R7 | **Four duplicate Transfermarkt ids stored in `players` need a manual decision** | ids `118779`, `390687`, `948958`, `967296` are each claimed by two different players. They are **neutralised** (the identity linker now drops ambiguous matches and the injury loader filters them out), but **not repaired** — and because the bio columns are COALESCE-protected, no future re-run will ever clear them on its own. A manual `UPDATE` is required. At least three of the four pairs look plainly wrong rather than genuinely ambiguous. Repairing these also resolves R8 |
| R8 | **Gate on the scout-assessment plan (R3): the eight players behind R7's duplicate ids compute to 100% availability rather than "unscored"** | a player with no injury rows is indistinguishable from a player who was never fetched. `model/medical.py` has no consumer yet, so nothing is scored wrongly today — but this must be resolved before the Medical dimension is wired into the scorecard, or the platform will reward the players it knows least about. Repairing R7's four duplicates addresses both items at once |

**Small leftovers (cheap, opportunistic):**

- **SkillCorner per-90 labelling** — physical metrics are per-full-match (~95 min) but suffixed
  `_p90`. Rankings unaffected (percentile-based); displayed absolute numbers overstate ~5–11%.
  Either rescale or relabel "per match".
- **Adopt Impect's `leg` for preferred foot** — Impect has it at ~97% across all seven leagues;
  we currently take foot from the EFL-only Transfermarkt scrape. (Impect has birth date and
  birthplace too, but **no contract date and no height** — verified against the API.)
- **Stale reference files** — `data/reference/impect_metric_map.csv` and some
  `metric_registry.py` comments still say 41 Impect metrics; the live count is 45.
- **Persist per-metric percentiles** — `load_scorecard_percentiles` is still computed live (player
  detail + Compare only). Only worth doing if opening player cards feels slow.
- **Optional polish** — fold the Player-types and Physical tabs into the Players workspace.

---

## Roadmap

**Done** (Phases 0–11 core):
- ✅ Phases 0–9 (demo build) · Phase 10 (real EFL data + SkillCorner) · panel demo
- ✅ Phase 11 (Impect migration): provider-neutral metric layer, EFL flipped to Impect-only,
  6 new leagues added, Impect's exact definitions displayed
- ✅ Club recruitment scorecard (1–5 composite) built and made the primary ranking; Style-fit
  retired; 4 club-framework metrics added (91 total); physical extended to PL2 + Scottish Prem
- ✅ Within-season scoring (Season selector); archetype lens for Full Back + Winger;
  UX fixes (season-specific "Players analysed", all-round shown alongside archetype composite,
  excluded archetype metrics struck through, clickable scorecard rows, clear-selection buttons)
- ✅ Documentation reorganised (this hub + frozen history + deep-dive spokes)

**Next** (in rough priority order):

1. ✅ **Unified "Players" workspace (DONE)** — merged the three overlapping tabs (Shortlist +
   Club scorecard + Player profile) into ONE master-detail workspace: a composite-ranked list
   (objective composite default, within-season) with Minutes + dimension bands + Measured %, and
   on click/search a full player detail (bio + score tiles + trajectory + the club-framework
   **grand table**: Source · Season total · Per-90 · Percentile · 1–5 Band, archetype-aware +
   charts re-pointed to the club per-position/archetype metrics + an "all tracked metrics"
   expander). **Money is an opt-in secondary layer** ("Show affordability (modelled)", off by
   default) — never affects the default ranking. Dead code left for the app.py refactor (#7):
   the old `_shortlist`/`_club_scorecard`/`_profile`/`_scorecard_player_detail` functions.
   *Follow-up polish:* fold Player-types/Physical into the workspace if wanted (deferred).

2. ✅ **Persist scorecards to the database (DONE)** — a `player_scorecards` table written by a new
   pipeline stage (`model/scorecard_run.py`, runs after Valuation, before the shortlist).
   One row per player-season **per archetype** ('All Metrics' for everyone + the Full Back /
   Winger lenses), storing both composites in separate columns. **This retired Style-fit from the
   offline path:** `constrain/filters.py` now ranks the `shortlists` table on
   `objective_composite` (was `fit_score`), and the old identity-profile "on-profile" gate no
   longer excludes anyone — matching the dashboard. The dashboard now **reads** the stored table
   (with a live-compute fallback if it is empty), so every consumer sees identical numbers.
   Verified: stored == live to 0.0, writer idempotent, 160 tests pass.
3. **Midfield archetypes** (DM / Box-to-Box / AM) — await the club's per-archetype metric lists
   (the workbook doesn't fully specify them; not fabricated).
4. **Scout-entry fields** for the two human dimensions (Psychological, Medical), completing the
   *full* composite per player.
5. **Real financial models (deferred, a separate workstream):** the club's real **wage framework**
   (CSV drop-in) + a better **valuation model**. The current wage grid (±10% vs payrolls) and
   valuation regression (CV R² ~0.75, but ±40% median error within league) are honest *screening*
   placeholders, not decision-grade — fine to defer; they firm up the money layer when ready.
6. **Full StatsBomb retirement** — seed player identity from Impect, then delete the StatsBomb
   ingest and its ~21 GB of raw events.
7. ✅ **Refactor `dashboard/app.py` (DONE 2026-08-10)** — 2,560 lines → 191, split into 15
   focused modules with one-way dependencies; 337 lines of dead code removed. See register R2.
8. **Playing-style clusters: split by season + move off StatsBomb** — the k-means (`model/archetypes.py`)
   currently pools 2024/25 + 2025/26 and reads the StatsBomb-era `player_season_metrics` with `ROLE_METRICS`.
   It should cluster within season on the Impect neutral layer. Style label only (never touches the
   composite), so low priority — but it is the last season-mixing and StatsBomb-read in the app.

**Data re-runs:** a full data *fetch* is only needed for a new season or a new league — EXCEPT the
season currently being played, which is always re-pulled (`config.LIVE_SEASON_ID`, see the in-season
model above). Everything else (metric or formula changes) is a fast local rebuild from data already
on disk — no fetch.

---

## Working principles

- **Objective and honest:** verify facts against primary sources; label every modelled input;
  never present a stand-in as real. Where a metric substitutes another, name it for what it
  truly is (see the Glossary).
- **Reproducible:** everything runs in Docker (Python 3.11) against Postgres 16; config via
  `lofc.config.settings`; schema changes via Alembic migrations; `pytest` green before done.
- **Confidential data stays local:** the club documents (`docs/*.xlsx`, `*.docx`) and licensed
  feeds (Impect, SkillCorner, Transfermarkt pulls) are gitignored and never published.

(Claude-specific session rules — including the git-commit policy — live in `CLAUDE.md`, which
is local-only and not part of the repository.)
