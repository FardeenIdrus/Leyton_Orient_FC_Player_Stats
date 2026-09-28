# P17 + P18 — Squads & loans is dropping data we already hold

> **Status: P17 and P17b DONE 2026-09-28 (not yet deployed). P18 still planned.**
> Written and verified against the live database 2026-09-28. Every figure below is
> reproducible with the queries given — **re-run them before starting P18**, because the
> loan scrape moves and the counts will shift.
>
> **P17 + P17b as built** — `attach_loans`, `resolve_loan_player_ids`,
> `with_last_season_position` and `loan_view` in `dashboard/tabs/squads.py`, pinned by
> `tests/test_loan_join.py` (17) and `tests/test_loan_position_filter.py` (16). Suite
> 1,033 → **1,066**. Measured on the live data afterwards: squad frame still **3,783** rows
> with **409** loans attached (was 303) and 0 duplicate club/player pairs; Loans table still
> **411** rows with **380** identities resolved (was 303) and **379** positions (was 280).
> `objective_composite` unchanged — 3,345 rows, mean 3.029426.
>
> **Read `CLAUDE.md` and `plan/BUILD_PLAN.md` first.** This file is the detail behind register
> rows P17 and P18; it does not restate the platform's operating model.

---

## Why these two first

Both show the platform claiming nothing is there when Transfermarkt shows it plainly. That is
the failure mode that costs recruiters' confidence fastest — and the owner has already been
challenged on it. **Neither needs new scraping.** The data is in the database today; two joins
are failing to reach it.

---

## P17 — 106 of 411 loans are invisible on Squads & loans

### The defect

> **Corrected 2026-09-28.** An earlier draft of this file cited `squads.py:74`. That is
> `squad_frame`, which is only the FALLBACK used when `transfermarkt_squads` is empty
> (`squads.py:199`). The frame the page actually renders is **`registered_squad_frame`**
> (`squads.py:189`, rendered at `squads.py:496`), and its defect is two lines, not one.

`src/lofc/dashboard/tabs/squads.py:244` and `:297`

```python
# 244 — discards all 108 orphan loans BEFORE the merge ever sees them
"FROM player_loans WHERE season_id = %(s)s AND player_id IS NOT NULL "
...
# 297 — then merges on the key half of them do not have
out = out.merge(loans, on="player_id", how="left")
```

`player_id` is our internal id. But the squad frame is built from `transfermarkt_squads`,
which is keyed on **`tm_player_id`**. Loan rows for players we hold no internal id for
therefore never match, and the "On loan from" / "Loan ends" columns render blank. The
`IS NOT NULL` filter does most of the damage: it removes the rows at source.

The same two-key problem exists in **`loans_frame`** (`squads.py:84`), which powers the
separate Loans table. It has no `player_id` filter, so all 411 loans list there — but it
`LEFT JOIN`s `players` on `player_id`, so the 108 show with blank bio, position and rating
when we hold all three for 77 of them. Same fix, same test.

### Verified case — Joel Catesby

Transfermarkt shows him at **Accrington Stanley, on loan from Everton FC U21, until 31/05/2027**.

We hold exactly that:

```sql
SELECT player_name, tm_player_id, player_id, club_name, parent_club, loan_ends
FROM player_loans WHERE player_name ILIKE '%Catesby%';
-- Joel Catesby | 1083709 | NULL | Accrington Stanley | Everton FC U21 | 2027-05-31
```

The page renders **"On loan from" blank** — while his **contract DOES show** (8 months left),
because contract comes from a different join. So the row is half-populated from two sources,
which is why it reads as missing data rather than a broken join.

### The numbers (2026-09-28)

```sql
WITH squad AS (SELECT tm_player_id FROM transfermarkt_squads)
SELECT
 (SELECT count(*) FROM player_loans WHERE season_id=319)                          AS loans_held,
 (SELECT count(*) FROM player_loans WHERE season_id=319 AND player_id IS NOT NULL) AS join_by_player_id,
 (SELECT count(*) FROM player_loans l JOIN squad s ON s.tm_player_id=l.tm_player_id
   WHERE l.season_id=319)                                                          AS join_by_tm_id,
 (SELECT count(*) FROM player_loans l JOIN squad s ON s.tm_player_id=l.tm_player_id
   WHERE l.season_id=319 AND l.player_id IS NULL)                                  AS recovered;
```

| | |
|---|---|
| Loans held | **411** |
| Match on `player_id` (today) | **303** |
| Match on `tm_player_id` | **409** |
| **Recovered by the fix** | **106** |

The 2 that match neither have a `tm_player_id` absent from the squad scrape — a loan at a club
outside our seven leagues. Correctly absent; nothing to fix.

### Duplication risk — one real case, must be handled

`tm_player_id` is unique within each of the two source tables:

```sql
SELECT count(*) FROM (SELECT tm_player_id FROM player_loans
                      WHERE season_id=319 GROUP BY 1 HAVING count(*)>1) x;   -- 0
SELECT count(*) FROM (SELECT tm_player_id FROM transfermarkt_squads
                      GROUP BY 1 HAVING count(*)>1) x;                        -- 0
```

**But it is NOT unique in `players`.** Verified 2026-09-28 — joining loans to `players` on
`tm_player_id` returns **412 rows for 411 loans**:

```sql
SELECT lo.player_name, lo.tm_player_id, count(p.player_id), string_agg(p.player_id::text, ', ')
FROM player_loans lo JOIN players p ON p.tm_player_id = lo.tm_player_id
WHERE lo.season_id = 319 GROUP BY 1,2 HAVING count(p.player_id) > 1;
-- David Kamara | 1076889 | 2 | 2000224875, 445315
```

One StatsBomb-seeded id and one Impect-minted id both claim the same Transfermarkt player —
the known identity-split defect (15 such pairs exist across the full `players` table).

**`registered_squad_frame` already defends against this** at `squads.py:250` with
`ours.drop_duplicates("tm_player_id", keep=False)`, and the loan fix must do the same:
**drop the ambiguous key rather than pick one**. Guessing would attach one man's loan to
another. This matters — a previous version of the squad view duplicated players via a loose
join (Yusuf Akhamrich appeared twice), so the risk is not theoretical.

### Proposed fix

Prefer `player_id` where present, fall back to `tm_player_id`. Do it in the frame rather than
in SQL if that reads more clearly — `registered_squad_frame` already merges several sources in
pandas.

**Guard rails:**
- Row count must stay **3,783** — the squad frame is the scrape, and a join must never add or
  drop a row. Assert it.
- Zero duplicate `(Club, Player)` pairs afterwards.
- A loan must never attach to the wrong player: match on the exact id, never on name.

### Tests to write first

1. A loan with `player_id` set attaches (regression — the path that already works).
2. **A loan with only `tm_player_id` attaches** — the defect. Use Catesby's real values.
3. A player with no loan stays blank, not `"None"`.
4. Row count is unchanged by the join.
5. No duplicate player-club pairs after the join.
6. **A `tm_player_id` claimed by two `players` rows attaches NO loan and adds NO row** —
   use David Kamara's real values (1076889 → 2000224875, 445315).

---

## P17b — "On loan only" silently discards the Position filter

*Added to P17's scope 2026-09-28, reported by the owner. Verified the same day.*

### The defect

`src/lofc/dashboard/tabs/squads.py:511-533`

```python
position = c3.selectbox("Position", position_options(view))
view = filter_by_position(view, position)        # applied to the SQUAD frame
show  = c4.radio("Show", ["Everyone", "On loan only", "Contract expiring (under 12 months)"])

if show == "On loan only":
    loans = prepare(loans_frame(season_id, rating_season_id))
    if not loans.empty:
        loans["League"] = loans["competition_id"].map(names).fillna("-")
        if league != "All":
            loans = loans[loans["League"] == league]     # League  re-applied
        if club != "All":
            loans = loans[loans["Club"] == club]         # Club    re-applied
    view = loans                                         # <-- WHOLESALE REPLACEMENT
```

"On loan only" **replaces** `view` with a freshly built `loans_frame`. League and Club are
re-applied to the replacement; **Position is not**, so the position the user selected is
thrown away. Set Position = Centre Forward, click "On loan only", and every position comes
back. `filter_by_position` is simply never called on the loans frame.

`loans_frame` does carry a usable `Position` column — it selects `n.position_group`, which
`prepare` renames to `Position` — so the filter would work. It is never invoked.

### The second-order problem — filtering alone is not enough

`loans_frame` joins position from the CURRENT season only, and additionally requires the
competition to match (`squads.py:119-120`):

```sql
LEFT JOIN player_metrics_neutral n
       ON n.player_id = l.player_id AND n.season_id = %(cur)s
      AND n.competition_id = l.competition_id
```

There is no `"(last season)"` fallback, unlike the squad frame. Measured 2026-09-28 on 411
loans:

| | rows with a Position |
|---|---|
| Today (`player_id` join, this season only) | **280 (68%)** |
| After P17's `tm_player_id` fix | **359 (87%)** |
| Plus a last-season fallback | **379 (92%)** |

So merely calling `filter_by_position` would correctly filter — but against a column blank
for a third of loanees, and `filter_by_position` deliberately excludes rows with no position
("he cannot be asserted into a position group"). **Fix both together or the bug fix reads as
a new one**: the recruiter selects Centre Forward and loses 131 loanees who have one.

The `AND n.competition_id = l.competition_id` condition costs only 2 rows and is a separate,
optional tidy — not required here.

### The fix

1. Apply `filter_by_position(loans, position)` after the League/Club filters.
2. Give `loans_frame` the same last-season position fallback the squad frame has, with the
   **same `"(last season)"` suffix** — `_bare_position` already strips it, so the filter
   keeps working across both tiers.
3. Build `position_options` from the frame actually being shown, so the dropdown never
   offers a position the current view cannot contain.

### Tests to write first

1. **"On loan only" + Position=Centre Forward returns only centre forwards** — the defect.
2. League and Club filters still apply on the loans view (regression).
3. A loanee with no current-season position but a last-season one is INCLUDED, suffixed.
4. A loanee with no known position at all is excluded from a specific position filter but
   present under "All".
5. The suffix is stripped for matching — `"Centre Forward (last season)"` matches
   `"Centre Forward"`.
6. Switching Show back to "Everyone" restores the unfiltered-by-loan squad view.

---

## P18 — 518 squad members show no position

### The defect

The Position column uses **Impect's** position, derived from minutes played, with a fallback to
last season's Impect position labelled `"(last season)"`. There is no third tier.
`transfermarkt_squads.position` is populated for **100% of 3,783 rows** and is never read.

### The numbers (2026-09-28)

| | |
|---|---|
| Squad rows | 3,783 |
| Position observed in 2026/27 | 2,650 |
| Position from last season, labelled | 615 |
| **Blank** | **518** |
| Rows where the **scrape** has a position | **3,783 (100%)** |

### The complication — the vocabularies differ

Transfermarkt uses 16 position names; the platform uses 8 groups. A mapping is required, so
this is **not** a one-line fallback.

| Transfermarkt | n | → platform group |
|---|---|---|
| Centre-Back | 693 | Centre Back |
| Centre-Forward | 551 | Centre Forward |
| Central Midfield | 509 | Central Mid |
| Goalkeeper | 398 | Goalkeeper |
| Right-Back | 302 | Full Back |
| Left-Back | 290 | Full Back |
| Defensive Midfield | 234 | Defensive Mid |
| Attacking Midfield | 227 | Attacking Mid |
| Left Winger | 220 | Winger |
| Right Winger | 207 | Winger |
| Left Midfield | 58 | **decide** — Winger or Central Mid? |
| Right Midfield | 50 | **decide** — Winger or Central Mid? |
| Midfielder | 28 | **decide** — too vague to map? |
| Striker | 7 | Centre Forward |
| Second Striker | 5 | **decide** — Centre Forward or Attacking Mid? |
| Defender | 4 | **decide** — too vague to map? |

The first ten (3,631 of 3,783) are unambiguous and match the merges the club framework already
makes — Left/Right Back → Full Back, Left/Right Winger → Winger, exactly as
`club_framework.PERFORMANCE_METRICS` does.

The last six (145 rows) need a decision. **The honest default for the vague ones
(`Midfielder`, `Defender`, 32 rows) is to leave them blank** rather than assert a group the
source did not state — the same rule the platform already applies to unknown contract dates.

### Decisions needed before coding

1. **Should Impect still win where both exist?** My view: **yes.** Impect's is derived from
   minutes actually played, which is where he lines up; Transfermarkt's is a registration
   label. The scrape should be the third tier, used only when Impect has nothing.
2. **Left/Right Midfield (108 rows)** — Winger or Central Mid? Affects which peer group a
   reader assumes.
3. **`Midfielder` / `Defender` (32 rows)** — map or leave blank? Recommend blank.

### Labelling — non-negotiable

The column already distinguishes observed from inferred with `"(last season)"`. A scrape-sourced
position is **also** inferred and must say so — e.g. `"Full Back (registered)"`. Three tiers,
three visibly different states. Do not silently mix a registration label with an observed one.

> Per the UX principle in `CLAUDE.md` (register P15): **the label carries the fact.** Do not add
> a caption explaining the tiers.

### Tests to write first

1. Impect's position wins where both exist.
2. The scrape's position fills in where Impect has none, **labelled as registered**.
3. `"(last season)"` still beats the scrape — an Impect position from last season is a stronger
   claim than a registration label.
4. Every one of the 16 Transfermarkt values maps or is deliberately left blank — no value
   silently falls through.
5. A vague value (`Midfielder`) does not become a specific group.
6. The Position **filter** (`filter_by_position`) still works across all three tiers, matching
   on the bare position with any suffix stripped.

---

## Order and sizing

**P17 first**, with **P17b** folded into the same piece of work. Smaller, no design
decisions, and it fixes a case the owner has already been challenged on. P17b touches the
same two frames, so doing it separately would mean reading `loans_frame` twice.

**P18 second**, and only after the three mapping decisions are answered. Roughly the size of
the Central Mid / Box-to-Box work — the code is small, the decisions are the work.

**Neither changes any score.** `objective_composite` is untouched; this is display only. Verify
that explicitly after each:

```sql
SELECT count(*), round(avg(objective_composite)::numeric,6)
FROM player_scorecards WHERE archetype='All Metrics' AND season_id=318;
-- expect 3345 rows, mean 3.0293
```

---

## After these, still open (do not drop)

- **P14 — stale data is invisible.** No freshness date on screen for scoring data, and nothing
  reads `data/ops/last_failure`. A failed Monday cron serves last week's numbers looking
  normal. **Already happened once** (2026-09-07). Marked **do before January**.
- **P12 — assessments cannot be withdrawn or corrected.** INSERT-only; a mistake prints "Final"
  on a report permanently. Test data had to be cleared with hand-written SQL.
- P15 caption debt · P13 discovery vs confirmation · P11 per-match tracking · league-strength
  adjustment.
