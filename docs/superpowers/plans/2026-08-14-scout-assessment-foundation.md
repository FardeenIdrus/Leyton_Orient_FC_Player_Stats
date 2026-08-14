# Scout Assessment — Foundation and Scoring (R3a-1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Everything the scout assessment system needs *below* the user interface — the club's criteria encoded, the tables, user accounts, and `assessed_composite` — so that a signed-off assessment produces a score.

**Architecture:** Five layers, each testable alone. The club's per-position criteria become a data module beside `club_framework.py`. Assessments live in three new tables. Authentication uses the standard library only. A resolver turns many submitted assessments into one scoring value per dimension. `scorecard.py` gains a third composite through the same interface `financial_resale` already uses.

**Tech Stack:** Python 3.11 in Docker, PostgreSQL 16, SQLAlchemy 2.0 + Alembic, pandas, pytest.

**Spec:** `docs/superpowers/specs/2026-08-10-scout-assessment-design.md` — read Decisions 6–15 before starting.

**Scope split:** this plan is the foundation. **The interface — evidence panel, assessment form, sign-off view, badges, and watchlist integration (spec §7) — is a separate plan (R3a-2)** and must invoke the frontend design skill, per spec §16. Nothing here renders anything.

## Global Constraints

- **Everything runs in Docker.** Prefix every command: `docker compose exec app …` (add `-T` when piping). Host is Python 3.14; the container is 3.11. Database: `docker compose exec -T db psql -U lofc -d lofc`.
- **No new dependencies.** Standard library plus pandas / SQLAlchemy / Streamlit, all already installed. Authentication must use `hashlib.scrypt` — **do not add passlib, bcrypt, or any auth library.**
- **No network in tests. No database in unit tests** — keep the tested unit pure and pass frames in, following `tests/test_medical.py`.
- **Schema changes go through Alembic.** Current head is `6677cea28903`.
- **Never run `git push`.** Commits are local, authored by the repository owner, with **no `Co-Authored-By` trailer and no mention of Claude, AI, or an assistant** in any commit message. Stage only the files a task touches, by explicit path — never `git add -A`.
- **Do not run any scraper, the valuation, the identity linker, or the full pipeline.** The database holds recovered data.
- Existing test count is **319**; it must only go up.
- **Nothing in this plan changes the default ranking.** `objective_composite` and `full_composite` must be byte-identical afterwards.

---

### Task 1: Encode the club's per-position criteria

**Files:**
- Create: `src/lofc/model/club_criteria.py`
- Test: `tests/test_club_criteria.py`

**Interfaces:**
- Consumes: nothing
- Produces: `PSYCHOLOGICAL_CRITERIA: dict[str, list[str]]`, `MEDICAL_CRITERIA: dict[str, list[MedicalCriterion]]`, `MedicalCriterion` (frozen dataclass with `text: str` and `kind: str`), and `POSITION_GROUPS: tuple[str, ...]`

**Source data:** the club's criteria are extracted verbatim to
`.superpowers/sdd/2026-08-10-tm-injury-scrape/club-criteria-extracted.json`, keyed by the club's
**ten** profile names. Read that file; do not re-parse the `.docx`.

That JSON lives in a gitignored scratch directory, so it may be absent on a fresh checkout. The
`.docx` remains the ultimate source. To regenerate it:

```bash
docker compose exec app python -c "
import zipfile, re, json
z = zipfile.ZipFile('docs/LOFC - Position Archetype.docx')
xml = z.read('word/document.xml').decode('utf8', 'ignore')
xml = re.sub(r'</w:p>', chr(10), xml); xml = re.sub(r'</w:tc>', ' | ', xml)
lines = [re.sub(r'&amp;', '&', l.strip()) for l in re.sub(r'<[^>]+>', '', xml).split(chr(10)) if l.strip()]
ORDER = ['Goalkeeper','Right Back','Left Back','Centre Back','Defensive Mid','Central Mid','Attacking Mid','Left Winger','Right Winger','Centre Forward']
def bullets(i):
    out = []
    for l in lines[i+1:i+12]:
        if l.startswith(chr(8226)): out.append(l.lstrip(chr(8226) + ' ').strip())
        elif out: break
    return out
med = [bullets(i) for i, l in enumerate(lines) if re.match(r'^\|?\s*Medical & Durability', l)]
psy = [bullets(i) for i, l in enumerate(lines) if re.match(r'^\|?\s*Psychological Profile', l)]
print(json.dumps({ORDER[k]: {'medical': med[k], 'psychological': psy[k]} for k in range(10)}, indent=1))
"
```

Sanity check on the output: 10 profiles, and psychological counts of 3, 3, 3, 4, 3, 3, 5, 5, 5, 2
in the order above.

**The ten club profiles map onto our eight position groups** (Decision 6). Six map straight
across: Goalkeeper, Centre Back, Defensive Mid, Central Mid, Attacking Mid, Centre Forward. Two
are unions:

- **Full Back** = Right Back ∪ Left Back
- **Winger** = Left Winger ∪ Right Winger

**The merges are already decided — encode exactly these, do not invent others:**

*Full Back, psychological:* all six bullets are distinct. **No merges.** → 6 criteria.

*Full Back, medical:* `"Permanent signings undergo MRI scan"` and `"Minimum 60% availability over
prior 2 seasons"` appear identically on both sides — **keep one of each**. The two hamstring
bullets are **not** identical (`"No recurring hamstring injuries within the prior 12 months"` is
time-bounded; `"No recurring hamstring or calf injuries"` is broader by type) — **keep both**,
because merging them would discard a constraint the club wrote. → 4 criteria.

*Winger, psychological:* two genuine near-duplicate pairs merge. **Use the Right Winger wording
verbatim in both cases** — never write new text:
- `"High pressing work rate in defensive phase"` absorbs `"Work rate in defensive transitions; tracks back when required"`
- `"Competitive drive to impact matches consistently"` absorbs `"Competitive edge; wants to be the difference-maker"`
The other six are distinct. → 8 criteria.

*Winger, medical:* `"No hamstring injury in prior 12 months (sprint-dependent position)"` and
`"No hamstring injury in prior 12 months"` are the same requirement — **keep the Left Winger
wording**, which carries the club's rationale. `"Minimum 60% availability…"` appears on both —
keep one. `"Quadriceps and hip flexor screening clear"` and `"Hip and groin screening clear for
high-COD activities"` concern different structures — **keep both**. → 5 criteria.

**Medical criterion classification** (Decision 7), applied to the bullet text:
- contains `"availability"` → `kind="availability"`
- contains `"undergo"` (i.e. "Permanent signings undergo MRI scan…") → `kind="protocol"`
- everything else → `kind="screening"`

**Criterion counts vary from 2 to 8 by position. That is the club's document, not an error** —
Centre Forward genuinely lists only two psychological bullets. Do not pad any position.

- [ ] **Step 1: Write the failing test**

```python
"""The club's per-position Psychological and Medical criteria, encoded verbatim."""

import pytest

from lofc.model import club_framework as cf
from lofc.model.club_criteria import (
    MEDICAL_CRITERIA,
    POSITION_GROUPS,
    PSYCHOLOGICAL_CRITERIA,
    MedicalCriterion,
)


def test_every_position_group_the_framework_scores_has_criteria():
    # The criteria must cover exactly the positions club_framework weights.
    assert set(POSITION_GROUPS) == set(cf.DIMENSION_WEIGHTS)
    for position in POSITION_GROUPS:
        assert PSYCHOLOGICAL_CRITERIA[position], position
        assert MEDICAL_CRITERIA[position], position


def test_the_merged_positions_have_the_agreed_counts():
    # Full Back = Right Back u Left Back; Winger = Left u Right Winger (Decision 6).
    assert len(PSYCHOLOGICAL_CRITERIA["Full Back"]) == 6
    assert len(MEDICAL_CRITERIA["Full Back"]) == 4
    assert len(PSYCHOLOGICAL_CRITERIA["Winger"]) == 8
    assert len(MEDICAL_CRITERIA["Winger"]) == 5


def test_centre_forward_keeps_its_two_criteria_unpadded():
    # The club really does list only two. Padding would invent criteria.
    assert len(PSYCHOLOGICAL_CRITERIA["Centre Forward"]) == 2


def test_merged_winger_text_is_the_club_wording_not_a_new_sentence():
    winger = PSYCHOLOGICAL_CRITERIA["Winger"]
    assert "High pressing work rate in defensive phase" in winger
    assert "Competitive drive to impact matches consistently" in winger
    # The absorbed left-side phrasings must NOT appear as separate criteria.
    assert not any("difference-maker" in c for c in winger)
    assert not any("tracks back when required" in c for c in winger)


def test_no_duplicate_criteria_within_a_position():
    for position in POSITION_GROUPS:
        psych = PSYCHOLOGICAL_CRITERIA[position]
        assert len(psych) == len(set(psych)), position
        texts = [c.text for c in MEDICAL_CRITERIA[position]]
        assert len(texts) == len(set(texts)), position


def test_medical_criteria_are_classified_three_ways():
    kinds = {c.kind for cs in MEDICAL_CRITERIA.values() for c in cs}
    assert kinds <= {"availability", "screening", "protocol"}
    # Every position states an availability requirement.
    for position in POSITION_GROUPS:
        assert any(c.kind == "availability" for c in MEDICAL_CRITERIA[position]), position


def test_the_mri_bullet_is_protocol_not_a_player_attribute():
    # "Permanent signings undergo MRI scan" says nothing about the player (Decision 7).
    mri = [c for cs in MEDICAL_CRITERIA.values() for c in cs if "undergo" in c.text]
    assert mri, "expected at least one protocol criterion"
    assert all(c.kind == "protocol" for c in mri)


def test_a_screening_criterion_is_neither_availability_nor_protocol():
    full_back = {c.text: c.kind for c in MEDICAL_CRITERIA["Full Back"]}
    assert full_back["Minimum 60% availability over prior 2 seasons"] == "availability"
    assert full_back["Permanent signings undergo MRI scan"] == "protocol"
    assert full_back["No recurring hamstring or calf injuries"] == "screening"


def test_criteria_are_immutable_value_objects():
    criterion = MEDICAL_CRITERIA["Winger"][0]
    with pytest.raises(Exception):
        criterion.text = "changed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec app python -m pytest tests/test_club_criteria.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lofc.model.club_criteria'`

- [ ] **Step 3: Write the implementation**

Create `src/lofc/model/club_criteria.py`. Transcribe the bullets from the extracted JSON
verbatim into module-level literals — **do not read the JSON at runtime**, it lives in a
gitignored scratch directory. Structure:

```python
"""The club's per-position Psychological and Medical criteria, transcribed verbatim from
`docs/LOFC - Position Archetype.docx`.

This is the companion to `club_framework.py`: that module holds WHAT the club measures from
data, this one holds what a human scores. Both are the club's own words, not our invention.

TEN club profiles map onto our EIGHT position groups (Decision 6). Right/Left Back merge into
Full Back and Left/Right Winger into Winger, de-duplicated where two bullets state the same
requirement. Where they state overlapping but distinct requirements, BOTH are kept -- merging
them would discard a constraint the club wrote.

Criterion counts vary from 2 to 8 by position. That is the club's document. Do not pad.
"""

from __future__ import annotations

from dataclasses import dataclass

POSITION_GROUPS: tuple[str, ...] = (
    "Goalkeeper", "Centre Back", "Full Back", "Defensive Mid",
    "Central Mid", "Attacking Mid", "Winger", "Centre Forward",
)


@dataclass(frozen=True)
class MedicalCriterion:
    """One of the club's Medical & Durability requirements.

    `kind` follows Decision 7:
      availability -- computed as a figure and shown as evidence; never produces a band
      screening    -- pass/fail, recorded by the assessor; warns, never overrides (Decision 13)
      protocol     -- a club process step, not a player attribute; never scored
    """

    text: str
    kind: str


PSYCHOLOGICAL_CRITERIA: dict[str, list[str]] = {
    # ... transcribe from the extracted JSON, applying the merges above ...
}

MEDICAL_CRITERIA: dict[str, list[MedicalCriterion]] = {
    # ... transcribe, classifying each bullet by kind ...
}
```

Fill both dictionaries from the JSON. Every string must match the club's wording exactly —
the tests check specific phrases.

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec app python -m pytest tests/test_club_criteria.py -v`
Expected: PASS — 9 tests

- [ ] **Step 5: Run the full suite**

Run: `docker compose exec app python -m pytest -q`
Expected: PASS — **328 tests** (319 + 9)

- [ ] **Step 6: Commit**

```bash
git add src/lofc/model/club_criteria.py tests/test_club_criteria.py
git commit -m "feat: encode the club's per-position psychological and medical criteria"
```

---

### Task 2: Data model and migration

**Files:**
- Modify: `src/lofc/store/models.py` (append three models near `WatchlistEntry`)
- Create: `alembic/versions/<generated>_scout_assessments.py`
- Test: `tests/test_store.py` (append)

**Interfaces:**
- Consumes: `club_criteria.POSITION_GROUPS` (for nothing at runtime — the tables are generic)
- Produces: models `User`, `ScoutAssessment`, `ScoutCriterionScore`, and the matching tables

**Schema** (spec §13, amended by Decision 14):

`users` — `id`, `username` (unique), `full_name`, `role`, `password_hash`, `is_active`, `created_at`.
Roles: `scout`, `medical`, `head_of_recruitment`, `admin`.

`scout_assessments` — `id`, `player_id` → players, `competition_id`, `season_id`,
`dimension` (`Psychological` | `Medical Risk`), `author_id` → users, `band` (float, the value
that scores), `band_note`, `screening_failed` (bool, medical only), `notes`,
`status` (`draft` | `submitted` | `signed_off`), `approved_by` → users (nullable),
`approved_at` (nullable), `created_at`, `updated_at`.

`scout_criterion_scores` — `id`, `assessment_id` → scout_assessments (cascade delete),
`criterion_key` (the criterion text), `score` (int 1–5, nullable — psychological),
`passed` (bool, nullable — medical screening).

**Also add to `player_injuries`:** an `entered_by` column → `users`, nullable. It was
deliberately deferred when that table was created because `users` did not exist. Manual injury
entry needs it.

**Note on `assessed_composite`:** the two new columns on `player_scorecards` are added in
**Task 5**, not here, so that migration lands with the code that writes them.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_store.py`:

```python
def test_scout_assessment_table_shape():
    from lofc.store.models import ScoutAssessment

    columns = {c.name for c in ScoutAssessment.__table__.columns}
    assert {"player_id", "competition_id", "season_id", "dimension", "author_id",
            "band", "status", "approved_by", "approved_at", "screening_failed"} <= columns
    # A new assessment is a draft until someone submits it.
    assert ScoutAssessment.__table__.c.status.server_default.arg == "draft"


def test_users_table_stores_a_hash_not_a_password():
    from lofc.store.models import User

    columns = {c.name for c in User.__table__.columns}
    assert "password_hash" in columns
    assert "password" not in columns, "never store a plaintext password"
    assert User.__table__.c.username.unique


def test_criterion_scores_carry_either_a_score_or_a_pass_flag():
    from lofc.store.models import ScoutCriterionScore

    columns = {c.name for c in ScoutCriterionScore.__table__.columns}
    assert {"assessment_id", "criterion_key", "score", "passed"} <= columns
    # Psychological uses `score`, medical screening uses `passed`; both nullable.
    assert ScoutCriterionScore.__table__.c.score.nullable
    assert ScoutCriterionScore.__table__.c.passed.nullable


def test_player_injuries_gained_entered_by():
    from lofc.store.models import PlayerInjury

    assert "entered_by" in {c.name for c in PlayerInjury.__table__.columns}
    assert PlayerInjury.__table__.c.entered_by.nullable
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec app python -m pytest tests/test_store.py -k "scout or users or criterion or entered_by" -v`
Expected: FAIL — `ImportError: cannot import name 'ScoutAssessment'`

- [ ] **Step 3: Add the models**

Append to `src/lofc/store/models.py`, following the file's existing style. Ensure `Boolean`,
`Float`, `Date`, `DateTime`, `ForeignKey`, `UniqueConstraint` are in the imports at the top.

```python
class User(Base):
    """A person who can record or approve an assessment.

    USER DATA: never written or cleared by the pipeline. Passwords are stored only as a
    scrypt hash (see dashboard/auth.py); the plaintext never reaches the database.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String)          # scout | medical | head_of_recruitment | admin
    password_hash: Mapped[str] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())


class ScoutAssessment(Base):
    """One person's judgement of one dimension for one player-season.

    Decision 14: a `submitted` assessment SCORES. Sign-off does not gate visibility or
    ranking -- it marks the assessment approved and controls what may be exported as final.
    Nothing here is ever deleted, so disagreement between two assessors stays visible.
    """

    __tablename__ = "scout_assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("players.player_id"), index=True)
    competition_id: Mapped[int] = mapped_column(Integer, index=True)
    season_id: Mapped[int] = mapped_column(Integer, index=True)
    dimension: Mapped[str] = mapped_column(String, index=True)   # Psychological | Medical Risk
    author_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    band: Mapped[float | None] = mapped_column(Float, nullable=True)
    band_note: Mapped[str | None] = mapped_column(String, nullable=True)
    screening_failed: Mapped[bool] = mapped_column(Boolean, server_default="false")
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, server_default="draft")
    approved_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(),
                                                          onupdate=func.now())


class ScoutCriterionScore(Base):
    """One criterion inside an assessment. Psychological criteria carry `score` (1-5);
    medical screening criteria carry `passed`. Exactly one of the two is set."""

    __tablename__ = "scout_criterion_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assessment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("scout_assessments.id", ondelete="CASCADE"), index=True)
    criterion_key: Mapped[str] = mapped_column(String)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
```

And add to the existing `PlayerInjury` model:

```python
    entered_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
```

- [ ] **Step 4: Generate and review the migration**

Run: `docker compose exec app alembic revision --autogenerate -m "scout assessments"`

Open the generated file. Confirm `down_revision = "6677cea28903"`, and that it creates **only**
`users`, `scout_assessments`, `scout_criterion_scores` and adds `player_injuries.entered_by`.
**Delete any operation touching another table** — autogenerate picks up unrelated model drift,
and this database holds live recovered data.

- [ ] **Step 5: Apply and verify**

```bash
docker compose exec app alembic upgrade head
docker compose exec -T db psql -U lofc -d lofc -c "\d scout_assessments"
docker compose exec -T db psql -U lofc -d lofc -c "\d users"
```
Expected: both tables exist with the columns above.

Then confirm nothing was destroyed:
```bash
docker compose exec -T db psql -U lofc -d lofc -c "SELECT COUNT(contract_until) AS contracts, (SELECT COUNT(*) FROM player_injuries) AS injuries FROM players;"
```
Expected: **1363 contracts, 3766 injuries** — unchanged. **If either number moved, stop and report.**

- [ ] **Step 6: Run the full suite**

Run: `docker compose exec app python -m pytest -q`
Expected: PASS — **332 tests**

- [ ] **Step 7: Commit**

```bash
git add src/lofc/store/models.py alembic/versions/ tests/test_store.py
git commit -m "feat: scout assessment tables"
```

---

### Task 3: Authentication

**Files:**
- Create: `src/lofc/dashboard/auth.py`
- Create: `src/lofc/admin.py`
- Test: `tests/test_auth.py`

**Interfaces:**
- Consumes: `User` from Task 2
- Produces: `hash_password(password: str) -> str`, `verify_password(password: str, stored: str) -> bool`, `ROLES: tuple[str, ...]`, `can(role: str, action: str) -> bool`, and an `admin` CLI with a `create-user` command

**Hashing:** `hashlib.scrypt` from the standard library. Store as
`scrypt$<n>$<r>$<p>$<salt_hex>$<hash_hex>` so parameters travel with the hash and can be
changed later without invalidating existing users. Use `secrets.token_bytes(16)` for the salt
and `hmac.compare_digest` for comparison — **never `==`**, which leaks timing.

**Permissions** (spec §12):

| action | scout | medical | head_of_recruitment | admin |
|---|---|---|---|---|
| `assess_psychological` | ✅ | ✅ | ✅ | ✅ |
| `assess_medical` | ✅ | ✅ | ✅ | ✅ |
| `enter_injury` | ✅ | ✅ | ✅ | ✅ |
| `sign_off` | — | — | ✅ | ✅ |
| `manage_users` | — | — | — | ✅ |

**Decision 16: everyone assesses; only sign-off is restricted.** The department is small enough
that splitting the two dimensions by role would block routine work. The role is therefore a
**record** — displayed wherever an assessment appears ("entered by J. Smith (scout)") — not a
restriction. Tightening later is one line in `_PERMISSIONS`, with no migration and no data change.

- [ ] **Step 1: Write the failing test**

```python
"""Password hashing and role permissions. No database, no network."""

import pytest

from lofc.dashboard.auth import ROLES, can, hash_password, verify_password


def test_a_correct_password_verifies():
    stored = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", stored)


def test_a_wrong_password_does_not_verify():
    stored = hash_password("correct horse battery staple")
    assert not verify_password("Correct horse battery staple", stored)
    assert not verify_password("", stored)


def test_the_same_password_hashes_differently_each_time():
    # A per-user salt means two users with the same password do not share a hash.
    assert hash_password("same") != hash_password("same")


def test_the_stored_hash_never_contains_the_password():
    stored = hash_password("hunter2")
    assert "hunter2" not in stored


def test_the_hash_carries_its_parameters_so_they_can_change_later():
    stored = hash_password("x")
    assert stored.startswith("scrypt$")
    assert len(stored.split("$")) == 6


def test_a_malformed_stored_hash_is_rejected_not_crashed():
    for bad in ("", "notahash", "scrypt$1$2", "bcrypt$a$b$c$d$e"):
        assert not verify_password("x", bad)


def test_roles_are_exactly_the_four_the_spec_defines():
    assert set(ROLES) == {"scout", "medical", "head_of_recruitment", "admin"}


def test_every_role_may_assess_both_dimensions():
    """Decision 16: the department is too small to split the dimensions by role.
    The role records WHO entered a band; it does not restrict which band they may enter."""
    for role in ROLES:
        assert can(role, "assess_psychological"), role
        assert can(role, "assess_medical"), role
        assert can(role, "enter_injury"), role


def test_sign_off_is_the_only_gated_assessment_action():
    assert can("head_of_recruitment", "sign_off")
    assert can("admin", "sign_off")
    assert not can("scout", "sign_off")
    assert not can("medical", "sign_off")


def test_only_admin_manages_users():
    assert can("admin", "manage_users")
    for role in ("scout", "medical", "head_of_recruitment"):
        assert not can(role, "manage_users"), role


def test_an_unknown_role_or_action_is_denied_not_crashed():
    assert not can("intern", "sign_off")
    assert not can("admin", "launch_missiles")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec app python -m pytest tests/test_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lofc.dashboard.auth'`

- [ ] **Step 3: Write the implementation**

Create `src/lofc/dashboard/auth.py`:

```python
"""Authentication and role permissions for the scout assessment system.

Passwords are hashed with hashlib.scrypt from the standard library -- deliberately no new
dependency. The stored form carries its own parameters:

    scrypt$<n>$<r>$<p>$<salt_hex>$<hash_hex>

so the cost can be raised later without invalidating existing users: verify with the
parameters in the stored string, and re-hash on the next successful login if they are stale.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

# scrypt cost. n must be a power of two. These are the interactive-login parameters from
# the Python docs; raising n is the way to make hashing more expensive later.
_N, _R, _P = 2 ** 14, 8, 1
_DKLEN = 32

ROLES: tuple[str, ...] = ("scout", "medical", "head_of_recruitment", "admin")

# Decision 16: EVERY role may assess both dimensions. The department is small enough that
# splitting them by role would block routine work, so the role is a RECORD of who entered a
# band -- displayed wherever the assessment appears -- rather than a restriction.
# Sign-off is the only gated assessment action. To tighten this later, narrow the sets below:
# no migration and no data change is needed, because the roles already recorded stay valid.
_ASSESSING = {"assess_psychological", "assess_medical", "enter_injury"}

_PERMISSIONS: dict[str, frozenset[str]] = {
    "scout": frozenset(_ASSESSING),
    "medical": frozenset(_ASSESSING),
    "head_of_recruitment": frozenset(_ASSESSING | {"sign_off"}),
    "admin": frozenset(_ASSESSING | {"sign_off", "manage_users"}),
}


def hash_password(password: str) -> str:
    """Hash a password for storage. A fresh random salt per call, so two users sharing a
    password do not share a hash."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                            n=_N, r=_R, p=_P, dklen=_DKLEN)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """True if `password` produced `stored`. A malformed or unrecognised stored value
    returns False rather than raising -- a corrupt row must not crash a login page."""
    try:
        scheme, n, r, p, salt_hex, digest_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
                                n=int(n), r=int(r), p=int(p), dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def can(role: str, action: str) -> bool:
    """Whether `role` may perform `action`. Unknown roles and actions are denied."""
    return action in _PERMISSIONS.get(role, frozenset())
```

Create `src/lofc/admin.py`:

```python
"""User administration CLI. There is deliberately no self-service signup.

    python -m lofc.admin create-user --username fi --name "..." --role admin
"""

from __future__ import annotations

import argparse
import getpass

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from lofc.config import settings
from lofc.dashboard.auth import ROLES, hash_password
from lofc.store.models import User


def create_user(username: str, full_name: str, role: str, password: str) -> None:
    if role not in ROLES:
        raise SystemExit(f"unknown role {role!r}; expected one of {', '.join(ROLES)}")
    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        if session.scalar(select(User).where(User.username == username)):
            raise SystemExit(f"user {username!r} already exists")
        session.add(User(username=username, full_name=full_name, role=role,
                         password_hash=hash_password(password)))
        session.commit()
    print(f"created {role} {username!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage platform users")
    sub = parser.add_subparsers(dest="command", required=True)
    new = sub.add_parser("create-user")
    new.add_argument("--username", required=True)
    new.add_argument("--name", required=True)
    new.add_argument("--role", required=True, choices=ROLES)
    args = parser.parse_args()

    if args.command == "create-user":
        password = getpass.getpass("password: ")
        if not password:
            raise SystemExit("empty password")
        create_user(args.username, args.name, args.role, password)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec app python -m pytest tests/test_auth.py -v`
Expected: PASS — 11 tests

- [ ] **Step 5: Run the full suite**

Run: `docker compose exec app python -m pytest -q`
Expected: PASS — **343 tests** (332 + 11)

- [ ] **Step 6: Commit**

```bash
git add src/lofc/dashboard/auth.py src/lofc/admin.py tests/test_auth.py
git commit -m "feat: password hashing, role permissions and the user admin CLI"
```

---

### Task 4: Resolve assessments into scoring bands

**Files:**
- Create: `src/lofc/model/scout_scores.py`
- Test: `tests/test_scout_scores.py`

**Interfaces:**
- Consumes: `scout_assessments` rows (passed in as a frame — no database in the tests)
- Produces: `resolve_bands(assessments: pd.DataFrame) -> pd.DataFrame` returning one row per
  `(player_id, competition_id, season_id)` with columns `psychological_band`, `medical_band`,
  `psychological_status`, `medical_status`

**The resolution rule** (Decision 14, spec §12):
1. A **signed-off** assessment wins for its dimension.
2. If none is signed off, the **most recent submitted** one scores.
3. `draft` never scores.
4. The two dimensions resolve **independently** — a signed-off Medical does not affect Psychological.
5. The returned `*_status` column carries `signed_off` or `submitted`, so the caller can badge it.

This mirrors the interface `financial_resale` already presents to `scorecard.py`, which is why
Task 5 is a small change.

- [ ] **Step 1: Write the failing test**

```python
"""Turning many submitted assessments into one scoring band per dimension."""

import pandas as pd

from lofc.model.scout_scores import resolve_bands

PSY, MED = "Psychological", "Medical Risk"


def _rows(*records) -> pd.DataFrame:
    frame = pd.DataFrame(list(records))
    frame["updated_at"] = pd.to_datetime(frame["updated_at"])
    return frame


def test_a_submitted_assessment_scores_without_sign_off():
    # Decision 14: sign-off is not a gate on scoring.
    out = resolve_bands(_rows(
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=3.8, status="submitted", updated_at="2026-08-01"),
        dict(player_id=1, competition_id=4, season_id=318, dimension=MED,
             band=3.0, status="submitted", updated_at="2026-08-01"),
    ))
    assert out.loc[0, "psychological_band"] == 3.8
    assert out.loc[0, "medical_band"] == 3.0
    assert out.loc[0, "psychological_status"] == "submitted"


def test_a_signed_off_assessment_beats_a_newer_submitted_one():
    out = resolve_bands(_rows(
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=4.0, status="signed_off", updated_at="2026-08-01"),
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=2.0, status="submitted", updated_at="2026-08-09"),
    ))
    assert out.loc[0, "psychological_band"] == 4.0
    assert out.loc[0, "psychological_status"] == "signed_off"


def test_the_most_recent_submitted_wins_when_none_is_signed_off():
    out = resolve_bands(_rows(
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=2.0, status="submitted", updated_at="2026-08-01"),
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=4.5, status="submitted", updated_at="2026-08-09"),
    ))
    assert out.loc[0, "psychological_band"] == 4.5


def test_a_draft_never_scores():
    out = resolve_bands(_rows(
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=5.0, status="draft", updated_at="2026-08-09"),
    ))
    assert out.empty or pd.isna(out.loc[0, "psychological_band"])


def test_the_two_dimensions_resolve_independently():
    out = resolve_bands(_rows(
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=3.0, status="submitted", updated_at="2026-08-01"),
        dict(player_id=1, competition_id=4, season_id=318, dimension=MED,
             band=2.0, status="signed_off", updated_at="2026-08-02"),
    ))
    assert out.loc[0, "psychological_status"] == "submitted"
    assert out.loc[0, "medical_status"] == "signed_off"


def test_the_same_player_in_two_seasons_resolves_separately():
    out = resolve_bands(_rows(
        dict(player_id=1, competition_id=4, season_id=317, dimension=PSY,
             band=2.0, status="submitted", updated_at="2026-08-01"),
        dict(player_id=1, competition_id=4, season_id=318, dimension=PSY,
             band=4.0, status="submitted", updated_at="2026-08-01"),
    )).set_index("season_id")
    assert out.loc[317, "psychological_band"] == 2.0
    assert out.loc[318, "psychological_band"] == 4.0


def test_an_empty_frame_returns_an_empty_result_with_the_right_columns():
    out = resolve_bands(pd.DataFrame(columns=[
        "player_id", "competition_id", "season_id", "dimension",
        "band", "status", "updated_at"]))
    assert out.empty
    assert {"psychological_band", "medical_band"} <= set(out.columns)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec app python -m pytest tests/test_scout_scores.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lofc.model.scout_scores'`

- [ ] **Step 3: Write the implementation**

Create `src/lofc/model/scout_scores.py`:

```python
"""Resolve many submitted assessments into one scoring band per dimension.

Decision 14: a `submitted` assessment SCORES. Sign-off marks it approved and controls what
may be exported as final; it is not a gate on ranking. A signed-off assessment still wins
over a newer submitted one, because it is the reviewed judgement.

The frame this returns is keyed the same way `financial_resale` is, so `scorecard.py`
consumes it through the interface it already has.
"""

from __future__ import annotations

import pandas as pd

PSYCHOLOGICAL = "Psychological"
MEDICAL = "Medical Risk"

KEY = ["player_id", "competition_id", "season_id"]
_SCORING_STATUSES = ("signed_off", "submitted")
OUTPUT_COLUMNS = KEY + ["psychological_band", "psychological_status",
                        "medical_band", "medical_status"]


def _winner(group: pd.DataFrame) -> pd.Series:
    """Signed-off wins; otherwise the most recently updated submitted assessment."""
    signed = group[group["status"] == "signed_off"]
    pool = signed if not signed.empty else group[group["status"] == "submitted"]
    return pool.sort_values("updated_at").iloc[-1]


def resolve_bands(assessments: pd.DataFrame) -> pd.DataFrame:
    """One row per player-season with the band that scores for each dimension."""
    if assessments.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    scoring = assessments[assessments["status"].isin(_SCORING_STATUSES)]
    if scoring.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    records: dict[tuple, dict] = {}
    for (dimension, *key), group in scoring.groupby(["dimension"] + KEY):
        row = _winner(group)
        prefix = "psychological" if dimension == PSYCHOLOGICAL else "medical"
        record = records.setdefault(tuple(key), dict(zip(KEY, key)))
        record[f"{prefix}_band"] = float(row["band"]) if pd.notna(row["band"]) else None
        record[f"{prefix}_status"] = row["status"]

    return pd.DataFrame(list(records.values())).reindex(columns=OUTPUT_COLUMNS)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec app python -m pytest tests/test_scout_scores.py -v`
Expected: PASS — 7 tests

- [ ] **Step 5: Run the full suite**

Run: `docker compose exec app python -m pytest -q`
Expected: PASS — **350 tests** (343 + 7)

- [ ] **Step 6: Commit**

```bash
git add src/lofc/model/scout_scores.py tests/test_scout_scores.py
git commit -m "feat: resolve scout assessments into scoring bands"
```

---

### Task 5: `assessed_composite`

**Files:**
- Modify: `src/lofc/model/scorecard.py`
- Modify: `src/lofc/model/scorecard_run.py`
- Modify: `src/lofc/store/models.py` (two columns on `PlayerScorecard`)
- Create: `alembic/versions/<generated>_assessed_composite.py`
- Test: `tests/test_scorecard.py` (append)

**Interfaces:**
- Consumes: the frame from `scout_scores.resolve_bands`
- Produces: `assessed_composite` and `assessed_weight_covered` on each scorecard row

**The change to `scorecard.py`:** `build_scorecards` gains an optional `scout_bands` parameter,
handled exactly like the existing `financial_resale`. Where a player has both scout bands, they
enter `dim_bands` and a third composite is computed over **four** dimensions — Performance,
Physical, Psychological and Medical. **Not six: per spec Decision 15, the modelled Financial and
Resale dimensions are deliberately excluded from `assessed_composite`, in every case, whether or
not the player has a market value.** `full_composite` (Performance + Physical + Financial +
Resale) remains the only composite carrying modelled money, exactly as today.

**Decision 9 — `assessed_composite` is NULL unless BOTH dimensions are present.** A player with
only one is not partially assessed; he is unassessed for this purpose.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_scorecard.py`:

```python
def test_composite_renormalises_so_the_both_or_neither_guard_must_live_in_the_caller():
    """_composite happily renormalises over whatever is present -- give it Psychological
    without Medical and it returns a number. That is why Decision 9's both-or-neither rule
    is enforced in build_scorecards before calling it, not inside it. This test exists so
    nobody "simplifies" the guard away believing _composite already handles it."""
    from lofc.model.scorecard import _composite
    from lofc.model import club_framework as cf

    weights = cf.DIMENSION_WEIGHTS["Winger"]
    partial = {cf.PERFORMANCE: 4.0, cf.PHYSICAL: 3.5, cf.PSYCHOLOGICAL: 3.8}
    value, covered = _composite(partial, weights, cf.DATA_DIMENSIONS + cf.SCOUT_DIMENSIONS)
    assert value is not None and covered < 1.0


def test_assessed_composite_excludes_financial_and_resale():
    """Decision 15: assessed_composite = Performance + Physical + Psychological + Medical --
    never the modelled Financial and Resale dimensions. Financial and Resale are present in
    `bands` here, exactly as they would be for a real player with a market value, precisely to
    prove they are NOT picked up: ASSESSED_DIMENSIONS never names them, so `covered` stops at
    0.86, not 1.0, and the two modelled bands cannot move `value`."""
    from lofc.model.scorecard import ASSESSED_DIMENSIONS, _composite
    from lofc.model import club_framework as cf

    weights = cf.DIMENSION_WEIGHTS["Winger"]
    bands = {cf.PERFORMANCE: 4.0, cf.PHYSICAL: 3.5, cf.FINANCIAL: 3.0,
             cf.RESALE: 4.0, cf.PSYCHOLOGICAL: 3.8, cf.MEDICAL: 3.0}
    value, covered = _composite(bands, weights, ASSESSED_DIMENSIONS)
    assert covered == pytest.approx(0.86, abs=0.01)
    assert value == pytest.approx(3.66, abs=0.01)


def test_assessed_composite_does_not_move_when_the_money_bands_change():
    """The regression Decision 15 exists to catch: if changing Financial or Resale ever moved
    assessed_composite, modelled money would have leaked back into the assessed tier."""
    from lofc.model.scorecard import ASSESSED_DIMENSIONS, _composite
    from lofc.model import club_framework as cf

    weights = cf.DIMENSION_WEIGHTS["Winger"]
    base = {cf.PERFORMANCE: 4.0, cf.PHYSICAL: 3.5, cf.PSYCHOLOGICAL: 3.8, cf.MEDICAL: 3.0}
    cheap = dict(base, **{cf.FINANCIAL: 1.0, cf.RESALE: 1.0})
    expensive = dict(base, **{cf.FINANCIAL: 5.0, cf.RESALE: 5.0})
    no_market_value = dict(base)  # Scottish/PL2 player: Financial and Resale absent entirely

    assert (_composite(base, weights, ASSESSED_DIMENSIONS)
            == _composite(cheap, weights, ASSESSED_DIMENSIONS)
            == _composite(expensive, weights, ASSESSED_DIMENSIONS)
            == _composite(no_market_value, weights, ASSESSED_DIMENSIONS))


def test_objective_and_full_composites_are_unchanged_by_scout_bands():
    """The default ranking must not move when an assessment lands."""
    from lofc.model.scorecard import _composite
    from lofc.model import club_framework as cf

    weights = cf.DIMENSION_WEIGHTS["Winger"]
    without = {cf.PERFORMANCE: 4.0, cf.PHYSICAL: 3.5, cf.FINANCIAL: 3.0, cf.RESALE: 4.0}
    with_scout = dict(without, **{cf.PSYCHOLOGICAL: 3.8, cf.MEDICAL: 3.0})

    assert (_composite(without, weights, [cf.PERFORMANCE, cf.PHYSICAL])
            == _composite(with_scout, weights, [cf.PERFORMANCE, cf.PHYSICAL]))
    assert (_composite(without, weights, cf.DATA_DIMENSIONS)
            == _composite(with_scout, weights, cf.DATA_DIMENSIONS))
```

Ensure `import pytest` is present at the top of that test file.

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec app python -m pytest tests/test_scorecard.py -k assessed -v`
Expected: FAIL — `ImportError: cannot import name 'ASSESSED_DIMENSIONS' from 'lofc.model.scorecard'`.

- [ ] **Step 3: Implement**

In `src/lofc/model/scorecard.py`:

1. Near the top of the module, define the dimension list `assessed_composite` sums over —
   **not** `cf.DATA_DIMENSIONS + cf.SCOUT_DIMENSIONS`, which would pull in the modelled
   Financial and Resale dimensions:
```python
# Decision 15: assessed_composite is real data (Performance, Physical) plus human judgement
# (Psychological, Medical) -- deliberately NOT cf.DATA_DIMENSIONS, which also carries the
# modelled Financial and Resale dimensions. Money stays out of every ranking-shaped number
# in the platform; do not "complete" this list later.
ASSESSED_DIMENSIONS = [cf.PERFORMANCE, cf.PHYSICAL] + cf.SCOUT_DIMENSIONS
```
2. Add the parameter: `def build_scorecards(neutral, financial_resale=None, archetype_by_position=None, scout_bands=None)`.
3. Index it like the existing frame:
```python
    scout = None
    if scout_bands is not None and not scout_bands.empty:
        scout = scout_bands.set_index(["player_id", "competition_id", "season_id"])
```
4. After the financial/resale block, add the scout bands to `dim_bands`:
```python
        psychological = medical = None
        if scout is not None and (player_id, competition_id, season_id) in scout.index:
            srow = scout.loc[(player_id, competition_id, season_id)]
            if pd.notna(srow.get("psychological_band")):
                psychological = round(float(srow["psychological_band"]), 2)
            if pd.notna(srow.get("medical_band")):
                medical = round(float(srow["medical_band"]), 2)
        # Decision 9: both, or neither. One dimension is not a partial assessment.
        if psychological is not None and medical is not None:
            dim_bands[cf.PSYCHOLOGICAL] = psychological
            dim_bands[cf.MEDICAL] = medical
```
5. Compute the third composite and add both fields to `record`. Note this uses
   `ASSESSED_DIMENSIONS`, not `dim_bands`' full key set — `dim_bands` may also carry
   `cf.FINANCIAL` / `cf.RESALE` from the financial/resale block above, and `_composite` only
   sums the dimensions named in the list it is given, so those two are never picked up here:
```python
        assessed, assessed_w = (None, 0.0)
        if cf.PSYCHOLOGICAL in dim_bands and cf.MEDICAL in dim_bands:
            assessed, assessed_w = _composite(
                dim_bands, weights, ASSESSED_DIMENSIONS)
```
and in the record dict:
```python
            "psychological_band": dim_bands.get(cf.PSYCHOLOGICAL),
            "medical_band": dim_bands.get(cf.MEDICAL),
            "assessed_composite": assessed,
            "assessed_weight_covered": assessed_w,
```

**Do not change how `objective` or `full` are computed.** They already pass an explicit
dimension list, so adding keys to `dim_bands` cannot affect them — the tests above prove it.

In `src/lofc/store/models.py`, add to `PlayerScorecard`:
```python
    psychological_band: Mapped[float | None] = mapped_column(Float, nullable=True)
    medical_band: Mapped[float | None] = mapped_column(Float, nullable=True)
    assessed_composite: Mapped[float | None] = mapped_column(Float, nullable=True)
    assessed_weight_covered: Mapped[float | None] = mapped_column(Float, nullable=True)
```

In `src/lofc/model/scorecard_run.py`, load the assessments and pass them through:
```python
    assessments = pd.read_sql(
        "SELECT player_id, competition_id, season_id, dimension, band, status, updated_at "
        "FROM scout_assessments", engine)
    scout_bands = resolve_bands(assessments)
```
and include the four new columns in whatever column list it writes.

- [ ] **Step 4: Migration**

```bash
docker compose exec app alembic revision --autogenerate -m "assessed composite"
```
Review it: it must add **only** the four columns to `player_scorecards`. Then:
```bash
docker compose exec app alembic upgrade head
```

- [ ] **Step 5: Verify the default ranking did not move**

```bash
docker compose exec -T db psql -U lofc -d lofc -c "SELECT COUNT(*) FILTER (WHERE objective_composite IS NOT NULL) AS scored, ROUND(AVG(objective_composite)::numeric,4) AS avg_obj FROM player_scorecards WHERE archetype='All Metrics';"
```
Record the numbers, re-run `docker compose exec app python -m lofc.model.scorecard_run`, and run
the query again. **`avg_obj` must be identical.** If it moved, stop and report — the default
ranking changed, which this plan forbids.

- [ ] **Step 6: Run the full suite**

Run: `docker compose exec app python -m pytest -q`
Expected: PASS — **354 tests** (319 existing + 35 new: 9 + 4 + 11 + 7 + 4)

- [ ] **Step 7: Commit**

```bash
git add src/lofc/model/scorecard.py src/lofc/model/scorecard_run.py src/lofc/store/models.py alembic/versions/ tests/test_scorecard.py
git commit -m "feat: assessed_composite from scout assessments"
```

---

## Definition of done

- The club's criteria are encoded verbatim, with the Full Back and Winger merges as specified.
- `users`, `scout_assessments` and `scout_criterion_scores` exist; `player_injuries` has `entered_by`.
- Passwords hash with stdlib scrypt; roles gate the four actions; an admin can be created by CLI.
- A submitted assessment resolves to a scoring band; a signed-off one wins over a newer submitted one.
- `assessed_composite` is computed over Performance + Physical + Psychological + Medical — 86% of
  the outfield weight, deliberately excluding the modelled Financial and Resale dimensions (spec
  Decision 15) — and is NULL unless both scout dimensions exist.
- **`objective_composite` and `full_composite` are unchanged** — verified numerically, not assumed.
- 354 tests pass.

## What this plan deliberately does not do

- **No user interface.** No login screen, no assessment form, no evidence panel, no badges. That
  is R3a-2, which must invoke the frontend design skill per spec §16.
- **No injury evidence display.** The panel showing availability, injury history and the coverage
  warning belongs to R3a-2.
- **No export.** That is R3c.
- **No watchlist integration.** The assessment-status badge on watchlist rows, the "Assess" action
  from a watchlist row, and filtering the watchlist by assessment status (spec §7) are all
  interface work for R3a-2, not this foundation plan. No change to the `watchlist` table is
  required here or there — the status is derived by joining on the (player, competition, season)
  triple both tables already share.
- **Nothing is wired into the Players tab.** `assessed_composite` is computed and stored, but no
  surface reads it yet.
