# Player Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A one-page landscape player report — rendered in the dashboard and exported as a print-ready PDF — that a scout, the Head of Recruitment, the manager and the chairman can all read, for any player in any of the eight position groups.

**Architecture:** Pure Python assembles a `ReportData` object from data that already exists (percentiles, composites, assessments, injury evidence). Pure functions render each chart as **inline SVG**. A Jinja2 template lays the page out with **print CSS**. The dashboard serves the HTML; a host-side Playwright command turns the same HTML into a PDF. One template, one stylesheet, one set of numbers — the page and the PDF cannot drift.

**Tech Stack:** Python 3.11 (Docker), Jinja2 (already installed), inline SVG (no chart library in the export path), Playwright/Chromium on the host for PDF, pytest.

**Spec:** `docs/superpowers/specs/2026-08-28-player-report-design.md`

## Global Constraints

- **Everything runs in Docker**: `docker compose exec app pytest …`. Host is Python 3.14 and will fail; container is 3.11.
- **No new container dependencies.** Jinja2 is present. Playwright runs on the host, outside the container.
- **`objective_composite` must remain 3.029285 across 6,573 rows** (`archetype='All Metrics'`). This feature reads; it computes no new score. Verify after every task.
- **Do NOT touch scoring**: `club_framework.py`, `impect_map.py`, `scorecard.py`, `scorecard_run.py`, `score.py`, `build_neutral.py`, `impect_translate.py`, `normalise.py`, `constrain/filters.py`, `model/medical.py`.
- **Every figure states its comparison set** — league, season, position group, and the 450-minute threshold. A percentile with no stated peer group is meaningless.
- **Absent data reads as absent** — never zero, never a blank implying nothing happened.
- **Colour never carries meaning alone.** The page is printed and read in black and white.
- **Provenance on every judgement** — who assessed, who approved, when — plus the data snapshot date.
- **The narrative is never generated.** Free-text fields are written by a scout or omitted.
- **No staff names** in code, comments, fixtures or UI copy.
- **Do NOT run any git command that writes.** The user handles version control.
- Suite is at **694 passing** and must stay green.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/lofc/model/report_categories.py` | **New.** Category membership per position; computing a category score from percentiles. Pure, no I/O. |
| `src/lofc/report/data.py` | **New.** Assembles everything one report needs into a frozen `ReportData`. Pure given its inputs. |
| `src/lofc/report/svg.py` | **New.** Inline-SVG chart builders: percentile bars, radar, scatter, category strips. Pure — strings in, SVG string out. |
| `src/lofc/report/templates/report.html.j2` | **New.** The one-page Jinja2 layout. |
| `src/lofc/report/templates/report.css` | **New.** Print CSS — A4 landscape, page margins, black-and-white safe. |
| `src/lofc/report/render.py` | **New.** Binds `ReportData` + SVG + template into a self-contained HTML string. |
| `src/lofc/dashboard/tabs/report.py` | **New.** The dashboard page and download button. |
| `scripts/report_to_pdf.py` | **New.** Host-side: HTML file → PDF via Playwright. |
| `src/lofc/store/assessments.py` | **Modify.** Three narrative columns. |
| `src/lofc/dashboard/tabs/assess.py` | **Modify.** Three narrative inputs on the form. |
| `alembic/versions/<hash>_assessment_narrative.py` | **New.** Additive migration. |
| `src/lofc/dashboard/app.py` | **Modify.** Register the page. |

Dependency direction: `report_categories` → `report/data` → `report/svg` → `report/render` → `dashboard/tabs/report`. No cycles.

---

## Task 1: Category model

**Files:**
- Create: `src/lofc/model/report_categories.py`
- Test: `tests/test_report_categories.py`

**Interfaces:**
- Consumes: `scorecard._resolved_performance(position, archetype) -> list[str]`, `club_framework.PERFORMANCE_METRICS`.
- Produces:
  - `CATEGORIES: dict[str, dict[str, list[str]]]` — position → category name → resolved metric names
  - `INVERTED: frozenset[str]` — metrics where lower is better
  - `SCATTER_AXES: dict[str, tuple[str, str]]` — position → (x category, y category)
  - `category_score(percentiles: dict[str, float], position: str, category: str) -> float | None`
  - `category_scores(percentiles: dict[str, float], position: str) -> dict[str, float]`

- [ ] **Step 1: Write the failing tests**

```python
"""Report categories: grouping the club's own per-position metrics into the five or six
bands a reader can hold in their head. Pure — no database, no Streamlit."""

import pytest

from lofc.model import report_categories as rc
from lofc.model.scorecard import _resolved_performance


def test_every_position_has_categories():
    from lofc.model import club_framework as cf
    for pos in cf.PERFORMANCE_METRICS:
        assert pos in rc.CATEGORIES, f"{pos} has no categories"
        assert rc.CATEGORIES[pos], f"{pos} has empty categories"


def test_category_metrics_are_all_real_resolved_metrics():
    """No invented metrics. Every member must be a metric the scoring layer actually
    resolves for that position — otherwise the category is measuring something the club
    never asked for."""
    for pos, cats in rc.CATEGORIES.items():
        resolved = set(_resolved_performance(pos, "All Metrics"))
        for cat, metrics in cats.items():
            for m in metrics:
                assert m in resolved, f"{pos}/{cat}: {m} is not a resolved metric"


def test_no_metric_appears_in_two_categories_for_one_position():
    """Double-counting a metric would weight it twice in the same reader's mental model."""
    for pos, cats in rc.CATEGORIES.items():
        seen = [m for metrics in cats.values() for m in metrics]
        assert len(seen) == len(set(seen)), f"{pos} double-counts a metric"


def test_category_score_is_the_mean_of_member_percentiles():
    pcts = {"pass_value_p90": 80.0, "deep_progressions_p90": 60.0,
            "packing_bypassed_opponents_p90": 70.0, "dribble_carry_value_p90": 50.0}
    assert rc.category_score(pcts, "Central Mid", "Progression") == 65.0


def test_a_metric_where_lower_is_better_is_inverted():
    """Turnovers: a player in the 90th percentile for turnovers is BAD at retention.
    Without inversion the category would reward giving the ball away."""
    assert "turnovers_p90" in rc.INVERTED
    pcts = {"pass_completion_pct": 80.0, "turnovers_p90": 90.0}
    # retention = mean(80, 100-90) = 45.0
    assert rc.category_score(pcts, "Central Mid", "Retention") == 45.0


def test_a_missing_metric_drops_out_and_the_rest_renormalise():
    """Same rule the composite already uses: absent dimensions drop out, they do not
    count as zero."""
    pcts = {"pass_value_p90": 80.0, "deep_progressions_p90": 60.0}
    assert rc.category_score(pcts, "Central Mid", "Progression") == 70.0


def test_a_category_with_no_populated_metrics_returns_none():
    """None, never 0.0 — a category we cannot measure is not a category the player scored
    zero in."""
    assert rc.category_score({}, "Central Mid", "Progression") is None


def test_category_scores_omits_unmeasurable_categories():
    scores = rc.category_scores({"pass_completion_pct": 50.0}, "Central Mid")
    assert "Retention" in scores
    assert "Progression" not in scores


def test_scatter_axes_exist_for_every_position_and_name_real_categories():
    for pos, (x, y) in rc.SCATTER_AXES.items():
        assert x in rc.CATEGORIES[pos], f"{pos} x-axis {x} is not a category"
        assert y in rc.CATEGORIES[pos], f"{pos} y-axis {y} is not a category"
        assert x != y


def test_unknown_position_raises():
    """Never score a player against categories that do not exist for his position."""
    with pytest.raises(KeyError):
        rc.category_score({}, "Sweeper Keeper", "Progression")
```

- [ ] **Step 2: Run to verify they fail**

Run: `docker compose exec app pytest tests/test_report_categories.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lofc.model.report_categories'`

- [ ] **Step 3: Implement the module**

```python
"""Group the club's per-position metrics into the handful of categories a reader can hold
in their head.

NOTHING HERE IS INVENTED. Every member is one of the club's own Performance metrics as
resolved to its live Impect successor by `scorecard._resolved_performance`. The grouping is
presentation — a way to say "he progresses well but presses little" without making the
reader average sixteen bars themselves. It is not a new model and produces no new score.

A category is the MEAN of its members' percentiles, renormalised over the members actually
present, so a metric with no data drops out rather than counting as zero — the same rule
`scorecard._composite` already applies to dimensions.
"""

from __future__ import annotations

# Metrics where a HIGH percentile is BAD. A player in the 90th percentile for turnovers is
# poor at retention, not good at it, so the percentile is flipped before it enters a category.
INVERTED: frozenset[str] = frozenset({"turnovers_p90"})

CATEGORIES: dict[str, dict[str, list[str]]] = {
    "Goalkeeper": {
        "Shot stopping": ["gk_gsaa_p90", "gk_shot_stopping_pct"],
        "Claiming": ["gk_catches_p90"],
        "Sweeping": ["defensive_touches_outside_box_p90"],
        "Distribution": ["pass_value_p90", "packing_bypassed_opponents_p90"],
    },
    "Centre Back": {
        "Defending": ["ball_wins_p90", "defensive_value_p90", "blocks_p90"],
        "Duels": ["aerial_win_pct", "ground_duel_win_pct"],
        "Pressing": ["counterpressures_p90", "pressures_p90"],
        "Progression": ["packing_bypassed_opponents_p90", "deep_progressions_p90",
                        "pass_value_p90"],
        "Retention": ["pass_completion_pct", "turnovers_p90"],
    },
    "Full Back": {
        "Defending": ["ball_wins_p90", "defensive_value_p90"],
        "Duels": ["aerial_win_pct", "ground_duel_win_pct"],
        "Pressing": ["counterpressures_p90", "pressures_p90"],
        "Progression": ["packing_bypassed_opponents_p90", "deep_progressions_p90",
                        "pass_value_p90", "dribble_carry_value_p90", "dribble_count_p90"],
        "Creation": ["assists_p90", "open_play_assists_p90", "xa_p90",
                     "passes_into_box_p90", "cross_bypassed_opponents_p90",
                     "touches_in_box_p90"],
        "Retention": ["pass_completion_pct", "turnovers_p90"],
        "Scoring": ["goals_p90", "np_xg_p90", "np_xg_xa_p90"],
    },
    "Defensive Mid": {
        "Progression": ["packing_bypassed_opponents_p90", "deep_progressions_p90",
                        "pass_value_p90", "dribble_carry_value_p90"],
        "Creation": ["xa_p90", "passes_into_box_p90", "assists_p90",
                     "open_play_assists_p90"],
        "Retention": ["pass_completion_pct", "turnovers_p90"],
        "Pressing": ["counterpressures_p90", "pressures_p90", "ball_wins_p90"],
        "Duels": ["ground_duel_win_pct", "aerial_win_pct"],
    },
    "Central Mid": {
        "Progression": ["packing_bypassed_opponents_p90", "deep_progressions_p90",
                        "pass_value_p90", "dribble_carry_value_p90"],
        "Creation": ["xa_p90", "passes_into_box_p90", "assists_p90",
                     "open_play_assists_p90"],
        "Retention": ["pass_completion_pct", "turnovers_p90"],
        "Pressing": ["counterpressures_p90", "pressures_p90", "ball_wins_p90"],
        "Duels": ["ground_duel_win_pct", "aerial_win_pct"],
    },
    "Attacking Mid": {
        "Scoring": ["goals_p90", "shots_p90", "np_xg_p90", "np_xg_xa_p90"],
        "Creation": ["assists_p90", "open_play_assists_p90", "xa_p90",
                     "passes_into_box_p90", "cross_bypassed_opponents_p90",
                     "touches_in_box_p90"],
        "Progression": ["packing_bypassed_opponents_p90", "deep_progressions_p90",
                        "on_ball_value_p90", "pass_value_p90", "dribble_carry_value_p90",
                        "dribble_count_p90"],
        "Retention": ["pass_completion_pct", "turnovers_p90"],
        "Pressing": ["counterpressures_p90", "pressures_p90", "ball_wins_p90"],
    },
    "Winger": {
        "Scoring": ["goals_p90", "shots_p90", "np_xg_p90", "np_xg_xa_p90"],
        "Creation": ["assists_p90", "open_play_assists_p90", "xa_p90",
                     "passes_into_box_p90", "cross_bypassed_opponents_p90",
                     "touches_in_box_p90"],
        "Progression": ["packing_bypassed_opponents_p90", "deep_progressions_p90",
                        "on_ball_value_p90", "pass_value_p90", "dribble_carry_value_p90",
                        "dribble_count_p90"],
        "Retention": ["pass_completion_pct", "turnovers_p90"],
        "Pressing": ["counterpressures_p90", "pressures_p90", "ball_wins_p90"],
    },
    "Centre Forward": {
        "Scoring": ["goals_p90", "shots_p90", "np_xg_p90", "goal_conversion_pct",
                    "xg_overperformance_p90", "xg_per_shot"],
        "Creation": ["assists_p90", "open_play_assists_p90", "xa_p90",
                     "passes_into_box_p90", "cross_bypassed_opponents_p90",
                     "touches_in_box_p90"],
        "Progression": ["packing_bypassed_opponents_p90", "deep_progressions_p90",
                        "on_ball_value_p90", "pass_value_p90", "dribble_carry_value_p90",
                        "dribble_count_p90"],
        "Retention": ["pass_completion_pct", "turnovers_p90"],
        "Pressing": ["counterpressures_p90", "pressures_p90", "ball_wins_p90"],
        "Aerial": ["aerial_win_pct"],
    },
}

# Two categories per position that best separate its genuine styles. Both axes are category
# percentiles, so the scatter is in the same units as the strips beneath it.
SCATTER_AXES: dict[str, tuple[str, str]] = {
    "Goalkeeper": ("Distribution", "Shot stopping"),
    "Centre Back": ("Progression", "Defending"),
    "Full Back": ("Creation", "Defending"),
    "Defensive Mid": ("Progression", "Pressing"),
    "Central Mid": ("Progression", "Pressing"),
    "Attacking Mid": ("Creation", "Scoring"),
    "Winger": ("Creation", "Scoring"),
    "Centre Forward": ("Creation", "Scoring"),
}


def category_score(percentiles: dict[str, float], position: str,
                   category: str) -> float | None:
    """The mean percentile across a category's members, or None if none are measurable.

    Raises KeyError for an unknown position or category — a player must never be scored
    against categories that do not exist for his position.

    Returns None, never 0.0, when nothing is measurable: a category we cannot measure is not
    a category the player scored zero in.
    """
    members = CATEGORIES[position][category]
    present = [(100.0 - percentiles[m]) if m in INVERTED else percentiles[m]
               for m in members if percentiles.get(m) is not None]
    if not present:
        return None
    return round(sum(present) / len(present), 1)


def category_scores(percentiles: dict[str, float], position: str) -> dict[str, float]:
    """Every measurable category for a position. Unmeasurable ones are omitted, not zeroed."""
    out = {}
    for category in CATEGORIES[position]:
        score = category_score(percentiles, position, category)
        if score is not None:
            out[category] = score
    return out
```

- [ ] **Step 4: Run to verify they pass**

Run: `docker compose exec app pytest tests/test_report_categories.py -v`
Expected: 10 passed

- [ ] **Step 5: Mutation-test the inversion**

Remove `turnovers_p90` from `INVERTED` and confirm `test_a_metric_where_lower_is_better_is_inverted` FAILS. Revert. If it passes, the test is not pinning the rule.

- [ ] **Step 6: Verify against live data**

```bash
docker compose exec app python -c "
from lofc.model.report_categories import category_scores, CATEGORIES
import pandas as pd
from sqlalchemy import create_engine
from lofc.config import settings
eng = create_engine(settings.database_url)
p = pd.read_sql(\"SELECT metric, percentile FROM player_percentiles WHERE season_id=318 AND position_group='Central Mid' LIMIT 200\", eng)
print('categories for Central Mid:', list(CATEGORIES['Central Mid']))
"
```
Expected: five categories named, no exception.

- [ ] **Step 7: Full suite + ranking**

Run: `docker compose exec app pytest -q` → 694 + 10 = **704**
Run the ranking check → **3.029285 / 6573**

---

## Task 2: Narrative fields on the assessment

**Files:**
- Modify: `src/lofc/store/models.py` (`ScoutAssessment`)
- Modify: `src/lofc/store/assessments.py` (`save`, `load_for_player`)
- Modify: `src/lofc/dashboard/tabs/assess.py`
- Create: `alembic/versions/<hash>_assessment_narrative.py`
- Test: `tests/test_store_assessments.py`

**Interfaces:**
- Produces: `ScoutAssessment.summary`, `.why_sign`, `.considerations` — all `str | None`; `save(...)` gains three keyword arguments defaulting to `None`.

- [ ] **Step 1: Write the failing test**

```python
def test_save_stores_the_narrative_fields(engine):
    """The report's prose is written by a scout, never generated. It lives on the assessment
    so completing one produces the report's narrative as a side effect."""
    aid = _save(engine, summary="Progresses well under pressure.",
                why_sign="Elite ball retention for the level.",
                considerations="Limited aerial presence.")
    frame = store_assess.load_for_player(engine, 1, 4, 318)
    row = frame[frame["id"] == aid].iloc[0]
    assert row["summary"] == "Progresses well under pressure."
    assert row["why_sign"] == "Elite ball retention for the level."
    assert row["considerations"] == "Limited aerial presence."


def test_narrative_fields_default_to_none(engine):
    """A scout assessing before a fixture may write nothing. That must be an ordinary
    assessment, not a blocked one."""
    aid = _save(engine)
    frame = store_assess.load_for_player(engine, 1, 4, 318)
    row = frame[frame["id"] == aid].iloc[0]
    assert row["summary"] is None
```

Update the `_save` helper in that file to accept and pass the three new keywords.

- [ ] **Step 2: Run to verify it fails**

Run: `docker compose exec app pytest tests/test_store_assessments.py -k narrative -v`
Expected: FAIL — `TypeError: save() got an unexpected keyword argument 'summary'`

- [ ] **Step 3: Add the columns to the model**

In `src/lofc/store/models.py`, inside `class ScoutAssessment`, after `notes`:

```python
    # The player report's narrative, written by the assessor. Never generated: see
    # docs/superpowers/specs/2026-08-28-player-report-design.md section 4. A report with no
    # assessment simply omits these and says so.
    summary: Mapped[str | None] = mapped_column(String, nullable=True)
    why_sign: Mapped[str | None] = mapped_column(String, nullable=True)
    considerations: Mapped[str | None] = mapped_column(String, nullable=True)
```

- [ ] **Step 4: Generate and apply the migration**

```bash
docker compose exec app alembic revision --autogenerate -m "assessment narrative"
docker compose exec app alembic upgrade head
```

Open the generated file and confirm it contains exactly three `op.add_column` calls on `scout_assessments` and nothing else. Delete any unrelated drift.

Verify: `docker compose exec db psql -U lofc lofc -c "\d scout_assessments"` shows all three, nullable, and existing rows survive.

- [ ] **Step 5: Wire them through the store**

In `src/lofc/store/assessments.py`, add `summary`, `why_sign`, `considerations` to `save`'s keyword arguments (defaulting to `None`) and to the insert's values; add the three names to `_LOAD_COLUMNS`.

- [ ] **Step 6: Add the inputs to the assessment form**

In `src/lofc/dashboard/tabs/assess.py`, in the psychological form, add three `st.text_area` inputs — Summary, Why sign, Considerations — each with a caption saying they appear on the player report, and each optional. Pass them into `save`.

- [ ] **Step 7: Run the tests**

Run: `docker compose exec app pytest tests/test_store_assessments.py -v`
Then the full suite → **706**, and the ranking check.

---

## Task 3: Report data assembly

**Files:**
- Create: `src/lofc/report/__init__.py` (empty), `src/lofc/report/data.py`
- Test: `tests/test_report_data.py`

**Interfaces:**
- Consumes: `report_categories.category_scores`, `store.assessments.load_for_player`, `store.injuries.load_for_player`, `medical.availability_with_evidence`, `scout_scores.resolve_bands`, and **`scorecard.metric_percentiles(neutral)`**.

> **Percentile source — corrected during execution.** Do **NOT** read `player_percentiles`.
> That table holds only 22 metrics (a legacy set predating the Impect migration) and is
> missing `aerial_win_pct`, `ground_duel_win_pct`, `turnovers_p90`, `pass_value_p90`,
> `counterpressures_p90` and others — verified live, the Duels and Retention categories
> cannot be computed from it. Use `scorecard.metric_percentiles(neutral)`, which returns all
> 91 metrics and covers 16 of 16 for Central Mid. It is also the function the composite
> itself uses, so the report's percentiles and the player's bands come from one computation
> and cannot disagree.
- Produces:
  - `ReportData` — frozen dataclass with: `player_name, position, club, league, season_label, age, foot, height_cm, nationality, contract_until, minutes, goals, assists, composite, dimension_bands: dict[str, float|None], rank, peer_count, percentiles: dict[str, float], category_scores: dict[str, float], physical: dict[str, float], peers: list[tuple[str, float, float]], availability, injuries, narrative: Narrative|None, stamp: str, snapshot_date, comparison_text: str, flags: list[str]`
  - `Narrative` — frozen dataclass `(summary, why_sign, considerations, assessor, assessor_role, approver, approved_at)`
  - `build(engine, player_id, competition_id, season_id) -> ReportData`
  - `STAMP_DATA_ONLY = "Data only"`, `STAMP_PROVISIONAL = "Provisional"`, `STAMP_FINAL = "Final"`

- [ ] **Step 1: Write the failing tests**

```python
"""Assembling one player's report. In-memory sqlite; no live Postgres, no network."""

def test_stamp_is_data_only_with_no_assessment(engine):
    r = data.build(engine, 1, 4, 318)
    assert r.stamp == data.STAMP_DATA_ONLY
    assert r.narrative is None


def test_stamp_is_provisional_for_a_submitted_assessment(engine):
    _assess(engine, status="submitted", summary="Reads the game well.")
    r = data.build(engine, 1, 4, 318)
    assert r.stamp == data.STAMP_PROVISIONAL
    assert r.narrative.summary == "Reads the game well."
    assert r.narrative.assessor == "Scout One"


def test_stamp_is_final_for_a_signed_off_assessment(engine):
    _assess(engine, status="signed_off", summary="Reads the game well.")
    r = data.build(engine, 1, 4, 318)
    assert r.stamp == data.STAMP_FINAL
    assert r.narrative.approver is not None


def test_a_conflict_produces_no_bands_and_no_stamp_upgrade(engine):
    """Decision 17: two unsigned assessments that disagree score nothing. The report must
    not present a band as though someone decided."""
    _assess(engine, band=4.0); _assess(engine, band=2.0)
    r = data.build(engine, 1, 4, 318)
    assert r.dimension_bands.get("Psychological") is None
    assert r.stamp == data.STAMP_DATA_ONLY


def test_comparison_text_names_league_season_position_and_threshold(engine):
    """A percentile with no stated peer group is meaningless to a chairman."""
    r = data.build(engine, 1, 4, 318)
    for token in ("League One", "2025/26", "Central Mid", "450"):
        assert token in r.comparison_text


def test_absent_bio_fields_are_none_not_zero(engine):
    """A player with no recorded height is not 0cm."""
    r = data.build(engine, 2, 4, 318)   # fixture player with no bio
    assert r.height_cm is None
    assert r.foot is None


def test_rank_and_peer_count_are_within_league_season_and_position(engine):
    r = data.build(engine, 1, 4, 318)
    assert r.rank >= 1
    assert r.peer_count >= r.rank


def test_unknown_player_raises_rather_than_returning_an_empty_report(engine):
    with pytest.raises(ValueError):
        data.build(engine, 999999, 4, 318)
```

- [ ] **Step 2: Run to verify they fail**

Run: `docker compose exec app pytest tests/test_report_data.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lofc.report'`

- [ ] **Step 3: Implement `report/data.py`**

Assemble from the existing loaders. Requirements the tests pin:

- Stamp from the assessment state: none → `STAMP_DATA_ONLY`; any `submitted` → `STAMP_PROVISIONAL`; any `signed_off` → `STAMP_FINAL`; conflicting → `STAMP_DATA_ONLY` with no bands.
- `comparison_text` built from the league name, season label, position group and the literal `450` minute threshold.
- Every bio field `None` when absent — never a default.
- `rank` and `peer_count` computed within (competition, season, position group) over rankable players only.
- `peers` for the scatter: `(name, x_category_score, y_category_score)` for every rankable peer, so the target can be highlighted among them.
- `snapshot_date` from the most recent `player_scorecards` write.
- Raise `ValueError` naming the player id when the player-season does not exist.

Plain SQLAlchemy Core, matching `store/watchlist.py`, so it runs on sqlite in tests.

- [ ] **Step 4: Run to verify they pass**

- [ ] **Step 5: Verify against a real player**

```bash
docker compose exec app python -c "
from lofc.report.data import build
from lofc.dashboard.loaders import get_engine
import pandas as pd
from sqlalchemy import create_engine
from lofc.config import settings
eng = create_engine(settings.database_url)
row = pd.read_sql(\"SELECT player_id, competition_id FROM player_metrics_neutral WHERE season_id=318 AND position_group='Central Mid' AND rankable LIMIT 1\", eng).iloc[0]
r = build(eng, int(row.player_id), int(row.competition_id), 318)
print(r.player_name, '|', r.stamp, '|', r.comparison_text)
print('categories:', r.category_scores)
print('rank:', r.rank, 'of', r.peer_count)
"
```
Expected: a real name, a stamp, five categories, a plausible rank.

- [ ] **Step 6: Full suite + ranking** → **714**, 3.029285 / 6573

---

## Task 4: Inline SVG charts

**Files:**
- Create: `src/lofc/report/svg.py`
- Test: `tests/test_report_svg.py`

**Interfaces:**
- Produces (all return an SVG string):
  - `percentile_bars(labels: list[str], values: list[float], width=520) -> str`
  - `radar(axes: list[str], series: list[tuple[str, list[float | None], str]], size=340) -> str` — a `None` breaks the line rather than plotting the origin
  - `scatter(peers, target_name, x_label, y_label, size=380) -> str`
  - `category_strip(name: str, score: float, peers: list[float], width=200) -> str`
  - `BAND_COLOURS: dict[str, str]`

- [ ] **Step 1: Write the failing tests**

```python
"""The report's charts, as inline SVG strings. Pure: values in, markup out. No Streamlit,
no chart library, nothing to render — the assertions are on the markup itself."""

from lofc.report import svg


def test_percentile_bars_emits_one_bar_per_metric():
    out = svg.percentile_bars(["Goals", "Assists"], [80.0, 20.0])
    assert out.count("<rect") >= 2
    assert out.startswith("<svg")


def test_percentile_bars_labels_every_value():
    """A bar a reader cannot read the number off is decoration."""
    out = svg.percentile_bars(["Goals"], [80.4])
    assert "80.4" in out


def test_percentile_bars_does_not_rely_on_colour_alone():
    """The page is printed in black and white. The value must be legible without it."""
    out = svg.percentile_bars(["Goals"], [80.4])
    assert "80.4" in out and "<text" in out


def test_radar_draws_every_series():
    out = svg.radar(["A", "B", "C"], [("Player", [80, 60, 40], "#C8102E"),
                                      ("League", [50, 50, 50], "#333")])
    assert out.count("<polygon") + out.count("<polyline") >= 2
    assert "Player" in out and "League" in out


def test_radar_handles_a_missing_axis_value_without_drawing_zero():
    """A physical metric we do not hold must not plot as the origin — that reads as
    'no distance covered' rather than 'not measured'."""
    out = svg.radar(["A", "B"], [("Player", [80, None], "#C8102E")])
    assert out.startswith("<svg")


def test_scatter_marks_the_target_distinctly_and_names_it():
    peers = [("A. Player", 20.0, 30.0), ("Target Man", 70.0, 80.0)]
    out = svg.scatter(peers, "Target Man", "Progression", "Pressing")
    assert "Target Man" in out
    assert "Progression" in out and "Pressing" in out


def test_category_strip_places_the_player_within_the_distribution():
    out = svg.category_strip("Pressing", 72.0, [10.0, 50.0, 90.0])
    assert "Pressing" in out and "72" in out


def test_every_chart_escapes_text():
    """Player and club names reach these directly. An unescaped angle bracket breaks the
    page, and the page is a document that leaves the building."""
    out = svg.scatter([("A <b>Name", 10.0, 10.0)], "A <b>Name", "X", "Y")
    assert "<b>" not in out
    assert "&lt;b&gt;" in out
```

- [ ] **Step 2: Run to verify they fail**

- [ ] **Step 3: Implement `report/svg.py`**

Hand-built SVG. Requirements:

- Every text value escaped with `html.escape`.
- `percentile_bars`: horizontal bars, label left, value right of the bar, coloured by band but with the number always present.
- `radar`: regular polygon axes, one polyline per series, banded background rings, axis labels, a legend. A `None` value breaks the line rather than plotting zero.
- `scatter`: points for peers, the target in the club red with a ring and its name; quadrant lines at the mean; axis labels.
- `category_strip`: a horizontal track with peer positions as light marks and the player as a filled marker, the score printed.
- `BAND_COLOURS`: the club palette from `dashboard/theme.py` (`RED = "#C8102E"`), plus greens and greys. **Do not introduce a new palette.**

- [ ] **Step 4: Run to verify they pass**

- [ ] **Step 5: Eyeball one chart**

```bash
docker compose exec app python -c "
from lofc.report import svg
open('/tmp/c.svg','w').write(svg.percentile_bars(['Goals','Assists','Pressures'],[80.4,20.1,55.0]))
print('written')
"
docker compose cp app:/tmp/c.svg ./data/exports/_chart_preview.svg
```
Open it. It must be legible, aligned, and readable without colour.

- [ ] **Step 6: Full suite + ranking** → **722**

---

## Task 5: HTML template, print CSS and render

**Files:**
- Create: `src/lofc/report/templates/report.html.j2`, `src/lofc/report/templates/report.css`, `src/lofc/report/render.py`
- Test: `tests/test_report_render.py`

**Interfaces:**
- Produces: `render.to_html(data: ReportData) -> str` — a self-contained HTML document with the CSS inlined and every chart embedded as SVG.

**Before writing the template, invoke the frontend design skill** (`example-skills:frontend-design`) and follow it. This page is read by the chairman and the manager; presentation is a requirement of the spec, not a preference. Consult `docs/Samson Tovide - Data Report.pdf` for the reference layout — two horizontal bands, decision above evidence.

- [ ] **Step 1: Write the failing tests**

First the fixture every test below uses — a complete `ReportData` with overridable fields, so
each test states only what it cares about:

```python
from lofc.report import data, render


def _fixture(**overrides):
    base = dict(
        player_name="A Player", position="Central Mid", club="A Club",
        league="League One", season_label="2025/26", age=24.1, foot="right",
        height_cm=182, nationality="England", contract_until="30 Jun 2027",
        minutes=2100.0, goals=4.0, assists=6.0, composite=3.9,
        dimension_bands={"Performance": 4.1, "Physical": 3.6},
        rank=7, peer_count=102,
        percentiles={"pass_value_p90": 70.0}, category_scores={"Pressing": 62.0},
        physical={"distance_p90": 55.0},
        peers=[("A Player", 60.0, 62.0), ("B Player", 30.0, 40.0)],
        availability=0.92, injuries=[], narrative=None,
        stamp=data.STAMP_DATA_ONLY, snapshot_date="28 Aug 2026",
        comparison_text="2025/26 · League One only · compared to League One Central Mids over 450 minutes",
        flags=[])
    base.update(overrides)
    return data.ReportData(**base)


def test_html_is_self_contained():
    """It is emailed and opened offline. No external stylesheet, no CDN, no <img src=http>."""
    out = render.to_html(_fixture())
    assert "<style" in out
    assert "http://" not in out and "https://" not in out


def test_the_stamp_appears_on_the_page():
    out = render.to_html(_fixture(stamp="Provisional"))
    assert "Provisional" in out


def test_the_comparison_set_appears_on_the_page():
    out = render.to_html(_fixture())
    assert "League One" in out and "450" in out


def test_absent_narrative_says_so_rather_than_leaving_a_gap():
    out = render.to_html(_fixture(narrative=None))
    assert "No scout assessment recorded" in out


def test_absent_bio_reads_as_not_recorded_never_zero():
    out = render.to_html(_fixture(height_cm=None))
    assert "not recorded" in out.lower()
    assert ">0cm<" not in out


def test_player_name_is_escaped():
    out = render.to_html(_fixture(player_name="A <script>alert(1)</script>"))
    assert "<script>" not in out


def test_print_css_sets_landscape_a4():
    out = render.to_html(_fixture())
    assert "@page" in out and "landscape" in out
```

- [ ] **Step 2: Run to verify they fail**

- [ ] **Step 3: Write the CSS**

`@page { size: A4 landscape; margin: 8mm; }`. Two bands. System font stack — no web fonts, since the file must render offline. Print-safe: no background-dependent meaning, adequate contrast, `print-color-adjust: exact` where a band's colour is informative but always with the number beside it.

- [ ] **Step 4: Write the template**

Band 1: identity, bio panel, summary/why-sign/considerations (or the absent notice), club verdict with composite, dimension bands, provenance and named advisory flags.
Band 2: counting stats, percentile bars, scatter, radar, category strips, availability.
Footer: comparison text, stamp, snapshot date.

- [ ] **Step 5: Implement `render.to_html`**

Jinja2 `Environment` with `autoescape=True`, template loaded from the package directory, CSS read and inlined into a `<style>` block, charts rendered by Task 4 and inserted with `|safe` (they are generated markup, and their text was escaped inside `svg.py`).

- [ ] **Step 6: Run to verify they pass**

- [ ] **Step 7: Full suite + ranking** → **729**

---

## Task 6: The dashboard page and the PDF command

**Files:**
- Create: `src/lofc/dashboard/tabs/report.py`, `scripts/report_to_pdf.py`
- Modify: `src/lofc/dashboard/app.py`
- Modify: `cli_commands.txt`

- [ ] **Step 1: Build the page**

A "Report" page: a player search (reuse `dashboard/search.py`), then the rendered report shown inline via `st.html`, plus a `st.download_button` serving the HTML with filename `<player>_<season>_report.html`.

Register it in `app.py` in the Scouting group, following the existing pattern. It must sit behind the login gate like every other page.

- [ ] **Step 2: Write the PDF command**

`scripts/report_to_pdf.py` — takes an HTML path and an output PDF path, runs Playwright/Chromium headless, `page.pdf(landscape=True, format="A4", print_background=True)`.

**This runs on the host, not in the container** — Playwright is installed on the host. Say so in the file's docstring and in `cli_commands.txt`.

- [ ] **Step 3: Append to `cli_commands.txt`**

```
# Turn a downloaded player report into a print-ready PDF (runs on the host, not in Docker)
python3 scripts/report_to_pdf.py ~/Downloads/player_report.html ~/Downloads/player_report.pdf
```

- [ ] **Step 4: Verify end to end**

`docker compose restart dashboard`, then check `docker compose logs --tail=40 dashboard` for tracebacks.

Then, in a browser (Playwright, `webapp-testing` skill): sign in, open the Report page, pick a Central Mid, confirm the report renders, download the HTML, and run it through `report_to_pdf.py`. Open the PDF and confirm it is one landscape page with legible charts.

Save the PDF to `data/exports/` (gitignored) and a screenshot to `.superpowers/sdd/`.

- [ ] **Step 5: Verify all eight positions**

Generate a report for one player in each of the eight position groups. Confirm each renders without exception, shows its own categories, and states its own comparison set. Record any position whose layout breaks.

- [ ] **Step 6: Full suite + ranking** → 729, 3.029285 / 6573

---

## Task 7: Documentation

- [ ] **Step 1:** Record the feature in `plan/BUILD_PLAN.md` (current state and register), `CLAUDE.md`, `docs/architecture.md` (the new `report/` package and its dependency direction), and `README.md`.
- [ ] **Step 2:** Mark register item **P7** as built; leave **P8** (availability donut) open with its reason.
- [ ] **Step 3:** Record what the report deliberately omits versus the reference — appearances, starts, the availability donut, loan status, agency, academy, photograph — each with why.
- [ ] **Step 4:** Confirm no confidential file is staged: `git status --short` and `git ls-files | grep -iE '\.key|\.pdf|tovide|kabia'` → empty.

---

## Final verification

- [ ] `docker compose exec app pytest -q` → **729 passing**
- [ ] `objective_composite` = **3.029285** over **6,573** rows
- [ ] A report renders for one player in each of the eight positions
- [ ] The PDF is one landscape page, charts legible, readable in black and white
- [ ] Every figure states its comparison set; the stamp and snapshot date are present
- [ ] A player with no assessment produces a valid report saying so
- [ ] No new container dependency
