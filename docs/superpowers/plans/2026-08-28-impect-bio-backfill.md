# Impect bio backfill — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill `players.foot` and `players.nationality` from the Impect feed already on
disk, without ever overwriting a stored value.

**Architecture:** `impect_translate.translate_target` starts emitting `foot` and
`nationality`; a new `model/player_bio.py` links them to our `player_id` using the *same*
functions the metric build uses, dedupes deterministically, and writes them with
`COALESCE(column, :incoming)` so the stored value always wins. A new pipeline stage runs
after Identity.

**Tech Stack:** Python 3.11 (in Docker), pandas, SQLAlchemy 2.0 Core, pytest, Postgres 16.

**Spec:** `docs/superpowers/specs/2026-08-28-impect-bio-backfill-design.md`

## Global Constraints

- **Everything runs in the container:** `docker compose exec -T app <cmd>`. The host is
  Python 3.14 and will not run this code.
- **No schema change and no Alembic migration.** `foot` and `nationality` already exist
  on `players`.
- **Foot values are lowercase**, drawn from exactly `{"left", "right", "both"}`.
  `dashboard/app.py:226` filters with `.isin([choice.lower(), "both"])`; an uppercase
  value silently breaks that filter.
- **The new write is `COALESCE(column, :incoming)` — stored wins.** This is the OPPOSITE
  direction from `identity.py` / `valuation.py`, which are `COALESCE(:incoming, column)`.
  Do not "harmonise" them.
- **Never compute `IMPECT_ID_OFFSET + playerId` directly.** Use the linkage functions
  named in Task 3; the offset alone mints duplicate identities.
- **Nothing in scoring may change.** Verified: no scoring module references `foot` or
  `nationality`.
- Run the full suite with `docker compose exec -T app pytest -q`. Baseline measured
  2026-08-28: **739 passing, 0 failing.**

---

### Task 1: `translate_target` emits foot and nationality

**Files:**
- Modify: `src/lofc/ingest/impect_translate.py` (the `ident` selection, ~line 59, and the
  rename block, ~line 87)
- Test: `tests/test_impect_translate.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `translate_target(target)` frames gain two columns — `foot`
  (`str | None`, lowercase) and `nationality` (`str | None`). Tasks 3 and 4 rely on
  these exact names.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_impect_translate.py`. Match the fixture style already in that file —
read it first and build the input frame the same way it builds its existing ones.

```python
def test_translate_emits_lowercase_foot_and_nationality(tmp_path, monkeypatch):
    """Impect ships LEG as LEFT/RIGHT/BOTH. The stored convention is lowercase, and
    dashboard/app.py filters foot with .isin([choice.lower(), "both"]) -- an uppercase
    value would silently exclude every Impect-sourced player from that filter."""
    frame = _minimal_impect_frame(leg="RIGHT", playerCountry="Scotland")
    out = _translate(frame)
    assert out.loc[0, "foot"] == "right"
    assert out.loc[0, "nationality"] == "Scotland"


def test_unrecognised_leg_becomes_none_rather_than_passing_through():
    """A future Impect enum change must not poison the column or break the filter."""
    frame = _minimal_impect_frame(leg="UNKNOWN_NEW_VALUE", playerCountry="England")
    out = _translate(frame)
    assert out.loc[0, "foot"] is None


def test_missing_leg_and_country_become_none():
    frame = _minimal_impect_frame(leg=None, playerCountry=None)
    out = _translate(frame)
    assert out.loc[0, "foot"] is None
    assert out.loc[0, "nationality"] is None
```

- [ ] **Step 2: Run them and confirm they fail**

```bash
docker compose exec -T app pytest tests/test_impect_translate.py -q
```
Expected: FAIL — `KeyError: 'foot'`.

- [ ] **Step 3: Implement**

In `src/lofc/ingest/impect_translate.py`, add the mapping near the top:

```python
# Impect ships LEG as an upper-case enum. The stored convention is lowercase, and
# dashboard/app.py:226 filters with .isin([choice.lower(), "both"]) -- an upper-case
# value would silently exclude every Impect-sourced player from the foot filter.
# An unrecognised value maps to None rather than passing through, so a future enum
# change cannot poison the column.
IMPECT_FOOT = {"LEFT": "left", "RIGHT": "right", "BOTH": "both"}
```

Extend the dominant-identity selection (currently
`ident = frame.loc[dom_idx, ["playerId", "playerName", "birthdate", "position"]]`) to
carry the two new source columns. Guard on presence — an older parquet may lack them:

```python
    bio_cols = [c for c in ("leg", "playerCountry") if c in frame.columns]
    ident = frame.loc[dom_idx,
                      ["playerId", "playerName", "birthdate", "position"] + bio_cols]
```

Then in the rename block, add `"playerCountry": "nationality"` to the existing dict, and
after the `birth_date` coercion add:

```python
    result["foot"] = (result["leg"].map(IMPECT_FOOT) if "leg" in result.columns
                      else None)
    result = result.drop(columns=["leg"], errors="ignore")
    if "nationality" not in result.columns:
        result["nationality"] = None
    # object-dtype NaN reads as a value downstream; None is what the loaders expect.
    for c in ("foot", "nationality"):
        result[c] = result[c].where(result[c].notna(), None)
```

- [ ] **Step 4: Run the tests**

```bash
docker compose exec -T app pytest tests/test_impect_translate.py -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lofc/ingest/impect_translate.py tests/test_impect_translate.py
git commit -m "impect: carry preferred foot and nationality through translation"
```

---

### Task 2: pin that the new columns cannot leak into `player_metrics_neutral`

This task exists because Task 1 widened a frame that flows into the metric table's
writer. `combine()` ends with `return out[ordered]`, so the columns are dropped by
construction — this pins that guarantee before anything comes to depend on it.

**Files:**
- Test only: `tests/test_build_neutral.py` (create if absent; check first)

**Interfaces:**
- Consumes: `translate_target` from Task 1.
- Produces: nothing.

- [ ] **Step 1: Write the test**

Read the existing `combine()` tests first and reuse their fixtures if present.

```python
def test_combine_drops_bio_columns_so_they_cannot_reach_the_metric_table():
    """translate_target now carries foot/nationality. player_metrics_neutral has no such
    columns, and write_for does a raw to_sql -- a leaked column would fail the insert.
    combine()'s registry-driven `out[ordered]` is what prevents it."""
    spine = _spine_fixture()
    impect = _impect_fixture().assign(foot="right", nationality="Scotland")
    out = combine(spine, impect, None, None)
    assert "foot" not in out.columns
    assert "nationality" not in out.columns
```

- [ ] **Step 2: Run it**

```bash
docker compose exec -T app pytest tests/test_build_neutral.py -q
```
Expected: PASS immediately — this is a characterisation test, not a red-green cycle. If
it FAILS, stop and report: the leak is real and Task 1 needs rework.

- [ ] **Step 3: Commit**

```bash
git add tests/test_build_neutral.py
git commit -m "test: pin that bio columns cannot leak into player_metrics_neutral"
```

---

### Task 3: `model/player_bio.py` — pure logic

Pure functions only. No database, no pipeline wiring — those are Task 4.

**Files:**
- Create: `src/lofc/model/player_bio.py`
- Test: `tests/test_player_bio.py`

**Interfaces:**
- Consumes: `foot` / `nationality` columns from Task 1.
- Produces, relied on by Task 4:
  - `bio_from_frames(frames: list[pd.DataFrame]) -> pd.DataFrame` — returns columns
    exactly `["player_id", "foot", "nationality"]`, one row per `player_id`.
  - `bio_fill_stmt()` — a SQLAlchemy `update` with bindparams `pid`, `ft`, `nat`.

- [ ] **Step 1: Write the failing tests**

```python
"""Filling foot and nationality from Impect.

The stored value always wins: Impect fills gaps, it never corrects. See
docs/superpowers/specs/2026-08-28-impect-bio-backfill-design.md, Decision 1.
"""

import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from lofc.model.player_bio import bio_fill_stmt, bio_from_frames
from lofc.store.models import Base


def _frame(rows):
    return pd.DataFrame(rows, columns=["player_id", "foot", "nationality",
                                       "minutes", "season_id"])


def test_one_row_per_player():
    out = bio_from_frames([_frame([[1, "left", "Wales", 900, 318],
                                   [1, "left", "Wales", 400, 318]])])
    assert len(out) == 1
    assert list(out.columns) == ["player_id", "foot", "nationality"]


def test_the_later_season_wins():
    out = bio_from_frames([_frame([[1, "left", "Wales", 3000, 318],
                                   [1, "right", "Scotland", 90, 319]])])
    assert out.loc[out.player_id == 1, "nationality"].iloc[0] == "Scotland"


def test_within_a_season_more_minutes_wins():
    out = bio_from_frames([_frame([[1, "left", "Wales", 90, 318],
                                   [1, "right", "Scotland", 3000, 318]])])
    assert out.loc[out.player_id == 1, "nationality"].iloc[0] == "Scotland"


def test_result_does_not_depend_on_input_order():
    """3 of 5,654 players carry two nationalities. Whichever wins must be the same on
    every run, or the column churns for no reason."""
    a = [[1, "left", "Wales", 500, 318], [1, "right", "Scotland", 500, 318]]
    first = bio_from_frames([_frame(a)])
    second = bio_from_frames([_frame(list(reversed(a)))])
    pd.testing.assert_frame_equal(first, second)


def test_a_sparse_newer_season_does_not_discard_an_older_seasons_value():
    """Season 319 (2026/27) is already configured. Early-season files have poor `leg`
    coverage, so a fresher row can carry nationality but no foot. Taking the freshest
    ROW would drop the foot value 2025/26 did have; each field is taken independently."""
    out = bio_from_frames([_frame([[1, None, "Scotland", 90, 319],
                                   [1, "left", "Scotland", 3000, 318]])])
    assert out.loc[0, "foot"] == "left"
    assert out.loc[0, "nationality"] == "Scotland"


def test_rows_with_neither_field_are_dropped():
    """A row carrying nothing is not worth an UPDATE."""
    out = bio_from_frames([_frame([[1, None, None, 900, 318]])])
    assert out.empty


def test_empty_input_returns_the_empty_shape_not_an_error():
    out = bio_from_frames([])
    assert out.empty
    assert list(out.columns) == ["player_id", "foot", "nationality"]


@pytest.fixture
def engine():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    pd.DataFrame([{"player_id": 1, "player_name": "Stored Both",
                   "foot": "right", "nationality": "England"},
                  {"player_id": 2, "player_name": "Stored Neither",
                   "foot": None, "nationality": None}]
                 ).to_sql("players", eng, index=False, if_exists="append")
    return eng


def _row(engine, pid):
    with engine.begin() as c:
        return dict(c.execute(text("SELECT foot, nationality FROM players "
                                   "WHERE player_id = :p"), {"p": pid}).mappings().one())


def test_a_stored_value_is_never_overwritten(engine):
    """Decision 1. Only 16 players have foot from both sources and they agree on 13 --
    not grounds to relitigate 1,660 stored values."""
    with engine.begin() as c:
        c.execute(bio_fill_stmt(), [{"pid": 1, "ft": "left", "nat": "Brazil"}])
    assert _row(engine, 1) == {"foot": "right", "nationality": "England"}


def test_a_gap_is_filled(engine):
    with engine.begin() as c:
        c.execute(bio_fill_stmt(), [{"pid": 2, "ft": "left", "nat": "Brazil"}])
    assert _row(engine, 2) == {"foot": "left", "nationality": "Brazil"}


def test_an_incoming_null_never_blanks_a_stored_value(engine):
    """The 11 Aug 2026 failure mode: one degraded source nulled 1,381 contract dates."""
    with engine.begin() as c:
        c.execute(bio_fill_stmt(), [{"pid": 1, "ft": None, "nat": None}])
    assert _row(engine, 1) == {"foot": "right", "nationality": "England"}


def test_a_player_not_in_the_batch_is_untouched(engine):
    with engine.begin() as c:
        c.execute(bio_fill_stmt(), [{"pid": 2, "ft": "left", "nat": "Brazil"}])
    assert _row(engine, 1) == {"foot": "right", "nationality": "England"}
```

- [ ] **Step 2: Run and confirm they fail**

```bash
docker compose exec -T app pytest tests/test_player_bio.py -q
```
Expected: FAIL — `ModuleNotFoundError: lofc.model.player_bio`.

- [ ] **Step 3: Implement the pure half**

```python
"""Fill players.foot and players.nationality from the Impect feed.

Impect carries preferred foot for 85-99% of players in every league; Transfermarkt,
our only previous source, reaches 2-6% in the Scottish leagues and PL2. Nationality has
never been written by anything at all -- the column is empty for all 5,848 players while
Impect carries it at ~100%.

The stored value ALWAYS wins: this fills gaps, it never corrects. Only 16 players have a
foot value from both sources, which is far too small a sample to justify overwriting
1,660 stored values -- so the safe direction is the only one taken. See
docs/superpowers/specs/2026-08-28-impect-bio-backfill-design.md.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import bindparam, func, update

from lofc.store.models import Player

BIO_COLUMNS = ["player_id", "foot", "nationality"]


def bio_from_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """One row per player_id, chosen deterministically across every league season.

    A player appears in several league seasons. The freshest record wins: sort by
    season then minutes, with player_id last so the order is TOTAL -- two rows that tie
    on both must still resolve the same way on every run, or the column churns.
    """
    usable = [f for f in frames if f is not None and not f.empty]
    if not usable:
        return pd.DataFrame(columns=BIO_COLUMNS)

    all_rows = pd.concat(usable, ignore_index=True)
    for c in ("foot", "nationality"):
        if c not in all_rows.columns:
            all_rows[c] = None
    # A row carrying neither field is not worth an UPDATE.
    all_rows = all_rows.dropna(subset=["foot", "nationality"], how="all")
    if all_rows.empty:
        return pd.DataFrame(columns=BIO_COLUMNS)

    ranked = all_rows.sort_values(
        ["season_id", "minutes", "player_id"], ascending=[False, False, True],
        kind="mergesort")
    # Per FIELD, not per row. drop_duplicates would take the freshest row wholesale, so
    # a sparse early-season 2026/27 record carrying nationality but no foot would win --
    # and silently discard the foot value the completed 2025/26 season did have.
    # groupby.first() skips nulls per column, so each field independently takes the
    # freshest value that actually exists.
    out = (ranked.groupby("player_id", sort=False)[["foot", "nationality"]]
                 .first().reset_index())
    out = out.dropna(subset=["foot", "nationality"], how="all")
    out["player_id"] = out["player_id"].astype("int64")
    return out[BIO_COLUMNS].reset_index(drop=True)


def bio_fill_stmt():
    """UPDATE players SET foot/nationality, filling ONLY where the column is empty.

    Note the COALESCE direction: `COALESCE(column, :incoming)` -- the STORED value wins.
    This is deliberately the opposite of identity.py and valuation.py, which are
    `COALESCE(:incoming, column)` so a fresh Transfermarkt scrape can correct a value.
    Impect is a gap-filler here, not a corrector; do not harmonise the two directions.
    """
    table = Player.__table__
    return (update(table)
            .where(table.c.player_id == bindparam("pid"))
            .values(foot=func.coalesce(table.c.foot, bindparam("ft")),
                    nationality=func.coalesce(table.c.nationality, bindparam("nat"))))
```

- [ ] **Step 4: Run the tests**

```bash
docker compose exec -T app pytest tests/test_player_bio.py -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lofc/model/player_bio.py tests/test_player_bio.py
git commit -m "model: player_bio -- deterministic Impect bio selection, gap-fill only"
```

---

### Task 4: linkage, CLI and pipeline stage

**Files:**
- Modify: `src/lofc/model/player_bio.py` (append `collect`, `apply`, `main`)
- Modify: `src/lofc/pipeline.py` (new stage after the Identity step)
- Modify: `cli_commands.txt` (append the command with a comment, per CLAUDE.md)

**Interfaces:**
- Consumes: `bio_from_frames`, `bio_fill_stmt` (Task 3); `translate_target` (Task 1).
- Produces: `python -m lofc.model.player_bio` as a pipeline stage.

- [ ] **Step 1: Implement `collect`**

Append to `src/lofc/model/player_bio.py`. The linkage MUST come from the same functions
the metric build uses — see Global Constraints.

```python
def collect(engine) -> pd.DataFrame:
    """Bio for every Impect target, keyed by OUR player_id.

    The linkage is not re-derived here. It comes from the same two functions the metric
    build uses, so a player's bio can never attach to a different identity than their
    metrics did:

      - StatsBomb-spined leagues (the four English): build_neutral.load_impect, which
        matches through impect_check.match_to_ours.
      - Impect-spined leagues (Scottish x2, PL2): impect_spine.attach_identity, which
        REUSES an existing player_id where the player is already known and mints one
        only where they are not.

    Computing IMPECT_ID_OFFSET + playerId directly would be wrong: it would mint a
    second identity for every Scottish player already in the database under a StatsBomb
    id, and hang their bio off a row nothing else references.
    """
    from lofc.config import settings
    from lofc.ingest.impect import averages_path
    from lofc.ingest.impect_translate import translate_target
    from lofc.model.build_neutral import load_impect
    from lofc.model.impect_check import load_overrides
    from lofc.model.impect_spine import attach_identity

    ours = pd.read_sql(
        "SELECT player_id, player_name, birth_date, tm_player_id FROM players", engine)
    overrides = load_overrides()

    frames: list[pd.DataFrame] = []
    for target in settings.impect_targets:
        if not averages_path(target.iteration_id).exists():
            print(f"  (skipped {target.label}: no parquet on disk)")
            continue
        # Verified against the live config: the four English leagues carry an
        # sb_competition_id for seasons 317/318; the Scottish leagues, PL2, and EVERY
        # 2026/27 target carry None -- 2026/27 has no StatsBomb data, so it is
        # Impect-spined too, and correctly takes the attach_identity branch.
        if target.sb_competition_id is not None:
            linked = load_impect(engine, target.sb_competition_id, target.sb_season_id)
        else:
            linked = attach_identity(translate_target(target), ours,
                                     None, overrides)
        if linked is None or linked.empty:
            continue
        keep = linked.reindex(
            columns=["player_id", "foot", "nationality", "minutes"]).copy()
        keep["season_id"] = target.season_id
        frames.append(keep.dropna(subset=["player_id"]))
        print(f"  {target.label}: {len(keep)} players linked")
    return bio_from_frames(frames)
```

The `sb_competition_id is not None` predicate has already been verified against the
live config — the 14 targets for seasons 317/318 split 8 English (id present) / 6
Scottish+PL2 (`None`), and all 7 of the 2026/27 targets are `None`.

- [ ] **Step 2: Implement `apply` and `main`**

```python
def apply(engine, bio: pd.DataFrame) -> dict[str, int]:
    """Write the fill, reporting how many rows actually gained each field.

    Counted by comparing before and after rather than by counting UPDATE statements:
    every row is updated, but most are no-ops because the value is already stored.
    """
    if bio.empty:
        return {"foot": 0, "nationality": 0}
    before = pd.read_sql("SELECT player_id, foot, nationality FROM players", engine)
    rows = [{"pid": int(r.player_id),
             "ft": r.foot if pd.notna(r.foot) else None,
             "nat": r.nationality if pd.notna(r.nationality) else None}
            for r in bio.itertuples()]
    with engine.begin() as conn:
        conn.execute(bio_fill_stmt(), rows)
    after = pd.read_sql("SELECT player_id, foot, nationality FROM players", engine)
    merged = before.merge(after, on="player_id", suffixes=("_b", "_a"))
    return {c: int((merged[f"{c}_b"].isna() & merged[f"{c}_a"].notna()).sum())
            for c in ("foot", "nationality")}


def main() -> None:
    from lofc.store.load import get_engine
    engine = get_engine()
    for column in ("foot", "nationality"):
        n = pd.read_sql(
            f"SELECT count(*) n FROM players WHERE {column} IS NOT NULL", engine).n[0]
        print(f"before: {column} on {n} players")
    filled = apply(engine, collect(engine))
    print(f"filled: foot +{filled['foot']}, nationality +{filled['nationality']}")


if __name__ == "__main__":
    main()
```

`get_engine` is imported from `lofc.store.load` (verified — this is where
`build_neutral.py:39` takes it from, NOT `lofc.store.db`).

- [ ] **Step 3: Run it against the live database and record real numbers**

```bash
docker compose exec -T app python -m lofc.model.player_bio
```

- [ ] **Step 4: Verify nothing that should be stable moved**

```bash
docker compose exec -T db psql -U lofc -d lofc -c "
SELECT count(*) rows, round(avg(objective_composite)::numeric,6) mean
FROM player_scorecards;"
```
Expected, unchanged (measured 2026-08-28): **10,533 rows, mean 3.027036**. If either
moved, STOP and report —
no scoring module reads foot or nationality, so a change means something else broke.

```bash
docker compose exec -T db psql -U lofc -d lofc -c "
SELECT count(*) FROM player_metrics_neutral;"
```
Expected, unchanged (measured 2026-08-28): **11,222 rows**.

- [ ] **Step 5: Wire the pipeline stage**

In `src/lofc/pipeline.py`, immediately AFTER the Injuries step (which follows Identity):

```python
        # Fills players.foot / players.nationality from Impect. Runs AFTER Identity so
        # it can see Transfermarkt's values and leave them alone: this stage is a
        # gap-filler (COALESCE(column, :incoming)), never a corrector. No scoring input
        # reads either column, so it cannot move a composite.
        ("Player bio: fill preferred foot + nationality from Impect",
         [sys.executable, "-m", "lofc.model.player_bio"]),
```

- [ ] **Step 6: Confirm the stage is registered in the right position**

```bash
docker compose exec -T app python -c "
from lofc.pipeline import build_steps
for i,(label,_) in enumerate(build_steps()): print(i, label)" | tail -8
```
Expected: the bio stage appears after Identity and Injuries, before the scorecard step.

- [ ] **Step 7: Append to `cli_commands.txt`**

```
# Fill preferred foot + nationality on `players` from the Impect feed (gap-fill only --
# a stored Transfermarkt value is never overwritten). Runs inside the pipeline; this is
# the standalone form.
docker compose exec app python -m lofc.model.player_bio
```

- [ ] **Step 8: Full suite**

```bash
docker compose exec -T app pytest -q
```
Expected: **739 + the new tests**, zero failures.

- [ ] **Step 9: Commit**

```bash
git add src/lofc/model/player_bio.py src/lofc/pipeline.py cli_commands.txt
git commit -m "pipeline: fill preferred foot and nationality from Impect"
```

---

### Task 5: verify the outcome and update the documentation

**Files:**
- Modify: `plan/BUILD_PLAN.md` (CURRENT STATE + pending work register)
- Modify: `docs/DATA_ARCHITECTURE.md` (bio provenance)
- Modify: `CLAUDE.md` (one-paragraph status)

- [ ] **Step 1: Measure coverage per competition, after**

```bash
docker compose exec -T app python -c "
import pandas as pd
from sqlalchemy import create_engine
from lofc.config import settings
e = create_engine(settings.database_url)
q = '''SELECT m.competition_id, count(DISTINCT m.player_id) players,
  round(100.0*count(DISTINCT p.player_id) FILTER (WHERE p.foot IS NOT NULL)
        /count(DISTINCT m.player_id),0) foot,
  round(100.0*count(DISTINCT p.player_id) FILTER (WHERE p.nationality IS NOT NULL)
        /count(DISTINCT m.player_id),0) nat
FROM player_metrics_neutral m JOIN players p USING (player_id)
WHERE m.season_id = 318 GROUP BY 1 ORDER BY 1'''
print(pd.read_sql(q, e).to_string(index=False))"
```

Record the table. The Scottish and PL2 rows are the point of the exercise; if their
`foot` has not moved from 2-6% into the 60-97% range, the linkage is wrong — STOP and
report rather than documenting a non-result.

- [ ] **Step 2: Confirm no stored foot value changed**

The COALESCE direction guarantees this, but it is the one property whose failure would
be silent and damaging, so verify it rather than trusting it. Before the run, capture:

```bash
docker compose exec -T db psql -U lofc -d lofc -tAc "
SELECT count(*) FROM players WHERE foot IS NOT NULL;" > /tmp/foot_before.txt
```

After, confirm the count only ever grew, and that a spot sample of previously-stored
values is unchanged:

```bash
docker compose exec -T db psql -U lofc -d lofc -c "
SELECT foot, count(*) FROM players GROUP BY foot ORDER BY 2 DESC;"
```
The pre-existing counts (right 1234, left 406, both 20) must each have grown or held —
never shrunk.

- [ ] **Step 3: Check the player report renders the new fields**

Open the dashboard, generate a report for a Scottish Premiership player, and confirm the
bio block shows a real foot and nationality instead of "not recorded".

```bash
docker compose exec -T app python -c "
import pandas as pd
from sqlalchemy import create_engine
from lofc.config import settings
e = create_engine(settings.database_url)
print(pd.read_sql('''SELECT p.player_name, p.foot, p.nationality
FROM players p JOIN player_metrics_neutral m USING (player_id)
WHERE m.competition_id = 901 AND m.season_id = 318 AND p.foot IS NOT NULL
LIMIT 5''', e).to_string(index=False))"
```

- [ ] **Step 4: Confirm the dashboard foot filter still works**

The lowercase constraint exists for this. Every distinct foot value must be in the set
the filter tests against:

```bash
docker compose exec -T db psql -U lofc -d lofc -c "
SELECT DISTINCT foot FROM players WHERE foot IS NOT NULL;"
```
Expected: exactly `left`, `right`, `both`. Anything else breaks
`dashboard/app.py:226` — STOP and fix.

- [ ] **Step 5: Update the documentation**

- `plan/BUILD_PLAN.md`: note in CURRENT STATE that foot and nationality now fill from
  Impect with real coverage numbers; add to the pending work register that **height and
  contract expiry remain Transfermarkt-only and stay at 2-6% for Scottish/PL2** (item
  R6), so the gap is recorded rather than assumed closed.
- `docs/DATA_ARCHITECTURE.md`: record bio provenance per field — which source supplies
  each, and the gap-fill precedence rule with its reason.
- `CLAUDE.md`: one sentence in the status paragraph.

- [ ] **Step 6: Commit**

```bash
git add plan/BUILD_PLAN.md docs/DATA_ARCHITECTURE.md CLAUDE.md
git commit -m "docs: record Impect bio provenance and the remaining height/contract gap"
```

---

## Self-review

**Spec coverage:** Problem → Tasks 1/3/4. Decision 1 (gap-fill) → Task 3 statement +
tests. Decision 2 (reuse linkage) → Task 4 Step 1. Decision 3 (translate + no leak) →
Tasks 1 and 2. Decision 4 (dedupe) → Task 3 tests. "What Impect cannot supply" → Task 5
Step 5, recorded as a live gap. Testing section → Tasks 1-3. Verification section →
Task 5.

**Type consistency:** `bio_from_frames` returns `["player_id", "foot", "nationality"]` in
Task 3 and is consumed with exactly those names in Task 4. `bio_fill_stmt` binds `pid` /
`ft` / `nat` in both the tests and `apply`.

**Soft spots closed during review:** the `sb_competition_id` predicate and the
`get_engine` import path (`lofc.store.load`, not `lofc.store.db`) were both verified
against the live config and codebase while writing this plan. A row-wise dedupe bug was
found and fixed the same way — see the per-field `groupby.first()` note in Task 3, which
would otherwise have destroyed foot coverage once 2026/27 files land. The fixture helpers
in Tasks 1 and 2
(`_minimal_impect_frame`, `_spine_fixture`) must be built to match the conventions
already in those test files, which the implementer is told to read first.
