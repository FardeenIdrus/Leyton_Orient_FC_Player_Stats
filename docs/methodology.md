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
  position and age band.

A player must pass both gates **and** the position's on-profile minimum thresholds. Survivors
are ranked; if none qualify, the closest on-profile players are returned as near-misses so the
result is never empty.

---

## What is real, and what is a labelled stand-in

| Input | Status | Notes |
|---|---|---|
| Player performance | **Real** | StatsBomb open data, 2015/16 PL / La Liga / Serie A |
| Market values | **Real** | Transfermarkt, matched by name (~98%) |
| Player ages | **Real** | from Transfermarkt birth dates |
| Wage framework (the club's ceiling) | **Stand-in** | anchored to the EFL 50%-of-turnover rule and LOFC's published turnover; position/age shape assumed |
| Player wages | **Stand-in (modelled)** | from a position x age x performance-tier table; never derived from market value (a flat percentage would understate cheap players) |
| Identity profile (what the club wants) | **Stand-in** | a constructed "hard-working, progressive, press-resistant" profile |

Every stand-in is an editable data file and swaps for the club's real document with no code
change. See `scaling.md` for the path to real, current-season data.

## Honest limitations

- **Demo data is 2015/16 top-flight**, because Leyton Orient's division is not on the free
  StatsBomb tier. The method is league-agnostic; on this data the affordability filter is
  largely demonstrative (top-flight wages dwarf a League One ceiling), and it bites correctly
  on real lower-league data.
- **The wage framework is present-day** while the players are 2015/16, so we make no literal
  "could sign X for Y" claims; the years align on real current-season data.
- **On-ball events only.** Off-ball movement and positioning are not measured.
- **Name matching** across short names and full legal names leaves rare mismatches, caught by
  an implausible-age guard and logged; club-level disambiguation is the documented upgrade.
