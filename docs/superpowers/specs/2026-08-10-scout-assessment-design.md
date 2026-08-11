# Design — Scout assessment system (R3a-0 + R3a)

_Status: proposed. Written 2026-08-10._

Closes the largest remaining gap between the platform and the club's own recruitment
framework: the two dimensions a human scores. Together they carry **22.7% of the outfield
weight** (Medical Risk 13.6% + Psychological 9.1%) and are the reason the "Measured" column
currently reads 64% for an outfielder.

## Scope

| In scope | Out of scope (own specs, later) |
|---|---|
| **R3a-0** — Transfermarkt injury + appearance scrape | **R3b** — scout document upload |
| **R3a** — user accounts, scout assessment entry, scoring | **R3c** — player-profile export |

R3b and R3c are deliberately separate: neither the score nor the assessment workflow depends
on them. R3a-0 comes first because the availability rule must be designed against real injury
records, not guesses.

---

## 1. Background — what the club document actually specifies

`docs/LOFC - Position Archetype.docx` already defines both dimensions **per position**, and
the evaluation scorecard in it literally has `Score (1–5) | ___` blanks. This is not a new
feature; it is the club's existing paper form, digitised. The criteria are transcribed
verbatim into code, exactly as `PERFORMANCE_METRICS` and `DIMENSION_WEIGHTS` already are.

**Confidentiality:** the source `.docx`/`.xlsx` remain gitignored and unpublished, per the
established pattern. The *encoded* framework lives in the repository, as `club_framework.py`
already does.

---

## 2. Decisions

Decisions 1–5 are already recorded in `model/club_framework.py`. These continue the same
numbering and the same principle: where the club's document is silent or inconsistent,
resolve it from the club's own numbers and document it, rather than asking or inventing.

### Decision 6 — Left/Right variants are merged, de-duplicated

The docx defines ten profiles (GK, RB, LB, CB, DM, CM, AM, LW, RW, CF) against our eight
position groups. The performance metric lists for Left and Right Back are identical, and
`club_framework.py` already merges them. **The psychological bullets are not identical.**

Right Back names decision-making in transition, resilience after being beaten 1v1, and
competitive drive. Left Back names composure in deep build-up, willingness to recover after
attacking runs, and positional discipline. Both plainly apply to any full back.

**Resolution: take the union of both sides' criteria, merging bullets that express the same
requirement.** Assumption-free — it discards nothing the club asked for — and consistent with
the existing Full Back / Winger merge. Recorded per criterion so the origin stays traceable.

### Decision 7 — Medical criteria are three different kinds, scored differently

Forcing every medical bullet onto one 1–5 opinion scale would be less rigorous than the club's
paper form. Each bullet is classified:

| Kind | Example | Treatment |
|---|---|---|
| `availability` | "Minimum 60% availability over prior 2 seasons" | **Computed** from injury + appearance data (§4) |
| `screening` | "No ACL or significant knee ligament injury within prior 12 months" | **Pass/fail**, acts as a cap (§5) |
| `protocol` | "Permanent signings undergo MRI scan on 8 sites" | **Not scored.** A club process step, not a player attribute. Shown as a checklist reminder |

The `protocol` class matters: "undergo an MRI scan" says nothing about the player and must
never move a score.

### Decision 8 — Psychological criteria are equal-weighted

The band is the mean of that position's criterion scores. The club lists them as a flat set
with no individual weights; equal weighting adds no unstated preference. This is Decision 1
applied one level down.

### Decision 9 — `assessed_composite` is NULL unless **both** scout dimensions exist

A partially assessed player must not appear in a ranked list beside a fully assessed one.
Requiring both means every non-NULL `assessed_composite` reflects a complete human assessment.

### Decision 10 — Availability counts injury absence only

Only games missed **through injury** enter the calculation. Deriving availability from minutes
played was tested and rejected: 73% of rankable 2025/26 players fall below a 60% bar on
minutes ÷ (46 × 90), which is rotation and substitution, not injury. Minutes measure
selection; the medical dimension must measure fitness.

A player who was fit but simply not picked is therefore **not penalised** — his games missed
through injury is zero and his availability is 100%.

---

## 3. R3a-0 — Transfermarkt injury and appearance scrape

### Sources (both verified live, 2026-08-10)

| Page | Fields |
|---|---|
| `/verletzungen/spieler/<id>` | season, injury type, from, until, days out, **games missed** |

**One page only.** The appearance page (`/leistungsdatendetails/…`) was evaluated and
rejected: its column layout shifts between competition types and its header row is a sort
link rather than labels, so squad-count parsing would be brittle. The injury page already
carries a Games missed column in a stable, labelled six-column table, which is all the
availability rule needs. This halves the runtime and removes the fragile parser.

### Modules

- **`ingest/transfermarkt_common.py`** (new) — the polite fetch client (2.5s delay, browser
  user agent, exponential backoff) extracted from `transfermarkt_efl.py` so both scrapers
  share one implementation. `transfermarkt_efl.py` imports it; its behaviour is unchanged.
- **`ingest/transfermarkt_injuries.py`** (new) — fetches the injury page per player, parses,
  writes `data/reference/transfermarkt/injuries.csv`.

### Operating characteristics

- **Input:** the 2,619 distinct `tm_player_id` values in `efl_values.csv`.
- **Runtime:** 2,619 × 1 page × 2.5s ≈ **1.8 hours**. An overnight job, never interactive.
- **Resumable:** appends per player and skips ids already captured on restart. A 3.6-hour run
  must not be lost to one failure.
- **Atomic final write**, matching `efl_values.csv`. A failed run leaves the previous file
  intact — the behaviour that preserved the data when Transfermarkt was down on 2026-08-04.
- **Per-player failure is logged and skipped**, never fatal. A player with no injuries yields
  an empty history, which is a valid result and not an error.
- **Run together with B1** (`transfermarkt_efl --force`), clearing the stale 10 Jun 2026
  contract snapshot in the same session, since both hit the same site.

### Injury categorisation

Raw text is stored verbatim. A normalised `injury_category` maps onto the categories the club
names: `hamstring`, `calf`, `groin`, `knee_ligament`, `ankle`, `hip`, `muscular`, `other`.
Unmapped text falls to `other` and is logged, so new phrasings surface rather than vanish.

### Coverage — stated plainly

`tm_player_id` exists only for EFL players.

| Leagues | Players (2025/26) | Medical facts |
|---|---|---|
| Championship, League One, League Two, National League | 2,298 | Scraped |
| PL2, Scottish Premiership, Scottish Championship | 1,047 | Manual entry only |
| | **3,345** | **69% automated / 31% manual** |

---

## 4. Availability

One documented function, `model/medical.py`:

```
availability = 1 − (games missed through injury ÷ scheduled games)      clamped to [0, 1]
```

Computed over the prior two seasons, matching the club's wording. All four EFL leagues play
**46** league games, so the two-season window is **92** scheduled games. The constant is held
per competition, not hard-coded at the call site, so other leagues can be added.

A `-` in the Games missed column means the injury cost no matches (typically an off-season
injury) and reads as **0**.

Undefined only when a player has no Transfermarkt id, in which case the criterion is unscored
rather than defaulted and the assessment cannot complete without manual entry.

**Known limitation:** a mid-season transfer or a player who joined the league part-way through
the window is measured against the full 92 games, which slightly understates his availability.
The manual override exists for this case, and it only ever affects a player who was *also*
injured.

---

## 5. Scoring rules

### Psychological

```
band = mean(criterion scores)          each criterion scored 1–5
```

All of the position's criteria must be scored or the assessment stays a draft.

### Medical

Anchored on the club's own stated bar, exactly as the existing percentile→band formula is
anchored on their median/70th thresholds:

```
band = 3 + 5 × (availability − 0.60)          clamped to [1, 5]
```

60% availability — the club's stated minimum — yields **3.0**, their stated minimum composite.
100% yields 5.0. The band falls to 1.0 at 20% availability, consistent with their veto
language. One club-given anchor, one endpoint, nothing invented.

**Screening criteria act as caps.** Any failed `screening` criterion caps the band at **2.0**
and raises an explicit `medical_screening_failed` flag, mirroring the club's deviation
protocol ("requires independent orthopedic assessment", "triggers enhanced medical protocol").

The flag is raised **separately from the existing veto**, deliberately. `VETO_BAND = 2.0` and
the existing test is `band < 2.0`, so a band capped *at* 2.0 does not trip it. Rather than
invent a fractionally lower cap to force the veto, the failed screening is surfaced as its own
named flag — clearer to a recruiter, and it leaves the club's stated veto rule untouched.

Consistent with the rest of the platform, **both are advisory**: they flag the player, they
never remove them from any list.

### Override

Either band may be overridden by an authorised user. An override requires a **mandatory
reason**, and stores the original computed value, the new value, the author and the timestamp.
The player detail shows overridden bands as such.

---

## 6. Transparency: what the page must tell the user

**This is a hard requirement, not a nice-to-have.** Every assumption, caveat and coverage limit
behind the scores in this design must be shown to the user, on the page — not left in this
document for someone to have read in advance. The wording must be short: a recruiter reads this
between meetings, so a wall of text fails the requirement as surely as saying nothing.

The page must disclose at least the following, each as a short, plain-English line — no jargon,
no statistics vocabulary:

1. **Most players score the maximum on Medical.** 77% of players (2,201 of 2,870 measured) had
   no injuries in the two-season window and would score the top band of 5.0. The dimension is
   designed to flag the injury-prone, not to separate healthy players from each other.
2. **Where injury data comes from and who it misses.** Transfermarkt, English leagues only.
   Coverage: Championship 98%, League One 95%, League Two 96%, National League 92%; Premier
   League 2 16%, Scottish Premiership 7%, Scottish Championship 3%. Outside the English leagues,
   a scout must enter it by hand or the player has no medical score.
3. **What "availability" counts.** Matches missed through injury, over the last two seasons,
   against a 92-match window. A fit player who simply was not picked is **not** penalised — he
   counts as fully available.
4. **What it deliberately does not use.** Minutes played was rejected as a measure: 73% of
   players would fall below the club's 60% bar on minutes alone, which reflects squad rotation
   rather than fitness.
5. **What the injury categories do and do not affect.** Illness, knocks and unspecified entries
   land in "other". Category never changes the availability figure, which counts matches missed
   regardless. Categories matter only for the club's specific screening criteria.
6. **Where the 1–5 scale comes from.** 60% availability scores 3.0 because that is the club's own
   stated minimum standard; 100% scores 5.0. Nothing in the scale is invented.
7. **A known blind spot.** A player who joined part-way through the window is measured against
   the full 92 matches, which understates his availability. Only affects players who were also
   injured; the manual override exists for it.
8. **Psychological is entirely human judgement.** There is no data behind it — it is the scout's
   assessment against the club's own criteria for that position.
9. **Nothing here excludes a player.** Every flag is advisory, consistent with the rest of the
   platform.
10. **Every figure shows its provenance and its date** — scraped versus hand-entered, who entered
    it, and when.

**Implementation note.** These belong on the page itself, not buried in a separate document: a
compact "What this covers / what it doesn't" panel, plus short inline captions next to the
figures they qualify. Detailed UI layout is for the implementation plan, not this spec.

---

## 7. `assessed_composite`

Not a new formula. The existing `_composite()` in `model/scorecard.py` called with a longer
dimension list — weighted average over the dimensions present, divided by the weight present.

| Composite | Dimensions | Outfield weight | Role |
|---|---|---|---|
| `objective_composite` | Performance + Physical | 64% | **Default ranking — unchanged** |
| `full_composite` | + Financial + Resale (modelled) | 77% | Opt-in money view — unchanged |
| `assessed_composite` | + Psychological + Medical | **100%** | Opt-in, assessed players only |

Worked example, a League One winger with Performance 4.0, Physical 3.5, Financial 3.0,
Resale 4.0, Psychological 3.8, Medical 3.9:

| Composite | Weighted sum | ÷ weight present | Result | Measured |
|---|---|---|---|---|
| objective | 2.4091 | 0.6364 | **3.79** | 64% |
| full | 2.8636 | 0.7727 | **3.71** | 77% |
| assessed | 3.7409 | 1.0000 | **3.74** | 100% |

A player with no market value (Scottish/PL2) has Financial and Resale absent, so the same
assessment yields **3.81 at 86% measured**. Renormalisation handles it and the Measured %
column keeps the difference visible — the mechanism already used for missing physical data.

**Why this is safe:** the default ranking never includes the scout dimensions, so shipping
this moves nothing. Medical carries a ±0.30 swing on `full_composite`, and in League One a
±0.30 band spans 238 of 573 players — which is precisely why an unassessed player must be
absent from the assessed view rather than ranked badly within it (Decision 9).

---

## 8. Users and roles

Authentication is required because an unattributed scout rating has little value and a medical
override must be traceable to a person.

- **Hashing:** `hashlib.scrypt` from the standard library. **No new dependency.**
- **Bootstrap:** the first admin is created by CLI (`python -m lofc.admin create-user`). There
  is no self-service signup.
- **Session:** Streamlit session state, cleared on logout.

| Role | Permissions |
|---|---|
| `scout` | Create Psychological assessments; view everything |
| `medical` | Create Medical assessments and overrides; manual injury entry |
| `head_of_recruitment` | Both, plus full assessment history |
| `admin` | Manage users |

**Latest-per-role wins.** Psychological takes the most recent `scout` assessment; Medical the
most recent from a `medical`-capable user. Nothing is deleted — prior assessments remain
visible and attributed, so disagreement is on screen rather than averaged away.

This deliberately avoids an approval workflow. A sign-off state machine can be added later
without changing the scoring path.

---

## 9. Data model

One Alembic migration.

**`users`** — id, username (unique), full_name, role, password_hash, is_active, created_at.

**`scout_assessments`** — id, player_id, competition_id, season_id, dimension
(`Psychological` | `Medical Risk`), author_id → users, `band` (the value that scores),
`band_computed` (the value the rule produced before any override; equal to `band` when not
overridden), `override_reason`, `screening_failed` (boolean, medical only), notes,
status (`draft` | `complete`), created_at, updated_at.
Scoped to (player, competition, season) — the same triple as every other player row, and the
same choice already made for `watchlist`.

**`scout_criterion_scores`** — assessment_id, criterion_key, score (1–5, nullable),
passed (boolean, nullable). Numeric for psychological, boolean for medical screening.

**`player_injuries`** — id, player_id, tm_player_id, season_label, injury_type_raw,
injury_category, date_from, date_until, days_out, games_missed,
**`source`** (`transfermarkt` | `manual`), **`entered_by`** → users (null when scraped),
created_at.

**`player_season_availability`** — player_id, competition_id, season_id, games_missed,
scheduled_games, availability_pct, `source`, `entered_by`, updated_at.

**`player_scorecards`** — two new columns: `assessed_composite`, `assessed_weight_covered`.

### One schema, two provenances

Manual and scraped records share one table and one scoring rule; the rule never inspects
`source`. A hand-assessed Scottish Premiership player and a scraped League One player are
computed identically and are directly comparable. Only the **display** differs — every field
shows its origin ("from Transfermarkt, 14 Aug 2026" vs "entered by <name>, 12 Aug 2026").

This is safe specifically because the Medical band is an **absolute** rule against a fixed bar,
not a percentile. A hand-entered value cannot shift anyone else's score. The same would not be
acceptable for Performance or Physical, which are ranked within league peers.

For manual entry, scouts record the **summary fields the criteria test** — availability %,
injuries in the prior 12 months by category, total days out — not an injury-by-injury log.
Same fields the scrape produces, entered in a form somebody will realistically complete.

---

## 10. Modules

| Module | Purpose | Depends on |
|---|---|---|
| `ingest/transfermarkt_common.py` | Shared polite fetch client | — |
| `ingest/transfermarkt_injuries.py` | Scrape + parse injuries and appearances | common |
| `model/club_criteria.py` | The club's per-position criteria, verbatim, typed by kind | — |
| `model/medical.py` | Availability + medical band rule | club_criteria |
| `model/scout_scores.py` | Latest-per-role bands keyed (player, competition, season) | store |
| `model/scorecard.py` | *Modified:* accepts `scout_bands`, emits `assessed_composite` | club_framework |
| `model/scorecard_run.py` | *Modified:* passes scout bands, persists new columns | scout_scores |
| `dashboard/auth.py` | Login gate, current user, role checks | store |
| `dashboard/tabs/assessment.py` | The entry form | club_criteria, auth |
| `admin.py` | `create-user` CLI | store |

`model/scout_scores.py` mirrors the interface of the existing `financial_resale` frame, which
is why the change to `scorecard.py` is small and surgical rather than structural.

---

## 11. Dashboard

- **Login gate** in front of the whole app; the current user and role are shown in the sidebar.
- **New "Assessment" tab** — search a player, see their computed medical facts and injury
  history, score the club's criteria for their position, save. Role-gated: a `scout` cannot
  write a Medical band.
- **Player detail** gains a scout section — the two bands, who assessed and when, criterion
  breakdown, and the injury history table. Visible to everyone; editable per role.
- **Players tab** gains an optional "Assessed" ranking mode: filters to assessed players and
  ranks on `assessed_composite`, with Measured % beside every row. **Off by default.**

---

## 12. Testing

All parser tests run against **saved HTML fixtures. No network access in the test suite.**

- **Parsers** — injury rows including "no injuries", multi-season histories, missing "until"
  (ongoing injury), `-` in games missed, and the header row being skipped.
- **Availability** — no injuries (→ 1.0), games missed exceeding scheduled games (clamped to
  0.0), window filtering by season.
- **Medical band** — the anchors (60% → 3.0, 100% → 5.0, 20% → 1.0), clamping, and the
  screening cap at 2.0 including the case where availability alone would have scored 5.
- **Psychological** — mean, and that an incomplete set stays a draft and does not score.
- **Composite** — `assessed_composite` NULL when either dimension is missing (Decision 9),
  correct renormalisation with and without market value, and that `objective_composite` and
  `full_composite` are **byte-identical to their current values**.
- **Roles** — a `scout` cannot write a Medical band; an override without a reason is rejected.
- **Provenance** — manual and scraped records produce identical bands.
- **Idempotency** — re-running the scorecard writer changes nothing.

The existing 191 tests must remain green.

---

## 13. Error handling

| Situation | Behaviour |
|---|---|
| Transfermarkt down | Existing files untouched; run reports and exits non-zero |
| Single player page fails | Logged, skipped, run continues |
| Scrape interrupted | Resumes from checkpoint, skipping captured ids |
| Unknown injury phrasing | Stored raw, categorised `other`, logged |
| Player has no TM id | No scraped facts; manual entry is the only path |
| Player has no scheduled-games constant | Criterion unscored; manual entry required |
| Unknown position group | Assessment blocked with a clear message — never scored against no criteria |
| Partial assessment | Stays `draft`; does not reach the composite |

---

## 14. What does not change

`objective_composite`, `full_composite`, the default Players ranking, the `shortlists` table
ordering, and all 191 existing tests. `assessed_composite` is opt-in and NULL until a human
has completed both dimensions for that player.

---

## 15. Follow-ons (registered, not in scope)

- **R3b** — scout document upload. Uploads are an **evidence trail, never a scoring input**,
  which is what makes deferring them safe. Medical documents are special-category personal
  data under UK GDPR and need a club policy decision before storage is designed.
- **R3c** — player-profile export.
- Extend the injury scrape beyond the EFL if Transfermarkt ids can be resolved for
  Scottish/PL2 players.
- Scrape the appearance page for squad counts, if mid-season transfers turn out to distort
  real assessments in practice (§4, Known limitation).
- Sign-off workflow, if the club wants an authoritative assessment rather than latest-per-role.

---

## 16. Open questions

- **Is a Medical dimension that awards 77% of players an identical maximum, while carrying 13.6%
  of the outfield composite weight, the intended behaviour?** Recorded as an open design question
  in `plan/BUILD_PLAN.md`'s pending work register (R3) — not yet decided. **Must be settled before
  the band formula in §5 is built**: building it now would silently encode an answer nobody has
  actually chosen.
