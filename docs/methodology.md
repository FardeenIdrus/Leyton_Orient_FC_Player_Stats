# Methodology

> **What this is.** How a player goes from provider data to a 1–5 rating, a ranked list and
> (opt-in) an affordability verdict, plus the rules of the Club vs League One page. Every number
> is computed by the code named alongside it; the site's **What goes into each rating** page
> shows the same rules. **Current state (2026-11-16):** 39 scored metrics (32 Impect + 7
> SkillCorner), peer-pool floor of 10 with a midfield fallback pool, no league-strength
> adjustment. Where each metric comes from: `docs/architecture.md`.

The guiding principle: percentile ranking within honest peer groups does the core work.
Machine learning is used in one place only, the market-value regression (§8).

---

## 1. Data basis

| Source | What it gives | Leagues | Seasons |
|---|---|---|---|
| **Impect** | Event data: the 32 Performance metrics, minutes, position, birth date, foot | 25 competitions (`src/lofc/leagues.py`): the EFL (Championship, League One, League Two), National League, Scottish Premiership and Championship, Premier League 2, and 18 more added 2026-10-26 (e.g. Irish Premier Division, Ligue 2, Allsvenskan) | 2024/25 on; calendar-year seasons ("2026") file under the season starting that year |
| **SkillCorner** | Tracking data: the 7 Physical metrics (and more for display) | Championship, League One, League Two, National League, Premier League 2, Scottish Premiership, Irish Premier Division (`config.DEFAULT_SKILLCORNER_TARGETS`) | 2025/26, 2026/27 (Ireland: 2025, 2026) |
| **Transfermarkt** (scraped) | Market value, contract end, loans, injuries, height | Values used for the four English leagues | Values for 2025/26 only |

So a 2024/25 rating has no Physical part, and neither does any rating in a league SkillCorner
does not cover (the Scottish Championship and 17 of the 18 newer leagues): those are rated on
Performance alone.

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
per 90. The minimum-minutes filter never goes below 450.

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
(`CLUB_SUCCESSOR`), and the site names it for what it actually measures. Some club
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

The **"Top speed"** column on the Players page shows `top5_psv99_kmh` — SkillCorner's **PSV-99
Top 5**, the average of his five fastest matches, in km/h. It is the same value that is one of
the seven Physical metrics, not an extra one. SkillCorner's single fastest reading (the peak
speed its own app shows) is **not in our feed**: the feed's `peak_velocity` is an average of
per-match peaks, so a "Peak speed" figure was not added (checked 2026-11-16).

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
position is rescaled to 100%, which keeps the club's relative emphasis exactly. Outfield
Performance : Physical is 65 : 35 (owner 2026-11-16; the document's 40 : 30 became 45.5 :
24.5, the same 70 of 110, so the other four areas are unchanged):

| Area | Outfield (used → rescaled) | Goalkeeper |
|---|---|---|
| Performance | 45.5% → 41.4% (document: 40%) | 50% |
| Physical | 24.5% → 22.3% (document: 30%) | none (folded into Performance, per the club's GK table) |
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

For an outfielder with both data areas, the ranking therefore weights **Performance 65%
and Physical 35%** (41.4 and 22.3 rescaled to their total; 57% and 43% before 2026-11-16).
Composites are rounded to two decimals, exact halves up (3.065 → 3.07). An outfielder with no tracking
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

Rating chips are shaded by the same thresholds (web: `chip` in `static/js/common.js`;
Streamlit: `players.band_colour`): **below 2.0** red, **2.0 to under 3.0** amber, **3.0 to
under 4.0** light green, **4.0 and above** green; no rating = grey "—".

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

> Composite = 3.59 × 0.65 + 4.70 × 0.35 = **3.98** (4.07 under the old 57 : 43)

He also has modelled money bands (Financial Fit 3.15, Resale Potential 3.62), so his
`full_composite` is 3.86. No area is below 2.0, so no veto.

## 5. Peer-pool floor: when a rating is not a ranking

A percentile is only as meaningful as the pool behind it. In a pool of three, whoever
happens to have played decides the order; a player alone in his pool takes the 50th
percentile on every metric (mid-rank) and scores 3.00 on everything.

So a composite is **withheld from the ranked list** when fewer than
**`MIN_PEERS_FOR_RANKING` = 10** rankable players share its league + season + position pool
(`scorecard.pool_is_thin`). The number is still computed and stored. The Players page says
how many players were withheld and why; **Squads & loans** lists them with current-season
facts. The pool size is counted from the whole season's scorecards, so narrowing the
filters never makes a pool look thinner than it is.

**Midfield fallback (owner, 16 Nov 2026).** A Defensive, Central or Attacking Mid pool below
10 is rated against **all midfielders** of that league + season (every rankable Defensive,
Central and Attacking Mid). Only his percentiles come from the combined pool; his metrics and
weights stay his own position's. If the combined pool is also below 10 he stays not rated.
Pools of 10+ and all other positions are unchanged. The pages tag him "Rated against all
midfielders" and quote no rank. Stored as `player_scorecards.peer_pool` ('position' /
'midfield') and `peer_pool_size` (`scorecard.pool_assignment`).
*Example:* Lyall Cameron, the only rankable Scottish Premiership Central Mid in 2026/27, was
3.00 on everything (pool of 1). Against all Scottish Premiership midfielders, still on the
Central Mid metrics: Composite 3.09 against 38 on the Mac copy; **3.06 against 40 on the live
server** after its re-score (2026-11-16 — the server's data was newer).

A player who is not rated shows "—" for every percentile and band, and one line: "Not rated:
only N <Position>s in <League> with 450+ minutes (needs 10)."

A player's true standing ("8th of 13") is quoted only within his own pool
(`scorecard.rank_in_pool`). The Players list is sorted by composite across whichever leagues
are selected, and its first column is "#", not "Rank": a composite says how a player
compares within his own league, not across leagues.

## 6. Archetypes — "Rank as" (optional lens)

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

The default is **All Metrics** (the full list). When an archetype is picked
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

Shown as a Playing style filter, a Style column, a Style fit section on the player
card, and explained to recruiters on Reference → How playing styles work. Never read by the rating or the ranking. Team style influences receptions
(a winger in a direct side receives more in behind) — accepted.

## 6c. Similar players (player card + Similar players page; owner-approved 2026-11-16, method revised 2026-11-20)

"Similar players" on the card lists the 10 players whose profile on the rating's measures is
closest to his; the **Similar players** page (`/similar/<player>/<competition>/<season>`, reached
from the card, not in the navigation) shows the same list and breaks one match down measure by
measure. Code: `core/similar.py`; tests `tests/test_core_similar.py`, `tests/test_web_similar.py`,
`tests/test_similar_real.py`.

| Step | Rule |
|---|---|
| Pool | Same season and position group, **rated** players only (an Overall from a pool of 10+, so 450+ minutes), never the player himself. **Same league** (default) or **All leagues** |
| Measures | The position's rating measures: Performance (club list, stored names) + Physical (SkillCorner). Goalkeepers: Performance only |
| z-score | Per measure z = (value − mean) / sd (population sd) **within league + season + position** (the pool he was rated in: a thin midfield group uses all the league's midfielders, as his rating does). Lower-is-better measures (Turnovers) sign-flipped; \|z\| clipped at 3 |
| Weight | The measure's share of Overall: its weight inside its dimension × the dimension's share (`club_vs_league.overall_weights`, read from `club_framework` at run time — outfield 65 : 35) |
| Correlation R | The measures' correlation matrix on the season's position pool (all leagues, z-scores): **Ledoit–Wolf shrinkage** (`sklearn.covariance.LedoitWolf`) fitted on the players who have every measure, converted to a correlation matrix. If fewer than 3 × (number of measures) players have every measure: pairwise correlation (pairs of measures with 20+ players; else 0) shrunk toward identity by the Ledoit–Wolf intensity of all players with gaps filled by 0. Eigenvalues floored at 10⁻⁶ (always positive definite) |
| Distance | **Weighted Mahalanobis** over the measures both have (set S): d² = Δᵀ D R_SS⁻¹ D Δ / Σ w, Δ = z gaps, D = diag(√w), R_SS = R restricted to S (not re-estimated). With R = identity this is the old weighted Euclidean √(Σ w·Δ² / Σ w). Needs ≥ 70% of the target's own Overall weight present for both, else he is left out |
| Similarity % | The **% of all pairs** of players at that position and season (all leagues; pairs whose shared weight is ≥ 70% of the larger of the two players' own weight) that are **further apart** than this pair. Whole number, .5 up; identical = 100. Help text: "More alike than this % of all <position> pairs." |
| Order | By similarity only. Overall is shown as rated in his own league; never ranked across leagues |
| Filters | League (one league; only with All leagues), Max age, Min minutes (900 / 1,350 / 1,800), Contract (Under 6 / Under 12 months: whole calendar months left < 6 or < 12, already-expired dates included, unknown dates left out — the Squads rule). They narrow the candidates only; the similarity number never changes. Still the top 10, no cut-off |
| Biggest differences | The 2 measures with the largest weight × \|z gap\|, shown as his z minus this player's ("Sprints +1.2"); + = he is better. Descriptive only, not the score |

**Why z-scores within the league.** Each measure is placed against his own league, so "All
leagues" compares *profiles*, never levels across leagues (no league-strength adjustment
exists). The page says: "Measures are compared within each player's own league."

**Why distance, not cosine.** Cosine similarity compares only the *shape* of a profile: a
player with the same shape at half the level scores 100%. Distance on z-scores penalises the
level gap (test: a near-copy ranks first; same shape at half the level is over 10× further away).

**Why Mahalanobis.** Measures that move together (the running measures, the two top speeds)
would otherwise count the same thing several times. Mahalanobis allows for every correlation at
once, partly or fully, instead of an on/off grouping at |r| ≥ 0.8. Two exact copies of a measure
(weight w each) add w·Δ² — one copy's worth — where weighted Euclidean adds 2w·Δ² (test). A
pair whose gaps run *against* a positive correlation (better on one, worse on its partner)
counts as further apart than the same gaps on unrelated measures.

**Why the 70% rule uses Overall weights.** Physical is 35% of an outfielder's Overall: a player
with no physical data covers 65% of a tracked player's weight, so the two are never matched. A
player with no physical data (most non-English leagues) is compared on the performance measures
he has, and the card says "No physical data for him: compared on performance only."

**Why a pair rank.** The % reads the same at every position: 80 means this pair is closer than
80% of all pairs of that position. Distances concentrate (many measures), so most top-10 lists
sit between about 60 and 99.

**Measures that move together (|r| ≥ 0.8 in R, 2026/27)** — shown as a "linked" tag on the page:

| Position | Pairs |
|---|---|
| Goalkeeper | Goals saved above average · Shot stopping % |
| Centre Back, Centre Forward | High-speed runs · High-speed running distance; High-speed runs · Sprints; Sprints · Sprint distance; the two top speeds |
| Full Back | as Centre Back, plus Expected assists · NP xG + xA |
| Defensive Mid | as Centre Back, plus Bypassed opponents (packing) · Deep progressions |
| Central Mid (fallback rule: 38 players with every measure) | Bypassed opponents · Deep progressions; High-speed runs · High-speed running distance; Sprints · Sprint distance |
| Winger | High-speed runs · Sprints; Sprints · Sprint distance; the two top speeds |
| Attacking Mid | Sprints · Sprint distance; the two top speeds |

Ledoit–Wolf shrinkage on the real pools is small (0.02–0.17), so R stays close to the sample
correlations.

**Worked example.** Three measures, weights A 0.5, B 0.3, C 0.2; r(A, B) = 0.6, C unrelated.
Target z = (1.0, 0.0, −0.5); candidate z = (0.5, 0.4, no value).
Shared weight = 0.5 + 0.3 = 0.8 of the target's 1.0 → 80% ≥ 70%, kept.
D·Δ = (√0.5 × −0.5, √0.3 × 0.4) = (−0.354, 0.219).
R_SS⁻¹ = [[1, −0.6], [−0.6, 1]] / 0.64 → (0.125 + 0.048 + 1.2 × 0.0775) / 0.64 = 0.416.
d = √(0.416 / 0.8) = **0.721** (with R = identity it would be √(0.173 / 0.8) = 0.465: he is
worse on A but better on its partner B, which counts as further apart).
If the position's pair distances were 0.3, 0.6, 0.8, 1.0, 1.4, three of five are further apart →
**60**.
Real case: Charlie Wellens (Full Back, League One 2026/27) → Elijah Campbell, d = 1.106; 235,390
of 291,301 Full Back pairs are further apart → **81**, top of his League One list.

**The Similar players page.** Header: the player (name, club, league, position, season), linked
to his card. The filters above; the list (click a row or its "Why"; the first is selected). The
breakdown of the selected match, one row per measure in the score, largest weight × |z gap|
first: Measure · Weight (% of Overall) · both stored values · both z ("vs league") · Difference
(match − him, z). A measure one of them lacks shows "—" and "not used". "Open in Compare" opens
the two on Compare. One line under the table: "Score uses every measure together, allowing for
measures that move together."

Built once per season and position per data version (`webcache`), warmed with the card
(0.1–0.3 s per position; 2026/27 keeps 1.4 M pair distances, 5.5 MB); a request takes
under 10 ms. Never read by the rating or the ranking.

## 6d. No ranking across leagues (owner 2026-11-20, cross-league audit)

A rating or percentile only compares a player with his own league, season and position, so no
page orders, subtracts or colours "best" across leagues:

* **Players:** one tab per chosen league, each ranked within its league ("#" = rank in that
  league); the CSV has one block per league with "League" and "Rank in league".
* **Card, "Against our <position>s":** rank, "our best", the better/worse lists and the radar's
  Orient median (all percentile-based) use only our players rated in **his league that
  season**. Ours rated elsewhere stay in the table, tagged "Rated in <league>", unranked. If none
  of ours shares his league: one line ("None of our <pos>s was rated in <league> in <season>, so
  ratings are not compared.") and no rank.
* **Raw values, every target (owner 2026-11-20):** "Every metric, player by player" shows each
  rating measure as the stored RAW value (per 90, %, m, km/h) for him and every one of ours,
  whatever the league, green = best and red = worst in each row (lower-is-better measures
  flipped; a difference that does not show at the displayed precision is not coloured), under
  "Raw values, each in his own league". The card's "vs ours" columns are his raw value minus the
  median raw value of our current players at the position (number only; the unit is in the row),
  green when better for him. Raw values share units across leagues; no league-strength
  adjustment is applied (director's decision).
* **Phases (owner 2026-11-23):** the physical rows of that table switch between All phases,
  In possession and Out of possession (SkillCorner's split, per 90); green / red are worked out
  within the phase shown. Speed and agility have no split.
* **Position (register N10, 2026-11-20):** every player in this section is taken on his row AT
  the card's position that season; one of ours who played only elsewhere is listed "Not rated at
  <position>".
* **Compare:** each player can be from any season we hold. When leagues or seasons differ: no
  best/worst colours, no rating differences; a season-on-season change from another league reads
  "was X.XX (<league>)" with no delta. The Orient line is drawn only beside League One players
  of its season, from ours rated in League One.
* Club vs League One and Similar players: sections above. Still open from the audit (owner to
  decide): Physical squad Excel and band sort, Scout reports "Data agrees/disagrees", Watchlist
  and Scout reports rating sort.

## 6e. Game performances (per-match Impect scores; owner 2026-11-23) — monitoring only

Never part of a rating (register P11). Code: `ingest/impect_matches.py`, `core/game_performances.py`.

| Step | Rule |
|---|---|
| Leagues | Championship, League One, League Two, National League, Premier League 2 — the season being played |
| Data | Impect's per-match player scores: IMPECT, Offensive IMPECT and Defensive IMPECT (packing), **raw match totals** (Impect's default view, not scaled to 90; owner 2026-11-23). Positions summed; his position = the one played longest |
| Percentile | Per score, per game: the share of the OTHER games of 45+ minutes at that position (our position groups) in that league season with a strictly lower score — "better than X%" |
| Level | On the whole-number % shown: Top above 80, Low below 20, Average between (Impect's bands). A game under 45 minutes is shown hollow and not counted |
| Player page | Last 10 games, % on every dot, IMPECT / Offensive / Defensive switch, Top / Average / Low counts |
| Watchlist | "Last 5" = IMPECT % of his last five counted games, newest on the right; "In form" = Top in 3 or more of them |
| Linking | Impect player ids → ours with the same linkage as every other Impect step; unlinked players kept with no player_id |

*Check against Impect (23 Nov 2026):* Lyall Cameron (Dundee United, Scottish Premiership), the six
games Impect's "Game performances" plots: our level matches Impect's on all six; the % differ by
2–10 points (Impect does not publish its comparison pool).

## 6f. Club score per game (owner 2026-11-23, N21) — display only

The club's own formula (§4–5) applied to ONE game, beside Impect's scores, so staff can see and
check each game on the club's terms. Never part of a rating or the ranking (register P11).
Code: `model/game_scoring.py`, `ingest/impect_matches.py` (step 4), `core/game_performances.py`.

| Step | Rule |
|---|---|
| Data | Impect `/matches/{id}/player-kpis` (game totals; a KPI not listed = none happened) and SkillCorner `get_physical` without `group_by` (one row per player per game; rows failing SkillCorner's physical check are left out). SkillCorner rows join on our player + game date |
| Metrics | Every Performance and Physical metric of his position, built as the season metric is (`impect_map`, `skillcorner_map`): rates per 90 of that game; ratios from that game's counts. A ratio with nothing to divide by (no aerial duels) and top-5 peak speed (no per-game value) are left out — never estimated |
| Pool | Every game of 45+ minutes at that position (the midfield fallback as in §5) in that league season |
| Bands | Metric percentile (mid-rank, as the season scoring) → 1–5 band → the club's weights → Performance, Physical; Overall = Performance 65 : Physical 35 |
| Shown % | "Better than X%" of the other pool games, as for Impect's scores; Top above 80, Low below 20 |
| Under 45 min | Values shown, no rating |
| Player page | Overall / Performance / Physical / Impect tabs; click a game → every metric: game value, per 90, %, band, weight, source; Excel: every game this season + a Sources sheet |

## 6g. Fixtures: which games to watch and why (owner 2026-11-27, phase 5) — display only

Every UK and Irish league game (plus EFL Cup fixtures, and games a scout adds by hand) in the
next 7 / 14 days or the past 3 weeks. Nothing is hidden by default; a filter says how many games
it hides. A game's players = everyone who has played for either club this season (club of his
latest game). Signals per player (`core/fixtures.py`):

| Signal | Rule |
|---|---|
| Scout verdict | Any of his reports (all are listed); **Scouts disagree** = Sign or Monitor Priority and Don't sign |
| In form | Top (club Overall per game better than 80% of games at his position) in 3+ of his last 5 rated games, or 6+ of his last 10 |
| Rising | Average "better than %" of his last 5 rated games at least 20 points above the 5 before (needs 10) |
| Breaking through | Under 23; 200+ minutes in his club's last 5 games and at least double the 5 before |
| Not seen yet | Season Overall 3.5+ in his own league and no scout report (not shown when a report may be about him) |

Filters in different groups must all be true of the same player; ticks in one group are
alternatives. Scout priorities and watchlist players are always listed in an open game.
Reports not linked to a player (no name + birth-date match) are **suggested** by club + surname
and linked only when a person clicks Link (`scout_report_links`, kept by the linking stage).
Regions: by league for Scotland and Ireland, else `reference/club_regions.csv`. EFL Cup:
fixtures only (its game scores would compare clubs of different leagues).

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

- **Fee gate:** market value ≤ the transfer budget set in the filters.
- **Wage gate:** modelled weekly wage within the wage-framework ceiling for his position and
  age band. The wage is a band from **×0.70 to ×1.40** of the central estimate. He passes if
  the **low** end fits, and is flagged **wage-marginal** if the band straddles the ceiling,
  so borderline cases go to a person rather than being dropped.

The wage estimate is a league × position × age × performance-tier grid anchored to
published league wage reporting (`store/reference_data.py`); it is never derived from
market value. Both the wage grid and the ceiling are stand-ins until the club's real wage
data is loaded.

Survivors are ranked on `objective_composite`, the same stored number the site shows
(`player_scorecards`, written by `model/scorecard_run.py`). If nobody passes at a given
budget, the five best by composite are returned as near-misses.

## 10. Contract-expiry filter

The **Contract expiry** filter offers *Any*, *Out of contract summer 2027*,
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
- **No physical data** for 2024/25, the Scottish Championship or the newer leagues SkillCorner
  does not cover (all but Ireland); those ratings are Performance only.
- **Money is 2025/26 English leagues only**, and fair value is a screening signal with
  wide error (§8).
- **Event data is on-ball.** Off-ball work is seen only through the SkillCorner Physical
  metrics.
- **Modelled wages are a prior.** Real asking wages come from agents.

## Club vs League One (new web site, owner 2026-11-09)

The page answers one question: **where do we fall short of a top-6 League One side this season,
and who could close the gap?** Every number on it is a stored rating, minutes figure or
percentile; the page only picks, weights by minutes and compares. Code: `src/lofc/core/club_vs_league.py`.

**The rules, in plain English**

1. **This season only.** A player counts if he has an Overall rating this season: 450+ minutes
   and a peer pool big enough to rate (small pools are never rated).
2. **Top 6.** The six League One clubs whose players have the highest average Overall rating
   this season, weighted by minutes (each player's rating × his minutes, summed, ÷ the club's
   minutes). The Top 6 card also shows Performance and Physical (the same minutes-weighted
   club average) and Orient's own row with its rank.
3. **Our level.** Our best player at the position rated this season in League One. Players rated
   only last season, or only in another league (on loan), are listed with a tag ("25/26", or the
   league's name) but never set our level.
4. **Positions.** Goalkeeper, Centre Back, Full Back, Midfield (Defensive, Central and Attacking
   Mid together), Winger, Centre Forward. A rating is always the player's own, from his own
   position pool; a midfielder's sub-position is shown as a tag.
5. **Top-6 bar.** For each of the six clubs, its best rated player at the position; the bar is
   the median of those players, and each one is named. If fewer than 4 of the 6 clubs have a
   rated player there yet (early season), last season's top 6 is used for that position, with
   last season's data, and the page says so.
6. **Gap.** The bar minus our level, biggest first. "Biggest shortfalls" compares our player's
   percentiles with the median of the named players' and shows the three biggest; opening a row
   lists every metric where we are behind, biggest first, with no cut-off ("Every shortfall"). Each shortfall
   shows ours, the top-6 median and "Behind" (the unrounded difference, .5 rounded up) — one
   figure, the same in both lists. Percentiles are plain numbers (100 = best); ordinals are used
   only for league ranks.
7. **Players who could close the gap.** This season's rated players at the position (not ours)
   with an Overall above our level — **one list per league, every such player** (no top-15 cap
   since 13 Nov 2026; caption "<N> full backs above <our player> · ranked within <league>"),
   because a rating compares a player only with his own league, ranked by Overall.
   **Other leagues (owner 2026-11-20, decision A):** the "above our level" filter, "Top-6 level
   only", the "Top-6 level" badge and "vs our best" apply to the League One tab only (an Overall
   from another league is not on our scale). Every other tab lists every rated player at the
   position, always ranked by Gap closed (ties by Overall, no figure last); caption
   "<N> wingers · by Gap closed within <league>". Every
   heading sorts the list (13 Nov 2026): numbers highest first, Player and Club A–Z, a second
   click reverses; the choice is kept in the address (`sort=`). Three columns, one per shortfall metric
   from "Biggest shortfalls", show his percentile in his own league and position (green 70+,
   grey 30–69, red below 30); each column can be sorted, and the recruiter can choose other
   metric columns (Gap closed, below). "vs our best" is his Overall minus our
   level (2 decimals, .5 rounded up as the card's "vs ours"); the gap is closed when it reaches
   the gap size. "Top-6 level" marks an Overall at or above the bar. Filters: age, contract,
   "Strong on 2+ of our weaknesses" (70th percentile or better on at least 2 of the 3) and
   "Top-6 level only" (at or above the bar); both off by default. No market value, fee or wage
   is shown. Leagues: a multi-select of every league with candidates (England's first),
   default League One, Championship and League Two; the choice is remembered in that browser.
8. **Big picture.** Our rank among League One clubs, this season and last, on the minutes-
   weighted club averages of Overall, Performance, Physical, the seven physical metrics and ten
   performance measures from players' season figures: Attack (non-pen xG, expected assists,
   touches in box), Progression (bypassed opponents, deep progressions, passes into box) and
   Without the ball (pressures, ball wins, ground-duel win %, aerial win %). Every measure must
   have League One data this season (tested): progressive passes and ball recoveries were
   replaced on 10 Nov 2026 because Impect does not provide them. The Physical section has a
   switch (13 Nov 2026): All phases · In possession · Out of possession (`phase=tip|otip` in the
   address). In / out of possession use SkillCorner's phase splits (`player_detail_metrics`
   "phys_tip.<metric>" / "phys_otip.<metric>", per 90), with the same club calculation
   (minutes-weighted, ranked 1–24, both seasons). Top speed and Average match top speed have no
   split and show "—" there. Code: `club_vs_league.phase_frame`.

**Worked example (real data, 9 Nov 2026, season 2026/27): Centre Back**

* Top 6 this season (average Overall, weighted by minutes): Stockport County 3.52, Milton Keynes
  Dons 3.45, Leicester City 3.35, Wigan Athletic 3.20, Bradford City 3.18, Peterborough United
  3.16. We are 23rd of 24.
* Each club's best rated centre back: Kyron Gordon 4.29 (Stockport), Jack Sanders 3.74 (MK Dons),
  Caleb Okoli 3.68 (Leicester), Jon Mellish 3.75 (Wigan), George Pratt 3.82 (Bradford), Thomas
  O'Connor 3.46 (Peterborough). All six clubs have one, so this season's bar is used.
* Bar = the median of 3.46, 3.68, 3.74, 3.75, 3.82, 4.29 = (3.74 + 3.75) ÷ 2 = **3.75** (the page works from the unrounded ratings).
* Our level = our best centre back rated this season in League One: Joseph Olowu **2.85**.
* Gap = 3.75 − 2.85 = **0.90**, shown on the page as −0.90.
* Biggest shortfall: Distance — Olowu at the 5th percentile, the six named centre backs' median 90th.

Wingers that day used last season's bar: only 3 of this season's top-6 clubs had a rated winger
yet, so the bar came from 2025/26's top 6 (5 of them had one).

**Gap closed (owner 2026-11-13; raw values and gap size owner 2026-11-23)**

How much of our player's shortfall against the top 6 a player would make up, on **raw values**
(per 90, %, m, km/h from `player_metrics_neutral`) on every league tab. Raw values share units
across leagues; percentiles from two leagues do not (owner 2026-11-23). No league-strength
adjustment is made (director's decision).

1. **Shortfall measures.** Where our player's percentile is below the median percentile of the
   named top-6 players (the "Every shortfall" set; both sides are League One, so percentiles are
   comparable here). Code: `club_vs_league.gap_profile`.
2. **Raw profile.** For each of those measures: our player's raw value and the top-6 players'
   median raw value; kept only when the median is better (lower for `LOWER_IS_BETTER`).
   Code: `raw_profile`.
3. **Share closed per measure** = (his raw − ours) ÷ (top 6 − ours), kept between 0 and 1: 0 if he
   is no better than our player, 1 at or beyond the top-6 level (no extra credit); a measure he
   has no value for closes nothing. E.g. xA: ours 0.02, top 6 0.08 → a player at 0.05 closes 50%.
4. **Weight of each measure** = its share of Overall (Performance 65 : Physical 35 for
   outfielders; inside Performance the club's "All Metrics" weights; Physical equal; goalkeepers
   Performance only — `overall_weights`) **× the size of its gap in League One spreads** (|top 6 −
   ours| ÷ the standard deviation of League One's rated players at the position this season;
   owner decision B, 2026-11-23: a big shortfall counts more than a near-zero one; a measure
   with no spread is left out — `gap_size`). Measures that move together (|r| ≥ 0.8, decision D)
   share one weight (`grouped_weights`).
5. **Gap closed = 100 × Σ weight × share ÷ Σ weight**, a whole number (.5 up); "—" if there is no
   shortfall to close. Code: `gap_closed`.

*Why gap size (decision B).* Real data, Full Back 2026/27: our gap on Pressures is 0.49 per 90 =
0.08 League One spreads (almost nothing); on Sprints 6.65 per 90 = 1.92 spreads (large). Without
the gap size, closing the Pressures gap would count as much as closing the Sprints gap.

By default it counts every shortfall. When the recruiter chooses the metric columns (up to 5),
it counts only those; if none of them is a shortfall it shows "—". "Rank by: Gap closed" orders
each league's list by it (ties by Overall). "Strong on 2+" always uses the 3 biggest shortfalls.
The metric columns show his percentile within his own league (display only).

**Minutes (owner 2026-11-16).** Our compared player (level strip, Gap map row) and each named
top-6 player (Gap map detail) show this season's minutes; under 900 (`LOW_MINUTES`) a small "low
minutes" marker is added. The old line "Gap closed % is relative to his own league." was removed
on 2026-11-23 (raw values on every tab).

**On the page.** "How this is worked out" shows Gap closed as a mini table built live from the
page's own figures: the player it is measured against and the first player by Gap closed in the
active league tab (his % is the list's figure). Rows: the 3 shortfall measures that count most
(weight × gap size) that the target has a value for, in each measure's unit: Ours, Top 6, Gap,
Target, Target − Ours, Share closed ("100% (capped)" past the top 6). Code: `gap_example`.

*Worked example (real data, 23 Nov 2026, 2026/27): Full Back, League One tab.* Our Charlie
Wellens 2.47; top-6 bar 3.64. First by Gap closed: Tyrese Noslin, 85%.

| Measure | Ours (Wellens) | Top 6 | Gap | Target (Noslin) | Target − Ours | Share closed |
|---|---:|---:|---:|---:|---:|---:|
| Dribbles (count) | 1.20 | 4.18 | 2.98 | 4.41 | 3.22 | 100% (capped) |
| Deep progressions | 6.25 | 12.89 | 6.64 | 12.51 | 6.27 | 94% |
| Aerial win % | 20% | 51% | 31% | 48% | 28% | 90% |
| …and 17 more measures | | | | | | |

Gap closed = Share closed on each shortfall, averaged with each measure's weight in the Full Back
rating and the size of its gap = 85%. Measures that move together count once.

**Measure against any of our players (owner 2026-11-13)**

By default a position is measured against our best player there. In the open Gap-map row, any
of our players who counts toward our level (rated this season in League One — the same rule as
our best) can be picked instead; the choice is kept in the address (`vs=<player id>`). For that
position only:

* Gap = the top-6 bar − **his** Overall; "Biggest shortfalls" and "Every shortfall" use **his**
  percentiles; the Gap-map row shows him, with "Back to our best".
* "Players who could close the gap" lists players rated above **him**; "vs our best" becomes
  "vs him" (his Overall minus the picked player's); Gap closed uses his shortfalls; the default
  metric columns and "Strong on 2+" use his 3 biggest shortfalls.
* Everything else is unchanged: the bar, the top 6, leagues, filters, "Top-6 level" (at
  or above the bar) and the other positions. Changing position goes back to our best; a player
  who does not count (rated elsewhere, last season only, another position, not ours) is ignored.
  Code: `club_vs_league.compared_player`, `gap_detail`, `measure_against`.
