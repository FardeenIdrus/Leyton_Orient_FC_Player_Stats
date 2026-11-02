# TASKS — the single list of what is open, in order

> **The one place to look for "what's next".** Updated after every task.
> Detail lives elsewhere (linked); this file only says WHAT, IN WHAT ORDER, and WHAT IT WAITS ON.
> Last updated: **2026-10-22**.

**How to read it.** Section 1 is built and waiting to ship. Section 2 is the work queue, in
priority order (value to the platform first). Section 3 is blocked on someone else. Section 4
is recurring. Section 5 is the backlog. Section 6 is recently done.

---

## 1. Built locally — waiting to deploy

| # | What | Verified | To ship |
|---|---|---|---|
| 1.1 | **Scout reports: names on line 2–3.** A report whose first line is a header ("CF (Right Foot) in a 4-4-2 (Live…)") now shows the player's name instead of "A New Player" | 2 of 4 unnamed reports recovered (Bim Pebble, Archie Jolland); the other 22 unchanged; the 2 with no name in them still return nothing | Deploy, then ONE forced sync on the server (below) |
| 1.2 | **Squads & loans: position for players who have not played (P18).** Blank → Transfermarkt's position, marked "(registered)". Owner's rules: Impect wins; Left/Right Midfield → Winger; Second Striker → Centre Forward; "Midfielder"/"Defender" stay blank | 424 blanks → 405 filled, 19 stay blank (vague); 0 existing positions changed; page renders; Centre Back filter includes the 74 registered | Deploy only |

| 1.4 | **Scout reports: explicit "Data vs scout" column + filter.** Replaces "Model view" ("Model agrees", "Model is lukewarm"). Labels: Data agrees / Data disagrees — rated 3.5+ or under 3.0; Average rating — 3.0 to 3.5; each with its season. New filter; tab "Data disagrees (N)" | 103 rated reports: 0 label mismatches against verdict, rating and season; each filter returns only its group; groups sum to all 681; tab = filter (31); 1,584 tests | **Owner reviewing locally**, then deploy |
| 1.5 | **Ireland physical data + card "no physical" line** (2026-10-26). SkillCorner editions 1081 (2025 → 318) and 1416 (2026 → 319) mapped to Irish Premier Division (10189). Card: blank physical section → "Physical — *no physical data for this league*" or "*… for this player*" (none for goalkeepers) | 1,788 tests; Irish ratings will move: physical now counts 43% | Deploy, then a full pipeline run (data must be rebuilt) |
| 1.3 | **Documentation consolidated** — one file per purpose (see BUILD_PLAN "Documentation map") | 0 dangling references; rewritten docs checked against code + live data; 1,565 tests pass | Commit only (docs) |

**Mac** (owner runs, after reviewing 1.4 locally):
```bash
git add -A src tests plan docs DEPLOY.md README.md .gitignore
git commit -m "scout reports: Data vs scout labels + filter, names from lines 2-3; squads registered positions (P18); docs consolidated"
git push
```
**Server:**
```bash
/opt/lofc/scripts/deploy.sh
docker compose -f /opt/lofc/docker-compose.prod.yml exec -T app python -m lofc.store.scout_reports --force
```
(The forced sync is needed once: stored reports only re-read their names when the sheet changes.)

---

## 2. Work queue — in order

| # | Task | Why it matters | Waits on | Detail |
|---|---|---|---|---|
| 2.1 | **Player profiles** — 24 playing styles as labels + filter. **STYLE, NOT QUALITY** (owner 2026-10-23): attempts, shares and locations, not success; quality metrics only where no alternative (flagged). Wingers + full backs get two layers (where · what). Impect's own 32 profiles rejected as-is: several track quality (Deep-Lying Playmaker r 0.69 with Performance) | Discovery, not just checking (P13) | **Step 1 draft DONE 2026-10-23:** all 24 styles pass the 3 tests on 2025/26 (quality r < 0.3 except flagged aerial-won / dribbles; overlap < 0.7; 7/7 leagues); built from attempts, shares and zones in Impect data we already hold. Rule decided: best-fit style for everyone, Strong (avg ≥ 70, none < 50) / Leans (≥ 50) / No standout style. **Steps 1–2 BUILT locally 2026-10-23:** `model/styles.py` (rules, one file), `model/style_run.py` + table `player_style_signals` (migration d8f3b2c5e104) + pipeline step; stored values = analysis to 1e-14; 2025/26 no-style 1–16%. DM + CM are ONE style group "Central midfield" (owner 2026-10-23; style only, ratings unchanged): 26/27 CM "not enough minutes" 100% → 3%; AM kept separate (an all-midfield pool would restate position: DMs = 97% of top defensive touches). **Step 3 Style lab BUILT 2026-10-23** (`dashboard/style_lab.py`, page "Lab → Style lab", only when `SHOW_STYLE_LAB=true` — set in the Mac's .env, never on the server): sliders for Strong/Leans thresholds, label counts, per-style fit bars, live quality checks. **Step 4 BUILT locally 2026-10-23** to the approved mockup: sidebar Style box (dropdown + Strong only) under Position; "Archetype" renamed "Rank as"; Style column (pills, Leans in words); card Style pills + Style fit bars; methodology §6b. Verified headless as admin: Winger/League One 66 rows, Style=Wide 26, +Strong only 18, Thierry Gale card 52/10/92/90/55. Reference page **"How playing styles work"** built 2026-10-23 to the approved design (`dashboard/style_reference.py`, from the rules file; live worked example; "No standout style" explained in the Style column hover). "In plain words" wording to be confirmed with the Head of Recruitment. **ALL DEPLOYED 2026-10-23** (`4e52795`; style table filled: 4,194 / 4,383 / 3,419 players for 24/25 / 25/26 / 26/27; Style lab off on the server). **Open:** Head of Recruitment to review the styles and the "In plain words" wording | Owner decisions 2026-10-23 |
| 2.1b | **Impect expansion: 18 new competitions — LIVE 2026-10-26** (run-20261026T141902Z: 17/17 steps, 74/74 league-seasons, 0 failures, 57 min; 25 leagues, 18,444 players, 22,903 ratings; staging run matched). Was blocked by the login: the platform used the owner's own Impect login (13 competitions); the Head of Recruitment's login sees 26 (132 league-seasons). Mac .env switched 2026-10-26; SERVER .env still on the old login. Registry now 25 competitions → 74 league-seasons (original 21 identical + 53 new); calendar-year seasons file under the season starting that year (owner); EFL Cup excluded; 1,770 tests. New leagues: Impect only (no SkillCorner/Transfermarkt → Performance-only ratings, no contracts/values). **Built locally 2026-10-26 (1,735 tests):** league registry `lofc/leagues.py` (one line per competition; seasons from Impect's catalogue; id rules; reproduces the old 21 targets exactly; catalogue now fetched BEFORE choosing targets) · API retries with backoff `ingest/retry.py` (subagent) · integrity check `python -m lofc.store.integrity` (subagent; 0 orphans → FKs safe; 17 shared Transfermarkt ids; 8 possible duplicate identities) · `scripts/db_maintenance.sh` weekly VACUUM + `scout_sync` 7-day retention (subagent). **Also built 2026-10-26:** run record `pipeline_runs` + per-league failure isolation in 5 steps (a failing league is recorded, others continue, run ends \"partial\" exit 3); age dates from the season rule; verifier subagent review → 2 gaps fixed (escape paths; bad catalogue/calendar season no longer fatal); 1,759 tests. **Owner decision:** weekly_refresh treats a partial run as FAILED (last_failure written) — keep? Then: FKs migration; fix the 17 shared tm ids (incl. REGRESSION: tm 118779 Malone/Pack, fixed Aug, back again → identity step re-links). Plan for scale: full new-league load on the server into a separate `lofc_staging` DB first | Pipeline must stay reliable at ~4× scale | Impect; owner | Diagram: https://claude.ai/artifact/6ragLTMmnnNg7ZGsWznosm |
| 2.1c | **Regenerate the LOFC data pipeline page** after the 2.1b fixes — larger readable vertical flow naming files; readable ERD; what each provider call returns; replace the 19-step table with stages + why + what breaks (owner feedback 2026-10-26) | Owner's own codebase reference; for a senior engineer | After 2.1b | Current: https://claude.ai/artifact/6ragLTMmnnNg7ZGsWznosm |
| 2.1d | **✅ INSTALLED (verified in server crontab 2026-10-26), with the Sunday 04:00 `db_maintenance.sh`. Midweek refresh** (owner 2026-10-26): add a Thursday 04:15 UTC run of `weekly_refresh.sh` so Tue/Wed matches appear before the weekend. Add AFTER go-live, once a full 74-league run is timed on the server. Ask Impect/SkillCorner their match-processing lag | Recruiters wait a week for midweek games today | After go-live | cron: `15 4 * * 4 /opt/lofc/scripts/weekly_refresh.sh >> /opt/lofc/data/ops/cron.out 2>&1` |
| 2.1e | **Rebuild the Physical page** (owner 2026-10-26): it reads a one-off club SkillCorner EXPORT (League One 2025/26, 21 Orient players), ignores the Season selector and never refreshes. Rebuild on the SkillCorner API data the ratings use (6 leagues, 2025/26 + 2026/27, refreshed each run; no 2024/25 exists in the licence). Plan to owner first | Page is stale and misleading | Plan | Ireland SkillCorner editions: see 1.5 |
| 2.1f | **Transfermarkt for the 18 new leagues** — extend the Mac scraper (squads/contracts ~10–15 min; injuries ~6 h); ask the Head of Recruitment which leagues matter. Impect's Transfermarkt-id fields are empty (verified) | No contracts/values/injuries for new leagues | Head of Recruitment | |
| 2.2 | **Data-age date on screen** (P14) — per source: Performance (Impect), Physical (SkillCorner), Contracts & injuries (Transfermarkt), Scout reports; plus a warning naming any league whose latest refresh failed (from `pipeline_runs`) | A failed refresh today serves old numbers looking normal. **Do before January** | Nothing — ready | P14 |
| 2.3 | **Loans reach the server — ✅ LIVE 2026-11-02 (13fe78d; file loaded on the server: 411 loans, 384 linked, was 303).** The loan scrape now also writes `reference/transfermarkt/loans.csv`; new loader `python -m lofc.store.loans` (weekly pipeline step after squads; refuses a file under 70% of stored, `--allow-shrink` to override). Verified on the Mac: same 411 loans, identical content; linking now 381 vs 303 on the server (today's tm ids). 1,877 tests | Loans on the live site would have stayed on September's | Deploy + push the file | — |
| 2.4 | **Formula meeting — HELD; weights → 2.13** — decisions B1–B5 + top speed counted twice + distance/metres-per-minute counted twice | Some players are mis-weighted today; changes ratings | Meeting: owner + Head of Recruitment | Decisions B1–B5 below |
| 2.5 | **End-to-end data pipeline audit** | Catches silent data errors before recruiters do | Nothing — ready | Leads below (2.5a–g) |
| 2.6 | **Withdraw a mistaken assessment** (P12) | A mistake is permanent and prints on the "Final" report | Nothing — small build | P12 |
| 2.7 | **Per-match tracking** (P11) — "what changed this week" for watchlisted players | High, but a large build | Scoping with owner | P11 |
| 2.8 | **Head of Recruitment's smaller asks** — his 3 physical sliders per position (placeholders now); "individual threat score" (which Impect score?); table columns per position; maximum sliders | Finishes his review list | Head of Recruitment | BUILD_PLAN OPEN TASKS |
| 2.9 | **Player profile signal wording** (owner 2026-10-30; not dependent on the Head of Recruitment): "Long and diagonal passes, share of his attempts" → "Chipped and diagonal passes, as a share of all his passes" (Impect has no "long pass"; code counts DIAGONAL + CHIPPED); "Passes into the final third, share of his attempts" → "…, as a share of all his passes". Owner still reviewing the other signal names | Head of Recruitment asked what it meant | Owner's review | `styles.SIGNAL_LABELS` |
| 2.10 | **Profile additions (docs/Playing_Profiles_Tweaks_2.md) + Goalscorer winger — ✅ LIVE 2026-10-30 (8ca8554; style signals recomputed, verified on the server).** Owner: proceed with the list, quality signals included (no style/outcome split); goalscoring winger NOT in the list, not built. 12 new signals, Dribbler style (25 styles), reference page + new glossary tab "Playing styles" (every style signal, Impect's definitions). 1,806 tests. **Blocker found:** low passes pull against long passes (r −0.53 CB, −0.60 CM), so Strong Ball-playing CB 149 → 14 and Playmaker 128 → 9 (2025/26, 7 leagues). **Owner chose: drop long passes** (Strong: Ball-playing 28, Playmaker 24); done, 1,807 tests. **Goalscoring winger** (requested verbally): recommended = winger "What" style with the CF Scorer's 4 signals (67 of 415 Strong; 13 also Creator) Owner approved; **Goalscorer built** (67 of 415 Strong). 1,808 tests | Head of Recruitment's request | **Deploy** | Then deploy + `python -m lofc.model.style_run` on the server |
| 2.11 | **League weighting** (owner 2026-10-30) — **WITHHELD 2026-11-02: the Head of Recruitment chose a different approach for now (no league ratings). Work so far kept: squad ratings pulled for all 74 league-seasons; discussion workbook `League strength - Impect squad ratings.xlsx` (repo root, not tracked) for owner + colleague to choose mean / median / trimmed mean and single vs multi-season. Mean vs median changes the order for 20 of 25 leagues (mostly 1–3 places); medians swing up to ±0.12 between seasons.** Earlier note: Verified: Impect has NO ready league coefficient for players; `competitionCoefficient` is a match-prediction term (League One 0.108 > Championship 0.058), not strength. `getSquadRatings` gives team strength on one scale across leagues (one model: same intercept everywhere). 2025/26 league means: Championship 0.80 · League One 0.66 · Scottish Prem 0.59 · League Two 0.55 · National League 0.44 · PL2 0.43 · Ireland 0.35 · Scottish Champ 0.32. Not applied anywhere today: ratings are within-league percentiles | A 4.0 in Ireland ranks beside a 4.0 in the Championship | Plan to owner | Ratings are a daily series from 2019 — take the season's end date, not today; ask Impect what "value" means |
| 2.12 | **Current club ("now …") — LIVE 2026-10-30 (2ca95ac; 15,923 players, 12,045 named; 147 rated 26/27 show "now"). Follow-up fix built locally: card got no "now" when opened from search, and would have shown it twice from the table.** The club shown is the club of the stats (most minutes in that league-season), never where he is now: Eoin Kenny rated for Dundalk FC (Ireland 2026 = season 319) after joining Portsmouth; 111 rated 2026/27 players had another club that season. Impect `currentSquadId` (per-season player list) gives his club now. New: player list + club names in the Impect pull, table `player_current_club` (migration b7c2e9a4d613), pipeline step "Current club", card header + Players table show "Dundalk FC · now FC Portsmouth". Verified: 26/27 players 96% have one, 93% named; agrees with Transfermarkt 98%; for 289 of 301 loanees it is the LOAN club. 1,816 tests | Recruiters saw the wrong club | Deploy + data | Unnamed = clubs outside every competition we can access (mostly players who left our leagues) |
| 2.13 | **Per-metric Performance weights (formula meeting) — ✅ LIVE 2026-11-02 (eb1d17c; live smoke PASS).** From the club's workbook v5 (High/Mid/Low per position + archetype); five unevenly applied tables corrected to their tier ratios (GK 9:5:4, FB Attacking 5:3, FB Progressive 2:1, CF 14:7:3, Winger Crossing = All Metrics rescaled); exact fractions, every table sums to 1. Physical unweighted (club's decision), 57/43 unchanged. Card shows a scored metric with no value as "No value" (1 of 14,501 rated players today). Reference page + Excel: Weight column, archetype columns show their own weights. Before/after on live 2025/26 (method reproduces stored ratings 100%): mean change 0.04 (FB) – 0.18 (CF, GK); top 10 per league keeps 7–9. 1,871 tests | Changes every outfield rating | Owner + Head of Recruitment review the before/after, then deploy + rebuild scorecards | Physical weights still open (club: later) |
| 2.14 | **Assess Tavily for server-side Transfermarkt scraping** (colleague's suggestion, owner 2026-11-02; AFTER the major tasks). Use cases: club moves every 2–4 weeks; injury histories (missing for most players). FIRST question: Transfermarkt's AWS WAF blocks the server deliberately; if Tavily fetches through its own infrastructure to get round that block it is a proxy, which the owner declined (CLAUDE.md). Also check Transfermarkt's terms and Tavily's cost. Note: Impect's currentSquadId (2.12) already covers club moves weekly for all 25 leagues | Injury coverage, freshness | After major tasks | Decision for owner |
| 2.15 | **Scout reports not matched — ✅ LIVE 2026-11-02 (eb1d17c; live smoke PASS).** Cause: matching on name + date of birth, and the club sheet's DOBs are often wrong (Kian Leavy: ours 21/03/2002, sheet 21/03/2004; day/month swaps; duplicates). Live: 726 reports, 524 linked; ~75 fixable. New second tier in `model/scout_report_link.py`: name unique among OUR players + DOB compatible (identical, day/month swapped, same day+month with year ±2, or a DOB missing/implausible); duplicates no longer dropped; tolerant links printed for review. 1,894 tests | Recruiters cannot see scout reports on the player | Deploy, then `python -m lofc.model.scout_report_link` once (relinks + prints the review list) | Sync relinks only when the sheet changes |
| 2.16 | **Report page: write summary / Why sign / Considerations / Psychological / Medical on the report — ✅ LIVE 2026-11-02 (eb1d17c; live smoke PASS).** Owner: nothing stored (saved reports abandoned); all optional; Download ("Report by <user> · date", Psych/Medical marked "<name>'s view", screening ✓/✗, never changes a rating) and Download data-only; opens from a link with the player preselected. Rendered and checked in a browser. Report built once per click (cache 60 s) | Streamlines report writing | Deploy | Follow-up: "Write report" button on the player card |
| 2.17 | **✅ RESOLVED 2026-11-02: the report's category bars were replaced by the Playing style panel (owner: "put player profiles for reports"). Report chart categories** ("creation percentile", "retention", …): which metrics, from where, how computed; review whether they need changing. Reports must be comprehensive | Recruiters asked what they mean | Investigation | — |
| 2.18 | **HOTFIX: Players page crashed when filtering on Assists, Expected assists or Non-pen xG** (live, 2026-11-02, during a presentation). The pool already carries those three raw; the filter joined a second column of the same name → KeyError 'xa_p90'. Fixed: filter values join under private names (and a percentile filter now always reads the percentile). 2 regression tests; all 236 position × metric filters run clean on real data. 1,896 tests | Page crashed in front of users | Deploy (code only) | — |
| 2.19 | **Searched player did not open — ✅ LIVE 2026-11-02 (eb1d17c; live smoke PASS).** Cause: the pick was matched only within the sidebar's position/filters, and a stale table click won. Now the searched player always opens (caption if outside the list or unrated); the pick clears stale selections; a later table click still wins | Recruiters could not open players they searched | Deploy | Follow-up: players under 450 min are not in the search index |
| 2.20 | **✅ LIVE 2026-11-02 (eb1d17c; live smoke PASS).** **Compare page search ignores the sidebar position** (picking switches the sidebar; comparisons stay same-position) (like the Players search), so different positions can be compared | Saves changing the sidebar each time | Investigation → build | Mixed-position comparison design |
| 2.21 | **Compare page rebuilt — ✅ LIVE 2026-11-02 (eb1d17c; live smoke PASS).** Players as columns (no sideways scroll); Overall/Performance/Physical with green/red change vs last season; rating trend (3 seasons); playing style; scout verdicts; Performance radar = High+Mid metrics, always shown; physical radar (7 rated metrics); Performance + Physical tables (green best / red worst, rating metrics first, others collapsible). Removed on request: availability, club now, contract, loan | Comprehensive comparison | Deploy | B7 done locally (see B7) |
| 2.22 | **Games played — DROPPED (owner, 2026-11-02)**: Impect gives no true appearance count (only match-equivalents) | — | — | — |
| 2.23 | **All physical filters — ✅ LIVE 2026-11-02 (eb1d17c; live smoke PASS).** 23 metrics in 6 tabs (Distance, Speed, Intensity, Acceleration, Time to speed, Agility); "Max" sliders for the 6 lower-is-better; `psv99_kmh` (average match top speed) left out per the Head of Recruitment's earlier decision; hi_* glossary entries verified (= HSR + sprint, 5,809 rows). Checked on the real page | Granular physical search | Deploy | — |
| 2.24 | **Speed — ✅ LIVE 2026-11-02 (eb1d17c; live smoke PASS).** Measured: DB fast; ~17 s of Python on every cold cache, and caches expired every 5–10 min. Now: pipeline-data caches last 24 h keyed on a data-version token (Postgres write counters + table file ids + server start + date, checked every 30 s) so data is never older than the database; user-written data keeps 60 s; one-season reads; background warm-up when the version changes. 1,928 tests | Users waited 10+ s per action | Deploy, then measure on the server | Step B (vectorise build_candidates, precompute style labels) if still slow |
| 2.26 | **Blank cells show "—" not "None" — ✅ LIVE 2026-11-02 (eb1d17c; live smoke PASS).** All tables (Players ratings, Squads, Scout reports, card, watchlist, injuries). Squads dates stay real dates so they sort by date (their blanks still read "None", as do Minutes / Months left). Smoke test now fails if a table shows a format code ("%b %Y"). Squads also: Transfermarkt as-of dates + Player search. 2,075 tests | Tables read cleanly | Deploy | — |
| 2.25 | **Players under 450 minutes searchable** (owner approved 2026-11-02): card shows header, raw stats, physical, injuries, scout reports; caption "Not rated: under 450 minutes (N played)"; no rating/percentiles/style | Recruiters can look up anyone | Build (search index from all season players) | — |

**Audit leads (2.5) — found 2026-10-22 while rewriting the docs; each to be verified before fixing:**

| # | Lead |
|---|---|
| 2.5a | Financial/Resale bands and valuation features still use the old `rank(pct=True)` percentile (rank ÷ n), the method the scoring fixed as biased upward in small pools (`financial_resale._pct_within`, `normalise.compute_percentiles_wide`) |
| 2.5b | 12 of the valuation model's 27 features are empty for every 2025/26 player and filled with 50 — constants, carrying nothing |
| 2.5c | The stored `veto` flag is driven mostly by the modelled money areas (984 vetoes in 2025/26 vs 97 in 2024/25, which has no money layer) |
| 2.5d | The wage-grid tier reads the old Quality-era `player_scores.performance_score`, not the club composite |
| 2.5e | Stale labels: `club_framework.py` docstring (DM/CM "share one list"); pipeline step "87 metrics"; Physical page calls `psv99_kmh` "PSV-99" while the glossary says "Average match top speed" |
| 2.5f | Premier League 2 2026/27: 14 rankable players — almost every pool will be withheld |
| 2.5g | Detail-build slowness/warnings; DB bloat from delete+insert; nothing reads `last_failure` |
| 2.5h | Wage and identity reference tables (`wage_estimates`, `wage_framework`, `identity_profiles`) are only rebuilt by stages skipped under `IMPECT_ONLY` — a fresh database would not get them |
| 2.5i | The Transfermarkt scrape and squad-load stages only run if the legacy `SB_COMPETITIONS` setting lists EFL ids — without it the squad loader is skipped silently |
| 2.5j | The candidate pool and style clusters still rest on retired tables (`player_scores`, `player_season_metrics`): clusters exist only for the EFL 24/25–25/26 (overlaps 2.5d) |
| 2.5k | Shortlists and valuations cover 2025/26 EFL only, though 2026/27 is the live season |
| 2.5l | `requirements.lock` lacks `google-api-python-client` and `google-auth` (the image installs them from `pyproject.toml`) |
| 2.5n | Two "open-play assists" on the platform: the Performance metric `open_play_assists_p90` uses Impect's In Possession phase only (starts after 4 s on the ball at the back, so it EXCLUDES counter-attack assists); the new style signal uses all assists minus set pieces. Label or definition of the Performance metric may mislead |
| 2.5m | `transfermarkt_loans --season-id` help says "same as --season"; the code defaults to the live season. "87 metrics" in labels/docstrings (the registry holds 91) — with 2.5e |

**Decisions the owner owes (each unblocks a task above):**

| # | Decision | Options | Recommended |
|---|---|---|---|
| D11 | Archetypes vs the new profiles (2.1) | A keep both, renamed · B merge · C drop archetypes | Decide with the Head of Recruitment's definitions in hand |
| D-mpm | Metres per minute in/out of possession (125 / 149) exceed the all-phases figure (100) — correct but confusing | Show as is · show "—" for the split | "—" |

**Formula decisions for the meeting (2.4) — evidence measured 2026-10-02 on 2025/26:**

| # | Decision | Evidence |
|---|---|---|
| B1 | Is **57% Performance / 43% Physical** the intended split? | The club framework says 40/30; the ranking drops the two scout dimensions and rescales |
| B2 | Should Physical decide **69%** of the ranking? | Weight 43%, influence 69%: its 8 metrics are 4 concepts measured twice (HSR count/distance r 0.96, sprint count/distance 0.93). Remove the duplicates, or lower the weight to 30% (influence → 42%) |
| B3 | Should a rating built on **Performance alone** rank beside one built on both? | 581 of 3,345 ratings. Same average Performance, but 2.6× the rate of reaching 4.0 and 64% of the top 1% |
| B4 | Are the **five merged metric pairs** acceptable as single measurements? | 18 position-metric slots; each concept carries half the share the framework's two entries imply |
| B5 | Should **goalkeepers** be rated on 6 metrics with no physical component? | `long_ball_pct` unavailable; GK Performance spread 0.83, the widest of any position |
| B6 | **Top speed is scored twice** — all-match average (`psv99_kmh`) and top-5 average (`top5_psv99_kmh`), every outfield position. The Head of Recruitment does not want the all-match average | Drop it from scoring? Moves ratings |
| B7 | **Distance per 90 and metres per minute** are one measurement (r = 1.00), and **both are scored** for every outfield position. **Owner 2026-11-02: drop metres per minute — ✅ LIVE 2026-11-02 (eb1d17c; 39 metrics; owner ran the rescore).** | Drop one? Moves ratings · **Owner to revisit (noted 2026-11-02): harmless on the Compare radar (two near-identical axes); in the rating it counts running volume twice.** |

**Scouting decisions (backlog P21):**

| # | Decision | Note |
|---|---|---|
| A2 | Keep the platform **watchlist** (5 rows) alongside the sheet's **Players of Interest** (223)? | Same question, two lists; the sheet's is maintained |
| A3 | When a signed-off **assessment** and a **scout report** disagree, which is the club's view? | They differ: an assessment scores Psychological + Medical; a report is a per-match verdict |
| A4 | Rebuild the scouting form inside the platform, eventually? | Would remove "A New Player" for good. Never write back to the sheet |

---

## 3. Waiting on someone else

| # | What | Who | Status |
|---|---|---|---|
| 3.1 | Memory limits on the colleague's containers + house rules | Colleague | Message drafted 2026-10-16; not confirmed applied. Check: `docker stats --no-stream` LIMIT column |
| 3.2 | Platform domain → a `leytonorient.com` subdomain | Club IT (A record → 165.22.122.157) | Deferred |
| 3.3 | Email to Impect: "ball wins" equals "defensive touches" for 80–98% of rows; definitions of Offensive/Defensive IMPECT | Owner sends | Not sent |

---

## 4. Recurring (nobody else will do these)

| What | When | How |
|---|---|---|
| **Transfermarkt refresh** — contracts, squads, loans, injuries (cannot run on the server: AWS WAF) | **Before the January window**; occasionally for injuries | On the Mac — commands in `CLAUDE.md` → "RECURRING MANUAL TASK" |
| Check the weekly refresh succeeded | Mondays after 04:15 UTC | `cat /opt/lofc/data/ops/last_success /opt/lofc/data/ops/last_failure` (until 2.2 puts it on screen) |
| Check backups | Monthly | `ls -l /opt/lofc/backups` (14 nightly dumps) · DigitalOcean console → Backups (7 daily) |

---

## 5. Backlog — register items, lower priority

| # | What | Note |
|---|---|---|
| P13 | Discovery vs confirmation — the central design question | 2.1 is the first concrete step |
| P15 | ~15 captions on the Players page state facts nothing re-checks | Audit, replace with labels/columns |
| P21 | Platform watchlist & assessments barely used; the club's sheet is the real tool | Decisions A2–A4 in section 2 |
| P19 | `docs/architecture.md` is stale | Rewrite |
| P1 / P2 / R11 / R7 | Player identity: split ids, one pair awaiting a ruling, matcher can create duplicate Transfermarkt ids | Needs a careful session |
| P5 | Injury panel heading wrong for current-season spells | Small |
| P6 / P10 / R4 | Retire the legacy `player_season_metrics` table; unguarded DELETE in `store/load.py` | Cleanup |
| P7 / R3c | Player report export gated on sign-off | — |
| P8 | Availability report — not possible with current data | — |
| R6 | Transfermarkt squads for Scottish leagues + PL2 (low coverage) | — |
| — | Scout sheet: four tabs fetched but not stored | — |

---

## 6. Done recently (newest first)

| Date | What |
|---|---|
| 2026-10-26 | **18 new Impect competitions live** (25 leagues); league registry; per-league failure isolation + `pipeline_runs`; API retries; integrity check; DB maintenance; scout_sync retention; page footer removed |
| 2026-10-22 | Built (section 1): scout names on lines 2–3; Squads registered positions (P18); documentation consolidated (19 → 9 files). Local DB resynced from the server |
| 2026-10-16 | Deployed: Players opens on 2026/27; Scout reports show both ratings, Model view says which season; "Not in our data" only for unmatched players |
| 2026-10-16 | Server: nightly database dump (19:30 UTC, 14 kept, restore-tested); DigitalOcean backups daily; `.env` locked down; firewall; disk 77 GB; build-cache prune weekly; colleague's platform live at orient-matchanalysis.duckdns.org |
| 2026-10-16 | Top speed = average of the 5 fastest matches |
| 2026-10-12 → 15 | Head of Recruitment review round: physical per-90 fix, detail data, packing zones, glossary, reference page, sliders — see BUILD_PLAN work log |
