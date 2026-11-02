# Methodology

How a player goes from provider data to a 1–5 rating, a ranked list and an
affordability verdict. Every number below is computed by the code named alongside it;
the dashboard's **Methodology** and **What goes into each rating** pages show the same
rules. Where each metric comes from is documented in `docs/architecture.md`.

The guiding principle: percentile ranking within honest peer groups does the core work.
Machine learning is used in one place only, the market-value regression (§7).

---

## 1. Data basis

| Source | What it gives | Leagues | Seasons |
|---|---|---|---|
| **Impect** | Event data: the 32 Performance metrics, minutes, position, birth date, foot | Championship, League One, League Two, National League, Scottish Premiership, Scottish Championship, Premier League 2 | 2024/25, 2025/26, 2026/27 |
| **SkillCorner** | Tracking data: the 7 Physical metrics (and more for display) | The same, **except the Scottish Championship** | 2025/26, 2026/27 |
| **Transfermarkt** (scraped) | Market value, contract end, loans, injuries, height | Values used for the four English leagues | Values for 2025/26 only |

So a 2024/25 rating has no Physical part, and a Scottish Championship rating never has one.

## 2. One row per player, per league, per season

Each player gets one row per league season, built by `model/build_neutral.py` into
`player_metrics_neutral`. A player who moves between covered leagues mid-season has one
row per league, each judged on its own numbers.

**Minutes and per-90 rates (Impect).** Minutes are the real time a player was on the
pitch. Impect reports averages per match for each position he played; these are turned
back into season totals and divided by his minutes, then multiplied by 90
(`ingest/impect_translate.py`).

**Per-90 rates (SkillCorner).** SkillCorner's season figures for distances and effort
counts are averages **per appearance**, over whatever minutes he played in that
appearance. They are converted with `to_per90` (`ingest/skillcorner_map.py`):

> per-90 value = per-appearance value ÷ average minutes per appearance × 90

Without this, a starter would out-run a substitute simply by being on the pitch longer.
Metres per minute is already a rate, and the two top-speed measures are peaks, so those
three are left as they are.

**Position.** A player's position group is where he played the most minutes. Impect's ten
positions map to eight groups: Goalkeeper, Centre Back, Full Back (left or right wing-back
/ full back), Defensive Mid, Central Mid, Attacking Mid, Winger (left or right), Centre
Forward. Left and right are added together before choosing, so a player who split time
across both wings counts as a winger.

**The 450-minute floor.** Only players with **450+ minutes** (about five full matches) are
*rankable*. Below that a per-90 rate is noise: one goal in a 20-minute cameo reads as 4.5
per 90. The sidebar's minutes filter never goes below 450.

## 3. Percentiles: compare each player with his real peers

A raw per-90 number means nothing on its own: 2.5 tackles is excellent for a winger and
ordinary for a defensive midfielder. So every metric becomes a **percentile within the
same league, the same season and the same position group**, among rankable players
(`scorecard.metric_percentiles`).

The percentile is a **mid-rank**:

> percentile = (rank − 0.5) ÷ (number of players in the pool with a value for this metric) × 100

Ties share the average rank. The mid-rank puts the average percentile at exactly 50 in
every pool, whatever its size, so the league median really does sit at the club's
"minimum standard" (§4). The divisor counts only players who have that metric: a player
with no tracking data is not counted as the bottom of the Physical pool.

For **turnovers**, lower is better, so the percentile is flipped (100 − percentile). Every
other scored metric is higher-is-better.

Seasons are never mixed: each season is ranked against its own peers only.

## 4. The club scorecard: how a player gets his 1–5 rating

The framework is Leyton Orient's own, taken from two club documents: `Impect Data -
Positional Metrics.xlsx` (which metrics matter for each position) and `LOFC - Position
Archetype.docx` (the areas a player is judged on, their weights, and the 1–5 bars). It is
encoded in `model/club_framework.py` and computed by `model/scorecard.py`.

### Step 1 — the metrics

**Performance** uses the club's metric list for the position. Where the club names a
concept Impect does not measure directly, the nearest Impect measurement is used
(`CLUB_SUCCESSOR`), and the dashboard names it for what it actually measures. Some club
entries end up on the same Impect measurement (for example "counterpressures" and
"pressures in the opposition half" both resolve to counterpressures); that measurement
**counts once**. One club metric, long-ball %, has no Impect equivalent and is left out.

| Position | Performance metrics scored |
|---|---|
| Goalkeeper | 6 |
| Centre Back | 13 |
| Full Back | 22 |
| Defensive Mid | 16 |
| Central Mid (the club's box-to-box midfielder) | 20 |
| Attacking Mid | 21 |
| Winger | 21 |
| Centre Forward | 24 |

Across all positions that is **32 distinct Impect metrics**.

**Physical** uses the same **7 SkillCorner metrics** for every outfield position:
distance, high-speed-running count, high-speed-running distance,
sprint count, sprint distance, **average match top speed** (`psv99_kmh`) and **top speed
over his five fastest matches** (`top5_psv99_kmh`). Both speed measures are scored, each as
one of the seven.

Metres per minute is not scored: it is distance per 90 divided by 90 (correlation 0.999999 on
live data), so scoring both would count one measurement twice (owner decision 2026-11-02).
It stays on the platform as a display metric and a Players filter.

So the rating draws on **39 metrics: 32 Impect + 7 SkillCorner**.

The **"Top speed"** column on the Players page shows `top5_psv99_kmh`, the average of his
five fastest matches, in km/h. That column is display only; it is the same value that is
one of the seven Physical metrics, not an extra one.

### Step 2 — percentile to a 1–5 band

The club's document sets the **league median as the minimum standard** and the **70th
percentile as elite**. The band is a straight line through those two points:

> band = 3 + (percentile − 50) ÷ 20, kept between 1 and 5

| Percentile | Band | Meaning |
|---|---|---|
| 10 | 1.0 | Well below standard |
| 30 | 2.0 | Veto line |
| **50** | **3.0** | **Minimum standard (league median)** |
| **70** | **4.0** | **Elite** |
| 90+ | 5.0 | Top of the scale |

### Step 3 — average the bands in each area

**Performance** is a **weighted average** of its metrics' bands (since 2026-11-02). The club
tags each metric High, Mid or Low per position and per archetype (formula meeting, workbook
"Weightings to be assigned 5"); one weight per tier, each table summing to exactly 1
(`model/performance_weights.py`, which lists the five tables corrected to their tier ratios).
**Physical** is still a plain average: the club has not weighted it yet. A metric with no
value for this player drops out and the remaining weights are rescaled, rather than counting
as zero; the player card shows it as "No value". Dimension scores are rounded to two decimals.

### Step 4 — combine the areas

The club weights six areas. Its outfield weights add up to 110% in the document, so each
position is rescaled to 100%, which keeps the club's relative emphasis exactly:

| Area | Outfield (as written → rescaled) | Goalkeeper |
|---|---|---|
| Performance | 40% → 36.4% | 50% |
| Physical | 30% → 27.3% | none (folded into Performance, per the club's GK table) |
| Psychological | 10% → 9.1% | 20% |
| Medical Risk | 15% → 13.6% | 15% |
| Financial Fit | 10% → 9.1% | 10% |
| Resale Potential | 5% → 4.5% | 5% |

A composite is the weighted average of **the areas the player actually has**, with the
weights rescaled over those areas. A missing area never pulls a player down and never
removes him from the list.

### Step 5 — three composites, kept apart

| Composite | Areas | Use |
|---|---|---|
| **`objective_composite`** (shown as **Composite**) | Performance + Physical | **The ranking.** Real match and tracking data only. |
| `full_composite` | + Financial Fit + Resale Potential | Shown only with **Show affordability (modelled)** on. Never ranks. |
| `assessed_composite` (shown as **Scout-verified rating**) | Performance + Physical + Psychological + Medical Risk | Only when a scout has completed **both** Psychological and Medical. Never includes the money areas. |

For an outfielder with both data areas, the ranking therefore weights **Performance 57%
and Physical 43%** (36.4 and 27.3 rescaled to their total). An outfielder with no tracking
data, and every goalkeeper, is rated on **Performance alone**. Scout input never touches
`objective_composite`.

Psychological and Medical Risk are entered by scouts on a 1–5 scale. The Medical form
shows injury availability from Transfermarkt as evidence, but the band is the scout's.

### Step 6 — the club's gates are advisory flags

The club document says a composite below **3.0** means "do not proceed" and any single area
below **2.0** is an automatic veto. Both are computed (`below_min_composite`, `veto`) and
shown as flags, but **nobody is ever removed from the list** because of them. The veto
flag looks at every area the player has, including the modelled money areas; the
interface names which area tripped it, and only mentions the money areas when
affordability is switched on.

### Colours on screen

Rating cells on the Players page are shaded by the same thresholds
(`players.band_colour`): **below 2.0** red, **2.0 to under 3.0** amber, **3.0 to under 4.0**
light green, **4.0 and above** green.

### A worked example

**Fraser Murray, Full Back, Wigan Athletic, League One 2025/26** (4,092 minutes; 109 rankable
League One full backs). Recomputed from the current database.

A selection of his 22 Performance metrics:

| Metric (per 90) | Value | Percentile | Band |
|---|---|---|---|
| Expected assists | 0.20 | 99.5 | 5.00 |
| Passes into the box | 2.05 | 98.6 | 5.00 |
| Non-penalty xG | 0.11 | 95.9 | 5.00 |
| Assists | 0.24 | 93.1 | 5.00 |
| Pass value | 0.094 | 87.6 | 4.88 |
| Crosses (opponents bypassed) | 2.92 | 85.8 | 4.79 |
| Pressures | 17.6 | 74.8 | 4.24 |
| Deep progressions | 8.61 | 50.9 | 3.05 |
| Ground-duel win % | 50% | 36.2 | 2.31 |
| Pass completion % | 59% | 15.1 | 1.26 |
| Ball wins | 12.0 | 14.2 | 1.21 |
| Turnovers *(lower is better, flipped)* | 22.8 | 11.5 | 1.07 |
| Aerial win % | 33% | 7.8 | 1.00 |

Average of all 22 bands → **Performance 3.59**. Elite attacking output, pulled back by weak
aerial duels, ball wins and ball retention.

All seven Physical metrics:

| Metric | Value | Percentile | Band |
|---|---|---|---|
| High-speed-running distance (per 90) | 711 m | 93.9 | 5.00 |
| High-speed-running count (per 90) | 66.6 | 90.1 | 5.00 |
| Distance (per 90) | 10,184 m | 86.3 | 4.82 |
| Sprint count (per 90) | 14.0 | 85.4 | 4.77 |
| Sprint distance (per 90) | 255 m | 80.7 | 4.53 |
| Top speed, best 5 matches | 32.0 km/h | 81.1 | 4.56 |
| Average match top speed | 29.5 km/h | 75.0 | 4.25 |

Average → **Physical 4.70**.

> Composite = (3.59 × 0.3636 + 4.70 × 0.2727) ÷ (0.3636 + 0.2727) = **4.07**

He also has modelled money bands (Financial Fit 3.15, Resale Potential 3.62), so his
`full_composite` is 3.94. No area is below 2.0, so no veto.

## 5. Peer-pool floor: when a rating is not a ranking

A percentile is only as meaningful as the pool behind it. In a pool of three, whoever
happens to have played decides the order; a player alone in his pool takes the top
percentile on every metric and scores 4.90.

So a composite is **withheld from the ranked list** when fewer than
**`MIN_PEERS_FOR_RANKING` = 10** rankable players share its league + season + position pool
(`scorecard.pool_is_thin`). The number is still computed and stored. The Players page says
how many players were withheld and why; **Squads & loans** lists them with current-season
facts. The pool size is counted from the whole season's scorecards, so narrowing the
sidebar never makes a pool look thinner than it is.

A player's true standing ("8th of 13") is quoted only within his own pool
(`scorecard.rank_in_pool`). The Players list is sorted by composite across whichever leagues
are selected, and its first column is "#", not "Rank": a composite says how a player
compares within his own league, not across leagues.

## 6. Archetypes — "Rank as" in the sidebar (optional lens)

**Full Back** and **Winger** have archetypes. An archetype scores Performance on a
**subset** of the position's metrics, so a recruiter can rank players as a specific type.
Physical and the weights are unchanged. Defined in `ARCHETYPE_DROPS`
(`club_framework.py`); drops are matched on the underlying Impect metric, so a dropped
concept cannot survive under a second club name.

| Position | Archetype | Drops | Metrics left |
|---|---|---|---|
| Full Back | Attacking | Deep defending (tackles/interceptions, aerials, ball wins) | 19 |
| Full Back | Progressive Build & Recovery | Carrying, dribbling, crossing, box presence, xG | 16 |
| Winger | Direct & 1v1 Specialist | Safe possession and crossing | 17 |
| Winger | Crossing & Creative Threat | Solo ball-carrying | 20 |

The default is **All Metrics** (the full list). When an archetype is picked in the sidebar
("**Rank as**"), the list ranks on the archetype composite and the **All-round** composite
stays visible beside it. Other positions have a single club profile.

## 6b. Playing styles (labels, never ratings)

Each outfield player gets a **playing-style label** — how he plays, **not how well**. The
Head of Recruitment's 24 styles; rules in `model/styles.py`.

- **Signals** are what a player *attempts* and *where* he plays: pass attempts (successful +
  unsuccessful + neutral), shares of his own actions, touches and receptions by pitch zone,
  duels contested, presses. Quality is used only where no alternative exists, and declared:
  aerial duels **won** (Aerial) and **successful** dribbles (1v1 — Impect records no failed
  dribbles). Every other signal correlates under 0.3 with the Performance rating (2025/26).
- **Fit** for a style = the average percentile of its signals, against players in the same
  position, league and season (450+ minutes; pools under 10 get none). Defensive and central
  midfielders are compared together for style ("Central midfield") — Impect labels a
  two-man midfield as two defensive midfielders.
- **Label:** best fit ≥ 70 with no signal below 50 → **Strong** (e.g. "Playmaker"); best fit
  ≥ 50 otherwise → **Leans**; below 50 at every style → **No standout style**. Other Strong
  styles are added. Wingers are labelled twice: *where* (In behind · Pocket · Wide) and
  *what* (1v1 · Creator). Thresholds are fixed, so a label means the same for every user.

Shown as a Style filter in the sidebar, a Style column, a Style fit section on the player
card, and explained to recruiters on Reference → How playing styles work. Never read by the rating or the ranking. Team style influences receptions
(a winger in a direct side receives more in behind) — accepted.

## 7. Season shown

The Players page **opens on the newest season held, the one being played (2026/27)**
(`seasons.default_season_id`). Early in a season many pools are below the peer floor;
those players are withheld (§5) rather than the season being hidden. Earlier seasons stay
available from the selector and feed the player's trajectory chart.

## 8. Market value, Financial Fit and Resale Potential (modelled)

All money figures are **modelled estimates**. They appear only when **Show affordability
(modelled)** is on and never change the ranking.

### Fair value (`model/valuation.py`)

- Players are matched to their Transfermarkt value by birth date + name: first within their
  own league, then by name alone (rejected if it contradicts a known birth date), then
  across all scraped leagues (a loanee's value sits under his parent club), then against a
  maintained fallback file. Ages outside 16–38 are rejected as mismatches.
- **Only 2025/26 is valued**, and only in the Championship, League One, League Two and
  National League: scraped values are today's snapshot, and pairing them with another
  season's output would be wrong. 2024/25 and 2026/27 have no money layer.
- The model is a **ridge regression** predicting log(market value) from performance
  percentiles, age, minutes, position and league. Five-fold cross-validation produces
  every player's fair value **out of fold**, so no player is priced by a model that saw him.
- **Undervaluation = (fair value − market value) ÷ fair value.** Positive means the market
  prices him below what his output, age, position and league imply.

How reliable it is, measured on the stored out-of-fold values (1,467 valued players):

| League | Valued | Median abs. error | Median abs. % error | Log-correlation |
|---|---|---|---|---|
| Championship | 457 | €1.02m | 52% | 0.69 |
| League One | 503 | €140k | 41% | 0.56 |
| League Two | 450 | €61k | 34% | 0.51 |
| National League | 57 | €90k | 77% | −0.10 |

Pooled R² on the log scale is 0.71, but much of that is the model separating league price
levels. Within a league the ordering is moderately reliable; the point estimate is not a
price. In the National League there is no usable signal. **Fair value is a screening signal,
not a fee quote.**

### Financial Fit and Resale Potential (`model/financial_resale.py`)

Each blends two signals, each ranked 0–100 within league + season + position, averaged,
then banded with the same formula as §4:

- **Financial Fit** = wage headroom (how far his modelled wage sits under the wage ceiling)
  + undervaluation.
- **Resale Potential** = youth (younger is better) + market value (higher is better).

Players with no market value have no money bands; the areas drop out of
`full_composite` and the player is never excluded.

## 9. Affordability gates and the stored shortlist

With affordability on, two gates decide whether a player is **signable** (`constrain/filters.py`):

- **Fee gate:** market value ≤ the transfer budget set in the sidebar.
- **Wage gate:** modelled weekly wage within the wage-framework ceiling for his position and
  age band. The wage is a band from **×0.70 to ×1.40** of the central estimate. He passes if
  the **low** end fits, and is flagged **wage-marginal** if the band straddles the ceiling,
  so borderline cases go to a person rather than being dropped.

The wage estimate is a league × position × age × performance-tier grid anchored to
published league wage reporting (`store/reference_data.py`); it is never derived from
market value. Both the wage grid and the ceiling are stand-ins until the club's real wage
data is loaded.

Survivors are ranked on `objective_composite`, the same stored number the dashboard shows
(`player_scorecards`, written by `model/scorecard_run.py`). If nobody passes at a given
budget, the five best by composite are returned as near-misses.

## 10. Contract-expiry filter

The sidebar **Contract expiry** filter offers *Any*, *Out of contract summer 2027*,
*summer 2028*, and *Contract already expired (free agents)* (`seasons.contract_mask`).

- A forward horizon means **still under contract today and expiring by the cut-off**, so
  deals that have already ended are not swept in.
- There is no January option: of the 3,079 contract dates held, 2,981 end in May or June.
  A player whose deal ends in summer is in his final six months from January.
- An unknown contract date is excluded and the number hidden is shown. Coverage among
  rankable 2026/27 players runs from 63% (National League) to 93% (Championship), and is
  29% in Premier League 2.
- Contract data is a dated Transfermarkt snapshot, refreshed by hand; the page shows its
  date. Impect carries no contract data.

## 11. Not currently in use

**Style clusters (k-means).** The automatic grouping in `model/archetypes.py` is hidden
and superseded by the rule-based playing styles in §6b. It never fed the rating.

## Known limitations

- **Within-league only.** A composite compares a player with his own league's peers. There
  is no league-strength adjustment, so a 4.0 in League Two and a 4.0 in the Championship
  are not the same standard.
- **Early-season ratings are thin.** Small pools are withheld (§5); those that pass the
  floor still rest on fewer matches than a full season.
- **No physical data** for 2024/25 or the Scottish Championship; those ratings are
  Performance only.
- **Money is 2025/26 English leagues only**, and fair value is a screening signal with
  wide error (§8).
- **Event data is on-ball.** Off-ball work is seen only through the SkillCorner Physical
  metrics.
- **Modelled wages are a prior.** Real asking wages come from agents.
