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
| 2.1 | **Player profiles** — 24 playing styles (e.g. "In-behind winger"), a label + filter on the Players page and card | **Highest value.** Turns the platform from *checking* known players into *discovering* new ones (P13) | Head of Recruitment: definitions + 1–2 example players per style. Owner: decision 11 (below) | P4 in BUILD_PLAN register |
| 2.2 | **Data-age date on screen** (P14) — "Impect/SkillCorner data as of …" per source, and a visible warning if the Monday refresh failed | A failed refresh today serves old numbers looking normal. **Do before January** | Nothing — ready | P14 |
| 2.3 | **Loans cannot reach the server through the documented refresh.** The loan scrape writes only to the Mac's database (no CSV), and the server has no loans loader | Loans on the live site go stale from the next Transfermarkt refresh. **Must be fixed before the January refresh** | Nothing — ready | Found 2026-10-22 (architecture rewrite); verified in `ingest/transfermarkt_loans.py` |
| 2.4 | **Formula meeting** — decisions B1–B5 + top speed counted twice + distance/metres-per-minute counted twice | Some players are mis-weighted today; changes ratings | Meeting: owner + Head of Recruitment | Decisions B1–B5 below |
| 2.5 | **End-to-end data pipeline audit** | Catches silent data errors before recruiters do | Nothing — ready | Leads below (2.5a–g) |
| 2.6 | **Withdraw a mistaken assessment** (P12) | A mistake is permanent and prints on the "Final" report | Nothing — small build | P12 |
| 2.7 | **Per-match tracking** (P11) — "what changed this week" for watchlisted players | High, but a large build | Scoping with owner | P11 |
| 2.8 | **Head of Recruitment's smaller asks** — his 3 physical sliders per position (placeholders now); "individual threat score" (which Impect score?); table columns per position; maximum sliders | Finishes his review list | Head of Recruitment | BUILD_PLAN OPEN TASKS |

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
| B7 | **Distance per 90 and metres per minute** are one measurement (r = 1.00), and **both are scored** for every outfield position | Drop one? Moves ratings |

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
| 2026-10-22 | Built (section 1): scout names on lines 2–3; Squads registered positions (P18); documentation consolidated (19 → 9 files). Local DB resynced from the server |
| 2026-10-16 | Deployed: Players opens on 2026/27; Scout reports show both ratings, Model view says which season; "Not in our data" only for unmatched players |
| 2026-10-16 | Server: nightly database dump (19:30 UTC, 14 kept, restore-tested); DigitalOcean backups daily; `.env` locked down; firewall; disk 77 GB; build-cache prune weekly; colleague's platform live at orient-matchanalysis.duckdns.org |
| 2026-10-16 | Top speed = average of the 5 fastest matches |
| 2026-10-12 → 15 | Head of Recruitment review round: physical per-90 fix, detail data, packing zones, glossary, reference page, sliders — see BUILD_PLAN work log |
