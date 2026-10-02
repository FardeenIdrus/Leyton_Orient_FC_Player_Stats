# STATE — 30 September 2026

> Written so a new session can pick up with the same context. Read `CLAUDE.md` and
> `plan/BUILD_PLAN.md` first; this file is where two live threads actually stand.
>
> **Two threads are open at once.** They are independent and should not be interleaved:
> **(A) the scout-reports integration** and **(B) the scoring formula review**.

---

## 0. Deployment gap — what the server does NOT have

| | |
|---|---|
| Server (`/opt/lofc`, `main`) | `5a8ac0b` — *P17/P17b: recover 106 hidden loans…* |
| Local `HEAD` | `ee7e9f9` — *scout reports: read the club's scouting sheet…* |
| **Gap** | **1 commit, 30 files, ~3,100 lines** — the entire scout-reports feature |

Plus **uncommitted local work**: the percentile fix (`model/scorecard.py`), the scout-report
card UI, the Players-page Scouts column, and three new test files.

**Nothing of the scout-reports feature is live.** The recruitment team cannot see any of it.

### Before any deploy of the scout feature, the server also needs

1. `secrets/google-sheets.json` copied to `/opt/lofc/secrets/` — it is gitignored and does
   NOT travel with a deploy. Without it the sync stage exits with a clear message.
2. `SCOUT_SHEET_ID=1FYgoewo9rsXkURiZGhU5YHxtP9h786aEBv6VlFhla9M` in the server `.env`
   (this is the LIVE sheet — the local `.env` already points at it).
3. `alembic upgrade head` — migration `7fce0dc9323f` adds `scout_reports`,
   `scout_player_lookup`, `scout_sync`. `deploy.sh` runs migrations.
4. The cron entry — `scripts/scout_sync.sh` exists and is flock-guarded but is NOT installed:
   `* * * * * /opt/lofc/scripts/scout_sync.sh >> /opt/lofc/data/ops/scout_sync.log 2>&1`

**⚠️ The percentile fix (thread B) changes every rating.** Deploying it re-scores the whole
platform — see §2. Decide deliberately whether it ships with the scout feature or separately.

---

## A. SCOUT REPORTS

### Built and verified working (local only)

Reads the club's **live** Google Sheet, read-only, into Postgres.

| | |
|---|---|
| Reports stored | **449** from 6 scouts (LIVE sheet) |
| Linked to a platform player | **303** (255 distinct), **0 ambiguous** — 9 of them via a name read from the report text |
| Unlinked — outside our 7 leagues | 146 |
| Name recovered from the report text | 20, marked `†`, never linked |
| Sheet | LIVE (`1FYgoewo…`), shared with the service account as Viewer |

**Read-only is enforced twice and neither layer depends on our code:** the token carries
only `spreadsheets.readonly` (a write attempt returned **HTTP 403**, verified), and the
account is a **Viewer** on the file.

Modules: `ingest/scout_sheets.py` · `ingest/scout_reports.py` · `ingest/scout_lookup.py` ·
`store/scout_reports.py` · `model/scout_report_link.py` · `dashboard/tabs/scout_reports.py`.
One command runs the lot: `python -m lofc.store.scout_reports` (syncs, then links).

### ⚠️ THE `.env` TRAP — cost a full round of wrong conclusions, do not repeat

`docker compose` injects `env_file:` values at CONTAINER CREATION. Editing `.env` and then
`docker compose restart` does **NOT** update them — the old value survives as an environment
variable, and pydantic-settings gives environment variables precedence over the `.env` file.

The platform ran against the COPY of the sheet for two days while `.env` said otherwise, and
because the copy was only 12 reports behind, the matching counts read as confirmation.

**Use `docker compose up -d --force-recreate app`, then verify:**
`docker compose exec -T app printenv SCOUT_SHEET_ID`

The same applies on the server.

### RESOLVED — "A New Player" name recovery (2026-09-30)

**20 of 449 live reports** carried the dropdown's escape-hatch value. The scout writes the
real name into the Report Comments; the Head of Recruitment later adds the player to the
dropdown by hand, but the filed report keeps saying "A New Player". Confirmed current, not
historical — the 20 span 18 Aug to 26 Sep, and the sheet's `Database` tab is byte-identical
to `Form responses` and corrects none of them.

`name_from_comment()` reads the name from the first line, handling the four observed shapes
(name + full stop; name + verb; name + shirt number in brackets; leading shirt number +
name + dash). **20 of 20 recovered, 0 left as placeholder, 0 wrongly made linkable.**

**A recovered name IS matched to our players, on a second tier.** The form's dropdown and
our `players` table are different lists: 9 of the 20 are players we hold full data on,
mostly Premier League 2, whose reports previously opened nothing. They cannot use the strict
name + date-of-birth rule — there is no date, which is why they were missing from the
dropdown — so they match on NAME ALONE, with safety coming from refusing ambiguity: a name
held by two of our players links to neither. Live result: **9 matched, 0 ambiguous.** This
tier is reached ONLY by a recovered name; a dropdown-named player has a date available and
is never downgraded to name-only matching.

Rules pinned by tests (`tests/test_scout_new_player_name.py` 27, `test_scout_report_link.py` 21):
- A comment that does not open with something name-shaped keeps the placeholder.
- A candidate equal to the club name is refused (reports often open by setting the scene).

**Self-healing and automatic.** Extraction is a step inside the ordinary 60-second sync, not
a separate script. It fires only while the Player field still reads "A New Player", so a
corrected row in the sheet takes over on the next sync with no migration or cleanup.

Marked on screen with `†` and a column tooltip. Column `scout_reports.name_from_report`,
migration `26e5e1b5fff3`.

### OPEN ISSUE 2 — the real sheet has never been through a full cron cycle

The sync has only ever been run by hand. The 60-second cron is written but not installed,
so `missing_since` stamping and the unchanged-digest path have not been exercised against a
sheet that is actually being edited by six people.

### OPEN ISSUE 3 — four tabs are read but not stored

`Team Names` (903), `Fixtures Schedule` (151), `Players of Interest` (223),
`PlayersToFollowUpOn` (22) are fetched by `scout_sheets.fetch` and discarded. Only
`Form responses` and `Player Names` reach Postgres. The Coverage tab described in the plan
(computed from `Fixtures Schedule`, NOT imported — its stored version is already stale for
21 of 156 clubs) is therefore not built.

### Decisions open — SCOUT REPORTS

| | Decision | Notes |
|---|---|---|
| **A2** | Does the platform's **watchlist** (5 rows) survive alongside the sheet's **Players of Interest** (223)? | Register **P21**. Same question, two lists; the spreadsheet's is 45× larger and actually maintained. |
| **A3** | When a signed-off **assessment** and a **scout report** disagree, which is the club's view? | Register **P21**. They are not redundant — assessment scores Psychological + Medical and feeds `assessed_composite`; a report is a per-match verdict. |
| **A4** | Phase 2 — rebuild the JotForm form inside the platform? | The Head of Recruitment wants this "eventually". It would fix A1 permanently (a native Player field can accept an unknown player) and remove the 43% name-match failure. **Never write back to the sheet** — one writer at a time. |

---

## B. SCORING FORMULA REVIEW

### DONE 2026-09-30 — percentile scale centred (a real defect, now fixed)

`metric_percentiles` used `rank(pct=True)` = **rank ÷ n**, so percentiles ran `100/n .. 100`
and averaged **50 + 50/n**, never 50. Small pools were inflated most: pools under 30 players
averaged **3.14** against **3.01** for pools of 100+, correlation **−0.725** with pool size.

Fixed to `(rank − 0.5) ÷ n`. **A second defect was introduced and caught during the fix** —
the first attempt divided by pool size instead of the count of players holding the metric,
which would have deflated every metric with missing values to a band of 1.0.

**Verified after re-running `scorecard_run`:**

| | |
|---|---|
| Pools where all players have both dimensions | **14 of 14 average exactly 3.00** |
| Pools where no player has physical | **14 of 14 average exactly 3.00** |
| Mixed pools | 17 of 28 — residual is the 57/43-vs-100/0 weighting, a club decision |
| 25/26 mean | 3.0294 → **2.9972** |
| **Rank changes within pool** | **660 of 3,345 (20%), max 4 places** |

Tests 1,226 → **1,248**. **Not deployed.**

### Report status

`How Players Are Scored — Leyton Orient FC.pdf` exists at repo root — **16 pages, but built
on PRE-FIX numbers and therefore stale.** Must be regenerated.

Agreed changes for the rebuild:
1. Show the band formula's derivation — the club's two anchors (median → 3.0, 70th → 4.0)
   and the one line of arithmetic, so it does not read as arbitrary
2. Rewrite the missing-physical finding on the verified evidence below
3. Relabel "Metrics averaged (Centre Back)"
4. Method note — what "spread" and "how closely two things move together" mean
5. Rating distribution chart
6. Top-100 vs bottom-100 table
7. **Remove** the pool-size finding — that was this bug, now fixed

Build scripts: `/tmp/build_report_a.py` reads `/tmp/report_a.json` + `/tmp/matrix.json`
(regenerate both from the database), renders HTML, then Playwright → PDF on the HOST.

### Decisions open — SCORING (all for the Head of Recruitment)

| | Decision | Evidence |
|---|---|---|
| **B1** | Is **57% Performance / 43% Physical** the intended split? | Framework says 40/30; the ranking drops the two scout dimensions and rescales |
| **B2** | Should **Physical decide 69%** of the ranking? | Weight 43%, influence **69%**. Cause: its 8 metrics are 4 concepts measured twice (HSR count/distance r=0.96, sprint count/distance 0.94). Removing the duplicates addresses the cause; lowering the weight only reaches ~55% |
| **B3** | Should a rating covering **36%** of the framework rank beside one covering **64%**? | Same mean Performance (3.012 vs 3.028) but **19× the rate of reaching 4.4+**, and **20 of the top 33 players**. Already disclosed on screen via the existing **"Measured"** column |
| **B4** | Are the **five merged metric pairs** acceptable as single measurements? | 12 entries collapse onto a metric already counted, so the concept carries half the intended weight |
| **B5** | Should **goalkeepers** be rated on 6 metrics with no physical component? | `long_ball_pct` unavailable; GK Performance spread 0.83, the widest of any position |

---

## What I would push first, and why

**The scout-reports feature alone.** It is complete, verified against the live sheet, and
delivers something the recruitment team can use today. It touches **no score**.

The percentile fix changes 660 players' ranks and should ship as its own deploy, after the
Head of Recruitment has seen the report explaining it — not bundled into a feature release.

**Blocking the scout deploy: nothing.** A1 is resolved, the feature is complete and verified
against the live sheet. What remains is deployment mechanics:

1. `git push`, then `/opt/lofc/scripts/deploy.sh`
2. `scp secrets/google-sheets.json root@SERVER:/opt/lofc/secrets/` — gitignored, does not
   travel with a deploy
3. `SCOUT_SHEET_ID` in the server `.env`, then **`--force-recreate`**, not restart
4. Install the cron: `* * * * * /opt/lofc/scripts/scout_sync.sh >> /opt/lofc/data/ops/scout_sync.log 2>&1`

A2–A4 and the four unstored tabs can follow later.
