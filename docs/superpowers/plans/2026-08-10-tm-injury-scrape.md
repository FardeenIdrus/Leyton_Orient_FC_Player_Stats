# Transfermarkt Injury Scrape (R3a-0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scrape Transfermarkt injury histories for EFL players, load them into Postgres, and compute each player's availability — the objective input the Medical dimension needs.

**Architecture:** A polite single-page scraper writes a resumable CSV; a loader joins it to our players on `players.tm_player_id`; a pure function turns games-missed into an availability fraction. Nothing in this plan touches scoring — it delivers data and a calculation that the scout assessment system (plan 2) consumes.

**Tech Stack:** Python 3.11, `urllib.request` (stdlib), `re`, pandas, SQLAlchemy 2.0 + Alembic, pytest. All commands run inside Docker.

**Spec:** `docs/superpowers/specs/2026-08-10-scout-assessment-design.md` (sections 3, 4, 8, 11, 12)

## Global Constraints

- **Everything runs in Docker.** Prefix every command: `docker compose exec app …`. The host is Python 3.14; the container is 3.11.
- **No new dependencies.** Use the standard library plus what is already installed (pandas, SQLAlchemy, BeautifulSoup).
- **No network in tests.** Every parser test uses inline HTML strings, matching the existing `tests/test_transfermarkt_efl.py` pattern. There is no `tests/fixtures/` directory and this plan does not create one.
- **Schema changes go through Alembic.** Current head is `e2f7b91c6a55`.
- **Never run git commit or git push.** Print the commands for the user to run. The "Commit" step in each task means *print the command*, not execute it.
- **Scrape politeness is non-negotiable:** 2.5 second delay between requests, browser user agent, exponential backoff. Never lower these.
- Existing test count is **191**; it must only ever go up.

---

### Task 0: Decouple player identity from valuation

**The bug:** `load_efl_values()` at `src/lofc/model/valuation.py:206` starts with
`efl.dropna(subset=["market_value_eur"])`, discarding every scraped squad row that has no
market value **before matching begins** — and with it that player's Transfermarkt id, birth
date, foot and contract date. Transfermarkt prices only **15 of 596** National League players,
so 581 of them are thrown away for a missing *commercial* fact, even though their *identity*
data is complete (586 have a birth date).

Result: the National League has a `tm_player_id` for **60 of 769** players (8%), against
68–78% in the three EFL divisions above it.

Identity is not valuation. This task matches identity independently, which lifts the injury
scrape's reach from ~1,619 players to ~2,150 and improves National League contract coverage
for free.

**Approach:** additive. `match_players_efl` is left completely untouched so valuation cannot
regress — a new, simpler matcher does birth-date + name only, over the *full* CSV.

**Files:**
- Create: `src/lofc/model/identity.py`
- Modify: `src/lofc/pipeline.py:79` (add a step after Valuation)
- Test: `tests/test_identity.py`

**Interfaces:**
- Consumes: `_norm` and `_dob_name_match` from `lofc.model.valuation` (reused deliberately so the two matchers cannot drift apart on name normalisation)
- Produces: `load_efl_identity(path: Path | None = None) -> pd.DataFrame`, `match_identity(ours: pd.DataFrame, squad: pd.DataFrame) -> pd.DataFrame` returning columns `player_id, tm_player_id, birth_date, foot, contract_until, height_cm`, and `main() -> None`

- [ ] **Step 1: Write the failing test**

```python
"""Player identity matching, independent of whether Transfermarkt priced the player."""

import pandas as pd

from lofc.model.identity import load_efl_identity, match_identity

SQUAD_CSV_ROWS = [
    # A Championship player WITH a market value.
    {"league_code": "GB2", "competition_id": 3, "club_name": "Ipswich",
     "tm_player_id": 111, "player_name": "Sam Morsy", "date_of_birth": "1991-09-10",
     "position": "DM", "height_cm": 178, "foot": "right",
     "contract_until": "2027-06-30", "market_value_eur": 2000000},
    # A National League player with NO market value -- the case that is being dropped today.
    {"league_code": "CNAT", "competition_id": 65, "club_name": "Barnet",
     "tm_player_id": 222, "player_name": "Nicke Kabamba", "date_of_birth": "1993-05-05",
     "position": "CF", "height_cm": 188, "foot": "right",
     "contract_until": "2027-06-30", "market_value_eur": ""},
    # No Transfermarkt id -- cannot be used for identity at all.
    {"league_code": "CNAT", "competition_id": 65, "club_name": "Barnet",
     "tm_player_id": "", "player_name": "No Id", "date_of_birth": "1995-01-01",
     "position": "CB", "height_cm": 185, "foot": "left",
     "contract_until": "", "market_value_eur": ""},
]


def _csv(tmp_path):
    path = tmp_path / "efl_values.csv"
    pd.DataFrame(SQUAD_CSV_ROWS).to_csv(path, index=False)
    return path


def test_identity_load_keeps_players_with_no_market_value(tmp_path):
    # This is the whole point of the task: valuation drops these, identity must not.
    squad = load_efl_identity(_csv(tmp_path))
    assert 222 in set(squad["tm_player_id"])


def test_identity_load_drops_rows_with_no_transfermarkt_id(tmp_path):
    squad = load_efl_identity(_csv(tmp_path))
    assert len(squad) == 2
    assert squad["tm_player_id"].notna().all()


def test_match_identity_links_an_unvalued_player(tmp_path):
    squad = load_efl_identity(_csv(tmp_path))
    ours = pd.DataFrame([
        {"player_id": 900, "player_name": "Nicke Kabamba",
         "birth_date": "1993-05-05", "competition_id": 65},
    ])
    matched = match_identity(ours, squad)
    assert list(matched["player_id"]) == [900]
    assert int(matched.loc[0, "tm_player_id"]) == 222
    assert matched.loc[0, "foot"] == "right"


def test_match_identity_requires_the_same_birth_date(tmp_path):
    # Same name, different birth date: a namesake, never the same player.
    squad = load_efl_identity(_csv(tmp_path))
    ours = pd.DataFrame([
        {"player_id": 901, "player_name": "Nicke Kabamba",
         "birth_date": "2001-01-01", "competition_id": 65},
    ])
    assert match_identity(ours, squad).empty


def test_match_identity_is_league_scoped(tmp_path):
    # The right birth date and name, but we hold him in the wrong league.
    squad = load_efl_identity(_csv(tmp_path))
    ours = pd.DataFrame([
        {"player_id": 902, "player_name": "Nicke Kabamba",
         "birth_date": "1993-05-05", "competition_id": 3},
    ])
    assert match_identity(ours, squad).empty


def test_match_identity_skips_players_with_no_birth_date(tmp_path):
    squad = load_efl_identity(_csv(tmp_path))
    ours = pd.DataFrame([
        {"player_id": 903, "player_name": "Nicke Kabamba",
         "birth_date": None, "competition_id": 65},
    ])
    assert match_identity(ours, squad).empty
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec app python -m pytest tests/test_identity.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lofc.model.identity'`

- [ ] **Step 3: Write the implementation**

Create `src/lofc/model/identity.py`:

```python
"""Player identity from the Transfermarkt squad scrape -- independent of valuation.

WHY THIS EXISTS: `valuation.load_efl_values()` drops every scraped row without a market
value before matching, which also throws away that player's Transfermarkt id, birth date,
foot and contract date. Transfermarkt prices only 15 of 596 National League players, so
that league ended up with a TM id for 8% of players against 68-78% in the divisions above.

A Transfermarkt id is an IDENTITY fact; a market value is a COMMERCIAL one. One must not
gate the other. This module matches identity over the FULL scrape.

`valuation.match_players_efl` is deliberately left untouched -- it still owns valuation,
and this runs alongside it. The name-normalisation helpers are imported rather than copied
so the two matchers cannot drift apart.

Run:  python -m lofc.model.identity
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pandas as pd
from sqlalchemy import bindparam, create_engine, update

from lofc.config import settings
from lofc.model.valuation import (
    EFL_LEAGUE_IDS,
    EFL_SEASON_ID,
    _dob_name_match,
    _norm,
    _tmdir,
)
from lofc.store.models import Player

IDENTITY_COLUMNS = ["player_id", "tm_player_id", "birth_date", "foot",
                    "contract_until", "height_cm"]


def load_efl_identity(path: Path | None = None) -> pd.DataFrame:
    """Every scraped squad row that carries a Transfermarkt id and a birth date.

    Deliberately does NOT filter on market_value_eur -- that is the bug this fixes.
    """
    path = path or (_tmdir() / "efl_values.csv")
    frame = pd.read_csv(path)
    frame["nname"] = frame["player_name"].map(_norm)
    frame["birth_date"] = pd.to_datetime(frame["date_of_birth"], errors="coerce")
    frame["tm_player_id"] = pd.to_numeric(frame["tm_player_id"], errors="coerce")
    frame = frame.dropna(subset=["birth_date", "tm_player_id"])
    return frame.reset_index(drop=True)


def match_identity(ours: pd.DataFrame, squad: pd.DataFrame) -> pd.DataFrame:
    """Link our players to their Transfermarkt row on exact birth date + name,
    within the same league.

    `ours` needs columns: player_id, player_name, birth_date, competition_id.
    Birth date is required on both sides -- a name-only match is not safe enough to
    write an identity, as the 54-namesake audit showed.
    """
    by_dob: dict[tuple[int, object], list[int]] = defaultdict(list)
    for i, row in enumerate(squad.itertuples()):
        by_dob[(row.competition_id, row.birth_date.date())].append(i)

    rows = []
    for r in ours.itertuples():
        if pd.isna(r.birth_date):
            continue
        dob = pd.to_datetime(r.birth_date).date()
        i = _dob_name_match(_norm(r.player_name),
                            by_dob.get((r.competition_id, dob), []), squad)
        if i is None:
            continue

        def cell(name, cast=None):
            if name not in squad.columns:
                return None
            value = squad.at[i, name]
            if pd.isna(value) or value == "":
                return None
            return cast(value) if cast else value

        rows.append({
            "player_id": int(r.player_id),
            "tm_player_id": int(squad.at[i, "tm_player_id"]),
            "birth_date": dob,
            "foot": cell("foot"),
            "contract_until": cell("contract_until"),
            "height_cm": cell("height_cm", int),
        })
    return pd.DataFrame(rows, columns=IDENTITY_COLUMNS)


def main() -> None:
    path = _tmdir() / "efl_values.csv"
    if not path.exists():
        print(f"{path} not found -- run lofc.ingest.transfermarkt_efl first")
        return

    engine = create_engine(settings.database_url)
    ours = pd.read_sql(
        "SELECT DISTINCT n.player_id, p.player_name, p.birth_date, n.competition_id "
        "FROM player_metrics_neutral n JOIN players p ON p.player_id = n.player_id "
        f"WHERE n.season_id = {EFL_SEASON_ID} "
        f"AND n.competition_id IN ({','.join(str(c) for c in sorted(EFL_LEAGUE_IDS))})",
        engine)

    matched = match_identity(ours, load_efl_identity(path))
    if matched.empty:
        print("no identity matches")
        return

    stmt = (update(Player.__table__)
            .where(Player.__table__.c.player_id == bindparam("pid"))
            .values(tm_player_id=bindparam("tm"), foot=bindparam("ft"),
                    contract_until=bindparam("cu"), height_cm=bindparam("hc")))
    with engine.begin() as conn:
        conn.execute(stmt, [
            {"pid": int(r.player_id), "tm": int(r.tm_player_id),
             "ft": r.foot, "cu": r.contract_until,
             "hc": int(r.height_cm) if pd.notna(r.height_cm) else None}
            for r in matched.itertuples()])
    print(f"identity: linked {len(matched)} players to Transfermarkt")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec app python -m pytest tests/test_identity.py -v`
Expected: PASS — 6 tests

- [ ] **Step 5: Add the pipeline step**

In `src/lofc/pipeline.py`, immediately after the Valuation entry at line 79, insert:

```python
        ("Identity: link players to Transfermarkt (independent of market value)",
         [sys.executable, "-m", "lofc.model.identity"]),
```

It must run **after** valuation, so it can widen coverage that valuation established rather than be overwritten by it.

- [ ] **Step 6: Run it and measure the improvement**

```bash
docker compose exec app python -m lofc.model.identity
docker compose exec db psql -U lofc -d lofc -c "
SELECT n.competition_id, COUNT(DISTINCT n.player_id) AS ours,
       COUNT(DISTINCT n.player_id) FILTER (WHERE p.tm_player_id IS NOT NULL) AS with_tm
FROM player_metrics_neutral n JOIN players p ON p.player_id=n.player_id
WHERE n.season_id=318 GROUP BY 1 ORDER BY 1;"
```

Expected: competition 65 (National League) rises from **60** towards **~550**; competitions 3, 4 and 5 hold at or above their current 580 / 546 / 510. **If any of the top three falls, stop** — the new matcher is overwriting good data and must be made additive-only.

- [ ] **Step 7: Run the full suite**

Run: `docker compose exec app python -m pytest -q`
Expected: PASS — 197 tests (191 + 6)

- [ ] **Step 8: Commit (print the command)**

```bash
git add src/lofc/model/identity.py src/lofc/pipeline.py tests/test_identity.py
git commit -m "fix: link player identity to Transfermarkt independently of market value"
```

---

### Task 1: Shared polite fetch client

Extracts the HTTP client from `transfermarkt_efl.py` so both scrapers share one implementation. Behaviour is unchanged — this is a pure move.

**Files:**
- Create: `src/lofc/ingest/transfermarkt_common.py`
- Modify: `src/lofc/ingest/transfermarkt_efl.py:40-64` (delete `_fetch` and its module constants, import instead)
- Test: `tests/test_transfermarkt_common.py`

**Interfaces:**
- Consumes: nothing
- Produces: `fetch(url: str, retries: int = 3) -> str`, plus module constants `REQUEST_DELAY_S: float = 2.5` and `USER_AGENT: str`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the shared Transfermarkt HTTP client. No network."""

import pytest

from lofc.ingest import transfermarkt_common as tm


class _FakeResponse:
    def __init__(self, body: bytes = b"<html>ok</html>"):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def test_fetch_sends_browser_user_agent(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["ua"] = request.headers["User-agent"]
        return _FakeResponse()

    monkeypatch.setattr(tm.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(tm.time, "sleep", lambda seconds: None)

    assert tm.fetch("https://example.test/page") == "<html>ok</html>"
    assert "Mozilla" in captured["ua"]


def test_fetch_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(request, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError("transient")
        return _FakeResponse(b"recovered")

    monkeypatch.setattr(tm.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(tm.time, "sleep", lambda seconds: None)

    assert tm.fetch("https://example.test/page") == "recovered"
    assert calls["n"] == 3


def test_fetch_raises_after_exhausting_retries(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise OSError("down")

    monkeypatch.setattr(tm.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(tm.time, "sleep", lambda seconds: None)

    with pytest.raises(OSError):
        tm.fetch("https://example.test/page", retries=2)


def test_politeness_constants_are_not_weakened():
    assert tm.REQUEST_DELAY_S >= 2.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec app python -m pytest tests/test_transfermarkt_common.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lofc.ingest.transfermarkt_common'`

- [ ] **Step 3: Write the implementation**

Create `src/lofc/ingest/transfermarkt_common.py`:

```python
"""Shared, polite HTTP client for the Transfermarkt scrapers.

Transfermarkt is a third-party site we are a guest on. The delay, the browser user
agent and the backoff are deliberate and must not be weakened: one scrape run makes
thousands of requests, and an impolite client gets the club's IP blocked.
"""

from __future__ import annotations

import time
import urllib.request

REQUEST_DELAY_S = 2.5
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

_last_request = 0.0


def fetch(url: str, retries: int = 3) -> str:
    """Rate-limited GET with a browser user agent and exponential backoff."""
    global _last_request
    wait = REQUEST_DELAY_S - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=60) as response:
                _last_request = time.monotonic()
                return response.read().decode("utf-8", "ignore")
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("unreachable")
```

- [ ] **Step 4: Point the existing scraper at it**

In `src/lofc/ingest/transfermarkt_efl.py`, delete the `REQUEST_DELAY_S`, `USER_AGENT`, `_last_request` constants and the whole `_fetch` function (lines 40–64), and add to the imports:

```python
from lofc.ingest.transfermarkt_common import fetch as _fetch
```

Leave `TM_SEASON` where it is — it is used elsewhere in the file. Remove the now-unused `import time` and `import urllib.request` from `transfermarkt_efl.py` **only if** nothing else in the file uses them; check with `grep -n "time\.\|urllib\." src/lofc/ingest/transfermarkt_efl.py` before deleting.

- [ ] **Step 5: Run the full suite to verify nothing regressed**

Run: `docker compose exec app python -m pytest -q`
Expected: PASS — **201** (197 after Task 0, plus the 4 new ones)

- [ ] **Step 6: Commit (print the command, do not run it)**

```bash
git add src/lofc/ingest/transfermarkt_common.py src/lofc/ingest/transfermarkt_efl.py tests/test_transfermarkt_common.py
git commit -m "refactor: extract shared Transfermarkt fetch client"
```

---

### Task 2: Injury page parsers

Pure string functions. The injury page is a six-column table: `Season | Injury | from | until | Days | Games missed`.

**Files:**
- Create: `src/lofc/ingest/transfermarkt_injuries.py`
- Test: `tests/test_transfermarkt_injuries.py`

**Interfaces:**
- Consumes: nothing (pure functions)
- Produces: `parse_tm_date(str) -> str | None`, `parse_days(str) -> int`, `parse_games_missed(str) -> int`, `parse_injury_rows(html: str) -> list[dict]`. Each dict has keys `season_label, injury_type_raw, date_from, date_until, days_out, games_missed`.

- [ ] **Step 1: Write the failing test**

```python
"""Parser tests for the Transfermarkt injury history page. Pure functions, no network."""

from lofc.ingest.transfermarkt_injuries import (
    parse_days,
    parse_games_missed,
    parse_injury_rows,
    parse_tm_date,
)

# A cut-down copy of the real page: a header row, two injuries, and an ongoing one
# with no end date and no games missed.
INJURY_HTML = """
<table class="items">
<tr><th>Season</th><th>Injury</th><th>from</th><th>until</th><th>Days</th><th>Games missed</th></tr>
<tr><td>25/26</td><td>muscular problems</td><td>18/08/2025</td><td>26/08/2025</td><td>9 days</td><td>2</td></tr>
<tr><td>24/25</td><td>Ligament injury</td><td>16/07/2024</td><td>12/09/2024</td><td>59 days</td><td>10</td></tr>
<tr><td>25/26</td><td>Rest</td><td>26/05/2026</td><td>-</td><td>12 days</td><td>-</td></tr>
</table>
"""


def test_parse_tm_date_formats():
    assert parse_tm_date("18/08/2025") == "2025-08-18"
    assert parse_tm_date(" 16/07/2024 ") == "2024-07-16"
    assert parse_tm_date("-") is None
    assert parse_tm_date("") is None


def test_parse_days():
    assert parse_days("9 days") == 9
    assert parse_days("59 days") == 59
    assert parse_days("-") == 0
    assert parse_days("") == 0


def test_parse_games_missed_treats_dash_as_zero():
    # A dash means the injury cost no matches, typically an off-season injury.
    assert parse_games_missed("2") == 2
    assert parse_games_missed("10") == 10
    assert parse_games_missed("-") == 0
    assert parse_games_missed("") == 0


def test_parse_injury_rows_extracts_all_injuries():
    rows = parse_injury_rows(INJURY_HTML)
    assert len(rows) == 3
    assert rows[0] == {
        "season_label": "25/26",
        "injury_type_raw": "muscular problems",
        "date_from": "2025-08-18",
        "date_until": "2025-08-26",
        "days_out": 9,
        "games_missed": 2,
    }


def test_parse_injury_rows_skips_the_header_row():
    rows = parse_injury_rows(INJURY_HTML)
    assert all(r["season_label"] != "Season" for r in rows)


def test_parse_injury_rows_handles_ongoing_injury():
    ongoing = parse_injury_rows(INJURY_HTML)[2]
    assert ongoing["date_until"] is None
    assert ongoing["games_missed"] == 0


def test_parse_injury_rows_returns_empty_for_a_player_with_no_injuries():
    # A clean player's page has no data rows. This is a valid result, not an error.
    assert parse_injury_rows("<table class='items'></table>") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec app python -m pytest tests/test_transfermarkt_injuries.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lofc.ingest.transfermarkt_injuries'`

- [ ] **Step 3: Write the implementation**

Create `src/lofc/ingest/transfermarkt_injuries.py`:

```python
"""Transfermarkt injury history: the objective input to the club's Medical dimension.

ONE page per player -- /verletzungen/spieler/<id> -- a stable six-column table:
    Season | Injury | from | until | Days | Games missed

The appearance page was evaluated and rejected: its columns shift between competition
types and its header row is a sort link rather than labels. Games missed is all the
availability rule needs (see the design spec, section 4).
"""

from __future__ import annotations

import re

# Data rows start with a season in "25/26" form; the header row does not.
_SEASON_RE = re.compile(r"^\d{2}/\d{2}$")
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)


def _cell_text(fragment: str) -> str:
    """Strip tags and normalise whitespace, including Transfermarkt's &nbsp; padding."""
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = text.replace("&nbsp;", " ").replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def parse_tm_date(text: str) -> str | None:
    """'18/08/2025' -> '2025-08-18'. A dash (ongoing injury) or junk -> None."""
    match = re.search(r"(\d{2})/(\d{2})/(\d{4})", text or "")
    if not match:
        return None
    day, month, year = match.groups()
    return f"{year}-{month}-{day}"


def parse_days(text: str) -> int:
    """'9 days' -> 9. Absent or '-' -> 0."""
    match = re.search(r"\d+", text or "")
    return int(match.group(0)) if match else 0


def parse_games_missed(text: str) -> int:
    """'2' -> 2. A dash means the injury cost no matches -> 0."""
    match = re.fullmatch(r"\d+", (text or "").strip())
    return int(match.group(0)) if match else 0


def parse_injury_rows(html: str) -> list[dict]:
    """Every injury on the page. A player with no injuries yields an empty list."""
    rows: list[dict] = []
    for row_html in _ROW_RE.findall(html):
        cells = [_cell_text(c) for c in _CELL_RE.findall(row_html)]
        if len(cells) < 6:
            continue
        season, injury, date_from, date_until, days, games = cells[:6]
        if not _SEASON_RE.match(season):
            continue
        rows.append({
            "season_label": season,
            "injury_type_raw": injury,
            "date_from": parse_tm_date(date_from),
            "date_until": parse_tm_date(date_until),
            "days_out": parse_days(days),
            "games_missed": parse_games_missed(games),
        })
    return rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec app python -m pytest tests/test_transfermarkt_injuries.py -v`
Expected: PASS — 7 tests

- [ ] **Step 5: Commit (print the command)**

```bash
git add src/lofc/ingest/transfermarkt_injuries.py tests/test_transfermarkt_injuries.py
git commit -m "feat: parse Transfermarkt injury history pages"
```

---

### Task 3: Injury categorisation

Maps Transfermarkt's free-text injury names onto the categories the club names in its medical requirements.

**Files:**
- Modify: `src/lofc/ingest/transfermarkt_injuries.py` (append)
- Test: `tests/test_transfermarkt_injuries.py` (append)

**Interfaces:**
- Consumes: nothing
- Produces: `categorise_injury(raw: str) -> str` returning one of `hamstring`, `calf`, `groin`, `ankle`, `hip`, `knee_ligament`, `muscular`, `other`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_transfermarkt_injuries.py`:

```python
from lofc.ingest.transfermarkt_injuries import categorise_injury


def test_categorise_the_club_named_injuries():
    assert categorise_injury("Hamstring injury") == "hamstring"
    assert categorise_injury("Calf strain") == "calf"
    assert categorise_injury("Adductor pain") == "groin"
    assert categorise_injury("Cruciate ligament rupture") == "knee_ligament"
    assert categorise_injury("muscular problems") == "muscular"


def test_specific_joint_beats_the_generic_ligament_rule():
    # "Ankle ligament tear" must be ankle, not knee_ligament -- order matters.
    assert categorise_injury("Ankle ligament tear") == "ankle"


def test_unknown_phrasing_falls_back_to_other():
    assert categorise_injury("Rest") == "other"
    assert categorise_injury("Unknown injury") == "other"
    assert categorise_injury("") == "other"


def test_categorisation_is_case_insensitive():
    assert categorise_injury("HAMSTRING INJURY") == "hamstring"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec app python -m pytest tests/test_transfermarkt_injuries.py -k categorise -v`
Expected: FAIL — `ImportError: cannot import name 'categorise_injury'`

- [ ] **Step 3: Write the implementation**

Append to `src/lofc/ingest/transfermarkt_injuries.py`:

```python
# The categories the club names in its Medical & Durability requirements. Order matters:
# a specific joint is checked before the generic ligament/muscle rules, so that
# "ankle ligament tear" is an ankle injury and not a knee one.
INJURY_CATEGORIES: dict[str, tuple[str, ...]] = {
    "hamstring": ("hamstring",),
    "calf": ("calf",),
    "groin": ("groin", "adductor", "pubitis"),
    "ankle": ("ankle",),
    "hip": ("hip",),
    "knee_ligament": ("cruciate", "acl", "knee", "meniscus", "ligament"),
    "muscular": ("muscular", "muscle", "thigh", "quadriceps"),
}


def categorise_injury(raw: str) -> str:
    """Normalise Transfermarkt's free text. Unmapped phrasing returns 'other'.

    Callers should log 'other' results so new phrasings surface rather than vanish.
    """
    text = (raw or "").lower()
    for category, needles in INJURY_CATEGORIES.items():
        if any(needle in text for needle in needles):
            return category
    return "other"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec app python -m pytest tests/test_transfermarkt_injuries.py -v`
Expected: PASS — 11 tests

- [ ] **Step 5: Commit (print the command)**

```bash
git add src/lofc/ingest/transfermarkt_injuries.py tests/test_transfermarkt_injuries.py
git commit -m "feat: categorise Transfermarkt injury types"
```

---

### Task 4: Resumable scraper driver

The 1.8-hour run must survive interruption. A companion progress file records completed ids, so a player with **no** injuries is not re-fetched on resume (he writes no CSV rows, so the CSV alone cannot tell you he was done).

**Files:**
- Modify: `src/lofc/ingest/transfermarkt_injuries.py` (append)
- Test: `tests/test_transfermarkt_injuries.py` (append)

**Interfaces:**
- Consumes: `fetch` from Task 1, `parse_injury_rows` and `categorise_injury` from Tasks 2–3
- Produces: `injury_url(tm_player_id: int) -> str`, `output_path() -> Path`, `partial_path() -> Path`, `progress_path() -> Path`, `load_progress() -> set[int]`, `player_ids() -> list[int]`, `scrape(ids: list[int]) -> int`, `main() -> None`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_transfermarkt_injuries.py`:

```python
import csv

from lofc.ingest import transfermarkt_injuries as tmi

ONE_INJURY_HTML = """
<table class="items">
<tr><th>Season</th><th>Injury</th><th>from</th><th>until</th><th>Days</th><th>Games missed</th></tr>
<tr><td>25/26</td><td>Hamstring injury</td><td>18/08/2025</td><td>26/08/2025</td><td>9 days</td><td>2</td></tr>
</table>
"""


def _redirect_paths(monkeypatch, tmp_path):
    """Point the module's three file paths at a temporary directory."""
    monkeypatch.setattr(tmi, "output_path", lambda: tmp_path / "injuries.csv")
    monkeypatch.setattr(tmi, "partial_path", lambda: tmp_path / "injuries.csv.partial")
    monkeypatch.setattr(tmi, "progress_path", lambda: tmp_path / "injuries.progress")


def test_injury_url_uses_the_id_not_the_slug():
    # Transfermarkt resolves the player from the id and ignores the name slug.
    assert tmi.injury_url(88755).endswith("/verletzungen/spieler/88755")


def test_scrape_writes_rows_with_id_and_category(monkeypatch, tmp_path):
    _redirect_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(tmi, "fetch", lambda url: ONE_INJURY_HTML)

    assert tmi.scrape([111]) == 1

    rows = list(csv.DictReader(open(tmp_path / "injuries.csv")))
    assert len(rows) == 1
    assert rows[0]["tm_player_id"] == "111"
    assert rows[0]["injury_category"] == "hamstring"
    assert rows[0]["games_missed"] == "2"


def test_player_with_no_injuries_is_recorded_as_done(monkeypatch, tmp_path):
    _redirect_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(tmi, "fetch", lambda url: "<table class='items'></table>")

    tmi.scrape([222])

    # No CSV rows, but the id must still be marked complete or a resume refetches him.
    assert 222 in tmi.load_progress()


def test_failed_player_is_skipped_and_not_marked_done(monkeypatch, tmp_path):
    _redirect_paths(monkeypatch, tmp_path)

    def flaky(url):
        if "999" in url:
            raise OSError("page failed")
        return ONE_INJURY_HTML

    monkeypatch.setattr(tmi, "fetch", flaky)

    tmi.scrape([111, 999])

    progress = tmi.load_progress()
    assert 111 in progress
    assert 999 not in progress   # so a resume retries him


def test_resume_skips_completed_ids_and_writes_one_header(monkeypatch, tmp_path):
    _redirect_paths(monkeypatch, tmp_path)

    calls = []

    def counting_fetch(url):
        calls.append(url)
        return ONE_INJURY_HTML

    monkeypatch.setattr(tmi, "fetch", counting_fetch)

    tmi.scrape([111])          # first run
    tmi.scrape([111, 222])     # resume: 111 already done

    assert len(calls) == 2     # 111 once, 222 once -- not three fetches

    text = (tmp_path / "injuries.csv").read_text()
    assert text.count("tm_player_id") == 1   # header written exactly once
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec app python -m pytest tests/test_transfermarkt_injuries.py -k "scrape or resume or url or done" -v`
Expected: FAIL — `AttributeError: module 'lofc.ingest.transfermarkt_injuries' has no attribute 'injury_url'`

- [ ] **Step 3: Write the implementation**

Append to `src/lofc/ingest/transfermarkt_injuries.py`:

```python
import argparse
import csv
from pathlib import Path

from lofc.config import settings
from lofc.ingest.transfermarkt_common import fetch

BASE_URL = "https://www.transfermarkt.co.uk"
FIELDNAMES = ["tm_player_id", "season_label", "injury_type_raw", "injury_category",
              "date_from", "date_until", "days_out", "games_missed"]


def injury_url(tm_player_id: int) -> str:
    """The slug is cosmetic -- Transfermarkt resolves the player from the id alone."""
    return f"{BASE_URL}/player/verletzungen/spieler/{tm_player_id}"


def _tm_dir() -> Path:
    return Path(settings.reference_data_dir) / "transfermarkt"


def output_path() -> Path:
    return _tm_dir() / "injuries.csv"


def partial_path() -> Path:
    return _tm_dir() / "injuries.csv.partial"


def progress_path() -> Path:
    """Ids already fetched. Needed because a player with no injuries writes no rows."""
    return _tm_dir() / "injuries.progress"


def load_progress() -> set[int]:
    path = progress_path()
    if not path.exists():
        return set()
    return {int(line) for line in path.read_text().split() if line.strip()}


def player_ids() -> list[int]:
    """Distinct Transfermarkt ids from the EFL market-value scrape."""
    path = _tm_dir() / "efl_values.csv"
    with open(path) as handle:
        ids = {int(row["tm_player_id"]) for row in csv.DictReader(handle)
               if row.get("tm_player_id")}
    return sorted(ids)


def scrape(ids: list[int]) -> int:
    """Fetch each player's injury page, appending as we go. Returns rows written.

    Resumable: ids already in the progress file are skipped, and a player whose page
    fails is logged but NOT marked done, so a later run retries him.
    """
    partial, progress, out = partial_path(), progress_path(), output_path()
    partial.parent.mkdir(parents=True, exist_ok=True)
    done = load_progress()
    written = 0

    with open(partial, "a", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        if handle.tell() == 0:
            writer.writeheader()
        for index, tm_id in enumerate(ids, start=1):
            if tm_id in done:
                continue
            try:
                html = fetch(injury_url(tm_id))
            except Exception as exc:               # one bad page must not end the run
                print(f"  [skip] {tm_id}: {exc}", flush=True)
                continue
            for row in parse_injury_rows(html):
                row["tm_player_id"] = tm_id
                row["injury_category"] = categorise_injury(row["injury_type_raw"])
                if row["injury_category"] == "other":
                    print(f"  [uncategorised] {row['injury_type_raw']!r}", flush=True)
                writer.writerow(row)
                written += 1
            handle.flush()
            with open(progress, "a") as marker:    # only after the page succeeded
                marker.write(f"{tm_id}\n")
            if index % 50 == 0:
                print(f"  {index}/{len(ids)} players", flush=True)

    # Atomic publish: an interrupted run never leaves a half-written injuries.csv.
    partial.replace(out)
    progress.unlink(missing_ok=True)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pull Transfermarkt injury histories for EFL players")
    parser.add_argument("--force", action="store_true",
                        help="re-pull even if injuries.csv already exists")
    parser.add_argument("--limit", type=int, default=None,
                        help="only the first N players (for a smoke test)")
    args = parser.parse_args()

    out = output_path()
    if out.exists() and not args.force and not progress_path().exists():
        print(f"{out} already present, skipping (use --force to re-pull)")
        return

    ids = player_ids()
    if args.limit:
        ids = ids[:args.limit]
    print(f"{len(ids)} players to fetch (~{len(ids) * 2.5 / 3600:.1f} hours)")
    written = scrape(ids)
    print(f"\nWrote {written} injury rows to {out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec app python -m pytest tests/test_transfermarkt_injuries.py -v`
Expected: PASS — 16 tests

- [ ] **Step 5: Smoke-test against the real site**

Run: `docker compose exec app python -m lofc.ingest.transfermarkt_injuries --limit 5 --force`
Expected: five players fetched in ~15 seconds, `injuries.csv` written. Inspect it:
`docker compose exec app head -5 /app/data/reference/transfermarkt/injuries.csv`

If any injury prints `[uncategorised]`, add the phrasing to `INJURY_CATEGORIES` in Task 3 and re-run.

- [ ] **Step 6: Commit (print the command)**

```bash
git add src/lofc/ingest/transfermarkt_injuries.py tests/test_transfermarkt_injuries.py
git commit -m "feat: resumable Transfermarkt injury scraper"
```

---

### Task 5: Database table and migration

**Files:**
- Modify: `src/lofc/store/models.py` (append a model near `WatchlistEntry`)
- Create: `alembic/versions/<generated>_player_injuries.py`
- Test: `tests/test_store.py` (append)

**Interfaces:**
- Consumes: nothing
- Produces: table `player_injuries` and the `PlayerInjury` model. Columns: `id, player_id, tm_player_id, season_label, injury_type_raw, injury_category, date_from, date_until, days_out, games_missed, source, created_at`

**Note for plan 2:** `entered_by` is deliberately **not** added here. It is a foreign key to `users`, which does not exist until the scout assessment plan creates it. That plan adds the column and its constraint.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_store.py`:

```python
def test_player_injuries_table_shape():
    from lofc.store.models import PlayerInjury

    columns = {c.name for c in PlayerInjury.__table__.columns}
    assert {"player_id", "tm_player_id", "season_label", "injury_category",
            "days_out", "games_missed", "source"} <= columns
    # Provenance defaults to the scraper; manual rows override it (plan 2).
    assert PlayerInjury.__table__.c.source.server_default.arg == "transfermarkt"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec app python -m pytest tests/test_store.py -k injuries -v`
Expected: FAIL — `ImportError: cannot import name 'PlayerInjury'`

- [ ] **Step 3: Add the model**

Append to `src/lofc/store/models.py` (make sure `Date` is in the SQLAlchemy import list at the top of the file):

```python
class PlayerInjury(Base):
    """One injury spell. Scraped from Transfermarkt, or entered by hand where
    Transfermarkt has no coverage (Scottish/PL2).

    ONE SCHEMA, TWO PROVENANCES: `source` records where the row came from, and the
    availability rule deliberately never inspects it -- a hand-entered Scottish
    player and a scraped League One player are computed identically and are directly
    comparable. Only the display differs.
    """

    __tablename__ = "player_injuries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("players.player_id"),
                                           index=True)
    tm_player_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    season_label: Mapped[str] = mapped_column(String)          # "25/26"
    injury_type_raw: Mapped[str] = mapped_column(String)       # Transfermarkt's own wording
    injury_category: Mapped[str] = mapped_column(String, index=True)
    date_from: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    date_until: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    days_out: Mapped[int] = mapped_column(Integer, server_default="0")
    games_missed: Mapped[int] = mapped_column(Integer, server_default="0")
    source: Mapped[str] = mapped_column(String, server_default="transfermarkt")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
```

- [ ] **Step 4: Generate and review the migration**

Run: `docker compose exec app alembic revision --autogenerate -m "player injuries"`

Open the generated file in `alembic/versions/`. Confirm `down_revision = "e2f7b91c6a55"` and that it creates **only** `player_injuries` — autogenerate sometimes picks up unrelated drift. Delete any operation that is not about this table.

- [ ] **Step 5: Apply and verify**

Run: `docker compose exec app alembic upgrade head`
Then: `docker compose exec db psql -U lofc -d lofc -c "\d player_injuries"`
Expected: the table exists with the columns above.

- [ ] **Step 6: Run the full suite**

Run: `docker compose exec app python -m pytest -q`
Expected: PASS — 218 tests

- [ ] **Step 7: Commit (print the command)**

```bash
git add src/lofc/store/models.py alembic/versions/ tests/test_store.py
git commit -m "feat: player_injuries table"
```

---

### Task 6: Load the CSV into Postgres

Joins on `players.tm_player_id`, which the valuation stage already populates (1,619 of 5,626 players today).

**Files:**
- Create: `src/lofc/store/injuries.py`
- Test: `tests/test_injury_load.py`

**Interfaces:**
- Consumes: `player_injuries` table from Task 5
- Produces: `injury_frame(csv_path: Path, players: pd.DataFrame) -> pd.DataFrame` (pure, testable without a database) and `main() -> None`

- [ ] **Step 1: Write the failing test**

```python
"""The injury CSV -> DB join. The frame builder is pure; no database needed."""

import pandas as pd

from lofc.store.injuries import injury_frame


def _write_csv(tmp_path, rows):
    path = tmp_path / "injuries.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


PLAYERS = pd.DataFrame({"player_id": [900, 901], "tm_player_id": [111, 222]})


def test_join_maps_tm_id_to_our_player_id(tmp_path):
    path = _write_csv(tmp_path, [{
        "tm_player_id": 111, "season_label": "25/26", "injury_type_raw": "Hamstring injury",
        "injury_category": "hamstring", "date_from": "2025-08-18", "date_until": "2025-08-26",
        "days_out": 9, "games_missed": 2,
    }])
    frame = injury_frame(path, PLAYERS)
    assert list(frame["player_id"]) == [900]
    assert frame.loc[0, "source"] == "transfermarkt"


def test_unmatched_tm_ids_are_dropped_not_guessed(tmp_path):
    # A Transfermarkt player we hold no metrics for must not invent a player_id.
    path = _write_csv(tmp_path, [{
        "tm_player_id": 555, "season_label": "25/26", "injury_type_raw": "Calf strain",
        "injury_category": "calf", "date_from": "2025-09-01", "date_until": "2025-09-10",
        "days_out": 9, "games_missed": 2,
    }])
    assert injury_frame(path, PLAYERS).empty


def test_frame_columns_match_the_table(tmp_path):
    path = _write_csv(tmp_path, [{
        "tm_player_id": 222, "season_label": "24/25", "injury_type_raw": "Ankle sprain",
        "injury_category": "ankle", "date_from": "2024-11-02", "date_until": "2024-11-20",
        "days_out": 18, "games_missed": 4,
    }])
    frame = injury_frame(path, PLAYERS)
    assert set(frame.columns) == {
        "player_id", "tm_player_id", "season_label", "injury_type_raw", "injury_category",
        "date_from", "date_until", "days_out", "games_missed", "source"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec app python -m pytest tests/test_injury_load.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lofc.store.injuries'`

- [ ] **Step 3: Write the implementation**

Create `src/lofc/store/injuries.py`:

```python
"""Load the scraped injury CSV into Postgres.

Joins on players.tm_player_id, which the valuation stage populates. A Transfermarkt
player we hold no metrics for is dropped rather than guessed at.

Run:  python -m lofc.store.injuries
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

from lofc.config import settings
from lofc.ingest.transfermarkt_injuries import output_path

COLUMNS = ["player_id", "tm_player_id", "season_label", "injury_type_raw",
           "injury_category", "date_from", "date_until", "days_out", "games_missed",
           "source"]


def injury_frame(csv_path: Path, players: pd.DataFrame) -> pd.DataFrame:
    """Scraped rows joined to our player ids, shaped exactly like the table."""
    frame = pd.read_csv(csv_path)
    if frame.empty:
        return pd.DataFrame(columns=COLUMNS)
    merged = frame.merge(players[["player_id", "tm_player_id"]],
                         on="tm_player_id", how="inner")
    merged["source"] = "transfermarkt"
    return merged.reindex(columns=COLUMNS)


def main() -> None:
    path = output_path()
    if not path.exists():
        print(f"{path} not found -- run lofc.ingest.transfermarkt_injuries first")
        return

    engine = create_engine(settings.database_url)
    players = pd.read_sql(
        "SELECT player_id, tm_player_id FROM players WHERE tm_player_id IS NOT NULL",
        engine)
    frame = injury_frame(path, players)

    with engine.begin() as conn:
        # Replace only what we scraped. Manually entered rows are never touched.
        conn.execute(text("DELETE FROM player_injuries WHERE source = 'transfermarkt'"))
        if not frame.empty:
            frame.to_sql("player_injuries", conn, if_exists="append", index=False)
    print(f"Loaded {len(frame)} injury rows for "
          f"{frame['player_id'].nunique() if not frame.empty else 0} players")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec app python -m pytest tests/test_injury_load.py -v`
Expected: PASS — 3 tests

- [ ] **Step 5: Commit (print the command)**

```bash
git add src/lofc/store/injuries.py tests/test_injury_load.py
git commit -m "feat: load Transfermarkt injuries into Postgres"
```

---

### Task 7: Availability calculation

The pure function the Medical band will be built on in plan 2.

**Files:**
- Create: `src/lofc/model/medical.py`
- Test: `tests/test_medical.py`

**Interfaces:**
- Consumes: nothing (pure)
- Produces: `SCHEDULED_GAMES: dict[int, int]`, `window_labels(season_id: int) -> tuple[str, ...]`, `games_missed_in_window(injuries: pd.DataFrame, season_id: int) -> int`, `availability(games_missed: int, competition_id: int, seasons: int = 2) -> float | None`

- [ ] **Step 1: Write the failing test**

```python
"""The availability rule -- the objective input to the club's Medical dimension."""

import pandas as pd
import pytest

from lofc.model.medical import (
    availability,
    games_missed_in_window,
    window_labels,
)

CHAMPIONSHIP = 3
SCOTTISH_PREM = 901


def test_a_player_who_missed_nothing_is_fully_available():
    assert availability(0, CHAMPIONSHIP) == 1.0


def test_the_club_minimum_bar():
    # 60% availability is the club's stated minimum: 40% of 92 games = 36.8 missed.
    assert availability(37, CHAMPIONSHIP) == pytest.approx(0.5978, abs=0.001)


def test_availability_is_clamped_at_zero():
    # More games missed than the window holds (long-term injury spanning seasons).
    assert availability(200, CHAMPIONSHIP) == 0.0


def test_half_the_window_missed():
    assert availability(46, CHAMPIONSHIP) == 0.5


def test_league_without_a_scheduled_games_constant_returns_none():
    # Scottish/PL2 have no Transfermarkt coverage; the criterion is unscored, not
    # defaulted -- a guessed availability would be worse than an honest gap.
    assert availability(5, SCOTTISH_PREM) is None


def test_window_labels_covers_the_season_and_the_one_before():
    assert window_labels(318) == ("24/25", "25/26")
    assert window_labels(319) == ("25/26", "26/27")


def test_games_missed_only_counts_the_window():
    injuries = pd.DataFrame({
        "season_label": ["23/24", "24/25", "25/26"],
        "games_missed": [99, 4, 6],
    })
    # 23/24 is outside a two-season window ending at 2025/26, so its 99 is ignored.
    assert games_missed_in_window(injuries, 318) == 10


def test_games_missed_with_no_injuries():
    empty = pd.DataFrame(columns=["season_label", "games_missed"])
    assert games_missed_in_window(empty, 318) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec app python -m pytest tests/test_medical.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lofc.model.medical'`

- [ ] **Step 3: Write the implementation**

Create `src/lofc/model/medical.py`:

```python
"""The Medical dimension's objective input: availability from injury history.

    availability = 1 - (games missed through injury / scheduled games)

Only games missed THROUGH INJURY enter the numerator, so a player who was fit but
simply not selected is not penalised. Deriving availability from minutes played was
tested and rejected: 73% of rankable 2025/26 players fall below a 60% bar on
minutes / (46 * 90), which measures rotation, not fitness.

The club states 60% availability over the prior two seasons as the minimum standard.
The band formula that consumes this lives alongside it (added in the scout
assessment plan).
"""

from __future__ import annotations

import pandas as pd

# League games per season. All four EFL leagues play 46. Held per competition rather
# than hard-coded so other leagues can be added when coverage allows.
SCHEDULED_GAMES: dict[int, int] = {
    3: 46,    # Championship
    4: 46,    # League One
    5: 46,    # League Two
    65: 46,   # National League
}

AVAILABILITY_SEASONS = 2

# Transfermarkt labels seasons "25/26"; our season_ids are 317 = 2024/25 upward.
_SEASON_LABELS: dict[int, str] = {317: "24/25", 318: "25/26", 319: "26/27"}


def window_labels(season_id: int, seasons: int = AVAILABILITY_SEASONS) -> tuple[str, ...]:
    """The Transfermarkt season labels in the availability window, oldest first."""
    ids = range(season_id - seasons + 1, season_id + 1)
    return tuple(_SEASON_LABELS[i] for i in ids if i in _SEASON_LABELS)


def games_missed_in_window(injuries: pd.DataFrame, season_id: int,
                           seasons: int = AVAILABILITY_SEASONS) -> int:
    """Total games missed through injury inside the window. No injuries -> 0."""
    if injuries.empty:
        return 0
    labels = window_labels(season_id, seasons)
    inside = injuries[injuries["season_label"].isin(labels)]
    return int(inside["games_missed"].fillna(0).sum())


def availability(games_missed: int, competition_id: int,
                 seasons: int = AVAILABILITY_SEASONS) -> float | None:
    """Fraction of scheduled games the player was fit for, clamped to [0, 1].

    Returns None for a competition with no scheduled-games constant -- the criterion
    is then unscored rather than defaulted, because a guessed availability feeding a
    medical score is worse than an honest gap.
    """
    scheduled = SCHEDULED_GAMES.get(competition_id)
    if not scheduled:
        return None
    total = scheduled * seasons
    return max(0.0, min(1.0, 1.0 - games_missed / total))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec app python -m pytest tests/test_medical.py -v`
Expected: PASS — 8 tests

- [ ] **Step 5: Commit (print the command)**

```bash
git add src/lofc/model/medical.py tests/test_medical.py
git commit -m "feat: availability calculation for the Medical dimension"
```

---

### Task 8: Pipeline wiring, full run, and documentation

**Files:**
- Modify: `src/lofc/pipeline.py:79` (insert a step after Valuation)
- Modify: `cli_commands.txt`
- Modify: `plan/BUILD_PLAN.md` (Pending work register)
- Modify: `docs/DATA_ARCHITECTURE.md`

**Interfaces:**
- Consumes: `lofc.store.injuries` from Task 6
- Produces: nothing new

- [ ] **Step 1: Add the pipeline step**

In `src/lofc/pipeline.py`, immediately after the **Identity** entry added in Task 0, insert:

```python
        ("Injuries: load the Transfermarkt injury history (skipped if not scraped)",
         [sys.executable, "-m", "lofc.store.injuries"]),
```

Order matters: Identity must run first, because the loader joins on `players.tm_player_id`.

The loader prints and returns cleanly when `injuries.csv` is absent, so the pipeline stays runnable on a machine that has never scraped.

- [ ] **Step 2: Verify the pipeline still runs end to end**

Run: `docker compose exec app python -m lofc.pipeline`
Expected: every step completes; the new Injuries step either loads rows or prints "not found -- run lofc.ingest.transfermarkt_injuries first".

- [ ] **Step 3: Run the real scrape**

This is the ~1.8 hour overnight job. **Run it together with the overdue B1 contract refresh**, since both hit Transfermarkt:

```bash
docker compose exec app python -m lofc.ingest.transfermarkt_efl --force
docker compose exec app python -m lofc.model.valuation
docker compose exec app python -m lofc.ingest.transfermarkt_injuries --force
docker compose exec app python -m lofc.store.injuries
```

If it is interrupted, re-run the third command — it resumes from the progress file.

- [ ] **Step 4: Sanity-check the loaded data**

```bash
docker compose exec db psql -U lofc -d lofc -c "
SELECT injury_category, COUNT(*) AS spells, ROUND(AVG(games_missed),1) AS avg_games
FROM player_injuries GROUP BY 1 ORDER BY 2 DESC;"
```

Expected: hamstring, muscular and knee_ligament dominate. If `other` is the largest category, the phrasings need adding to `INJURY_CATEGORIES` (Task 3) and the loader re-run — **no re-scrape needed**, categorisation happens at scrape time so re-run Task 4's scrape with `--force` only if you change the mapping.

- [ ] **Step 5: Append to `cli_commands.txt`**

```
# Pull Transfermarkt injury histories for EFL players (~1.8 hours, resumable).
docker compose exec app python -m lofc.ingest.transfermarkt_injuries --force
# Load the scraped injury history into Postgres (fast; also runs inside the pipeline).
docker compose exec app python -m lofc.store.injuries
```

- [ ] **Step 6: Update the documentation**

In `plan/BUILD_PLAN.md`, in the Pending work register: mark **B1 done** (with the refresh date), record that the injury scrape has landed with its coverage (the EFL only, and only players carrying a `tm_player_id`), and note the identity fix from Task 0 with the before/after National League numbers. Register "extend the squad scrape to Scottish Prem / Scottish Champ / PL2" as a new open item.

In `docs/DATA_ARCHITECTURE.md`, add a short section: the injury source, the one-page decision, the availability formula, and the coverage limit.

Update the test count wherever it says 191.

- [ ] **Step 7: Run the full suite**

Run: `docker compose exec app python -m pytest -q`
Expected: PASS — **229 tests** (191 existing + 38 new: 6 + 4 + 7 + 4 + 5 + 1 + 3 + 8)

- [ ] **Step 8: Commit (print the command)**

```bash
git add src/lofc/pipeline.py cli_commands.txt plan/BUILD_PLAN.md docs/DATA_ARCHITECTURE.md
git commit -m "feat: wire injury load into the pipeline, refresh docs"
```

---

## Definition of done

- `injuries.csv` exists and `player_injuries` is populated for the EFL.
- B1 is closed — contract data is no longer the 10 Jun 2026 snapshot.
- `availability()` is tested and ready for the scout assessment plan to consume.
- The pipeline runs end to end on a machine that has never scraped.
- 229 tests pass; no existing behaviour changed.
- National League `tm_player_id` coverage is up from 8% to ~70%+, and the three EFL
  divisions above it have not fallen.

## Deliberately deferred to plan 2

The spec's **`player_season_availability`** table is not created here. Availability is a pure
function of `player_injuries` plus a per-league constant, so storing it would be redundant
denormalisation — *until* manual entry exists, where a scout types an availability figure with
no injury log behind it. The table therefore arrives with manual entry, in plan 2.

## Known limitations (carried into plan 2)

- **Coverage:** only players with a `tm_player_id` — roughly **2,150** after Task 0 (up from 1,619). Scottish Premiership, Scottish Championship and PL2 are **not scraped at all** and depend entirely on manual entry; extending the squad scrape to those three leagues is a separate piece of work.
- **Mid-season transfers** are measured against the full 92-game window, slightly understating availability. Only affects a player who was also injured; the manual override covers it.
- `entered_by` is not on `player_injuries` yet — it arrives with the `users` table in plan 2.
