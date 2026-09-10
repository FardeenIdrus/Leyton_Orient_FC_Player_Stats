# Impect bio backfill — design

**Date:** 2026-08-28
**Status:** agreed, not yet implemented
**Branch:** `r3a0-injury-scrape`

## Problem

Two bio fields on `players` are far emptier than the data we already hold justifies.

Measured on the live database, season 318:

| competition | players | foot stored | nationality stored |
|---|---|---|---|
| Championship | 748 | 66% | **0%** |
| League One | 749 | 68% | **0%** |
| League Two | 745 | 62% | **0%** |
| National League | 769 | 38% | **0%** |
| Scottish Premiership | 385 | **3%** | **0%** |
| Scottish Championship | 284 | **2%** | **0%** |
| Premier League 2 | 1141 | **6%** | **0%** |

The Impect parquet files already on disk carry both fields, at far higher coverage:

| competition | Impect `leg` | Impect `playerCountry` |
|---|---|---|
| Championship | 99% | 100% |
| League One | 97% | 100% |
| League Two | 93% | 100% |
| National League | 86% | 99% |
| Scottish Premiership | 97% | 100% |
| Scottish Championship | 85% | 100% |
| Premier League 2 | 63% | 100% |

Nothing in the codebase has ever written `players.nationality`. The two writers of a
players row — `store/load.py:load_players_and_metrics` and
`build_neutral._register_minted_players` — both write only `player_id`, `player_name`,
`birth_date`. `foot` arrives solely from Transfermarkt, via `model/identity.py` and
`model/valuation.py`, whose Scottish and PL2 linkage rate is 2–6%.

The player report renders "Nationality — not recorded" for every player in the platform,
and "Foot — not recorded" for 97% of Scottish players. Both are visible to the chairman
and the manager.

## What Impect cannot supply

Verified against every Impect parquet: the feed carries **no height and no contract
expiry**. Those two fields remain Transfermarkt-only, and Scottish/PL2 coverage for them
stays at 2–6% until the Transfermarkt scrape is extended to those clubs (register item
R6). This design does not address them and must not be read as doing so.

`transfermarktId` is present as a column in the Impect files but is **0.0% populated in
every league**, so it cannot improve the identity linkage either.

## Scope

Fill `players.foot` and `players.nationality` from Impect. Nothing else.

## Decision 1 — gap-fill only; the stored value always wins

Where a value is already stored, Impect never overwrites it.

The empirical case for preferring one source over the other does not exist: only 16
players have a foot value from both sources, and they agree on 13. A 16-row sample is not
grounds for relitigating 1,660 stored values, so precedence is decided on principle:

- **No regression is possible.** Nothing currently correct can be changed by this work.
- **It delivers essentially the whole win anyway.** Transfermarkt is silent for 97% of
  Scottish players, which is exactly where the gain is.
- **Nationality has no conflict at all** — the column is 100% empty.

Measured effect on the minted (Impect-spined) population under gap-fill-only:

- foot: 16 → 1,593 players (0.7% → 72%)
- nationality: 0 → 2,191 players

The English leagues gain nationality for a further ~3,600 players and top up foot from
62–68% toward Impect's 93–99%.

### Precedence is stable regardless of run order

Both Transfermarkt writers — `identity.py:bio_update_stmt` and
`valuation.py:bio_update_stmt` — write `foot = COALESCE(:transfermarkt, foot)`: an
incoming value wins, a blank leaves the stored value alone. (That COALESCE is the fix for
the 11 Aug 2026 incident in which one degraded scrape nulled 1,381 contract dates;
`tests/test_bio_backfill.py` guards it.)
This design writes `foot = COALESCE(foot, :impect)` — the stored value wins. So if Impect
fills a gap in run N and Transfermarkt later learns that player, run N+1 overwrites with
Transfermarkt and every subsequent run is a no-op. Transfermarkt wins eventually and the
state converges. This is deliberate and must not be "simplified" into a single COALESCE
direction.

## Decision 2 — reuse the metric linkage, never re-derive it

Bio must attach to the same player the metrics attached to. The only way to guarantee
that is to use the same functions:

- **StatsBomb-spined leagues** (the four English): `build_neutral.load_impect(engine,
  competition_id, season_id)`, which already returns an Impect frame keyed by our
  `player_id` via `impect_check.match_to_ours`.
- **Impect-spined leagues** (Scottish ×2, PL2): `impect_spine.attach_identity(translated,
  ours, None, overrides)`, which returns the translated rows plus `player_id` — reusing an
  existing id where the player is already known, minting `IMPECT_ID_OFFSET + playerId`
  only where they are not.

Computing `IMPECT_ID_OFFSET + playerId` directly would be **wrong**: it would mint a
second identity for every Scottish player who is already in the database under a
StatsBomb id, and attach their bio to a player row nothing else references.

## Decision 3 — carry the fields through `translate_target`

`impect_translate.translate_target` currently drops `leg` and `playerCountry`. It will
emit them as `foot` (lowercased) and `nationality`, taken from the same dominant-identity
row (`dom_idx`, highest `matchShare`) that already supplies name, birthdate and position.

**This is safe because `build_neutral.combine()` ends with `return out[ordered]`**, where
`ordered` is registry-driven. Non-registry columns are dropped by construction, so the new
columns cannot leak into `player_metrics_neutral`. A regression test pins this.

### Foot must be lowercase

Impect emits `LEFT` / `RIGHT` / `BOTH`. The stored convention is lowercase, and
`dashboard/app.py:226` filters with
`candidates["foot"].isin([foot_choice.lower(), "both"])`. An uppercase value would make
the sidebar's preferred-foot filter silently exclude every Impect-sourced player. The
mapping is explicit and tested.

Verified: `leg` takes exactly three values, and **0 of 4,865 players disagree** across
iterations.

## Decision 4 — deterministic dedupe

A player appears in several league-seasons. One row per `player_id` is chosen by sorting
on `(season_id desc, minutes desc, player_id asc)` and taking the first — freshest record,
with a total order so the result cannot vary between runs.

3 of 5,654 players carry two different nationalities (dual nationals). The tiebreak above
resolves them deterministically; no attempt is made to model dual nationality.

## Architecture

One new module, one new pipeline stage, no schema change — `foot` and `nationality`
already exist on `players`, so there is no Alembic migration.

```
src/lofc/model/player_bio.py        (new)
  IMPECT_FOOT: dict[str, str]           {"LEFT": "left", ...}
  bio_from_frames(frames) -> DataFrame  pure; dedupe + tiebreak
  collect(engine) -> DataFrame          linkage per Decision 2
  bio_fill_stmt()                       UPDATE ... COALESCE(column, :incoming)
  apply(engine, bio) -> dict[str, int]  returns rows_filled per column
  main()                                CLI entry, prints before/after counts

src/lofc/ingest/impect_translate.py (modify)  emit foot + nationality
src/lofc/pipeline.py                (modify)  new stage after Identity
tests/test_player_bio.py            (new)
```

### Pipeline placement

The stage runs **after** `lofc.model.identity`, because it must see Transfermarkt's
values in order to leave them alone. It runs before `scorecard_run` only incidentally —
no scoring input depends on foot or nationality, so this stage cannot move a single
composite. That is a property worth asserting in verification, not assuming.

## Error handling

- A missing parquet for a target is skipped with a printed line, as the existing loaders
  do. The stage never fails the pipeline for an absent optional source.
- A player in `players` who appears in no Impect file is untouched.
- An unrecognised `leg` value maps to `None` rather than being written through, so a
  future Impect enum change cannot poison the column or break the dashboard filter.
- The whole write runs in one transaction.

## Testing

Unit (pure, no database):
1. `translate_target` emits `foot` lowercased and `nationality`.
2. An unrecognised `leg` value yields `None`.
3. `combine()` drops both columns — the leak regression guard.
4. Dedupe prefers the later season, then more minutes; result is order-independent.
5. Conflicting nationalities resolve deterministically.

Integration (against the test database):
6. A stored `foot` is never overwritten by a differing Impect value.
7. A NULL incoming value never blanks a stored value.
8. A player absent from Impect is left untouched.
9. Foot values written are drawn from the lowercase set the dashboard filter uses.

## Verification after implementation

Run against the live database and report actual numbers, not expected ones:

- foot and nationality coverage per competition, before and after
- count of stored foot values changed — **must be 0**
- `objective_composite` checksum before and after — **must be identical**
  (currently 3.029285 across 6,573 rows)
- row count of `player_metrics_neutral` and its column list — unchanged
- the full test suite

## Out of scope

Height, contract expiry, birthplace, loan status, the Transfermarkt duplicate-id defect
(register P1), and extending the Transfermarkt scrape to Scottish/PL2 clubs (R6).
