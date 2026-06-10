# Methodology

How a player goes from raw match events to a ranked, affordable, on-profile recommendation,
and where statistics does the work versus where machine learning earns its place.

The guiding principle: percentile ranking and regression do the core work; scikit-learn is
used only where it is the right tool (the valuation regression and the archetype clustering).
No deep learning, because regression and clustering are correct here.

---

## 1. Aggregation and per-90 normalisation

Event data is rolled up to one row per player per league season. Counting stats are
converted to **per-90-minute** rates so a regular starter and a substitute are comparable.

- **Minutes** are derived from the line-up position spells, correctly handling the fact that
  the match clock resets at half-time (a naive subtraction would undercount players who span
  the interval by the first-half stoppage time).
- Players under **450 minutes** (about five full matches) are flagged as small samples and
  excluded from ranking, so a strong cameo cannot top a chart.

## 2. Normalisation within position and within league

A raw per-90 number is meaningless on its own: 2.5 tackles is excellent for a winger and
ordinary for a defensive midfielder. So each metric is converted to a **percentile rank
within the player's position group and league** (90th percentile = better than 90% of
positional peers). Comparing within league avoids treating a 90th-percentile Serie A striker
as identical to a 90th-percentile Premier League striker; cross-league comparison would need a
league-strength adjustment, which is a documented future extension.

## 3. Two scores: Performance and Fit

A single blended "good for us" number conflates two questions a recruiter actually asks
separately, so we produce two scores, both 0-100, ranked within position and league:

- **Performance** = how good the player is. The mean of their percentiles across a broad set
  of stats relevant to their role (equal weight). Objective, data only.
- **Fit** = how well the player matches the club's identity. The identity-weighted sum of
  their percentiles on the profile metrics.

A lethal finisher who never presses scores high on Performance but lower on Fit for a pressing
team. Keeping them separate makes that visible.

## 4. Archetypes (clustering by style)

Within each position, players are grouped by **playing style** using k-means:

1. Each player's percentiles are **centred on their own average** first, so the clustering
   captures *relative strengths* (what they do more of) rather than overall quality. Without
   this step, clusters would just separate good players from bad.
2. Correlated metrics are reduced with **PCA** (keeping ~90% of the variance).
3. k-means runs for several values of k; the number of clusters is chosen by the best
   **silhouette** score. A fixed random seed makes assignments reproducible.
4. Each cluster is labelled from the metrics on which it stands out most.

The grouping is fully data-driven; only the plain-English labels are interpretation. On real
data this reproduced the classic positional archetypes (ball-playing vs stopper centre-backs,
poacher vs link forwards) with no hand-labelling. Silhouette scores are modest (0.16-0.29)
because football styles are a continuum, not cleanly separated blobs. A soft-assignment model
(Gaussian mixture: "70% poacher, 30% presser") is the documented next step.

## 5. Valuation and the undervaluation score

The target is a player's **market value** (from Transfermarkt), which StatsBomb does not have.

- Target is **log(market value)**, because values are heavily skewed; predictions are
  back-transformed to euros.
- Features are the performance percentiles plus **age, minutes, position and league**.
  Age matters: omitting it would make the model read old players as "cheap".
- The model is **Ridge regression** (`RidgeCV`, regularisation chosen automatically) for
  interpretable, stable coefficients. Gradient boosting is the documented upgrade if a linear
  fit proves too weak.
- **Cross-validation** produces every player's fair value out-of-fold, so no player is priced
  by a model that trained on them. This is also the honest answer to "what is the test set":
  the players are split, and each player is held out exactly once.
- **Undervaluation = fair value minus actual market value.** A positive gap means the market
  prices the player below what their performance, age and position imply: a bargain.

Reported accuracy: cross-validated **R-squared about 0.51** on the log scale, median absolute
error about 1.9m euros. That is deliberately not inflated: on-ball performance, age, position
and league explain roughly half of market value; reputation, contract situation and potential
drive the rest. The undervaluation score is a guide, not a precise price.

## 6. Affordability and the final shortlist

Two gates decide whether a player is signable, both adjustable from the dashboard:

- **Fee gate:** real market value within a transfer budget.
- **Wage gate:** modelled weekly wage within the club's wage-framework ceiling for that
  position and age band. The estimate is a band (x0.7 to x1.4 around the central figure)
  rather than a point: a player passes if the LOW end fits the ceiling, and is flagged
  **wage-marginal** when the band straddles it, so borderline cases go to human judgement
  (a call to the agent) instead of being silently dropped.

A player must pass both gates **and** the position's on-profile minimum thresholds. Survivors
are ranked; if none qualify, the closest on-profile players are returned as near-misses so the
result is never empty.

The wage grid is league-aware (a League One wage differs from a Championship one) and each
league's anchors cite their published sources. The grid is validated in aggregate by
`python -m lofc.model.wage_check`, which sums modelled wages per squad and reconciles them
against published payrolls (all eight league-seasons within tolerance; Leyton Orient's own
modelled bill lands within ~10% of its published Capology figure). One anchor (Championship)
was corrected after this reconciliation flagged it, which is the calibration loop working
as designed.

---

## 7. Physical data (SkillCorner tracking)

The club provided a SkillCorner export for League One 2025/26: tracking-derived physical
output (distances, high-speed running, sprints, accelerations, peak speed). Its scope
defines exactly what it can and cannot do:

- **Player-level data covers the Leyton Orient squad only** (21 players with season
  averages, matched to our StatsBomb ids by birth date + name, 21/21 matched).
- **Team-level data covers all 24 League One clubs**, as whole-team totals.

So the platform uses it for two things, and refuses a third:

1. **League benchmarking** (team level): where LOFC ranks among the 24 clubs on each
   physical dimension — the objective picture of the team's physical identity.
2. **A measured draft identity** (player level): what the current squad actually does
   physically, presented as evidence for the Director of Football to confirm or
   override — it describes how the team plays today, not how it should play. Once
   confirmed, it informs which on-ball traits (which exist for every player in every
   league) the Fit score weights.
3. **It never scores recruitment targets.** No tracking data exists for non-LOFC
   players, so any per-candidate "physical score" would be invented. Physical
   assessment of targets stays with scouts, using the squad benchmarks as reference
   points.

---

## What is real, and what is a labelled stand-in (Phase 10: real EFL data)

| Input | Status | Notes |
|---|---|---|
| Player performance | **Real** | StatsBomb paid feed: Championship, League One, League Two, National League, 2024/25 + 2025/26 (4,456 matches) |
| Player ages | **Real** | birth dates from the paid-feed lineups (99.6% coverage) |
| Market values | **Real** | Transfermarkt club squad pages (current snapshot), matched by birth date + name; a maintained-dataset fallback catches loanees from outside these leagues |
| Wage framework (the club's ceiling) | **Stand-in** | anchored to the EFL 50%-of-turnover rule and LOFC's published turnover; position/age shape assumed |
| Player wages | **Stand-in (modelled)** | league x position x age x performance-tier grid with uncertainty bands; sources cited per league; validated against published payrolls; never derived from market value |
| Identity profile (what the club wants) | **Stand-in** | a constructed "hard-working, progressive, press-resistant" profile |

Every stand-in is an editable data file and swaps for the club's real document with no code
change.

## Honest limitations

- **Valuation covers 2025/26 only.** Scraped market values are a current snapshot, so only
  the season just played is priced; pricing 2024/25 output with 2026 values would be wrong.
  Earlier seasons keep scores and archetypes (trajectory) but no fair value.
- **National League players are not valued.** Transfermarkt maintains values for only ~2.5%
  of fifth-tier players, so the league appears in scores and archetypes but not in the
  value/bargain rankings, and its rare valued players carry extra uncertainty.
- **Value-match rate is ~85% in the valued leagues.** The unmatched are mostly January
  movers and short-stay loanees; they keep scores and archetypes but no valuation. Matching
  is by birth date + name with an implausible-age guard.
- **Event collection has small gaps at the bottom of the pyramid:** 19 of 4,456 fixtures
  (0.4%, almost all National League) have no event data on the feed, slightly undercounting
  a few players' season totals. Spot-checks against published top-scorer tables are exact in
  the Championship and League One, and within one goal elsewhere once playoff inclusion is
  accounted for (our totals include playoffs).
- **Candidate evaluation is on-ball only.** Event data does not see off-ball movement; the
  SkillCorner tracking data fills that gap for our own squad and for team-level league
  benchmarking, but not for recruitment targets (see section 7).
- **Modelled wages are a screening prior.** Real asking wages come from agents; the grid
  orders the queue and classifies affordable / marginal / out of reach.
