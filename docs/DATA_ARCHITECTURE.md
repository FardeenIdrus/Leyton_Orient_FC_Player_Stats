# Data Sources & Architecture — reference

**Purpose:** one place that answers "what metrics do we have, from which source, and
which file does what". For presenting to the recruitment team and for onboarding.

Last updated: 2026-08-10. **Status: LIVE.** The combined 91-metric table
(`player_metrics_neutral`, 9,451 rows = every player × league × season across all 14
league-seasons: EFL + Scottish Premiership/Championship + Premier League 2) is the spine the
scoring reads. Scoring is 100% Impect + SkillCorner (zero StatsBomb). Players are ranked on
the club's 1–5 composite (`model/club_framework.py` + `model/scorecard.py`); see §4 for the
club framework mapping and `docs/methodology.md` §3b for the scoring method.

---

## 1. The four data sources at a glance

The platform combines four independent data feeds, joined together per player, per
league, per season. **91 metrics** per player in total (Impect 45 · StatsBomb advanced 12 · StatsBomb computed 10 · SkillCorner 24 — counts asserted at import in `metric_registry.py`). **The StatsBomb columns are empty in every league**: StatsBomb is retired from scoring, so they are dead columns pending removal (roadmap R4).

| Source | What it provides | # metrics | Definition file |
|---|---|---|---|
| **Impect** | On-ball performance (incl. packing, on-ball value, off-ball) | 45 | `src/lofc/ingest/impect_map.py` |
| **StatsBomb — advanced feed** | Advanced stats Impect lacks (possession-adjusted, xG buildup) | 12 | `src/lofc/ingest/statsbomb_season.py` |
| **StatsBomb — original** | Core event stats built at the start of the project | 10 | `src/lofc/store/models.py` |
| **SkillCorner** | Physical / tracking (speed, distance, sprints, agility) | 24 | `src/lofc/ingest/skillcorner_map.py` |

**Impect is the primary source.** Where Impect and StatsBomb both measure the same
thing (10 metrics: goals, assists, xG, etc.), Impect's version is used. StatsBomb only
fills the gaps Impect cannot cover.

### Why StatsBomb is in two files (a real capability split, not an accident)
StatsBomb data reaches us two ways, and they carry **different** metrics:
- **`models.py` + `aggregate/*`** = metrics we **compute ourselves from raw match
  events**. This can produce things StatsBomb's pre-computed feed does not expose —
  e.g. progressive passes/carries, blocks count, GK saves count, all-shots xG.
- **`statsbomb_season.py`** = **advanced stats StatsBomb pre-computes that we cannot
  replicate** from events (possession-adjusted tackles/pressures, xG buildup, etc.).

We verified (2026-07-20) that the pre-computed feed is **missing 6 of the original 15**,
so they can only come from our own event aggregation. The split is therefore kept by
design: "computed by us" vs "StatsBomb-proprietary". `models.py` remains the database
schema and the home of the 15 event-derived metric names.

---

## 2. What each file does

### Configuration
- `config.py` — which leagues/seasons to pull from each provider (Impect iterations,
  SkillCorner editions, StatsBomb competitions), plus credentials.

### Getting the data in (ingest)
- `ingest/impect.py` — downloads Impect player data → `data/raw/impect/`.
- `ingest/statsbomb_season.py` — downloads the StatsBomb advanced feed →
  `data/raw/statsbomb_season/`; **also defines the 12 advanced metrics** (`STATSBOMB_GAP_MAP`).
- `ingest/skillcorner_api.py` — downloads SkillCorner physical data → `data/raw/skillcorner/`.
- `ingest/statsbomb.py` + `aggregate/*` — the original pipeline that builds the 15
  original metrics from raw StatsBomb match events.
- `ingest/landing.py` — shared idempotent file read/write.

### Defining which metric comes from where (the maps)
- `ingest/impect_map.py` — the 45 Impect metrics + their source columns + confidence.
- `ingest/skillcorner_map.py` — the 24 physical metrics + their source columns.
- `ingest/statsbomb_season.py` — the 12 advanced metrics (map lives inside this file).
- `store/models.py` — the database table shapes; also currently holds the 15 original
  metric names (`PER90_COLUMNS`).

### Translating raw data into our metric names
- `ingest/impect_translate.py` — turns Impect's raw download into our metric names
  (per-90 conversion + minutes floor).
- `ingest/statsbomb_season.py` (`translate_frame`) — renames the advanced feed columns.

### The unified layer (Phase 11 — the cross-source machinery)
- `model/metric_registry.py` — **the single source of truth**: all 91 metrics, each with
  its one source and exact derivation; overlap winners declared; invariants asserted at
  import. Prints the inventory: `python -m lofc.model.metric_registry`.
- `model/build_neutral.py` — merges the four sources into one row per player
  (registry-driven, no collisions possible) and, with `--write`, loads it into the
  `player_metrics_neutral` table (clear-then-insert, idempotent). Pipeline step 15.
- `store/models.py` (`PlayerMetricNeutral`) — the combined table's schema, with its 91
  metric columns **generated from the registry** so schema and definitions cannot drift
  (enforced by a test).

### Checking the data is trustworthy (validation)
- `model/impect_check.py` — compares Impect vs StatsBomb on overlapping metrics.
- `model/skillcorner_check.py` — checks SkillCorner coverage vs our players.

### Reference (not code)
- `data/reference/impect_metric_map.csv` — spreadsheet copy of the Impect map.
- `data/reference/impect_definitions.csv` — Impect's own official metric definitions.
- `docs/impect_column_list.txt` — the full ~1,480 raw Impect columns (menu).

---

## 3. Full metric inventory (all 91, with exact derivations)

*These tables are generated from `src/lofc/model/metric_registry.py` — the unified
in-code registry. The registry is the single source of truth: every metric's source
and exact derivation lives there, is asserted at import time, and these tables mirror
it. Regenerate after any registry change.*

### A. IMPECT — 45 metrics

*Defined in `impect_map.py` (definitions) + `impect_translate.py` (the per-90 conversion).*

**Club-framework additions (4, confirmed with the club — the Impect stand-ins for StatsBomb-only club metrics):**
`gk_catches_p90` = BALL_WIN_NUMBER_BY_ACTION_CATCH (Claims) · `defensive_touches_outside_box_p90`
= DEFENSIVE_TOUCHES − DEFENSIVE_TOUCHES_IN_PITCH_POSITION_OWN_BOX (GK Aggressive Distance) ·
`cross_bypassed_opponents_p90` = BYPASSED_OPPONENTS_BY_ACTION_HIGH_CROSS + …LOW_CROSS (Successful
Box Cross%) · `dribble_count_p90` = BYPASSED_OPPONENTS_NUMBER_BY_ACTION_DRIBBLE (Dribble Attempts).

| Metric | Club stat | How it is produced (exact) |
|---|---|---|
| goals_p90 | Goals | per-90 from Impect per-match averages: season total = (GOALS) x matchShare summed over position rows, / minutes x 90 (impect_translate.py) |
| np_xg_p90 | NP xG | per-90 from Impect per-match averages: season total = (SHOT_XG − SHOT_XG_BY_ACTION_PENALTY_KICK) x matchShare summed over position rows, / minutes x 90 (impect_translate.py). Penalty xG is subtracted, so this is genuine non-penalty xG |
| shots_p90 | NP Shots | per-90 from Impect per-match averages: season total = (SHOT_AT_GOAL_NUMBER) x matchShare summed over position rows, / minutes x 90 (impect_translate.py) |
| xa_p90 | Open Play xG Assisted | per-90 from Impect per-match averages: season total = (EXPECTED_GOAL_ASSISTS) x matchShare summed over position rows, / minutes x 90 (impect_translate.py) |
| assists_p90 | Assists | per-90 from Impect per-match averages: season total = (ASSISTS) x matchShare summed over position rows, / minutes x 90 (impect_translate.py) |
| key_passes_p90 | Chances created | per-90 from Impect per-match averages: season total = (SHOT_ASSISTS) x matchShare summed over position rows, / minutes x 90 (impect_translate.py) |
| xg_overperformance_p90 | Over/Under Performance | per-90 from Impect per-match averages: season total = (GOALS - SHOT_XG) x matchShare summed over position rows, / minutes x 90 (impect_translate.py) |
| touches_in_box_p90 | Touches In Box | per-90 from Impect per-match averages: season total = (OFFENSIVE_TOUCHES_IN_PITCH_POSITION_OPPONENT_BOX) x matchShare summed over position rows, / minutes x 90 (impect_translate.py) |
| open_play_assists_p90 | Open Play Assists | per-90 from Impect per-match averages: season total = (ASSISTS_AT_PHASE_IN_POSSESSION) x matchShare summed over position rows, / minutes x 90 (impect_translate.py) |
| np_xg_xa_p90 | NP xG + xA | per-90 from Impect per-match averages: season total = (SHOT_XG − SHOT_XG_BY_ACTION_PENALTY_KICK + EXPECTED_GOAL_ASSISTS) x matchShare summed over position rows, / minutes x 90 (impect_translate.py). **Penalty xG is subtracted** so this matches the non-penalty `np_xg_p90`; an earlier version summed penalty-inclusive SHOT_XG, inflating penalty takers (fixed 2026-08-03, neutral table rebuilt) |
| post_shot_xg_p90 | (finishing quality) | per-90 from Impect per-match averages: season total = (POSTSHOT_XG) x matchShare summed over position rows, / minutes x 90 (impect_translate.py) |
| shot_threat_p90 | (shot threat) | per-90 from Impect per-match averages: season total = (PXT_SHOT) x matchShare summed over position rows, / minutes x 90 (impect_translate.py) |
| passes_completed_p90 | (passing base) | per-90 from Impect per-match averages: season total = (SUCCESSFUL_PASSES) x matchShare summed over position rows, / minutes x 90 (impect_translate.py) |
| passes_into_box_p90 | OP Passes Into Box | per-90 from Impect per-match averages: season total = (SUCCESSFUL_PASSES_TO_PITCH_POSITION_OPPONENT_BOX) x matchShare summed over position rows, / minutes x 90 (impect_translate.py) |
| pass_completion_pct | Passing% | season-total ratio from Impect: (SUCCESSFUL_PASSES) / (SUCCESSFUL_PASSES + UNSUCCESSFUL_PASSES) (impect_translate.py) |
| goal_conversion_pct | Goal Conversion Ratio | season-total ratio from Impect: (GOALS) / (SHOT_AT_GOAL_NUMBER) (impect_translate.py) |
| xg_per_shot | xG/Shot | season-total ratio from Impect: (SHOT_XG) / (SHOT_AT_GOAL_NUMBER) (impect_translate.py) |
| pass_value_p90 | Pass OBV | per-90 from Impect per-match averages: season total = (PXT_PASS) x matchShare summed over position rows, / minutes x 90 (impect_translate.py) |
| dribble_carry_value_p90 | Dribble & Carry OBV | per-90 from Impect per-match averages: season total = (PXT_DRIBBLE) x matchShare summed over position rows, / minutes x 90 (impect_translate.py) |
| defensive_value_p90 | Defensive Action OBV | per-90 from Impect per-match averages: season total = (PXT_BALL_WIN + PXT_BLOCK) x matchShare summed over position rows, / minutes x 90 (impect_translate.py) |
| on_ball_value_p90 | OBV | per-90 from Impect per-match averages: season total = (PXT_PASS + PXT_DRIBBLE + PXT_BALL_WIN + PXT_BLOCK + PXT_SHOT) x matchShare summed over position rows, / minutes x 90 (impect_translate.py) |
| packing_bypassed_opponents_p90 | (packing) | per-90 from Impect per-match averages: season total = (BYPASSED_OPPONENTS) x matchShare summed over position rows, / minutes x 90 (impect_translate.py) |
| packing_bypassed_defenders_p90 | (packing) | per-90 from Impect per-match averages: season total = (BYPASSED_DEFENDERS) x matchShare summed over position rows, / minutes x 90 (impect_translate.py) |
| packing_xg_p90 | (packing xG) | per-90 from Impect per-match averages: season total = (PACKING_XG) x matchShare summed over position rows, / minutes x 90 (impect_translate.py) |
| ground_duels_won_p90 | (tackle analogue) | per-90 from Impect per-match averages: season total = (WON_GROUND_DUELS) x matchShare summed over position rows, / minutes x 90 (impect_translate.py) |
| ball_wins_p90 | (Impect ball wins) | per-90 from Impect per-match averages: season total = (BALL_WIN_NUMBER) x matchShare summed over position rows, / minutes x 90 (impect_translate.py) |
| turnovers_p90 | Turnovers | per-90 from Impect per-match averages: season total = (BALL_LOSS_NUMBER) x matchShare summed over position rows, / minutes x 90 (impect_translate.py) |
| off_ball_receiving_p90 | (off-ball receiving) | per-90 from Impect per-match averages: season total = (BYPASSED_OPPONENTS_RECEIVING) x matchShare summed over position rows, / minutes x 90 (impect_translate.py) |
| pressures_p90 | Pressures | per-90 from Impect per-match averages: season total = (NUMBER_OF_PRESSES) x matchShare summed over position rows, / minutes x 90 (impect_translate.py) |
| counterpressures_p90 | Counterpressures | per-90 from Impect per-match averages: season total = (NUMBER_OF_PRESSES_COUNTER_PRESS) x matchShare summed over position rows, / minutes x 90 (impect_translate.py) |
| deep_progressions_p90 | Deep Progressions | per-90 from Impect per-match averages: season total = (BYPASSED_OPPONENTS_TO_PITCH_POSITION_FINAL_THIRD) x matchShare summed over position rows, / minutes x 90 (impect_translate.py) |
| aerial_win_pct | Aerial Win% | season-total ratio from Impect: (WON_AERIAL_DUELS) / (WON_AERIAL_DUELS + LOST_AERIAL_DUELS) (impect_translate.py) |
| ground_duel_win_pct | Tack/Dribbled Past% | season-total ratio from Impect: (WON_GROUND_DUELS) / (WON_GROUND_DUELS + LOST_GROUND_DUELS) (impect_translate.py) |
| gk_conceded_p90 | Goals conceded | per-90 from Impect per-match averages: season total = (CONCEDED_GOALS) x matchShare summed over position rows, / minutes x 90 (impect_translate.py) |
| gk_gsaa_p90 | Goals Saved Above Average | per-90 from Impect per-match averages: season total = (CONCEDED_POSTSHOT_XG - CONCEDED_GOALS) x matchShare summed over position rows, / minutes x 90 (impect_translate.py) |
| gk_shot_stopping_pct | Shot Stopping% | season-total ratio from Impect: (CONCEDED_POSTSHOT_XG - CONCEDED_GOALS) / (CONCEDED_POSTSHOT_XG) (impect_translate.py) |

### B. STATSBOMB advanced feed — 12 metrics

*Defined in `statsbomb_season.py` (definitions + pull + rename).*

| Metric | Club stat | How it is produced (exact) |
|---|---|---|
| pressures_opp_half_p90 | Pressures in Opposing Half | taken as-is from endpoint column player_season_fhalf_pressures_90 (pre-computed per-90/ratio by StatsBomb); mid-season movers minutes-weighted (statsbomb_season.py:translate_frame) |
| aggressive_actions_p90 | Aggressive Actions | taken as-is from endpoint column player_season_aggressive_actions_90 (pre-computed per-90/ratio by StatsBomb) — tackles/pressures/fouls within 2s of an opponent receiving; mid-season movers minutes-weighted (statsbomb_season.py:translate_frame) |
| padj_tackles_interceptions_p90 | PAdj Tackles & Interceptions | taken as-is from endpoint column player_season_padj_tackles_and_interceptions_90 (pre-computed per-90/ratio by StatsBomb) — possession-adjusted by StatsBomb; mid-season movers minutes-weighted (statsbomb_season.py:translate_frame) |
| padj_pressures_p90 | PAdj Pressures | taken as-is from endpoint column player_season_padj_pressures_90 (pre-computed per-90/ratio by StatsBomb) — possession-adjusted by StatsBomb; mid-season movers minutes-weighted (statsbomb_season.py:translate_frame) |
| xg_buildup_p90 | xGBuildup | taken as-is from endpoint column player_season_xgbuildup_90 (pre-computed per-90/ratio by StatsBomb) — xG of possessions the player took part in, excluding his shot/assist; mid-season movers minutes-weighted (statsbomb_season.py:translate_frame) |
| pressured_pass_pct | Pressured Pass% | taken as-is from endpoint column player_season_pressured_passing_ratio (pre-computed per-90/ratio by StatsBomb) — completion % of passes made under pressure; mid-season movers minutes-weighted (statsbomb_season.py:translate_frame) |
| successful_box_cross_pct | Successful Box Cross% | taken as-is from endpoint column player_season_box_cross_ratio (pre-computed per-90/ratio by StatsBomb); mid-season movers minutes-weighted (statsbomb_season.py:translate_frame) |
| dribbles_p90 | Dribbles | taken as-is from endpoint column player_season_total_dribbles_90 (pre-computed per-90/ratio by StatsBomb) — attempted dribbles; mid-season movers minutes-weighted (statsbomb_season.py:translate_frame) |
| dribble_success_pct | Dribble Success | taken as-is from endpoint column player_season_dribble_ratio (pre-computed per-90/ratio by StatsBomb); mid-season movers minutes-weighted (statsbomb_season.py:translate_frame) |
| gk_claims_pct | Claims | taken as-is from endpoint column player_season_clcaa (pre-computed per-90/ratio by StatsBomb) — claimable-cross claim rate vs the average keeper (CCAA); mid-season movers minutes-weighted (statsbomb_season.py:translate_frame) |
| gk_aggressive_distance | Goalkeeper Aggressive Distance | taken as-is from endpoint column player_season_da_aggressive_distance (pre-computed per-90/ratio by StatsBomb) — avg distance from goal of keeper defensive actions; mid-season movers minutes-weighted (statsbomb_season.py:translate_frame) |
| long_ball_pct | Long Ball% | taken as-is from endpoint column player_season_long_ball_ratio (pre-computed per-90/ratio by StatsBomb) — long-pass completion %; mid-season movers minutes-weighted (statsbomb_season.py:translate_frame) |

### C. STATSBOMB computed-by-us — 15 metrics

*Defined in counted in `aggregate/events.py`, per-90 in `aggregate/player_season.py`, names in `store/models.py`.*

| Metric | Club stat | How it is produced (exact) |
|---|---|---|
| tackles_p90 | (tackle count) | count of Duel events with duel type "Tackle" (events.py:192-194); count / minutes x 90 (player_season.py:134) |
| interceptions_p90 | Interceptions | count of Interception events (events.py:184); count / minutes x 90 (player_season.py:134) |
| blocks_p90 | Blocks/Shot numerator | count of Block events (events.py:186); count / minutes x 90 (player_season.py:134) |
| clearances_p90 | Clearances | count of Clearance events (events.py:188); count / minutes x 90 (player_season.py:134) |
| ball_recoveries_p90 | Ball recoveries | count of Ball Recovery events (events.py:190); count / minutes x 90 (player_season.py:134) |
| carries_p90 | — | count of Carry events (events.py:176); count / minutes x 90 (player_season.py:134) |
| progressive_carries_p90 | — | Carry events moving the ball >= 10m toward goal (end_x - start_x >= 10, events.py:179); count / minutes x 90 (player_season.py:134) |
| progressive_passes_p90 | — | completed passes moving the ball >= 15m toward goal (events.py:150); count / minutes x 90 (player_season.py:134) |
| passes_into_final_third_p90 | — | completed passes from own two-thirds (start_x < 80) ending in the final third (end_x >= 80) (events.py:152); count / minutes x 90 (player_season.py:134) |
| passes_p90 | — | count of all Pass events, completed or not (events.py:139); count / minutes x 90 (player_season.py:134) |
| dribbles_completed_p90 | — | Dribble events with outcome "Complete" (events.py:173); count / minutes x 90 (player_season.py:134) |
| np_goals_p90 | Non-penalty goals | Shot events with outcome "Goal", excluding penalties (events.py:166-169); count / minutes x 90 (player_season.py:134) |
| xg_p90 | — | sum of statsbomb_xg over ALL shots including penalties (events.py:163); count / minutes x 90 (player_season.py:134) |
| gk_saves_p90 | — | Goal Keeper events whose type contains "Saved" (Shot/Penalty Saved, Saved To Post; events.py:195-198); count / minutes x 90 (player_season.py:134) |
| save_pct | Save% | gk_saves / (gk_saves + goals conceded while the team's main goalkeeper) (player_season.py:138-142) |

### D. SKILLCORNER physical — 24 metrics

*Defined in `skillcorner_map.py` (definitions) + `skillcorner_api.py` (pull).*

| Metric | Club stat | How it is produced (exact) |
|---|---|---|
| distance_p90 | Total distance covered per match (m) | per-match average from SkillCorner column total_distance_full_all |
| meters_per_minute | Metres per minute (work rate) | per-match average from SkillCorner column total_metersperminute_full_all |
| running_distance_p90 | Running distance, 15-20 km/h (m) | per-match average from SkillCorner column running_distance_full_all |
| hsr_distance_p90 | High-speed-running distance, 20-25 km/h (m) | per-match average from SkillCorner column hsr_distance_full_all |
| sprint_distance_p90 | Sprint distance, >25 km/h (m) | per-match average from SkillCorner column sprint_distance_full_all |
| hi_distance_p90 | High-intensity distance (m) | per-match average from SkillCorner column hi_distance_full_all |
| hsr_count_p90 | High-speed-running efforts | per-match average from SkillCorner column hsr_count_full_all |
| sprint_count_p90 | Sprint efforts | per-match average from SkillCorner column sprint_count_full_all |
| hi_count_p90 | High-intensity efforts | per-match average from SkillCorner column hi_count_full_all |
| cod_count_p90 | Changes of direction | per-match average from SkillCorner column cod_count_full_all |
| psv99_kmh | Peak sprint speed, 99th percentile (km/h) | per-match average from SkillCorner column psv99 |
| top5_psv99_kmh | Peak sprint speed, average of top 5 (km/h) | per-match average from SkillCorner column psv99_top5 |
| medium_accel_count_p90 | Medium accelerations | per-match average from SkillCorner column medaccel_count_full_all |
| high_accel_count_p90 | High accelerations | per-match average from SkillCorner column highaccel_count_full_all |
| medium_decel_count_p90 | Medium decelerations | per-match average from SkillCorner column meddecel_count_full_all |
| high_decel_count_p90 | High decelerations | per-match average from SkillCorner column highdecel_count_full_all |
| explosive_accel_to_hsr_p90 | Explosive accelerations leading into high-speed running | per-match average from SkillCorner column explacceltohsr_count_full_all |
| explosive_accel_to_sprint_p90 | Explosive accelerations leading into a sprint | per-match average from SkillCorner column explacceltosprint_count_full_all |
| time_to_hsr **[lower = better]** | Time to reach high-speed running, top-3 avg (s) | per-match average from SkillCorner column timetohsr_top3 |
| time_to_hsr_post_cod **[lower = better]** | Time to HSR after a change of direction, top-3 avg (s) | per-match average from SkillCorner column timetohsrpostcod_top3 |
| time_to_sprint **[lower = better]** | Time to reach sprint, top-3 avg (s) | per-match average from SkillCorner column timetosprint_top3 |
| time_to_sprint_post_cod **[lower = better]** | Time to sprint after a change of direction, top-3 avg (s) | per-match average from SkillCorner column timetosprintpostcod_top3 |
| agility_505_90 **[lower = better]** | 505 agility test, 90-degree turn (s) | per-match average from SkillCorner column timeto505around90_top3 |
| agility_505_180 **[lower = better]** | 505 agility test, 180-degree turn (s) | per-match average from SkillCorner column timeto505around180_top3 |

### Overlap resolution (who wins when two sources could supply the same metric)

| Metric | Winner | Superseded |
|---|---|---|
| goals_p90 | impect | statsbomb_computed |
| np_xg_p90 | impect | statsbomb_computed |
| shots_p90 | impect | statsbomb_computed |
| assists_p90 | impect | statsbomb_computed |
| xa_p90 | impect | statsbomb_computed |
| key_passes_p90 | impect | statsbomb_computed |
| passes_completed_p90 | impect | statsbomb_computed |
| passes_into_box_p90 | impect | statsbomb_computed |
| pass_completion_pct | impect | statsbomb_computed |
| pressures_p90 | impect | statsbomb_computed |
| dribbles_p90 | statsbomb_advanced | statsbomb_computed |
| dribble_success_pct | statsbomb_advanced | statsbomb_computed |

## 4. Club framework → Impect mapping (finalized with the club)

The club's positional framework was written in the StatsBomb era. As the platform moves to
Impect, each club metric maps to an Impect equivalent, a verified Impect **successor**, or
the **closest alternative** where no exact twin exists. Guiding rule (confirmed with the club):
**every substitute is labelled by what it actually is** — its true Impect concept plus the
StatsBomb stat and definition it replaces — so nothing is dressed up as a stat it is not.

### 4a. Live now (already feeding Quality/Fit)

These successors are computed today and shown, with their StatsBomb lineage, in the
dashboard **Glossary** and score panels. See `docs/methodology.md` §3 for the table and
`SUCCESSOR_LINEAGE` / `IMPECT_SUCCESSOR` in the code.

### 4b. Agreed for the scoring rewire (verified against the Impect glossary; not yet live)

Confirmed with the club; these land when the scores are rewired to the club's per-position lists
(a separate, validated pass — the pipeline is re-run at that point). Each is glossary-verified.

| Club metric (StatsBomb) | Decision | Impect column(s) |
|---|---|---|
| Goalkeeper Aggressive Distance | Replace with **defensive touches outside the box** | `DEFENSIVE_TOUCHES − DEFENSIVE_TOUCHES_IN_PITCH_POSITION_OWN_BOX` |
| Claims ("caught balls") | Closest alternative — **catches**, labelled as such | `BALL_WIN_NUMBER_BY_ACTION_CATCH` |
| Pressured Pass% | Closest alternative — **bypassed opponents** (every position) | `BYPASSED_OPPONENTS` |
| (all positions) | Add **ball wins** | `BALL_WIN_NUMBER` |
| (all positions) | Add **counterpressure** | `NUMBER_OF_PRESSES_COUNTER_PRESS` |
| Goalkeeper crossing | Add **high cross / low cross** | `..._BY_ACTION_HIGH_CROSS`, `..._BY_ACTION_LOW_CROSS` |
| Dribble Success | Map to **dribble & carry value**, plus list all alternatives | `PXT_DRIBBLE` (+ `BYPASSED_OPPONENTS_NUMBER_BY_ACTION_DRIBBLE`, `BYPASSED_OPPONENTS_BY_ACTION_DRIBBLE`, `DISTANCE_TO_GOAL_COVERED_DRIBBLE`) |
| Dribble Attempts / Dribbles | Include the **actual count** | `BYPASSED_OPPONENTS_NUMBER_BY_ACTION_DRIBBLE` |

Note on the GK sweeper metric: Impect has no tracking-based "distance from goal", but it
does scope defensive touches by pitch position, so *defensive touches outside the own box*
(`DEFENSIVE_TOUCHES` minus `DEFENSIVE_TOUCHES_IN_PITCH_POSITION_OWN_BOX`) is a genuine
event-data proxy for sweeper-keeper behaviour.

---

## 5. Medical dimension: injury history and availability

**Status: the code path is built, wired into the pipeline, and the real scrape has completed
and been loaded (11 Aug 2026).** `player_injuries` holds production data for the EFL today.
**This section covers the injury data and the availability calculation only — Medical is not
yet wired into the composite score** (that is a later plan item, R3 in `plan/BUILD_PLAN.md`).

**Source: one Transfermarkt page per player** — `/verletzungen/spieler/<id>`, the injury
history page, a stable six-column table (`Season | Injury | from | until | Days | Games
missed`). `src/lofc/ingest/transfermarkt_injuries.py` parses it; `src/lofc/store/injuries.py`
loads the result into the `player_injuries` table, joining on `players.tm_player_id`
(populated by the Identity step — see below).

**Deliberately one page, not two.** The Transfermarkt appearance page (`/leistungsdaten/`)
was evaluated as an alternative/supplement and rejected: its columns shift between
competition types (cup vs league vs continental rows do not line up), and its header row is
a sort link rather than plain labels — parsing squad-level appearance counts off it would be
brittle in a way the injury-history page is not. `games_missed` from the injury page is all
the availability formula needs.

**Availability formula** (`src/lofc/model/medical.py`):

```
availability = 1 - (games missed through injury / scheduled games)
```

Only games missed **through injury** count against a player — being fit but unselected
(squad rotation, tactical benching) is not a penalty. The window is the **prior two
seasons, 92 scheduled games** (46 games/season × 2, for the Championship, League One,
League Two and National League). The club's stated minimum standard is 60% availability
over that window.

**Why not derive availability from minutes played** (the obvious proxy, and rejected):
**73% of rankable 2025/26 players fall below a 60% bar on minutes / (46 × 90)**. That bar
mostly measures squad rotation and positional competition, not fitness — a fit player who
started half his club's games would fail it. Injury-history-based availability answers the
actual medical question; minutes played does not.

**Coverage limit:** EFL only (Championship, League One, League Two, National League — the
four leagues with a `SCHEDULED_GAMES` constant), and only players carrying a
`tm_player_id`. The Scottish Premiership, Scottish Championship and Premier League 2 are not
scraped at all today and have no scheduled-games constant, so `availability()` returns
`None` for them rather than a guessed figure. Within the EFL, `tm_player_id` coverage rose
sharply after a Task 0 fix that stopped discarding a player's Transfermarkt identity when he
had no market value on file (see `plan/BUILD_PLAN.md`'s Pending work register for the exact
before/after numbers), and further after the 11 Aug 2026 scrape refresh. **2025/26
`tm_player_id` coverage:** Championship 730/748 (98%), League Two 714/745 (96%), League One
715/749 (95%), National League 711/769 (92%); the non-EFL leagues remain low (Premier League 2
16%, Scottish Premiership 7%, Scottish Championship 3%) and are out of scope for this dimension
until R6 (`plan/BUILD_PLAN.md`) extends the squad scrape.

**Current data state (11 Aug 2026, final run):** the real scrape
(`lofc.ingest.transfermarkt_injuries`) has completed against the refreshed player list —
**3,930 injury rows written to `data/reference/transfermarkt/injuries.csv`, 0 failed, 3,507
player pages fetched.** Loaded into Postgres: **3,766 rows for 1,176 players** (the gap to
3,930 is rows whose Transfermarkt id matches no player we hold metrics for — dropped, not
guessed). All rows carry `source = 'transfermarkt'`; the loader always clears existing
`source = 'transfermarkt'` rows before inserting, so the earlier 5-player smoke-test load has
been replaced.

**Completeness check:** of 2,701 linked EFL players in 2025/26, **2,701 had their injury page
fetched — zero were never fetched.** This matters because an unfetched player would otherwise
silently read as 100% available; there is now no such ambiguity for the EFL.

**Injury category distribution** (3,766 rows), average matches missed / average days out:

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

The clinical ordering is a sanity signal: knee-ligament injuries cost by far the most time,
which is what you would expect if the parsing is correct. The `other` bucket is dominated by
phrasings genuinely outside the club's named categories — "unknown injury" (301), "Knock"
(153), "Ill" (85), "Corona virus" (68), "Foot injury" (66), "Shoulder injury" (61) — honestly
uncategorised rather than mis-parsed. Category does **not** affect availability, which counts
matches missed regardless of category.

**Availability, validated end to end on real data:** computed for **2,870** player-season rows
across the four EFL leagues; **77 fall below the club's stated 60% bar**; the most affected are
recognisable long-term-injured players (e.g. Charlie Wyke, 128 matches missed, availability
0.0).

**Open design question (not yet decided):** under the design spec's band formula
`band = 3 + 5 × (availability − 0.60)`, **2,201 of 2,870 (77%)** would score the maximum
Medical band of 5.0, because they had no injuries recorded in the two-season window. Medical
carries 13.6% of the outfield composite weight. Whether a *risk* dimension that awards
three-quarters of players an identical maximum is the intended behaviour is an open question
for the scout-assessment plan — recorded in `plan/BUILD_PLAN.md`, not answered here.
