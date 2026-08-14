# Design — Scout assessment system (R3a-0 + R3a)

_Status: proposed. Written 2026-08-10. Revised 2026-08-14 — **Decision 12 reverses Decision 11**:
the Medical band is now entered by a person, and Transfermarkt injury data is evidence only. Nothing
in this document is built except the injury collector, its storage, the availability function and
the data-loss guards; the scout page, the assessment form, the sign-off states and the evidence
panel are **designed, not implemented**._

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
on them. R3a-0 comes first because the medical design had to be settled against real injury
records rather than guesses — and, as Decision 12 records, doing so overturned the design that
was written before the records existed.

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
| `availability` | "Minimum 60% availability over prior 2 seasons" | **Computed as a figure and displayed as evidence** (§4). Under Decision 12 it informs the assessor's judgement; it never produces a band |
| `screening` | "No ACL or significant knee ligament injury within prior 12 months" | **Pass/fail**, recorded by the assessor; raises a warning flag but never overrides the band they enter (Decision 13, §5) |
| `protocol` | "Permanent signings undergo MRI scan on 8 sites" | **Not scored.** A club process step, not a player attribute. Shown as a checklist reminder |

The `protocol` class matters: "undergo an MRI scan" says nothing about the player and must
never move a score.

**Amended by Decision 12.** When this decision was written, `availability` was expected to
produce the Medical band arithmetically. It no longer does. The three-way classification
survives — it is still the right way to read the club's bullets — but the `availability` class
is now an evidence figure shown to a human, not an input to a formula.

### Decision 8 — Psychological criteria are equal-weighted

The band is the mean of that position's criterion scores. The club lists them as a flat set
with no individual weights; equal weighting adds no unstated preference. This is Decision 1
applied one level down.

### Decision 9 — `assessed_composite` is NULL unless **both** scout dimensions exist

A partially assessed player must not appear in a ranked list beside a fully assessed one.
Requiring both means every non-NULL `assessed_composite` reflects a complete human assessment.
Under Decision 12 both dimensions are human judgements. Under Decision 14 a **submitted**
assessment counts — sign-off is not required for it to score, only to mark it approved.

### Decision 10 — The availability *figure* counts injury absence only

Only games missed **through injury** enter the availability calculation. Deriving availability
from minutes played was tested and rejected as a *substitute* for it: 73% of rankable 2025/26
players fall below a 60% bar on minutes ÷ (46 × 90), which is rotation and substitution, not
injury. Minutes measure selection; a fitness figure must measure fitness.

A player who was fit but simply not picked is therefore **not penalised** by the availability
figure — his games missed through injury is zero and his availability reads 100%.

**Minutes played is still shown, for a different job.** It is not folded into availability, but
it is displayed beside it as an **independent check on the injury record**: a player with 2,000+
minutes was demonstrably on the pitch whatever Transfermarkt does or does not say about him.
Decision 12 uses it in exactly that role and no other.

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

| Leagues | Players (2025/26) | Injury evidence |
|---|---|---|
| Championship, League One, League Two, National League | 2,298 | Scraped (see Decision 12 for how thin it gets) |
| PL2, Scottish Premiership, Scottish Championship | 1,047 | None scraped — the assessor works from the club's own sources |
| | **3,345** | **69% have scraped evidence / 31% have none** |

This is *evidence* coverage, not score coverage. Since Decision 12 no Medical score is produced
from this data at all, so a player outside the English leagues is not unscorable — he is
assessable on exactly the same footing as everyone else, with less on the screen in front of the
assessor.

---

## 4. Availability — an evidence figure, not a score

**Built.** `model/medical.py` exists and computes this today. What changed in Decision 12 is what
the number is *for*: it is displayed to the assessor and to anyone reading a player profile, and
it is never converted into a band.

One documented function, `model/medical.py`:

```
availability = 1 − (games missed through injury ÷ scheduled games)      clamped to [0, 1]
```

Computed over the prior two seasons, matching the club's wording. All four EFL leagues play
**46** league games, so the two-season window is **92** scheduled games. The constant is held
per competition, not hard-coded at the call site, so other leagues can be added.

A `-` in the Games missed column means the injury cost no matches (typically an off-season
injury) and reads as **0**.

Undefined when a player has no Transfermarkt id, and **equally undefined when he has an id but no
injury record** — the two cases are shown as "not known", never as a clean record and never
defaulted to 100%. See §9 for why that distinction is still only partly recoverable.

**Known limitation:** a mid-season transfer or a player who joined the league part-way through
the window is measured against the full 92 games, which slightly understates his availability.
It only ever affects a player who was *also* injured. Since Decision 12 this can no longer push
a score down by itself — it can only mislead a reader, which is why the window and the spells
behind the figure are shown in full rather than the percentage alone.

---

## 5. Scoring rules

### Psychological — unchanged

```
band = mean(criterion scores)          each criterion scored 1–5
```

Equal-weight mean of the club's criteria for that position (Decision 8). All of the position's
criteria must be scored or the assessment stays a draft. Decision 12 changes nothing here.

### Medical — entered by a person

**There is no formula.** The Medical band is entered by an authenticated user (Decision 16),
scoring the player against the club's per-position medical requirement checklist, with the
injury evidence on the screen in front of them (§6).

The evidence shown — availability %, matches missed, injury history by type and category, days
lost, recurrence, and minutes played — is **displayed to inform that judgement and is never
summed, weighted or mapped into a score**.

The scoring guide is the club's own 1–5 rubric, verbatim:

| Band | Club's wording |
|---|---|
| 1 | Unacceptable |
| 2 | Below Standard |
| 3 | Meets Standard |
| 4 | Above Standard |
| 5 | Elite |

**4 and 5 are defined by reference to an elite threshold, and the club has not defined one for
Medical.** Its metric tables carry both a "Minimum Standard" and an "Elite Threshold" column;
Medical & Durability lists minimum requirements only. So in practice **3 is the ceiling** for
this dimension until the club supplies an elite threshold — not as a rule the platform imposes,
but as a direct consequence of the club's own rubric having nothing to score 4 and 5 against.
The form states this next to the input rather than silently clamping the value.

#### Decision 12 — Medical is scored by human assessment; Transfermarkt is evidence only (2026-08-14)

**This supersedes Decision 11.** No automatic rule produces a Medical band. Transfermarkt injury
data is evidence, shown to a person, and nothing else.

**The evidence.** Injury-record coverage collapses down the pyramid:

| League | Linked to Transfermarkt | Have an injury record |
|---|---|---|
| Championship | 98% | 74% |
| League One | 95% | 39% |
| League Two | 96% | 32% |
| National League | 92% | 18% |
| Premier League 2 | 16% | 4% |
| Scottish Premiership | 7% | 5% |
| Scottish Championship | 3% | 1% |

Minutes played is an **independent** check on that: a player with 2,000+ minutes was demonstrably
available whatever Transfermarkt says. Of players with no injury record, **~37%** clear that bar,
and the rate is near-identical across leagues (**34%, 39%, 37%, 36%**) — so this signal is **not**
distorted by reporting coverage, which is precisely what makes it usable where the injury records
are not.

Combining both, what is actually knowable about a player's availability:

| League | Knowable |
|---|---|
| Championship | 84% |
| League One | 64% |
| League Two | 58% |
| **National League** | **49%** |

The unknown share climbs down the pyramid — exactly where this club recruits.

**Four reasons for the reversal:**

1. **Roughly half of National League targets are unknowable.** Any automatic score assigns them a
   number that is not evidence. There is no version of the formula that fixes this, because the
   input does not exist.
2. **The bias correlates with league.** It therefore corrupts precisely the cross-league
   comparison the platform exists to perform: the dimension would systematically say something
   different about a Championship player and a National League player for reasons that have
   nothing to do with either player.
3. **The club defines no elite threshold for Medical.** Under the club's own 1–5 rubric, 4 and 5
   are defined by reference to an elite threshold; Medical & Durability lists minimum requirements
   only. An automatic score therefore **cannot discriminate upward at all** — the best it can
   honestly do is 3, which is not a ranking.
4. **Medical risk is a gate, not a rank.** Real recruitment shortlists on ability and then
   medically screens the shortlist. Nobody ranks thousands of players by injury risk, because the
   question is "is there a problem with this one?", not "who is the 400th most durable?".

#### What Decision 11 was, and why it was abandoned

Decision 11 (agreed 2026-08-11, provisional from the day it was written) kept the automatic band
but capped it at 3.0, so that a missing injury record read as neutral rather than favourable. It
was a response to the same underlying finding recorded here — Transfermarkt's injury reporting
thins down the pyramid, and because Performance and Physical are scored *within league* while
Medical was scored on an absolute scale, the reporting gap did not cancel out and the dimension
rewarded obscurity. The cap removed the reward but kept the deeper problem: it still emitted a
number for players about whom nothing was known, and because it could never exceed 3.0 every
player without a recorded injury history landed on the identical band — it could only ever mark
players down, never tell two acceptable players apart. Decision 12 removes the number instead of
flattening it.
**This history is retained deliberately** — the guards, the coverage checks and the "not known"
labelling in this design exist because of what Decision 11 found, and deleting the record would
leave them looking unmotivated.

### Decision 13 — screening criteria WARN, they never override the assessor (agreed 2026-08-14)

An earlier draft had a failed `screening` criterion **cap** the entered band at 2.0. That is
reversed. **The platform never overwrites a qualified human's number.**

The assessor records each `screening` criterion as pass/fail. Any failure raises an explicit
`medical_screening_failed` flag, shown prominently on the assessment form, the player profile
and the export — but **the band the assessor entered stands unchanged**.

The reasoning: the assessor has seen the medical report and the scans; the platform has seen a
Transfermarkt row. A system that silently overrules the better-informed party is the same
failure mode that destroyed 1,381 contract dates on 11 Aug — code deciding it knew better than
the evidence in front of it. Where the platform and the person disagree, **surface the
disagreement, do not resolve it silently.**

If the assessor scores above the flag, the mandatory reason field captures why, and the
disagreement is visible to whoever signs off.

This leaves the club's own `VETO_BAND = 2.0` rule untouched: a genuinely unacceptable player is
scored below 2.0 by the assessor and trips the veto normally.

Consistent with the rest of the platform, **every flag is advisory**: it marks a player, it
never removes them from any list.

### Override

The Psychological band may be overridden by an authorised user: an override requires a
**mandatory reason**, and stores the computed mean, the new value, the author and the timestamp.
The player detail shows overridden bands as such.

The Medical band has **nothing to override** — it was a person's judgement to begin with. A
different judgement is a new assessment, submitted and signed off through §12, with both
retained and attributed.

---

## 6. Where the information appears

Injury history and availability are **player facts, not scout workflow.** A director asking why a
target is being pushed, and an analyst reading a shortlist, both need the injury record; neither
will ever open an assessment form. So the same evidence appears in **two** places:

| Place | Who sees it | Behaviour |
|---|---|---|
| **The player profile** | Everyone — analysts, directors, recruiters | **Read-only.** No assessment controls |
| **The assessment page** | any authenticated user (Decision 16) | Shown **alongside the form**, so the assessor judges with the evidence in front of them |

Neither copy is a summary of the other; both render the same evidence panel.

### The evidence panel

1. **Availability %** for the window, with the window stated (§4).
2. **Total matches missed** through injury in the window.
3. **The injury table** — one row per spell: type (raw Transfermarkt text), category, date from,
   date until, days out, matches missed, and **whether the spell falls inside the scoring
   window**. A spell outside the window is shown, greyed, not hidden — a scout wants the history
   even when the figure does not count it.
4. **Minutes played**, as the independent check on the injury record (Decision 10), not as a
   component of availability.
5. **The league coverage warning** — how much an empty injury record is worth in *this player's*
   league, using the Decision 12 figures. A blank record in the Championship and a blank record in
   the National League are different statements and must not look identical.
6. **Provenance on every row** — scraped versus hand-entered, by whom, and when.

**Designed, not implemented.** The collector, the storage and the availability function exist; the
panel does not.

---

## 7. Watchlist integration

**The gap this closes.** The watchlist (`src/lofc/store/watchlist.py`) already models the front
half of this workflow informally. Its statuses are **Watching · Scout sent · Contact agent ·
Dropped** (`WATCHLIST_STATUSES`). "Scout sent" is today a manual reminder that a scout was
dispatched — a note a recruiter types in, not a fact the platform verifies. The assessment system
makes that fact real. Left undesigned, the two features would sit side by side knowing nothing
about each other: a recruiter would tick "Scout sent" on a watchlist row and the assessment system
would have no idea a scout had, or had not, actually delivered.

**This is interface work belonging to R3a-2, not this foundation plan.** No change to the
`watchlist` table is required — the assessment status is derived by joining on the same (player,
competition, season) triple both tables already use. What follows specifies the integration so
R3a-2 does not have to design it from scratch.

1. **Each watched row shows its assessment status.** Not assessed / 🟠 Assessed — awaiting
   sign-off / 🟢 Signed off, using the **same badges and the same words-not-just-colour rule as
   Decision 14** (§12). A watchlist row and a player-profile row must never disagree about a
   player's status because they render two different badge sets.
2. **An "Assess" action directly from a watchlist row**, so a recruiter working their shortlist
   does not have to navigate back to the Players list to open the assessment form. Role-gated
   exactly as elsewhere (`can(role, "assess_psychological")` / `can(role, "assess_medical")`,
   §12) — the button is visible to any authenticated user (Decision 16), same as the profile's
   **Assess** button (§8).
3. **Filter the watchlist by assessment status**, answering "which of my targets still need a
   scout?" — not assessed, awaiting sign-off, or signed off.
4. **"Scout sent" stays a manual status.** It is **not** auto-driven from assessment state. It
   records *"I asked someone to look at this player"*; the assessment badge already reports
   *"someone did"*. Those are genuinely different facts — a recruiter may mark "Scout sent" weeks
   before an assessment lands, or a player may already carry a signed-off assessment from prior
   interest with no "Scout sent" ever recorded against this particular watchlist entry.
   Conflating the two would silently discard information the recruiter entered deliberately.

---

## 8. Workflow

1. A recruiter finds a player in the Players list.
2. He opens the **player profile** — performance, physical, injury history, availability, and the
   league coverage warning.
3. He clicks **Assess**. Any authenticated user may assess either dimension (Decision 16).
4. The form shows the club's criteria **for that player's position**: the Psychological bullets,
   each scored 1–5; and a Medical panel carrying the evidence panel of §6 plus the club's
   per-position medical requirement checklist.
5. The scout saves. The assessment is **submitted** and **scores immediately** (Decision 14),
   badged 🟠 *Assessed — awaiting sign-off*.
6. The Head of Recruitment reviews it and **signs it off**. The score does not change — the badge
   turns 🟢 *Signed off*, and the assessment becomes eligible for export as final rather than
   provisional.
7. The profile shows the assessed composite, who assessed it, who approved it, and both dates.

**Nothing in this workflow ever hides a player** (Decision 14). Step 6 changes the badge and what
may leave the building; it does not change what you can see or how anyone ranks.

---

## 9. Known defects in the injury evidence

Both are recorded here because this evidence is about to be put in front of people who will act
on it.

### D1 — Overlapping injury spells are double-counted. **Blocking.**

Transfermarkt lists concurrent diagnoses as separate rows. Charlie Wyke carries "Ankle injury"
and "Broken leg" **both** running 26 Oct 2024 → 30 Jan 2026, **462 days and 64 matches each**.
Summing the rows inflates the total: he reads as **128 matches missed against an actual 64**.

Scale: **73 spells across 54 players — 5% of those with an injury record.** It is not evenly
spread: it bites hardest in the severe cases, because concurrent diagnoses are exactly what
happens in a serious injury. The players it distorts are the players the dimension exists to
identify.

**Fix: merge overlapping date ranges before counting days and matches.** This **must be fixed
before this evidence is displayed to scouts** — a scout shown "128 matches missed" for a player
who missed 64 has been actively misinformed, which is worse than showing him nothing.

### D2 — "Never injured" and "never checked" remain partly indistinguishable

A player with no injury rows may have had a clean two seasons, or may simply never have been
covered. The minutes cross-check resolves roughly **37%** of them — 2,000+ minutes is direct
evidence of availability regardless of what was reported. **The remainder is genuinely unknown
and must be labelled as such, never as clean.** Decision 12 removes the scoring harm (nothing is
scored from it any more) but not the display obligation.

---

## 10. Transparency: what the page must tell the user

**This is a hard requirement, not a nice-to-have.** Every assumption, caveat and coverage limit
behind the scores in this design must be shown to the user, on the page — not left in this
document for someone to have read in advance. The wording must be short: a recruiter reads this
between meetings, so a wall of text fails the requirement as surely as saying nothing.

The page must disclose at least the following, each as a short, plain-English line — no jargon,
no statistics vocabulary:

1. **The Medical score is a person's judgement, not a calculation.** A member of medical staff
   scored this player against the club's requirement checklist. No number on this page was turned
   into that score by the platform.
2. **The injury data informs that judgement; it never determines it.** Availability, matches
   missed, days out and the injury table are shown to the assessor as evidence. They are not added
   up, weighted, or mapped to a band.
3. **How much a blank injury record is worth depends on the league.** Share of players with an
   injury record: Championship 74%, League One 39%, League Two 32%, National League 18%; Premier
   League 2 4%, Scottish Premiership 5%, Scottish Championship 1%. (Share linked to Transfermarkt
   at all: 98%, 95%, 96%, 92%; PL2 16%, Scottish Premiership 7%, Scottish Championship 3%.) Empty
   means "we have nothing" far more often at the bottom of the pyramid than at the top.
4. **What is actually knowable**, once minutes played is used as a cross-check: Championship 84%,
   League One 64%, League Two 58%, National League 49%. About half of National League targets
   cannot be established either way — say so, do not fill the gap.
5. **What "availability" counts.** Matches missed through injury, over the last two seasons,
   against a 92-match window. A fit player who simply was not picked is **not** penalised — he
   counts as fully available.
6. **What minutes played is for.** It is not part of availability (73% of players would fall below
   the club's 60% bar on minutes alone, which reflects squad rotation rather than fitness). It is
   shown as an independent check: 2,000+ minutes is proof of availability whatever the injury
   record says, and that check behaves the same in every league (34%, 39%, 37%, 36%).
7. **What the injury categories do and do not affect.** Illness, knocks and unspecified entries
   land in "other". Category never changes the availability figure, which counts matches missed
   regardless. Categories matter only for the club's specific screening criteria.
8. **Where the 1–5 scale comes from.** It is the club's own rubric — 1 Unacceptable, 2 Below
   Standard, 3 Meets Standard, 4 Above Standard, 5 Elite. For Medical the club has defined
   minimum requirements but **no elite threshold**, so 4 and 5 have nothing to be measured
   against and 3 is the practical ceiling. Nothing in the scale is invented.
9. **A known blind spot.** A player who joined part-way through the window is measured against
   the full 92 matches, which understates his availability. It only affects players who were also
   injured, and the spells behind the figure are shown so a reader can see it.
10. **"No injuries recorded" is not the same as "no injuries".** Where the platform cannot tell,
    it says "not known" rather than showing a clean record (§9, D2).
11. **Psychological is entirely human judgement.** There is no data behind it — it is the scout's
    assessment against the club's own criteria for that position.
12. **Nothing here excludes a player.** Every flag is advisory, consistent with the rest of the
    platform.
13. **Every figure shows its provenance and its date** — scraped versus hand-entered, who entered
    it, and when.

**Implementation note.** These belong on the page itself, not buried in a separate document: a
compact "What this covers / what it doesn't" panel, plus short inline captions next to the
figures they qualify. Detailed UI layout is for the implementation plan, not this spec.

---

## 11. `assessed_composite`

**Mechanism unchanged; both inputs are now human.** Not a new formula: the existing `_composite()`
in `model/scorecard.py` called with a longer dimension list — weighted average over the dimensions
present, divided by the weight present.

`assessed_composite` is **NULL unless both** Psychological **and** Medical have a **scoring**
assessment for that (player, competition, season) — that is, `submitted` **or** `signed_off`
(Decision 14). Only a `draft` fails to reach it. Sign-off does not gate the composite; it marks
the assessment approved and controls what may be exported as final (Decision 9, §12).

### Decision 15 — `assessed_composite` carries no modelled money (agreed 2026-08-14)

**This supersedes the definition given below when this section was first written**, which added
Financial and Resale (the two *modelled* dimensions) into `assessed_composite` alongside
Psychological and Medical.

**Why that was wrong**, verified against the code:

- `constrain/filters.py` sets `RANK_COLUMN = "objective_composite"` — Performance + Physical only.
  Nothing else in the platform is ever sorted on.
- `full_composite` is **stored but never used for ranking anywhere**. A grep across
  `src/lofc/dashboard/` and `src/lofc/constrain/` finds it only in column lists that load it for
  display, never in a sort.
- The affordability toggle ("Show affordability (modelled)") reveals money **columns and optional
  gates**. It has never changed the ranking metric.

Defining `assessed_composite` to include Financial and Resale would have made it **the first
ranking number in the platform's history to contain modelled money** — and it would do so in the
default view of the assessed tier, on a platform that advertises itself as 100% real football
data. The modelled wage grid is explicitly labelled elsewhere as a screening placeholder, not
decision-grade, and Decision 15 keeps it out of any composite a recruiter might rank on.

**The corrected definition.** `assessed_composite` = **Performance + Physical + Psychological +
Medical**. Real data plus human judgement. No money. There is one assessed tier — a reader who
wants money uses the existing opt-in `full_composite` columns, exactly as today; this decision
does not add a second, money-inclusive assessed composite.

| Composite | Dimensions | Outfield weight | Role |
|---|---|---|---|
| `objective_composite` | Performance + Physical | 64% | **Default ranking — unchanged** |
| `full_composite` | + Financial + Resale (modelled) | 77% | Opt-in money view — unchanged |
| `assessed_composite` | + Psychological + Medical (no modelled money — Decision 15) | **86%** | Opt-in, assessed players only |

Worked example, a League One winger with Performance 4.0, Physical 3.5, Financial 3.0,
Resale 4.0, Psychological 3.8 (the mean of his scored criteria), and Medical **3.0** — a
**scout-entered** band, the club's "Meets Standard", signed off by the Head of Recruitment. It is
*not* computed from his injury record; the same 3.0 could sit beside a clean record or an unknown
one, and the profile shows which. Financial and Resale are shown here only because they are needed
for the `full_composite` row of the table below — under Decision 15 they never enter the assessed
row for this player or any other.

Outfield weights are the club's own numbers normalised by their 1.10 sum (`DIMENSION_WEIGHTS` in
`model/club_framework.py`): Performance 0.40/1.10 = 0.3636, Physical 0.2727, Financial 0.0909,
Resale 0.0455, Psychological 0.0909, Medical 0.1364. The four weights `assessed_composite` actually
uses — Performance, Physical, Psychological, Medical Risk — are 0.3636, 0.2727, 0.0909 and 0.1364,
summing to **0.8636**.

| Composite | Working | Weighted sum | ÷ weight present | Result | Measured |
|---|---|---|---|---|---|
| objective | 4.0×0.3636 + 3.5×0.2727 | 2.4091 | 0.6364 | **3.79** | 64% |
| full | + 3.0×0.0909 + 4.0×0.0455 | 2.8636 | 0.7727 | **3.71** | 77% |
| assessed | + 3.8×0.0909 + 3.0×0.1364 (added to **objective**, not full — Financial and Resale are excluded, Decision 15) | 3.1636 | 0.8636 | **3.66** | 86% |

(2.4091 ÷ 0.6364 = 3.786 → **3.79**; 2.8636 ÷ 0.7727 = 3.706 → **3.71**; 3.1636 ÷ 0.8636 =
3.6624 → **3.66**. The Medical band is unchanged at 3.0, so this is the same underlying scout
judgement as before Decision 15 — only which dimensions get summed alongside it has changed.)

Because Decision 15 excludes the two modelled money dimensions for **every** player, not only
those lacking a market value, a player *with* Financial and Resale figures computes his
`assessed_composite` exactly the same way as a player without them — those two dimensions are
simply never in the sum. The 86%-weight, 3.66 result above is therefore the general case, not an
edge case: a Championship player with a market value and a Scottish Premiership player without one
land on the same 86% Measured once both scout dimensions exist. The renormalisation machinery in
`_composite()` that elsewhere handles missing physical data still exists, but for
`assessed_composite` it has nothing to renormalise around money for — money is excluded by
definition, not by absence.

**Why this is safe:** the default ranking never includes the scout dimensions, so shipping this
moves nothing, and — per Decision 15 — it never includes modelled money either, so it cannot move
the platform's money-free default view even indirectly. In practice the Medical band spans 1.0–3.0
(§5: the club has defined no elite threshold), so its effect on this player's composite runs from
3.35 to 3.66 — a **0.31** swing. 2.4091 + 0.3455 + 1.0×0.1364 = 2.8910 → **3.35**; at 3.0 it is
3.1636 → **3.66**. Were the club to define an elite threshold and a 5.0 become scoreable, the top
of that range would be 2.4091 + 0.3455 + 5.0×0.1364 = 3.4366 → **3.98**. An unassessed player is
still absent from the assessed view rather than ranked badly within it (Decision 9).

---

## 12. Users, roles and sign-off

Authentication is required because an unattributed scout rating has little value and a medical
override must be traceable to a person.

- **Hashing:** `hashlib.scrypt` from the standard library. **No new dependency.**
- **Bootstrap:** the first admin is created by CLI (`python -m lofc.admin create-user`). There
  is no self-service signup.
- **Session:** Streamlit session state, cleared on logout.

| Role | Permissions |
|---|---|
| `scout` | Assess **both** dimensions; manual injury entry; view everything |
| `medical` | Assess **both** dimensions; manual injury entry; view everything |
| `head_of_recruitment` | The above, plus **sign-off** |
| `admin` | The above, plus manage users |

### Decision 16 — everyone assesses; only sign-off is restricted (agreed 2026-08-14)

An earlier draft restricted the Psychological dimension to `scout` and the Medical dimension to
`medical`. **The recruitment department is currently small enough that such a split would block
routine work**, so the only permission that gates anything is **sign-off**.

**The role becomes a record rather than a restriction.** It is displayed wherever an assessment
appears:

> Medical band **3.0** — entered by **J. Smith (scout)**, 14 Aug 2026

so a reader can see that a scout entered a medical judgement rather than medical staff. That is
the honest-record principle doing the work a hard gate would otherwise do — visible rather than
silently prevented, consistent with the rest of the platform.

**Tightening later is one line in the permission map** — no migration, no data change, no
reassigning users. When the department grows and medical bands should come only from medical
staff, the map is edited and the roles already recorded stay valid.

**Self-sign-off is permitted, and labelled.** With three people, requiring a different approver
would jam the queue constantly — and since a submitted assessment already scores (Decision 14),
blocking it would gain nothing. But the record must not hide it:

> 🟢 Signed off by **F. Idrus (self-approved)**

A second pair of eyes and one pair of eyes must not look identical in a report going to a
director.

### Sign-off — **provisional, pending the owner's discussion with the recruitment team**

This replaces the earlier latest-per-role rule, under which the most recent assessment for a role
simply won. That rule gave a junior scout's assessment authority over a senior's purely by being
newer, and with Medical now a human judgement too (Decision 12) *both* dimensions would have been
decided by recency. The model below is written as the intended design, but it is **not settled**
— the club's recruitment team may want something else, and it is an open question in §21.

**Assessment states: `draft` → `submitted` → `signed_off`.**

### Decision 14 — sign-off is NON-BLOCKING (agreed 2026-08-14)

An earlier draft had only signed-off assessments score, leaving submitted work absent from the
ranking. **That is reversed.** A submitted assessment **scores immediately and ranks normally.**

**Why.** Every other gate in this platform flags but never excludes — the club's "below 3.0 = do
not proceed", the "under 2.0 = veto", the affordability gates, the medical screening flag. A
blocking sign-off would be the **only** place the platform hides a player from the user, and it
would hide them for an administrative reason rather than a football one. It would also make
completed work invisible: a player assessed on Monday would look identical to one nobody had
opened, until someone clicked approve.

| State | Scores and ranks? | Badge shown |
|---|---|---|
| No assessment | No — genuinely no data | *(none)* |
| **`submitted`** | **Yes, normally** | 🟠 **Assessed — awaiting sign-off**, with the assessor's name and date |
| **`signed_off`** | Yes | 🟢 **Signed off by \<name\>, \<date\>** |

**What sign-off then controls.** If an unsigned assessment scored identically with no other
difference, approval would be decorative and would never happen. So approval gates **what leaves
the building**, not what you can see inside it:

- **Exports and shared player reports mark unsigned assessments as provisional**, and can exclude
  them entirely.
- **An optional "signed-off only" filter** on the Players list, for presenting a shortlist
  formally. Off by default.

**Accepted cost.** A single scout's judgement moves the ranking before anyone reviews it. That is
acceptable *only because* the badge, the assessor's name, and any competing assessment are all
visible on the profile. It would not be acceptable if the number were anonymous.

**Accessibility:** colour never carries the meaning alone — the badge always states the status in
words, because printed reports and colour-blind users lose the colour.

### The rest of the model

- **Multiple scouts may submit** an assessment for the same player, dimension, competition and
  season. The Head of Recruitment marks **one** authoritative by signing it off; that one is the
  scoring value once it exists.
- **All submissions are retained and attributed.** Nothing is deleted or averaged away, so
  disagreement between two scouts is visible on the profile rather than silently resolved.
- Signing off records the approver and the timestamp alongside the original author and date.
- Where several assessments are submitted and none signed off, the **most recent** scores, and the
  profile shows the others alongside it.

---

## 13. Data model

One Alembic migration. `player_injuries` is **already built and migrated**; the rest is designed.

**`users`** — id, username (unique), full_name, role, password_hash, is_active, created_at.

**`scout_assessments`** — id, player_id, competition_id, season_id, dimension
(`Psychological` | `Medical Risk`), author_id → users, `band` (the value that scores once signed
off), `band_computed` (Psychological only — the mean before any override, equal to `band` when not
overridden; **NULL for Medical, where nothing computes a band**), `override_reason`,
`screening_failed` (boolean, medical only), notes,
status (`draft` | `submitted` | `signed_off`), `approved_by` → users (null until signed off),
`approved_at`, created_at, updated_at.
Scoped to (player, competition, season) — the same triple as every other player row, and the
same choice already made for `watchlist`. **Not unique on that triple:** several scouts may hold
submitted assessments for the same player and dimension; at most one may be `signed_off`.

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

Manual and scraped injury records share one table and one availability function; the function
never inspects `source`. A hand-entered Scottish Premiership record and a scraped League One
record produce the availability figure the same way and are directly comparable. Only the
**display** differs — every field shows its origin ("from Transfermarkt, 14 Aug 2026" vs "entered
by <name>, 12 Aug 2026"), which §6 requires on every row.

This is safe specifically because none of it is a percentile: the availability figure is an
absolute count against a fixed window, and since Decision 12 it does not become a score at all,
so a hand-entered record cannot shift anyone else's standing. The same would not be acceptable
for Performance or Physical, which are ranked within league peers.

For manual entry, scouts record the **summary fields the club's criteria test** — availability %,
injuries in the prior 12 months by category, total days out — not an injury-by-injury log.
Same fields the scrape produces, entered in a form somebody will realistically complete.

---

## 14. Modules

| Module | Purpose | Depends on | State |
|---|---|---|---|
| `ingest/transfermarkt_common.py` | Shared polite fetch client | — | **Built** |
| `ingest/transfermarkt_injuries.py` | Scrape + parse injury spells | common | **Built** |
| `store/injuries.py` | Loads scraped spells into `player_injuries` | store | **Built** |
| `model/medical.py` | Availability figure + window (no band rule — Decision 12) | — | **Built**; needs the D1 overlap merge (§9) |
| `model/club_criteria.py` | The club's per-position criteria, verbatim, typed by kind | — | Designed |
| `model/scout_scores.py` | **Signed-off** bands keyed (player, competition, season) | store | Designed |
| `model/scorecard.py` | *Modified:* accepts `scout_bands`, emits `assessed_composite` | club_framework | Designed |
| `model/scorecard_run.py` | *Modified:* passes scout bands, persists new columns | scout_scores | Designed |
| `dashboard/auth.py` | Login gate, current user, role checks | store | Designed |
| `dashboard/injury_panel.py` | The §6 evidence panel, rendered on both pages | medical, store | Designed |
| `dashboard/tabs/assessment.py` | The entry form + sign-off queue | club_criteria, auth | Designed |
| `admin.py` | `create-user` CLI | store | Designed |

`model/scout_scores.py` mirrors the interface of the existing `financial_resale` frame, which
is why the change to `scorecard.py` is small and surgical rather than structural.

---

## 15. Dashboard

> **Corrected 2026-08-14.** This section was written before Decision 16 and still carried the
> superseded role split — an Assess button limited to `scout` and `medical`, and a rule that a
> `scout` could not enter a Medical band. Decision 16 (§12) reversed that: **every role assesses
> both dimensions, and sign-off is the only gated action.** The permission map in
> `dashboard/auth.py` already implements Decision 16; the two bullets below now match it.

- **Login gate** in front of the whole app; the current user and role are shown in the sidebar.
- **Player detail** gains, for **everyone**: the §6 evidence panel (availability, matches missed,
  injury table, minutes played, coverage warning, provenance), read-only; plus a scout section
  showing the two bands, who assessed, who signed off, and when, with the criterion breakdown.
  Submitted-but-unsigned assessments appear here marked **pending**.
- **An "Assess" button** on the profile, visible to **any authenticated user** (Decision 16).
- **New "Assessment" page** — the club's criteria for the player's position, the same evidence
  panel beside the Medical input, save → **submitted**. **Not** dimension-gated by role: every
  role may enter both bands (Decision 16), and the assessor's role is recorded and displayed
  beside the band rather than restricting which band they may enter.
- **A sign-off queue** for `head_of_recruitment` and `admin`: submitted assessments awaiting
  sign-off. Sign-off is the **only** gated assessment action.
- **Players tab** gains an optional "Assessed" ranking mode: filters to players with both
  dimensions **assessed** (submitted or signed off) and ranks on `assessed_composite`, with
  Measured % and the status badge beside every row. **Off by default.** A separate, also-optional
  "signed-off only" filter narrows it further, for presenting a shortlist formally (Decision 14).

None of this is built.

---

## 16. Presentation quality — a hard requirement

**These three surfaces are seen by people outside the recruitment room, and their presentation is
part of the product, not decoration:**

1. **The assessment form** — used by scouts and medical staff, often at speed
2. **The workflow / sign-off view** — used by the Head of Recruitment
3. **The player report** — **shared with recruitment analysts and directors**, and exported

The report carries the highest bar: it leaves the building and represents the department's
judgement. A number without visible provenance, or a layout that buries the caveat, actively
misleads its reader.

### Requirements

- **Information hierarchy.** The decision comes first — the composite, the two human bands, the
  flags. Evidence supports it below. A reader who stops after the first screen must not be
  misled by what they missed.
- **Provenance is never optional.** Every figure states where it came from and when: scraped vs
  hand-entered, the assessor's name, the approver's name, the dates, the data snapshot date.
- **Caveats sit beside the number they qualify**, not in a footer. The league coverage warning
  belongs next to the availability figure, not at the bottom of the page (§10).
- **Colour never carries meaning alone.** Every badge and flag states its status in words, because
  printed reports and colour-blind readers lose the colour (Decision 14).
- **Density with scannability.** A recruiter reads this between meetings. Dense is fine; cluttered
  is not. Tables over prose for anything comparative.
- **The export must reproduce the screen faithfully**, including flags, provenance and the
  provisional/signed-off status. An export that quietly drops a warning is worse than no export.
- **Consistency with the existing dashboard** — the club theme, the existing typography and the
  established table and band-badge patterns already in `dashboard/theme.py` and `charts.py`. This
  is one product, not a new one bolted on.

### Build-time requirement

When these surfaces are implemented, the implementer **must invoke the relevant frontend/UI design
skill** before writing the page, and follow it. This is recorded here so it is a requirement of
the spec rather than a preference expressed once in conversation. The implementation plan must
carry it into the affected tasks explicitly.

---

## 17. Testing

All parser tests run against **saved HTML fixtures. No network access in the test suite.**

- **Parsers** — injury rows including "no injuries", multi-season histories, missing "until"
  (ongoing injury), `-` in games missed, and the header row being skipped. *(Built.)*
- **Availability** — no injuries (→ 1.0), games missed exceeding scheduled games (clamped to
  0.0), window filtering by season, and an unmapped season id raising rather than silently
  returning a short window. *(Built.)*
- **Overlap merge (D1)** — two spells covering the same dates count once, not twice; the Charlie
  Wyke case (462 days / 64 matches recorded twice) yields 64, not 128; partial overlaps merge to
  the union; adjacent-but-disjoint spells still sum.
- **Unknown vs clean (D2)** — a player with no injury rows reports "not known", never 100%
  available; a player with 2,000+ minutes and no rows is reported as available *on the minutes
  evidence*, labelled as such.
- **No automatic Medical band** — there is no function mapping availability to a band, and the
  composite path rejects a Medical band that has no `author_id`.
- **Psychological** — mean, and that an incomplete set stays a draft and does not score.
- **Sign-off** — a `submitted` assessment **does** reach `assessed_composite` (Decision 14); a
  signed-off assessment wins over a newer submitted one; a `draft` never scores; nothing is deleted.
- **Composite** — `assessed_composite` NULL unless both dimensions have a scoring assessment
  (Decision 9 as amended by Decision 14),
  correct renormalisation with and without market value, and that `objective_composite` and
  `full_composite` are **byte-identical to their current values**.
- **Roles** — a `scout` cannot write a Medical band; only `head_of_recruitment` can sign off; a
  Psychological override without a reason is rejected.
- **Provenance** — manual and scraped injury records produce identical availability figures.
- **Idempotency** — re-running the scorecard writer changes nothing.

The existing **301** tests must remain green.

---

## 18. Error handling

| Situation | Behaviour |
|---|---|
| Transfermarkt down | Existing files untouched; run reports and exits non-zero |
| Single player page fails | Logged, skipped, run continues |
| Scrape interrupted | Resumes from checkpoint, skipping captured ids |
| Unknown injury phrasing | Stored raw, categorised `other`, logged |
| Player has no TM id | No scraped evidence; the panel says so; assessment still possible |
| Player has a TM id but no injury rows | Shown as **not known**, never as a clean record (§9, D2) |
| Player has no scheduled-games constant | No availability figure shown; the panel says why |
| Overlapping spells | Merged before counting (§9, D1) — must ship before the panel does |
| Unknown position group | Assessment blocked with a clear message — never scored against no criteria |
| Partial assessment | Stays `draft`; does not reach the composite |
| Submitted but unsigned | Visible and marked pending; does not reach the composite |

---

## 19. What does not change

`objective_composite`, `full_composite`, the default Players ranking, the `shortlists` table
ordering, and all **319** existing tests. `assessed_composite` is opt-in and NULL until a human
has completed **both** dimensions for that player. Sign-off is **not** required for it to score
(Decision 14).

---

## 20. Follow-ons (registered, not in scope)

- **R3b** — scout document upload. Uploads are an **evidence trail, never a scoring input**,
  which is what makes deferring them safe. Medical documents are special-category personal
  data under UK GDPR and need a club policy decision before storage is designed.
- **R3c** — player-profile export.
- Extend the injury scrape beyond the EFL if Transfermarkt ids can be resolved for
  Scottish/PL2 players. Note the ceiling: only 16% / 7% / 3% of PL2 and Scottish players are
  linked at all today, and only 4% / 5% / 1% have an injury record.
- Scrape the appearance page for squad counts, if mid-season transfers turn out to distort
  what the panel shows in practice (§4, Known limitation).

---

## 21. Open questions

- **Open — is Head of Recruitment sign-off the right model (§12)?** It is written here as the
  design, but it is **provisional pending the owner's discussion with the recruitment team.** It
  adds an approval step and a queue somebody has to work; a club that assesses two players a week
  may want it, a club that assesses forty may not. The alternative previously specified
  (latest-per-role) was rejected because it gave authority by recency alone.

- **Open — is any automatic Medical scoring worth revisiting once real scout usage exists?**
  Decision 12 removes it on the evidence available today. Once scouts have entered a body of real
  assessments, that body becomes something an automatic rule could be checked against — which is
  the one thing that has never been possible. Worth asking then, on three conditions: injury
  coverage in the lower leagues has materially improved or the club supplies its own medical
  records; the club has defined an elite threshold for Medical, without which no rule can
  discriminate upward; and the entered assessments show the automatic figure would have agreed
  with the humans. **Absent all three, the answer stays no.**
