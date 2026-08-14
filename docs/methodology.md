# Methodology

> **STATUS (2026-08-10): current. The LIVE modelling scores on Impect + SkillCorner (zero
> StatsBomb in scoring).** Players are ranked on the club's real recruitment framework as a **1–5
> composite** (see §3b); the old invented **Style-fit is retired**. 91 metrics/player across
> the sources. The composite is computed by a pipeline stage and stored in `player_scorecards`, so the
> dashboard, the offline shortlist and the BI layer read identical numbers. Metric provenance:
> **`docs/DATA_ARCHITECTURE.md`**. Sections 1–2 below (per-90
> normalisation, percentile ranking) are unchanged and still current; §3 describes the older
> Quality/Fit scores, now superseded by the club composite in §3b.

How a player goes from raw match events to a ranked, affordable, on-profile
recommendation, and where statistics does the work versus where machine learning
earns its place.

The guiding principle: percentile ranking and regression do the core work;
scikit-learn is used only where it is the right tool (the valuation regression and
the archetype clustering). No deep learning, because regression and clustering are
correct here.

Data basis: **Impect** event data across the EFL (Championship, League One, League Two,
National League), the Scottish Premiership & Championship, and Premier League 2 — plus
**SkillCorner** physical/tracking data (EFL + Premier League 2 + Scottish Premiership,
2025/26) and scraped Transfermarkt market values (EFL).

---

## 1. Aggregation and per-90 normalisation

Event data is rolled up to one row per player per league season. Counting stats are
converted to **per-90-minute** rates so a regular starter and a substitute are
comparable.

- **Minutes** are derived from the line-up position spells, correctly handling the
  fact that the match clock resets at half-time (a naive subtraction would undercount
  players who span the interval by the first-half stoppage time). Playoff matches are
  included, which explains one-goal differences against regular-season-only published
  tables.
- Players under **450 minutes** (about five full matches) are flagged as small
  samples and excluded from ranking, so a strong cameo cannot top a chart.
- A player who moves between tracked leagues mid-season holds **one row per league**,
  each judged on its own numbers. This is correct data, not duplication; every
  downstream view keys by player + league + season.
- **Validation:** season goal totals were spot-checked against published golden-boot
  tables — exact in the Championship and League One (e.g. the League One top scorer
  at 23), within one goal in League Two, and National League differences fully
  explained by playoff inclusion plus the feed's 19 uncollected fixtures (see
  Honest limitations).

## 2. Normalisation within position and within league

A raw per-90 number is meaningless on its own: 2.5 tackles is excellent for a winger
and ordinary for a defensive midfielder. So each metric is converted to a
**percentile rank within the player's position group and league** (90th percentile =
better than 90% of positional peers in that division). Comparing within league avoids
treating a 90th-percentile League Two striker as identical to a 90th-percentile
Championship striker; the dashboard's Compare view warns when players from different
leagues are compared, and the valuation model is where league level is actually
accounted for (league is a feature there).

**Within one season, too.** Scoring and ranking are done for a **single season at a time**
(a sidebar selector; the latest season, 2025/26, is the default). So a player appears once,
on that season's form, ranked against that season's peers, with that season's data coverage
(SkillCorner physical exists for 2025/26 only, so a 2024/25 view has no Physical dimension).
Earlier seasons stay fully available — switch the selector — and also drive the player
profile's **trajectory** chart (improving or declining across seasons). Mixing seasons in one
ranking would both duplicate players and compare last season's form against this season's,
so it is avoided.

## 3. Two scores: Quality and Fit (superseded — see §3b)

> **Superseded (2026-07-27).** The invented **Style-fit is retired**, and players are now
> ranked on the club's real framework — the **1–5 composite** in §3b — not on these two
> scores. This section is kept as history of the earlier approach. The composite's
> **Performance dimension** is the current "how good is he" number, measured on the club's
> chosen metrics rather than the generic list below.

A single blended "good for us" number conflates two questions a recruiter asks
separately, so we produce two scores, both 0–100, ranked within position and league:

- **Quality** = how good the player is. The mean of their percentiles across a broad
  set of stats relevant to their role (equal weight). Objective, data only.
- **Fit** = how well the player matches the club's identity. The identity-weighted
  sum of their percentiles on the profile metrics.

A lethal finisher who never presses scores high on Quality but lower on Fit for a
pressing team. Keeping them separate makes that visible. The identity weights are a
labelled stand-in until the club provides its real profiles (a CSV drop-in).

### Exactly which metrics build each score (full transparency)

Both scores are computed from an explicit, published stat list — nothing is hidden in a
black box. The dashboard makes this visible in two places: the **Methodology → "Exactly
which metrics build each score"** panel (pick any position) and a compact **"How Fit and
Quality are built"** expander on every player profile. The lists there are read straight
from the live model, so what is shown is what is computed.

- **Quality** is the equal-weight mean of the percentiles on a position's role stats
  (`ROLE_METRICS` in `score.py`, mapped to Impect successors in Impect-only mode).
- **Fit** is the weighted sum of the percentiles on the identity profile's stats
  (`identity_profiles` table), each stat's weight shown as its share of the score, with an
  optional minimum-percentile floor used later by the on-profile filter.

### Honest substitution (naming a stat for what it truly is)

The platform now scores on Impect. Where the club historically tracked a StatsBomb stat
that Impect has no exact twin for, we score on the nearest measured Impect concept — but we
**never relabel it as the StatsBomb stat**. Each substitute is named for what it actually
measures, and both the dashboard **Glossary** and the score panels show the StatsBomb stat
it stands in for and why. The live substitutions feeding the scores are:

| Shown as (Impect) | Stands in for (StatsBomb) | Why it is not a straight rename |
|---|---|---|
| Ground duels won | Tackles | Impect has no tackle count; won ground duels is the nearest measured concept. |
| Ball wins | Interceptions / Ball recoveries | Impect counts possession regains that remove an opponent, not raw interception/recovery events. |
| Bypassed opponents (packing) | Progressive passes | Counts opponents taken out of the game, not distance-based progressive passes. |
| Deep progressions | Passes into final third | Counts opponents bypassed into the final third, not passes played. |
| Dribble & carry value | Progressive carries / Dribbles completed | PxT carry value, not a 1v1 take-on count. |
| Goals saved above average | Saves | Impect has no save count; GSAA is the shot-value successor. |
| Shot stopping % | Save % | Quality of shot-stopping (GSAA share of post-shot xG faced), not save volume. |

The full club framework → Impect mapping (including the metrics agreed with the club for the
forthcoming scoring rewire) is recorded in `docs/DATA_ARCHITECTURE.md` §4.

### 3b. The club recruitment scorecard — how a player gets his 1–5 score

This is the heart of the platform. Every player is given a single **overall score from 1 to
5** — his *composite* — and the shortlist is ranked on it. The whole calculation is Leyton
Orient's own recruitment framework, taken straight from the club's two documents:

- **`Impect Data - Positional Metrics.xlsx`** — which stats matter for each position (its
  `Input` sheet → `PERFORMANCE_METRICS` in [`club_framework.py`](../src/lofc/model/club_framework.py)).
- **`LOFC - Position Archetype.docx`** — the seven areas a player is judged on, how much each
  area counts for each position (→ `DIMENSION_WEIGHTS`), the 1–5 scoring, and the "minimum
  standard" / "elite" bars.

The engine is [`scorecard.py`](../src/lofc/model/scorecard.py). Nothing here is a black box —
the dashboard shows every number below for every player, in the **Players** tab's grand table.

The club judges a player on **seven areas** ("dimensions"): **Performance** (his football stats),
**Physical** (how much ground he covers, from tracking data), **Psychological**, **Medical**,
**Financial** (can we afford him), and **Resale** (could we sell him on for a profit). Today the
platform scores the two that come straight from real match data — **Performance and Physical** —
plus, optionally, the two money areas from a model. Psychological and Medical are left for a
scout to type in. Here is exactly how the score is built, step by step.

---

**Step 1 — Collect the player's stats, per 90 minutes.** For his position, the club lists the
stats that matter (for a full back: tackles-and-duels, crosses, assists, expected goals, passing,
ball retention, and so on). Each is expressed *per 90 minutes* so a regular starter and a
squad player are compared fairly (see §1).

**Step 2 — Turn each stat into a rank out of 100 (a "percentile").** A raw number like "0.24
assists per 90" means nothing on its own. So each stat is compared against every other player in
the *same position and same league this season*, and turned into a rank from 0 to 100:

- **90 means "better than 90% of his positional rivals"** on that stat; 50 means bang average
  (the league median); 10 means only 10% are worse.
- For most stats, higher is better. For a few, **lower** is better — for example *turnovers*
  (losing the ball). Those are flipped, so that a low turnover count correctly gives a *high*
  rank. (The flipped stats are listed in `LOWER_IS_BETTER`.)

**Step 3 — Turn each rank into a score from 1 to 5 (the "band").** This is where the club's own
bar comes in. The club document says the **league median is the minimum acceptable standard**,
and the **70th percentile is elite**. We anchor the 1–5 scale on exactly those two points:

> **band = 3 + (rank − 50) ÷ 20**, then capped so it never goes below 1 or above 5.

That gives a simple, honest conversion — no arbitrary cut-offs:

| Rank (percentile) | 1–5 band | Meaning (the club's words) |
|---|---|---|
| 10 | 1.0 | Well below standard |
| 30 | 2.0 | Below standard (this is the "veto" line) |
| **50 (median)** | **3.0** | **Minimum standard** |
| **70** | **4.0** | **Elite** |
| 90 | 5.0 | Well above elite |

So a player who is exactly league-average on a stat scores 3.0 on it; a genuinely elite one scores 4.0+.

**Step 4 — Average the stats in each area to get that area's 1–5 score.** For the Performance
area, we take the 1–5 band of every one of his performance stats and simply average them (each
stat counts equally — the club lists them as a flat set of "key indicators", so we add no hidden
preference). Two honest housekeeping rules:

- **A stat with no data simply drops out** of the average — it never drags the score down. (A
  player missing, say, crossing data is judged on the stats we *do* have.)
- **The same underlying measurement is only counted once.** The club sometimes lists two stats
  that Impect measures with a single number; we de-duplicate so it isn't double-weighted.

The Physical area works the same way, averaging his eight tracking stats (distance, high-speed
running, sprints, top speed, etc.).

**Step 5 — Combine the areas into the overall composite, using the club's weights.** The club
weights the areas differently per position. For an outfielder the club's weights are Performance
40%, Physical 30%, Psychological 10%, Medical 15%, Financial 10%, Resale 5%. We take a weighted
average of the area scores. **If an area has no data** (e.g. a player with no market value, so no
Financial score), it is left out and **the remaining weights are rescaled to fill the gap** — so
that player still gets a fair composite and stays in the ranking, rather than being penalised for
missing data.

**Step 6 — Two composites, so modelled money never quietly moves the rankings.** We publish two:

- **Objective composite (the default ranking)** — Performance + Physical only. 100% real match
  and tracking data. This is what the shortlist sorts on.
- **Full composite (opt-in)** — the same, plus the two **modelled** money areas (Financial +
  Resale, computed in [`financial_resale.py`](../src/lofc/model/financial_resale.py) and clearly
  labelled as estimates). It only appears when you tick **"Show affordability"** in the sidebar.

**The money areas, briefly (both modelled, both 1–5).** Each blends two signals, each ranked
0–100 within position + league, averaged, then banded exactly as in Step 3:

- **Financial Fit** = **wage headroom** (how far under our wage ceiling his modelled wage sits —
  cheaper is better) **+ undervaluation** (how far below his Transfermarkt fair value he is priced
  — a bigger bargain is better).
- **Resale Potential** = **youth** (younger = more years to sell him on) **+ market value** (a
  more valuable asset resells better).

Both rely partly on *modelled* inputs (a modelled wage, a modelled wage ceiling), so Financial is
the softest number on the platform, and both are computed **only for EFL-priced players** (Scottish
and PL2 players have no market value, so they simply rank on Performance + Physical). They will
firm up when the club's real wage framework is loaded. Like every dimension, both money bands are
**ranked within one season** (position + league + season) — never pooling 2024/25 with 2025/26.
Market values exist for 2025/26 only, so 2024/25 has no money layer at all.

**The "do not proceed" and "veto" flags are advisory — they never remove anyone.** The club
document says *composite below 3.0 = do not proceed* and *any single area below 2.0 = automatic
veto*. The platform shows these as flags, for honesty, but **never drops a player** because of
them — every league's players stay in the list, and any filtering is opt-in.

---

#### A worked example: one real full back, every number

Here is the full calculation for a real player — **Fraser Murray, full back, League One,
2025/26** — exactly as the engine computes it. (The dashboard shows this same breakdown for
every player.)

**His Performance stats → rank → 1–5 band** (a selection of his 22 scored stats; each ranked
against League One full backs):

| Stat (per 90) | His value | Rank /100 | 1–5 band |
|---|---|---|---|
| Expected assists | 0.20 | 100 | 5.00 |
| Passes into the box | 2.07 | 99 | 5.00 |
| Non-penalty expected goals | 0.11 | 97 | 5.00 |
| Assists | 0.24 | 93 | 5.00 |
| Cross completion (bypassing opponents) | 2.92 | 86 | 4.79 |
| Pressures | 17.6 | 76 | 4.32 |
| Counterpressures | 2.09 | 65 | 3.75 |
| Deep progressions | 8.61 | 52 | 3.09 |
| Ball-carry value | −0.005 | 50 | 3.00 |
| Ground-duel win % | 50% | 36 | 2.29 |
| Pass completion % | 59% | 15 | 1.25 |
| Turnovers *(lower is better → flipped)* | 22.8 | 10 | 1.02 |
| Aerial win % | 33% | 8 | 1.00 |

**Average of all 22 performance bands → Performance = 3.60.** The story is visible in the
numbers: elite attacking output (assists, expected goals, crossing all 5.0) dragged back toward
average by weak aerials and ball retention (1.0–1.3). Equal weighting keeps that honest — it
doesn't let his best stats hide his worst.

**His Physical stats → 1–5 band** (all eight, ranked against League One full backs):

| Stat (per 90) | Rank /100 | 1–5 band |
|---|---|---|
| Total distance | 93 | 5.00 |
| High-speed-running count | 98 | 5.00 |
| High-speed-running distance | 97 | 5.00 |
| Sprint count | 95 | 5.00 |
| Sprint distance | 93 | 5.00 |
| Metres per minute | 87 | 4.83 |
| Top-5% peak speed | 84 | 4.68 |
| Peak speed | 76 | 4.30 |

**Average of the eight physical bands → Physical = 4.85.** A relentless, high-output athlete.

**Combine into the composite.** Full-back weights (the club's 40/30, rescaled to the two areas
present): Performance 0.3636, Physical 0.2727.

> Objective composite = (3.60 × 0.3636 + 4.85 × 0.2727) ÷ (0.3636 + 0.2727) = **4.14**

That **4.14** is his headline score and where he sits in the ranking — a strong attacking,
high-running full back, held just short of the very top by his defensive and passing numbers.
No veto flag fires (no area is below 2.0) and he is well above the 3.0 minimum. *(He has no
market value entry, so the money areas drop out and his Full composite equals his Objective
composite; a player with money data would see the two differ.)*

---

**Five judgement calls** the club documents left open were settled objectively from the club's
own numbers (and are documented in the code and the dashboard): (1) each stat counts equally
within its area; (2) the median→3.0 / 70th→4.0 band anchoring above; (3) a goalkeeper has no
separate Physical area — it folds into Performance; (4) the money areas are modelled and clearly
labelled, the two human areas are scout-entered, and the composite is shown in the two honest
tiers above; (5) the club's outfield weights add up to 110% in the document, so each position is
rescaled to 100% (which preserves the club's intended relative emphasis exactly).

### 3c. Archetype lens (optional, opt-in)

Some positions have **archetypes** — sub-profiles that score the Performance dimension on a
*subset* of the position's metrics, so a recruiter can rank players **as a specific type**
(e.g. an *Attacking* full-back vs a *Progressive Build & Recovery* full-back). An archetype =
the full metric list **minus** the capabilities its column drops in the club's positional
workbook; the dimension weights and Physical are unchanged. Defined in `ARCHETYPE_DROPS`
(`club_framework.py`).

- **Full Back** — *All Metrics* (default) · *Attacking* (drops deep-defending) · *Progressive
  Build & Recovery* (drops attacking/carrying). **Winger** — *All Metrics* · *Direct & 1v1*
  (drops safe-possession + crossing) · *Crossing & Creative* (drops solo carrying).
- **Default is "All Metrics"** (the full-profile composite); the archetype is opt-in via a
  sidebar selector, and when chosen the **all-round composite stays visible alongside** the
  archetype score, so there is never a hidden "which number is real".
- **Deliberately not invented:** midfield's three club archetypes are genuinely different
  lists the workbook does not fully specify, so they are left to the club's per-archetype
  lists rather than fabricated; goalkeepers, centre-backs and centre-forwards have a single
  club profile by design.
- *Note:* this is a **scoring lens** ("rank the best attacking full-back"), distinct from the
  data-driven **playing-style clusters** in §4 ("what style does the data say he plays?").

## 4. Playing styles (clustering)

Within each position, players are grouped by **playing style** using k-means:

1. Each player's percentiles are **centred on their own average** first, so the
   clustering captures *relative strengths* (what they do more of) rather than
   overall quality. Without this step, clusters would just separate good players
   from bad.
2. Correlated metrics are reduced with **PCA** (keeping ~90% of the variance).
3. k-means runs for several values of k; the chosen k is **the largest within 0.02
   silhouette of the best**, so a position gets a third style only when the data
   genuinely supports one. On the EFL data this gives centre-forwards and attacking
   midfielders three football-sensible styles each; other positions honestly stay
   at two. A fixed random seed makes assignments reproducible.
4. Each cluster is labelled from the metrics on which it stands out most.

The grouping is fully data-driven; only the plain-English labels are interpretation.
Silhouette scores are modest because football styles are a continuum, not cleanly
separated blobs. A soft-assignment model (Gaussian mixture: "70% goalscorer, 30%
presser") is the documented next step.

> **Scope note (honest).** Unlike the scored dimensions, the style clustering is the one place that
> still **pools both seasons** and reads the older StatsBomb-era metric table (`player_season_metrics`
> / `ROLE_METRICS`) rather than the Impect neutral layer. The resulting label is stored per
> season-row (so a player's two seasons can carry different labels), and it is **only a style tag** —
> it never enters the 1–5 composite or the ranking. Moving it to within-season Impect clustering is a
> tracked roadmap item.

## 5. Valuation and the undervaluation score

The target is a player's **market value** (Transfermarkt), which StatsBomb does not
carry. Values for the four covered leagues are scraped from Transfermarkt's detailed
club squad pages (2,620 players, 96 clubs), which also supply date of birth, contract
end, preferred foot, height and the TM profile id.

### Matching a StatsBomb player to his Transfermarkt value

The paid feed's lineups carry birth dates, so matching is **birth date + name**, in
four stages (each tried only if the previous found nothing):

1. **In-league, DOB + name** — exact birth date within the player's own league, plus
   a fuzzy name check (namesakes with the same birthday are the reason the name check
   exists at all).
2. **In-league, name only** — for the rare player without a birth date; a name match
   that *contradicts* a known birth date is rejected as a different player.
3. **Cross-league, DOB + name** — a loanee's Transfermarkt value is listed under his
   **parent club**, which can be in a different division from where he is playing
   (e.g. a Championship club's forward on loan in League One). This stage searches
   all four scraped leagues. It caught 122 players the league-scoped stages missed.
4. **Maintained-dataset fallback** — loanees from *outside* the four leagues and
   January arrivals, matched DOB + name against a maintained public dataset, keeping
   only rows whose value was updated this season.

Guards: implausible ages (outside 16–38) are rejected and logged; unmatched players
are listed, not silently dropped. Current match rate: **1,643 of 2,291 rankable
2025/26 players valued (71.7%)**; the unmatched are dominated by National League
players (see below) and short-stay January movers.

### The model

- Target is **log(market value)** (values are heavily skewed); predictions are
  back-transformed to euros.
- Features are the performance percentiles plus **age, minutes, position and
  league**. Age matters: omitting it would make the model read old players as
  "cheap". League matters: it is how a Championship number and a League Two number
  live in one model honestly.
- The model is **Ridge regression** (`RidgeCV`, regularisation chosen automatically)
  for interpretable, stable coefficients. Gradient boosting is the documented upgrade
  if a linear fit proves too weak.
- **Cross-validation** produces every player's fair value **out-of-fold**, so no
  player is priced by a model that trained on him. This is also the honest answer to
  "what is the test set": every player is held out exactly once.
- **Undervaluation = fair value minus actual market value.** A positive gap means the
  market prices the player below what his output, age, position and league imply.
- **Two eras never mix.** The original 2015/16 demo data and the current EFL data
  train as separate models; and because scraped values are a *current snapshot*, only
  the season just played (2025/26) is priced — pricing 2024/25 output with 2026
  values would be dishonest. Earlier seasons keep scores and styles (trajectory) but
  no fair value.

### How reliable is the fair value? (measured, not asserted)

Headline: cross-validated **R² ≈ 0.745** on the log scale, median absolute error
≈ €160k. But the headline flatters, and the per-league breakdown is the honest
picture (out-of-fold error on the current build):

| League | n valued | median abs error | median abs % error | log-correlation |
|---|---|---|---|---|
| Championship | 554 | €940k | 49% | 0.75 |
| League One | 531 | €140k | 43% | 0.60 |
| League Two | 500 | €60k | 37% | 0.62 |
| National League | 58 | €92k | 75% | 0.06 |

- Much of the pooled R² is the **league feature** correctly separating four price
  tiers — the model knowing a Championship player outprices a League Two one.
- **Within a league, the ordering is real** (log-correlation 0.6–0.75): "this player
  is priced below peers with his output" is a trustworthy signal.
- **The point estimate is not a price.** Typical error is ~±40% within a league, and
  worst for cheap players, where Transfermarkt values are coarse (€25k steps, floor
  values that ignore output).
- Reputation, contract situation, potential and selling-club leverage drive prices
  and are not in the features; that — not sample size — is the accuracy ceiling.

**So the platform treats fair value as a screening and ranking signal: it orders the
queue and flags mispricing. It is not a fee quote.** This framing appears wherever
the number is shown.

## 6. Affordability and the final shortlist

Two gates decide whether a player is signable, both adjustable from the dashboard:

- **Fee gate:** real market value within a transfer budget.
- **Wage gate:** modelled weekly wage within the club's wage-framework ceiling for
  that position and age band. The estimate is a band (×0.7 to ×1.4 around the central
  figure) rather than a point: a player passes if the LOW end fits the ceiling, and
  is flagged **wage-marginal** when the band straddles it, so borderline cases go to
  human judgement (a call to the agent) instead of being silently dropped.

A player must pass **both affordability gates — and nothing else.** The old
identity-profile "on-profile" minimum-percentile gate is **retired**: the platform ranks
everyone on the club framework and never excludes a player on a quality threshold (the club's
own "< 3.0 = do not proceed" and "< 2.0 = veto" rules are advisory flags on the scorecard, not
filters). Survivors are ranked on the club's **objective composite**; if none qualify, the best
players by composite are returned as near-misses so the result is never empty.

**Both the dashboard and the offline shortlist rank on the same number.** The composite is
computed once by a pipeline stage (`model/scorecard_run.py`) and persisted to
`player_scorecards` — one row per player-season per archetype, with the objective and full
composites in separate columns. The stored `shortlists` table and the BI layer then read that
table, so there is no second, divergent ranking anywhere. (Before this, the offline shortlist
still ordered players by the retired Style-fit while the dashboard used the composite.)

### The contract-expiry filter (the free-transfer market)

A sidebar **Contract expiry** control filters to the out-of-contract market — *Any* (default),
*Out of contract summer 2027*, *summer 2028*, or *Contract already expired (free agents)*.

Three deliberate design points, each forced by what the data actually says:

- **No "January" option, on purpose.** English contracts effectively all end on 30 June — of the
  1,381 expiry dates we hold, **1,377 are June, 4 are May, and none are January**. A literal
  "expiring by January" filter would therefore return only deals that had *already lapsed* the
  previous summer: a misleading control. The January window matters because a player whose deal
  ends in summer is inside his **final six months** from that January — which is the same set as
  the summer horizon, and is read off the **Months left** column (≤ 6).
- **A forward horizon means "still under contract today, expiring by the cutoff."** Without that
  lower bound, "summer 2027" would also sweep in every contract that ran out in 2026 (447 rows on
  the current data) — players who have already left.
- **An unknown expiry date is excluded, but counted and shown.** Contract dates come only from the
  Transfermarkt scrape, so coverage is ~60–67% in the top three EFL divisions and **2–5% in the
  Scottish leagues, PL2 and the National League**. Silence would read as "nobody there is
  expiring", when the truth is "we do not know", so the Players tab states how many were hidden.

**The data is a dated snapshot, not a live feed.** The UI shows "Contract data as of *<date>*"
whenever the filter is on. Refreshing it is one command
(`python -m lofc.ingest.transfermarkt_efl --force`, then `python -m lofc.model.valuation` to push
the dates onto `players`); no code changes. Impect — our event-data provider — supplies birth
date, birthplace and preferred foot, but **not** contract dates or height, so Transfermarkt
remains the only source for this.

The wage grid is league-aware (a League One wage differs from a Championship one) and
each league's anchors cite their published sources (e.g. League One ≈ £4.1k/wk
average, Capology n=640). The grid is validated in aggregate by
`python -m lofc.model.wage_check`, which sums modelled wages per squad and reconciles
them against published payrolls: all eight league-seasons within tolerance, Leyton
Orient's own modelled bill within ~10% of its published figure. One anchor
(Championship) was corrected −30% after this reconciliation flagged it — the
calibration loop working as designed.

---

## 7. Physical data (SkillCorner tracking)

The club provided a SkillCorner export for League One 2025/26: tracking-derived
physical output (distances, high-speed running, sprints, accelerations, peak speed).
Its scope defines exactly what it can and cannot do:

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

## What is real, and what is a labelled stand-in

| Input | Status | Notes |
|---|---|---|
| Player performance | **Real** | Impect event data — EFL, Scottish Prem/Champ, Premier League 2 |
| Player ages / bio | **Real** | birth dates from the paid lineups (99.6%); contract, foot, height from the TM scrape |
| Market values | **Real** | Transfermarkt squad pages (current snapshot), matched by birth date + name in four stages |
| Physical output | **Real, scoped** | SkillCorner: LOFC squad + 24-club team level only |
| Wage framework (the club's ceiling) | **Stand-in** | anchored to the EFL 50%-of-turnover rule and LOFC's published turnover; position/age shape assumed |
| Player wages | **Stand-in (modelled)** | league × position × age × tier grid with uncertainty bands; sources cited per league; validated against published payrolls; never derived from market value |
| Identity profile (what the club wants) | **Stand-in** | a constructed "hard-working, progressive, press-resistant" profile |

Every stand-in is an editable data file and swaps for the club's real document with
no code change.

## Honest limitations

- **Fair value is a screening signal, not a price.** Within-league point estimates
  carry ~±40% typical error (see section 5); the within-league *ordering* is the
  trustworthy part. Improving point accuracy needs new feature classes (contract
  length, potential), not more of the same data.
- **Valuation covers 2025/26 only.** Scraped values are a current snapshot; earlier
  seasons keep scores and styles (trajectory) but no fair value.
- **National League players are not valued.** Transfermarkt maintains values for only
  ~2.5% of fifth-tier players, and the measured log-correlation there (~0.06) confirms
  there is no usable signal; the league appears in scores and styles but not in the
  value rankings, and its rare valued players carry an uncertainty caption.
- **Value-match rate is ~72% of rankable players overall** (higher in the valued
  leagues); the unmatched are mostly National League players, January movers and
  short-stay loanees. They keep scores and styles but no valuation, and are therefore
  absent from the shortlist pool (which requires a value to rank affordability).
- **Event collection has small gaps at the bottom of the pyramid:** 19 of 4,456
  fixtures (0.4%, almost all National League) have no event data on the feed,
  slightly undercounting a few players' season totals.
- **Candidate evaluation is on-ball only.** Event data does not see off-ball
  movement; the SkillCorner data fills that gap for our own squad and for team-level
  benchmarking, but not for recruitment targets (section 7).
- **Modelled wages are a screening prior.** Real asking wages come from agents; the
  grid orders the queue and classifies affordable / marginal / out of reach.
