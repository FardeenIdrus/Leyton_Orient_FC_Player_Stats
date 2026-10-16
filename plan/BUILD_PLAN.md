# BUILD PLAN — master plan & documentation hub

> **Read this first.** This file is the single, always-current map of the platform: what it
> is, where every other document lives, the state today, and what's next. It is kept small
> and up to date. It is the file to read on a fresh session or when onboarding.
>
> - **The current state and roadmap** are in this file (below).
> - **The rationale/history** of every past decision is in `plan/HISTORY.md` (frozen log —
>   read only when you need the *why* behind something).
> - **Technical deep-dives** are in `docs/` (see the Documentation map below).
>
> _Last updated: 2026-10-09._

---

## What this is (one paragraph)

The Leyton Orient FC **Player Recruitment Intelligence Platform** turns event and physical
data into a ranked shortlist of **affordable, undervalued** signings, scored on **the club's
own recruitment framework**. It is a *decision* platform (the IP is the scoring + ranking
model), not a reporting dashboard. It runs end to end via `docker compose up` +
`python -m lofc.pipeline`; the dashboard is at http://localhost:8501.

---

## Documentation map

| Document | What it covers | Read it when… |
|---|---|---|
| **`plan/BUILD_PLAN.md`** (this file) | Current state, doc index, roadmap, the **recurring manual tasks (M1/M2)** and the pending register | Always first — the entry point |
| **`CLAUDE.md`** — ⚠️ **OPERATING MODEL section** | Which of the TWO machines does what; the Transfermarkt/AWS-WAF block (M1); the laptop↔server drift (M2); the per-match roadmap (P11) | **Before touching data, the pipeline or deployment** |
| `plan/2026-09-28-P17-P18-squads-joins.md` | **The worked plan for P17 + P18** — verified counts, reproducible SQL, duplication checks, the mapping decisions P18 needs, and the tests to write first | **Before starting P17 or P18** |
| `plan/HISTORY.md` | Frozen append-only build log: every phase + decision + rationale | You need *why* a past decision was made |
| `plan/LOFC_Recruitment_Platform_Build_Plan.md` | The original client brief (frozen, never edited) | You want the original scope/requirements |
| `README.md` | Human front door: what it is, how to run it, repo layout | You're a new team member getting started |
| `docs/architecture.md` | System map: the pipeline stages, which file does what, data flow, dashboard tabs | You want to understand or change the code |
| `docs/DATA_ARCHITECTURE.md` | The 91-metric layer: the four data sources, per-metric provenance, the club→Impect mapping; §5 the Medical-dimension injury source and availability formula | You're working with metrics / data sources |
| `docs/methodology.md` | The scoring method: percentiles, the club 1–5 composite, the design decisions | You want to understand how players are scored |
| `docs/scaling.md` | Scaling considerations | You're planning growth / more leagues |
| `DEPLOY.md` | Deployment and operations | You're deploying or running in production |
| `data/reference/README.md` | The drop-in reference CSVs (wages, identity) | You're replacing a modelled input with real club data |
| `CLAUDE.md` | AI session pointer + working rules (local-only, not in git) | (Claude reads this automatically) |

`analysis/step*/` holds one-off working notes from the build — **historical, not living docs.**

---

## Current state (2026-08-25)

> **2026-08-25 — security-and-correctness audit, the last pass before recruitment staff get
> real access.** The platform was reachable over a public tunnel while carrying real
> vulnerabilities; this pass closed them, fixed a scoring-adjacent data bug, and cleaned up
> a round of display and identity defects found while reviewing the whole branch.
>
> **Security.** Streamlit's default (`showErrorDetails = "full"`) printed a complete Python
> traceback — file paths, SQL text, local variables — into a visitor's browser on any
> uncaught exception, including on the pre-login cookie-restore path; `.streamlit/config.toml`
> now sets `showErrorDetails = "none"` (the error is still logged server-side, only the
> browser echo is suppressed). A signed-in user's full name reached the top-right identity
> chrome and a status badge unescaped via `unsafe_allow_html=True` — an admin sets other
> users' names, and the session cookie cannot be `HttpOnly`, so a name containing `<script>`
> was a stored-XSS path to stealing another admin's session; `session.py`'s `_identity_html`
> and `badges.py`'s `_badge_html` now run every interpolated value through `html.escape()`,
> and every `unsafe_allow_html` call site in the app was swept and confirmed to be
> static/escaped content only. The dashboard's own SQLAlchemy engine
> (`dashboard/loaders.get_engine`, `admin.py`'s engine) now sets `hide_parameters=True` —
> without it, an `IntegrityError` from a racing duplicate-username INSERT would print the
> failing statement's bound parameters, including the new account's password salt and hash,
> into the error text; `store/users.create_user` also now catches that race's `IntegrityError`
> and turns it into the same plain "user already exists" `ValueError` the ordinary pre-check
> raises, rather than letting it propagate. A **behaviour-based login throttle**
> (`dashboard/login_throttle.py`) was added against password-spraying across many different
> usernames — the existing per-account lockout (5 failures) never fires against a spray,
> since no single account reaches it. **Deliberately not IP-based**: the app is reached
> through a bare `cloudflared` tunnel and a Caddy `reverse_proxy` with no forwarded-address
> normalisation, so there is no non-spoofable client address available to key a limiter on
> in either deployment; the throttle instead tracks distinct failing usernames within a
> rolling 5-minute window (8 is a genuine-office ceiling) and adds a 3-second delay to
> further failures once that signature is seen — a slowdown, never a lockout, so a real
> multi-person mistyping spree is inconvenienced, not locked out.
>
> **Percentiles were pooling two seasons.** Four functions grouped by competition and
> position but omitted season — `model/normalise.py::compute_percentiles_wide`,
> `model/score.py::compute_scores`, `model/wage_check.py::build_squad_estimates` and
> `constrain/filters.py::build_candidates` — so a 2024/25 player and a 2025/26 player in the
> same league/position were ranked against each other. All four now group by
> `competition_id, season_id, position_group`. **Verified on this database:**
> `objective_composite` — the club composite, the default ranking, computed by
> `model/scorecard.py`/`metric_percentiles`, which already grouped by season correctly — is
> **unaffected**: still 6,573 rows in the `'All Metrics'` archetype, average **3.029285**,
> identical to every earlier check. The bug lived in the *screening* layer (wage tiers,
> shortlist affordability), not the composite. `player_percentiles` holds 144,606 rows
> post-fix; the `shortlists` table now holds **909** rows (both re-verified directly against
> this database). The reported before/after deltas (734 players / 11.2% changing wage tier,
> 1,053 → 909 shortlist rows, 224 affordability flips, 141,104 of 144,606 percentile values
> changed) come from the recompute itself, which this pass did not re-run — the row counts
> above are the only figures independently re-checked here.
>
> **76 split player identities merged.** Two provider-matching paths (Impect matching and
> the Transfermarkt/valuation matcher) each minted their own internal player id on a match
> failure, so one real footballer could end up with his performance metrics under one id and
> his Transfermarkt link — and therefore contract, foot, height and injury history — under
> another. Reported as merged with no rows deleted and no orphans left; one pair (both already
> holding scored rows) was deliberately left unmerged for a human decision. **Verified
> directly against this database:** contract dates **1,412** (was 1,400), foot **1,660** (was
> 1,651), height **1,689** (was 1,679) — all three exactly match the reported after-figures.
> **No script or migration implements this merge** — unlike every other fix in this entry, it
> has no corresponding code in the diff, so treat it as a one-off manual database repair (the
> same pattern as R7's four-duplicate-id fix below) rather than a repeatable, reviewable
> process. **The root cause — the two matchers minting independent ids on failure — is
> unfixed**, so the split can recur on the next identity refresh.
>
> Separately, **three players had shared Transfermarkt ids** (twins and same-day namesakes),
> so one carried another's contract date; reported as cleared. **Not fully reconciled here:**
> this database currently holds **15** `tm_player_id` values each claimed by two different
> `players` rows, not zero. Some or all of these are plausibly the *expected* result of the
> 76-identity merge above (which explicitly does not delete either row, so a merged pair can
> legitimately share one Transfermarkt id going forward) rather than genuine unresolved
> duplicates — but there is no merge log or "canonical id" column to tell the two apart, so
> this could not be confirmed either way. **Recorded as an open item below** (register row
> R11) rather than asserted as done.
>
> **Injury loader rewritten to merge, not replace** (`store/injuries.py`). The old loader
> deleted every `source = 'transfermarkt'` row and reinserted the scrape — safe only because
> the scraper always covers every player. It does not: a squad-page scrape only visits
> *current* squads, so every summer transfer window drops hundreds of players who have left
> the four English leagues out of the file, and the old loader would have deleted their
> injury history along with them (411 such players reported, 375 still ranked in the data).
> `merge_transfermarkt_rows` now deletes and reinserts only the players actually present in
> the incoming file; every other player's rows, and every `source = 'manual'` row regardless
> of player, are untouched. The volume guard (`MIN_ROW_RATIO`) is rescoped to match — it now
> compares incoming vs. stored rows **for the players visited**, not the whole table, so it
> can no longer be fooled by ordinary squad turnover into treating a normal refresh as a
> shrink, or fail to catch one because the untouched leavers padded the denominator.
> **Verified on this database:** 3,772 transfermarkt-sourced injury rows for 1,176 players
> (the player count matches the last reported load exactly).
>
> **Goalkeeper metrics were computed for every position.** Impect's conceded-xG/shot-stopping
> columns (`gk_shot_stopping_pct`, `gk_gsaa_p90`, `gk_conceded_p90`, `gk_catches_p90`,
> `defensive_touches_outside_box_p90`, plus the retired `gk_saves_p90`/`save_pct`/
> `gk_claims_pct`/`gk_aggressive_distance`) are genuinely populated for every player, not just
> goalkeepers, because they are team defensive context ("conceded while this player was on
> the pitch"), not an individual save-quality figure. `dashboard/loaders.py`'s new
> `GOALKEEPER_ONLY_METRICS`/`_mask_goalkeeper_only_metrics` now null them out for every
> non-Goalkeeper row **at display only** — the underlying data is untouched (it is correct,
> just mislabelled for an outfielder), and scoring was never affected, since
> `club_framework.PERFORMANCE_METRICS` never listed these for an outfield position. An
> extreme goalkeeper reading in this data (very low minutes, small denominator) was
> investigated and reported as a real, correctly-computed figure, deliberately not clamped
> — the 450-minute rankable floor already excludes it from scoring.
>
> **Twelve retired StatsBomb metrics removed from the display vocabulary**
> (`dashboard/labels.py::LABELS`): `progressive_passes_p90`, `passes_into_final_third_p90`,
> `dribbles_p90`, `dribbles_completed_p90`, `carries_p90`, `progressive_carries_p90`,
> `tackles_p90`, `interceptions_p90`, `ball_recoveries_p90`, `gk_saves_p90`,
> `dribble_success_pct`, `save_pct` — confirmed zero non-null rows for each across
> `player_metrics_neutral`. They no longer appear in the glossary, full-stats table or
> charts, so a profile no longer shows an empty card for a stat nothing populates any more.
> The Player profile's raw goalkeeper/defender output tiles (Save %, Saves, Tackles,
> Interceptions) now self-check via `_output_tile_plan` and hide instead of showing "—"
> forever, with a pointer to the live Impect figures in the scorecard metrics below.
>
> **The advisory flag now names the dimension.** `veto` used to render as one generic line
> ("below the club minimum on a dimension"); `tabs/players.py::_veto_reasons` now names every
> dimension that tripped it and by how much — e.g. *"Resale Potential 1.58 is below the club
> minimum of 2.00"* — reading whichever of the six dimension bands (Performance, Physical,
> Financial, Resale, Psychological, Medical) are present on the row. Reported that 975
> players carried the unexplained version and over half of those tripped on a dimension not
> otherwise shown on screen (Financial/Resale, hidden unless "Show affordability" is on).
>
> **Interface.** Cookie-persisted logins (`dashboard/cookie_auth.py`): an HMAC-SHA256-signed
> token (`config.settings.session_secret`, stdlib `hmac`, never a password/hash) lets a
> browser refresh re-establish the session instead of bouncing back to the sign-in form —
> Streamlit's session state lives in server memory keyed to the websocket connection, which a
> refresh always reconnects fresh. Role, name and lock/must-change-password state are re-read
> from the live `users` row on every restore, never trusted from the token, so a deactivation
> takes effect immediately regardless of an outstanding cookie; an unset `SESSION_SECRET`
> simply disables cookie persistence rather than falling back to an insecure default. The
> Players table's per-row pandas `Styler` (zebra/affordability tint) was removed — a `Styler`
> emits inline CSS per cell, and on a ~50-column, several-hundred-row table rebuilt on every
> rerun (every filter change, every keystroke) that is a purely cosmetic cost; the one
> meaningful tint (affordability) is stated in words via the existing "Fee in budget"/"Wages
> in budget" checkbox columns instead. A **global player search** (`dashboard/search.py`) now
> spans every position and league for the season, built from the pre-filter candidate pool so
> it never depends on what the sidebar currently shows, with accent/case/punctuation-folded
> matching (`fold`/`filter_labels`) so "Mendez", "mendez" and "Méndez" all find the same
> player. The **Watchlist** gained current-season form (reusing the profile's own
> `_current_form_summary`, so the two can't disagree), a most-recent-injury-spell column, a
> contract-months-left countdown, and a "what needs a look" strip (contract ≤ 6 months,
> currently injured, not yet assessed) — and its "Quality" column (the retired
> `player_scores.performance_score`, a superseded 0–100 figure) was replaced with the real
> `objective_composite`/Performance/Physical bands. **Roughly two dozen sites** across the
> Players and Watchlist tables where a missing value reached the screen as the literal text
> "None" or "nan" (confirmed directly: `st.column_config.NumberColumn`/`LinkColumn` do not
> leave a missing cell blank for a `NaN`, `None` or `pd.NA` input — all three render as text)
> are fixed via a shared `dashboard/formatting.py` (`value_or_dash`/`numeric_or_dash`/
> `link_or_blank`), pre-formatting every such column to text with an em dash for "unknown"
> before it reaches the column config.
>
> **`scout_assessments` is no longer empty.** This database now holds **2** assessment rows
> (one Psychological `signed_off`, one Psychological `rejected`, same author, no Medical
> entries) — the first real use of the interface since it was built. `assessed_composite`
> remains **0 of 6,573** rows non-null (verified): neither player has a Medical entry yet, so
> `assessed_weight_covered` stays below the threshold needed to compute a composite. This is
> expected behaviour, not a defect, and does not change the "no scout has used the platform
> unprompted" caution in gap G3 below — but the "0 assessments" figure quoted in the
> 2026-08-24 entry above no longer holds and should not be repeated.
>
> **694 tests pass** (was 604; 511 before that; 365 before that) — collected and run directly
> against this checkout (`pytest -q` → `694 passed, 12 warnings`).
>
> **Data refreshed:** Transfermarkt squads and injuries were re-scraped and playing-style
> archetypes rebuilt, per the audit's own account — this pass did not re-run either and could
> not independently confirm them beyond the injury/bio row counts verified above.
>
> **Still not done:** the player-report export (R3c) and the final whole-branch review.

> **2026-08-24 — reject, admin user management, regrouped navigation, and the 2026/27
> season now loaded (not scored).** Recruitment staff are about to get real access, so this
> pass closed the remaining rough edges found in review rather than adding a new feature.
>
> **Reject (the third outcome on the sign-off queue, alongside sign-off and "enter your
> own").** A reviewer can now decline a submitted assessment. **The reason is optional** —
> earlier it was mandatory; forcing an explanation turned out to be the wrong bar for a
> reviewer who simply disagrees and wants it off the queue. Migration `19ac464d556d` adds a
> nullable `rejection_reason` column. A rejected assessment stays on the record, attributed,
> leaves the sign-off queue, never scores, and is never counted as a conflict; the scout sees
> it (and the reason, or a plain "no reason recorded" note) on the player's profile and can
> submit a fresh one. This is Decision 17 / Rule 4 applied to rejection exactly as it already
> applied to sign-off, not a new decision.
>
> **Admin Users page (`dashboard/tabs/users.py`), visible only to `admin`.** List every
> account, create one, reset a password, clear a lockout, deactivate and reactivate — all
> from the browser, gated on the `manage_users` permission (checked twice: once in `app.py`'s
> page registration, which is what actually keeps the page out of a non-admin's sidebar, and
> again at the top of the page itself). **`deactivate-user` and `reactivate-user` were also
> added to the `lofc.admin` CLI**, calling the exact same `store.users` functions the browser
> page does. **Users are never deleted** — `scout_assessments` rows reference `users.id` via
> `author_id`/`approved_by`, so deleting an account that has ever assessed or approved
> anything would break that foreign key and erase the attribution the whole system depends
> on. An admin cannot deactivate their own account (`model/user_admin.py::guard_deactivate`),
> so there is always at least one administrator left who can sign back in. **This closes the
> "no command to deactivate a user" gap noted below on 2026-08-17.**
>
> **Navigation regrouped.** The nine `st.navigation` pages (unchanged individually) are now
> grouped into section headers — **Scouting** (Players, Compare, Watchlist), **Assessment**
> (Assess, Sign-off), **Analysis** (Player types, Physical), **Reference** (Glossary,
> Methodology) — plus a tenth page, **Users**, in its own **Admin** section, present only for
> an administrator.
>
> **Chrome.** The players/leagues/season strip is now a slim, quiet info bar (`.lofc-infobar`
> in `theme.py`) rather than a KPI block competing with the page beneath it; the signed-in
> user's name, role and a sign-out control now sit top-right in the header (`theme.header`'s
> new `identity_slot`, rendered by `session.topbar_identity`) instead of in the sidebar.
>
> **Caches shortened to 60s** for every loader that carries `assessed_composite`
> (`load_scorecards`, `_stored_scorecards`, `load_scorecards_archetype` in
> `dashboard/loaders.py`) — at the old 600s TTL a scout who saved an assessment and switched
> to the assessed ranking could wait up to ten minutes for it to appear and reasonably
> conclude the save had failed. Loaders that only carry pipeline output (e.g.
> `load_current_form`, below) are unaffected and stay at 600s.
>
> **2026/27 (season_id 319) is now loaded — six leagues, not yet scored.** Both providers'
> live-season ingest has run: **1,771 players across 6 leagues** (Premier League 2 has not
> started), averaging **85 minutes played** each, nobody within reach of the 450-minute
> rankable threshold (max ~207). There is deliberately **no 2026/27 composite** — a player's
> profile now shows a **"Current form"** section (`loaders.load_current_form`,
> `tabs/players.py::_current_form`) with 2026/27 minutes/goals/assists as **plain facts,
> explicitly labelled "not a rating"**, alongside the dimension scores from his most recent
> **scored** season (2025/26). Realistically this stays unscored until enough of the season
> has been played — **expect that around October** (see the in-season model below).
>
> **Fixes made along the way, worth recording as resolved:**
> - The **Assess page lost its selected player on every keystroke** — any widget interaction
>   (e.g. picking a band) triggered a rerun that dropped the selection. Fixed by giving the
>   "currently assessing" player its own persistent session-state slot
>   (`dashboard/session.py::get_assess_target`/`resolve_assess_target`), separate from the
>   one-shot handoff used by "Assess this player" on the profile/watchlist.
> - The **watchlist showed blank club/position/age for any Scottish Premiership/Championship
>   or Premier League 2 player** — `store/watchlist.py::load` joined only the EFL-only
>   `player_season_metrics` table. It now joins `player_metrics_neutral` (the combined
>   7-league table the profile itself reads) first, via COALESCE, and derives age from
>   `players.birth_date` the same way the profile does, falling back to the valuation's age
>   only when no birth date is on file.
> - The **injury evidence panel's source column read "Scraped"** — internally accurate,
>   meaningless to a reader outside the building. Now labelled **"Transfermarkt"**
>   (`dashboard/evidence.py::SOURCE_LABELS`).
> - **Mid-season transfers could show the wrong club.** `ingest/impect_translate.py` picked
>   the "dominant" identity row (name, position, **and club**) by highest per-position
>   `matchShare` — but a player whose minutes at his new club were split across two or three
>   positions could show a lower matchShare there than his single settled position at the
>   old club, so the club shown was wrong for exactly the players a recruiter most needs it
>   right for. Club is now picked separately, by **total minutes per squad**, while
>   name/position/birthdate still come from the highest-matchShare row (unchanged).
> - The **"season under way, not yet rankable" banner used to render above every page**,
>   including Sign-off, Glossary and Methodology, where the season selector changes nothing
>   they show. It now renders only on the pages the season selection actually drives
>   (Players, Compare, Assess, Player types).
>
> **604 tests pass** (was 511; 365 before that; 301 before that). **`objective_composite`
> (the default ranking) is verified unchanged: 6,573 rows in the `'All Metrics'` archetype,
> average 3.029285** — identical to the 2026-08-14 figure below. `assessed_composite` and
> `scout_assessments` remain empty on this database (0 assessments recorded) — no scout input
> has touched the ranking, because no scout has used the interface yet (see the gaps register
> below).
>
> **Still not done:** the player-report export (R3c) and the final whole-branch review.

> **2026-08-17 — the scout-assessment interface is built, on the same branch
> (`r3a0-injury-scrape`, not pushed).** Login, the assessment form, the injury/availability
> evidence panel, status badges, the sign-off queue and watchlist integration are all live.
> Recruitment staff sign in — accounts are created by an administrator (`python -m lofc.admin
> create-user`); `set-password` is the only password-reset route (the `users` table holds no
> email address, so there is no self-service or email reset — an admin resets it in person) and
> `list-users` lists every account with its lock state — score a player against the club's own
> Psychological and Medical criteria (Medical is still a human-entered band with the injury
> evidence beside it, per Decision 12 — the platform never computes it), and a Head of
> Recruitment or admin signs assessments off from a queue. The Players list gained an opt-in
> "Rank on assessed composite" toggle, off by default. Navigation was rebuilt from `st.tabs` to
> `st.navigation` pages (new `dashboard/session.py`), so "Assess this player" (on the profile and
> on a watchlist row) genuinely carries the player to the Assess page instead of just switching a
> tab.
>
> **Decision 17 replaced the earlier tiebreak.** The design previously said the most recently
> submitted assessment wins when two disagree on the same dimension — that gave the final word to
> whoever saved last, which was the *normal* case rather than the exception, since sign-off was
> optional. The rule is now one line: **a signed-off assessment is never in conflict; two or more
> unsigned assessments that disagree score nothing** until someone with sign-off rights decides —
> by signing one of them off, by entering and signing off their own (pre-filled from either side,
> changed values marked "was 4, now 2"), or by leaving it, in which case the player reads
> "assessments conflict — not scored" (badge ⚪, grey — an honest "nobody has decided yet", not an
> error state). Authority comes from the act of signing off, never from the role: the Head of
> Recruitment's own entry does not outrank a scout's until it is the one signed off. Full
> reasoning: Decision 17, `docs/superpowers/specs/2026-08-10-scout-assessment-design.md` §12.
>
> **Auth gaps closed alongside the login screen:** passwords are scrypt-hashed (Python stdlib
> only, no new dependency), minimum 12 characters — length is deliberately the only rule, per
> NIST SP 800-63B — 5 failed logins locks an account for 15 minutes, and a session expires after
> 12 hours. **Still open (at the time): no command to deactivate a user account** — the
> `is_active` column exists and login honours it, but flipping it meant editing the database
> by hand. **Superseded 2026-08-24 above: both a CLI command and a full admin Users page now
> exist.**
>
> **Verified: `objective_composite` (the default ranking) is unchanged — 6,573 rows, average
> 3.029285 — and no scout input touches it;** the resolution machinery only ever writes
> `assessed_composite`, a column the objective ranking never reads. `scout_assessments` starts
> empty on a fresh database; nothing in the interface backfills it — it fills as staff use it.
> **511 tests pass** (was 365).
>
> **Still not done:** the player-report export (R3c) and the final whole-branch review — every
> commit on this branch was reviewed individually as it landed, but the cross-cutting pass across
> the whole branch has not happened.

> **2026-08-14 — scout-assessment foundation built, on branch `r3a0-injury-scrape` (50 commits,
> not pushed).** Two pieces landed, both complete: **R3a-0** (Transfermarkt injury data) and
> **R3a-1** (scout-assessment foundation, 5 tasks).
>
> **R3a-0 — injury data:** `ingest/transfermarkt_common.py` (shared polite fetch client, 2.5s
> delay, browser UA, backoff) + `ingest/transfermarkt_injuries.py` (resumable scraper, one page
> per player) + `store/injuries.py` (CSV→Postgres loader) + `model/medical.py` — availability
> with three **honest** states, `MEASURED` / `CONFIRMED_BY_MINUTES` / `UNKNOWN` (an unknown
> record returns `None`, never a confident 1.0) + the `player_injuries` table. **3,766 injury
> rows loaded for 1,176 players** (superseded the earlier figures quoted lower in this register).
>
> **R3a-1 — scout-assessment foundation:** `model/club_criteria.py` (the club's per-position
> Psychological and Medical criteria, transcribed verbatim from the club document — Full Back
> and Winger are de-duplicated unions of the club's left/right profiles; per-position counts vary
> 2–8, which is the source document, not an error) + `users` / `scout_assessments` /
> `scout_criterion_scores` tables + `player_injuries.entered_by` (migration `a3fd42bcb2c2`) +
> `dashboard/auth.py` (scrypt password hashing, stdlib only, no auth dependency; role
> permissions) + `admin.py` (the `create-user` CLI — corrected from `dashboard/admin.py`,
> the module actually lives at `src/lofc/admin.py`) + `model/scout_scores.py`
> (`resolve_bands()`: at this point, signed-off wins, else most recent submitted — **that
> tiebreak was replaced by Decision 17 on 2026-08-17, see above: two or more unsigned
> assessments now score nothing until someone decides**; drafts never score; the two
> dimensions resolve independently) + `assessed_composite` / `assessed_weight_covered` /
> `psychological_band` / `medical_band` on `player_scorecards` (migration `5e80ab6fe191`).
>
> **The design is fully settled** — `docs/superpowers/specs/2026-08-10-scout-assessment-design.md`
> (16 decisions). The load-bearing ones: **Decision 12** — Medical is a **human-entered band**,
> not computed from injury data. Injury-record coverage is 74% in the Championship but 18% in
> the National League, so an automatic score rewarded obscurity in exactly the direction this
> club recruits, and the club's own 1–5 rubric never defines the "elite threshold" that bands 4
> and 5 need for Medical — so Transfermarkt injury data is **evidence shown to the assessor,
> never a score.** **Decision 13** — screening criteria **warn, never override** the assessor's
> entered band. **Decision 14** — sign-off is **non-blocking**: a `submitted` assessment scores
> and ranks immediately; sign-off marks it approved and gates what may be exported as final
> (badges: 🟠 assessed / 🟢 signed off, always with words as well as colour). **Decision 15** —
> `assessed_composite` = Performance + Physical + Psychological + Medical = **86%** of outfield
> weight; it **excludes** the modelled Financial and Resale dimensions, because `RANK_COLUMN` is
> `objective_composite` and modelled money has never entered a ranking number (worked example:
> Performance 4.0, Physical 3.5, Financial 3.0, Resale 4.0, Psychological 3.8, Medical 3.0 →
> `assessed_composite` **3.66** at 86% measured). **Decision 16** — **every role may assess both
> dimensions**; only sign-off is gated. The role is a record displayed beside each entry, not a
> restriction; self-sign-off is allowed but labelled.
>
> **Verified state of the scoring, as of 2026-08-14:** `objective_composite` (the ranking) is
> **unchanged** — 6,573 rows, average **3.029285**. `assessed_composite` was **NULL for every
> player** — `scout_assessments` was empty, because **no interface existed yet to create an
> assessment. Superseded 2026-08-17 above: the interface is now built,** though
> `objective_composite` remains unchanged and `scout_assessments` still starts empty on a fresh
> database.
>
> **NOT built, stated at the time:** the entire user interface — no login screen, no assessment
> form, no evidence panel, no badges, no watchlist integration. That was **R3a-2**, planned but
> not written. **Superseded 2026-08-17 — see the note above: R3a-2 is now built.** The **player
> report export (R3c)** and the final whole-branch review remain not done (unchanged by R3a-2).
>
> **Open items as of 2026-08-14** (auth gaps — no password reset, no login rate limiting, no
> password strength rules — closed by R3a-2 on 2026-08-17; see the note above). **S4 (show
> "current club") is deferred until after the interface**, by the owner's decision — see the
> register entry below for why it matters. Contract data was refreshed 11 Aug 2026: **1,363
> players carry a contract date — 701 expiring summer 2027, 408 in 2028, 163 in 2029.** Coverage
> is roughly 55% in the top three English tiers, **28% National League, 2–5% Scottish/PL2 — not
> adequate coverage for those leagues.**
>
> **365 tests pass** (was 301 as of the 2026-08-11 note below; the scout-assessment branch added
> the rest — since risen to **511** with R3a-2, see the 2026-08-17 note above).

> **2026-08-03 — audit + fixes.** A full metric audit (club-document fidelity, API pull, computation)
> confirmed the framework is faithful to the club files and the composite maths is correct. It found
> and we **fixed**: (1) `np_xg_xa_p90` was penalty-inclusive though labelled "NP xG + xA" — now strips
> penalty xG to match `np_xg_p90` (neutral table rebuilt from landed data, no re-fetch); (2)
> Financial/Resale percentiles pooled both seasons — now ranked **within season**; (3) `metric_percentiles`
> made season-safe (groups by season) and a stray `id` column excluded from ranking. **UI fixes:** the
> advisory veto/minimum flag is now a styled amber callout; the Transfer-budget & Wage-budget controls
> (and the affordability KPI) are shown **only when "Show affordability" is on** (Option A — they gate
> nothing in the default view, so hiding them removes a misleading control); the **Compare** tab now
> charts the club's Performance metrics (archetype-aware, from the scorecard percentiles) instead of the
> retired Quality/Fit role metrics, and its Market column is money-gated; the cross-league name lookup now
> covers Scottish/PL2 (fixed "league 903" → "Premier League 2"). **Season split verified end-to-end** — every
> scoring path filters/groups by `season_id`, a both-season player holds two independent rows (unique
> `(player, competition, season)` triples), percentile peer groups are same-season only, and selecting a
> season yields scorecards from that season alone. 301 tests pass. *Known, non-scoring:* the playing-style **clusters** pool both seasons
> (and still read the StatsBomb-era table) — a style label only, it does not touch the composite (roadmap).
>
> **2026-08-03 (b) — more fixes.** (1) **Age** is now derived from `players.birth_date` at the season
> midpoint for **all** leagues (was read from `valuations`, EFL-valued only) — coverage jumped from
> ~35% to **~99.9%** (Scottish/PL2 went from 0 to full). (2) **Compare** gained a **raw physical
> comparison table** (SkillCorner per-90 output) — deliberately *raw*, because physical output is
> genuinely comparable across leagues (unlike the within-league percentile radar); mixed units, so a
> table not a radar. (3) The cross-league name lookup covered the last two spots (fixed "league 903").
> **Identity audit:** the 54 names sharing multiple player-ids are **all genuine namesakes** (distinct
> birth dates) — **zero split identities**; one unconfirmable case (a birth-date-less PL2 youth vs a
> senior L2/NL player) is a namesake by age. The Impect↔player-id matcher is sound.


**Scoring is 100% Impect + SkillCorner — zero StatsBomb in scoring.** (StatsBomb still runs
only to seed player identity — stable IDs, birth dates, league names — during the migration.)

- **Data:** **91 metrics** per player, **7 leagues** — the EFL (Championship, League One,
  League Two, National League), the Scottish Premiership & Championship, and Premier League 2
  — across **14 league-seasons** (2024/25 + 2025/26).
- **Physical (SkillCorner):** covers the EFL + Premier League 2 + Scottish Premiership.
  **2025/26 only.** The **Scottish Championship has no physical layer** — SkillCorner lists the
  competition and even a 2025/26 edition (id 1210), but holds **zero** physical/tracking data for
  it (verified against the live API: 0 players vs 358 for the Scottish Premiership). It is a
  SkillCorner data gap, not a config omission — so that league scores on Performance alone.
- **The scoring model is the club's real framework** (`model/club_framework.py` +
  `model/scorecard.py`), encoded from the club files in `docs/`:
  - `Impect Data - Positional Metrics.xlsx` → the per-position metric lists (`PERFORMANCE_METRICS`).
  - `LOFC - Position Archetype.docx` → the seven dimensions, their per-position weights
    (`DIMENSION_WEIGHTS`), the 1–5 scoring, and the median/70th thresholds.
- **Every player gets a 1–5 composite.** Three composites now exist in the schema:
  **objective** (Performance + Physical, real data — the default ranking, `RANK_COLUMN`,
  unaffected by anything below), **full** (adds the *modelled* Financial + Resale), and
  **assessed** (Performance + Physical + Psychological + Medical, 86% of outfield weight,
  excludes modelled money — Decision 15, see the 2026-08-14 note above). Psychological and
  Medical are scout inputs, entered through the **now-built** scout-assessment interface
  (R3a-2, 2026-08-17): the login gate, the assessment form, the evidence panel and the
  sign-off queue (`dashboard/{session,badges,evidence,transparency}.py`,
  `dashboard/tabs/{assess,signoff}.py`) all write through `model/scout_scores.py`'s
  `resolve_bands()` (Decision 17: a signed-off assessment always wins; two or more unsigned
  assessments that disagree score nothing until someone decides; a reviewer may also
  **reject** an assessment outright, with an optional reason, added 2026-08-24). `assessed_composite`
  starts NULL on a fresh database and fills in as staff assess players; it never feeds
  `objective_composite`, the default ranking. As of 2026-08-24 it is still all NULL — no
  scout has used the interface on this database yet.
- **The old invented "Style-fit" is retired** from every live surface. The Shortlist, Player
  profile, Compare, Player-types and Watchlist all rank/show the club composite.
- **Nobody is excluded automatically.** The club's "< 3.0 = do not proceed" / "< 2.0 = veto"
  rules are advisory flags only; affordability gates (fee + wage) are opt-in.
- **Scored WITHIN one season** (a sidebar **Season** selector; latest, 2025/26, is the
  default). Each player appears once, ranked against that season's peers with that season's
  coverage (physical is ~90% within 2025/26; 2024/25 has none). Earlier seasons stay fully
  available and power the profile **trajectory** chart. This fixed the earlier season-mixing
  (duplicate players + last-season-vs-this-season comparisons).
- **Archetype lens (opt-in)** for **Full Back** (Attacking / Progressive) and **Winger**
  (Direct & 1v1 / Crossing & Creative): the sidebar **Archetype** re-scores the Performance
  dimension on that archetype's metric subset and re-ranks, with the **all-round composite kept
  visible** alongside on both the Shortlist and the Club scorecard. Midfield archetypes are
  deferred (workbook doesn't fully specify their lists).
- **One "Players" workspace** (master-detail) — the former Shortlist + Club scorecard + Player
  profile tabs are merged into a single composite-ranked list with, on click or search, a full
  player detail: dimension scores + the club-framework **grand table** (Source · Season total ·
  Per-90 · Percentile · 1–5 Band) + charts on the club per-position (archetype) metrics.
  **Money is an opt-in secondary layer** (off by default — the default ranking is 100% real
  football data; market value/wages/affordability appear only when "Show affordability
  (modelled)" is ticked). **Ten pages now**, grouped in the sidebar (2026-08-24): Scouting
  (Players · Compare · Watchlist), Assessment (Assess · Sign-off), Analysis (Player types ·
  Physical), Reference (Glossary · Methodology), and — administrators only — Admin (Users).
- **The composite is persisted** to `player_scorecards` (a pipeline stage), so the dashboard, the
  offline `shortlists` table and the BI layer all read the *same* numbers. The `shortlists` table
  now ranks on `objective_composite` — **the retired Style-fit no longer orders anything anywhere.**
- **Contract-expiry filter (the free-transfer market)** — a sidebar **Contract expiry** selector
  (*Any* · *summer 2027* · *summer 2028* · *already expired*) plus **Contract** and **Months left**
  columns in the Players table. A forward horizon means "still under contract today, expiring by
  the cutoff", so lapsed deals never pad the list; players with no known expiry are excluded **and
  counted on screen**. **The filter works again following the B1 recovery** (see below): **702**
  players expiring by summer 2027, **1,110** by summer 2028, **35** already expired. The contract
  snapshot date is now **11 Aug 2026** (it was a 10 Jun 2026 snapshot before the incident). These
  figures reflect **2026/27 squads**, so a player who featured in 2025/26 but has since left the
  four English leagues will have no contract date — that is correct for recruitment (you want live
  contract positions), and it is why the numbers do not match the pre-incident 542 expiring summer
  2027, 822 by 2028, 447 already expired exactly. **There is deliberately no "January" option**: of
  those pre-incident dates, 1,377 of 1,381 were in June and none in January, so the January
  question was answered by *Months left ≤ 6* on a summer horizon — unaffected by the incident.
  **B1 — Transfermarkt contract/market-value refresh: ✅ DONE (11 Aug 2026).** The 11 Aug 2026
  scrape initially destroyed contract/foot/height data via a parsing bug; the bug was fixed and a
  recovery scrape ran successfully the same day. The database held **1,363** contract dates,
  **1,606** feet and **1,635** heights immediately after recovery, against 5,626 players. Market
  values were unaffected throughout (**2,526** present — that field is located by CSS selector,
  not by column position). **Superseded 2026-08-25** (register row R11 below): after the
  76-split-identity merge these stand at **1,412** contract dates, **1,660** feet and **1,689**
  heights. Full incident record and recovery outcome in the Pending work register below.
- **694 tests pass** (was 604, before that 511, before that 365). The dashboard renders clean.
  The scout-assessment foundation (schema, scoring resolution, injury data) **and its interface**
  (login, assessment form, evidence panel, badges, sign-off queue **with reject**, watchlist
  integration, admin user management) are both built — see the 2026-08-25, 2026-08-24 and
  2026-08-17 notes above and register items R3a-2/R3a-3/R11.

Full detail on the scoring: `docs/methodology.md` §3b. Full metric provenance:
`docs/DATA_ARCHITECTURE.md`.

---

### 2026-08-28 — data-quality fixes found by staff use (R3d)

Two defects reported from live use, both traced to source and fixed or documented.

**Luka Lynch filed as a Full Back** (Impect and Transfermarkt both call him an
offensive mid / right winger). Two separate causes:

1. *A real bug.* `impect_translate` chose a player's position by taking the single
   highest-`matchShare` ROW. Impect splits two of our groups across sides
   (`LEFT_`/`RIGHT_WINGER`, `LEFT_`/`RIGHT_WINGBACK_DEFENDER`), so those two were
   systematically under-counted — a player with 3.0 at centre forward and 2.0 + 2.0 on
   the wings read as a centre forward. Now summed per GROUP first
   (`impect_translate.dominant_position`). **Moves 29 of 1,999 Impect-spined rankable
   player-seasons (1.45%)**, overwhelmingly INTO Winger and Full Back. Affects
   Impect-spined leagues only — EFL positions come from the StatsBomb spine.
   **Takes effect on the next `build_neutral` run; the stored data is still pre-fix.**
2. *Not a bug.* Full Back genuinely is Lynch's largest group at 38.6%; his other 61.4%
   splits four ways. Platform-wide, **668 of 6,575 rankable player-seasons (10.2%)** are
   assigned a group holding under half their minutes, **219 (3.3%)** under 40%. Handled by
   disclosure: the new `player_position_shares` table (migration `a1c4e77b9d20`, 26,981
   rows) records the split and the report prints it.
   Scoring him in each position he played was prototyped and **rejected as not worth
   building**: his composite is 3.91–4.00 across Full Back / Attacking Mid / Winger /
   Centre Forward, so the label barely moves the number.

**Lyall Cameron showing 5 assists against Transfermarkt's 0.** Our arithmetic is exactly
right — `value × matchShare` recovers integer counts and the phase components sum to 5.0 —
and the club (Aberdeen) is right too; Transfermarkt confirms he played for both Rangers and
Aberdeen in 25/26. The gap is **definitional**: Impect's `ASSISTS` (glossary KPI 77) counts
four things — the final pass, deflected or blocked actions, fouls won leading to a converted
penalty or free kick, and forced own goals — where Transfermarkt counts only the first.
Systematic, not isolated: our assists run ~1.5× Transfermarkt's across the Scottish
Premiership and 1.35× StatsBomb's in League One, at correlation 0.90–0.92.
**No narrower KPI exists** — all 38 assist-family fields partition by zone/lane/phase, not
by assist type — so the fix is disclosure, not substitution: the definition is now printed
on the report, and "Chances created" (`SHOT_ASSISTS`, already mapped) sits beside Assists.

**Also added:** a Leyton Orient squad-median benchmark on every percentile bar and the
physical radar, with `n` always shown (the club has 1–6 rankable players per position) and
an explicit caveat when the club's league differs from the player's, because percentiles
are league-relative.

**Verified:** 763 tests pass (was 739). `objective_composite` unchanged at 10,533 rows /
3.027036. All 8 positions print as ONE page against the most position-fragmented player in
each — Centre Forward, which already spilled at 194.5mm BEFORE this work, now fits at
193.3mm.

**Still open:** the assist-definition gap is disclosed, not closed — it cannot be closed
from this feed. Height and contract expiry remain Transfermarkt-only (register R6). The
Impect bio backfill is specced but not built.


### 2026-08-28 (later) — report evidence: bands, per-position output, position fix applied

Four tasks, all verified end to end.

**1. Position group now chosen on MINUTES, and summed per group.** Two changes to
`impect_translate.dominant_position`: sum per position GROUP before choosing (Impect splits
Winger and Full Back across LEFT_/RIGHT_, so they were systematically under-counted), and
choose on minutes rather than matchShare (the two are the same measure — matchShare is
minutes / ~100 — but the report's split is in minutes, so 7 reports contradicted themselves).
**Label now agrees with the split for all 6,575 player-seasons; previously 7 did not.**

**2. Goals and assists per position** (`player_position_shares.goals/assists`, migration
`b6e2a91f4c73`). The report prints "2 goals as attacking mid · 2 goals as winger" beside the
season totals. **No score changes**: metrics stay whole-season across every position a player
filled. Splitting them was considered and REJECTED — 23% of all goals and assists in the
platform are earned outside the assigned position (1,233 players affected, 469 of whom earned
most of their output elsewhere), so splitting would gut real profiles and give a player two
different stat lines. Reconciled: per-position counts sum to the season total for all 3,345
rankable players, 0 mismatches.

**3. Physical radar rebuilt.** The percentile is now PRINTED under each axis label (it was a
polygon to eyeball). Six named bands — Elite (80-100), Very Good (65-80), Good (55-65), Above
Average (50-55), Below Average (25-50), Subpar (0-25) — drawn as rings, keyed in the footer
with their ranges in brackets. The Leyton Orient squad median is drawn as a second series.
The old "League average" ring was REMOVED: it was `[50] * 8`, a perfect octagon for every
player in every league by construction (measured: the real median is 50.5 on all eight axes),
so it looked like data and was a gridline. The band boundary between Above and Below Average
IS the 50th percentile, so the rings already carry what it pretended to.

**4. The position fix applied to the data.** `build_neutral --write` → `position_shares` →
`scorecard_run` → `constrain.run`. **25 position groups moved** (4 Centre Back→Full Back,
3 Winger→Attacking Mid, 3 Attacking Mid→Centre Forward, …). Row counts identical (11,222
neutral, 6,573 All Metrics scorecards); `objective_composite` mean 3.029393 → **3.029381**,
a shift of 0.000012 — the scale expected from 25 players changing peer group.

**Verified:** 778 tests pass (was 739). All 8 positions print as ONE page, measured against
the most position-fragmented player in each. Label-vs-split mismatches: 0. Composites outside
1-5: 0.

**Page budget note:** the additions cost real height, reclaimed by measurement rather than
guesswork — bars ceiling 320→250, radar 228→202, scatter 330→280, `@page` margin 8→7mm, and
the band key moved from beside the radar (6 stacked rows, ~15mm in a 64mm column) to one
inline row in the footer. `.evidence` is `flex:1`, so shrinking a chart does NOT shorten the
page; it only buys slack inside a fixed box. That is why the page grew despite smaller charts
until the decision band and footer were addressed directly.

### 2026-09-02 — the assessed-rating gap, advisory gating, player-card depth

**The "assessed composite never updates" report was a UI defect, not a scoring bug.**
Traced to source: of six assessments, Luke Berry and Daizen Maeda have BOTH scout dimensions
signed off and both correctly carry a rating (2.29 and 4.06). Jaze Kabia has Psychological
signed off and no Medical Risk row at all; Fletcher Holman's only assessment was rejected.
Decision 9 is "both, or neither" — so those two score nothing, correctly.

The problem is that badges are PER DIMENSION. Kabia's page shows a green "Signed off" while
the system holds an incomplete assessment, so the interface reported success and the rating
never appeared. Fixed by `scout_scores.missing_dimensions`, surfaced as a banner naming the
outstanding dimension. **Two of the first four assessed players hit this.**

**Renamed for the people using it:** "Assessed composite" is now **"Scout-verified rating"**
throughout the interface (the column name is unchanged). The toggle's help now states the
64% / 86% weight split and that one dimension alone scores nothing.

**Advisory flags now follow the affordability switch.** `_veto_reasons` takes
`include_modelled`; with money modelling off, Financial Fit and Resale Potential are dropped
rather than cited. Measured on 25/26: **965 players carry the flag and 390 (40%) trip ONLY on
those two**, so two in five advisories pointed at a number the reader had deliberately hidden.
A flag with no remaining visible reason now says nothing at all, rather than falling through
to "detail unavailable".

**Player card gained the report's context** (display only, no score moves):
- minutes by position, and goals by position, from `player_position_shares`
- a callout when the assigned position holds under half the player's minutes
- **the same player's other league-season this season, paired with its composite.** A loanee
  gets a row and a score per league because percentiles are league-relative; unlabelled that
  reads as a duplicate. Labelled it is a level-step signal — Aaron Loupalo-Bi rates **3.96**
  against PL2 peers and **2.63** in senior League Two. **116 players in 25/26 have such a
  pair.**

**Verified:** 789 tests pass (was 778). Dashboard restarts clean, 0 import errors.

### 2026-09-07 — archetype audit against the club workbook; open-issue register refreshed

**Archetypes, checked line by line against `docs/Impect Data - Positional Metrics.xlsx`:**

| club archetype (workbook) | implemented? |
|---|---|
| Right/Left Back — All Metrics / **Attacking** / **Progressive Build & Recovery** | ✅ faithful (RB sheet, row 1) |
| Wingers — All Metrics / **Direct & 1v1 Specialist** / **Crossing & Creative Threat** | ✅ faithful (WINGER sheet, row 0) |
| Centre Back / Centre Forward / Goalkeeper — All Metrics only | ✅ faithful (single column by design) |
| Midfield — **Defensive** / **Box to Box** / **Attacking Midfielder** | ⚠️ **partial** |

**The midfield gap, precisely.** The workbook holds midfield in two different places and
they do not agree in granularity:
- the **MF sheet** names three archetypes as *capability prose* (33 / 36 / 34 entries,
  27 shared, genuinely different — Box-to-Box adds dribbling, shots, box availability and
  crossing; Defensive adds aerial duels and influence on allowed chances);
- the **Input sheet** — which is what `PERFORMANCE_METRICS` was actually built from — has
  only **"Centre Midfield"** and **"Attacking Midfield"** rows. There is no Defensive
  Midfield row and no Box-to-Box row.

So the platform has `Defensive Mid`, `Central Mid` and `Attacking Mid` as position GROUPS,
and **Defensive Mid and Central Mid carry byte-identical metric lists** (both the Input
sheet's Centre Midfield row). Attacking Mid has its own. Net effect: **Attacking Midfielder
is reflected; Box-to-Box is not** — a box-to-box player is scored on the defensive
midfielder's list. Affects **102 Central Mid player-seasons** in 25/26.

**Register item B2 is more tractable than it has been recorded as.** It is filed as
"needs the club's per-archetype metric lists", but the MF sheet DOES specify three distinct
lists — as capabilities rather than metric names. The Full Back and Winger archetypes were
themselves derived by exactly this comparison (a clean include/exclude against the base
list), so the same technique is available here. It is a judgement call to be made WITH the
club, not a missing input. **Re-scope B2 from "blocked" to "needs a decision".**

**Documentation:** `CLAUDE.md` was stale (claimed 694 tests; actual 800) and has been
rewritten with a dated STATUS block and a read-order for the next session.

**2026/27 (season 319) is not scorable yet.** 1,771 players loaded across 6 leagues; highest
minutes in any league is **207** (National League) against a 450 threshold, and **zero**
players qualify anywhere. On current accumulation that is roughly **late October**, not
September as previously estimated.

### 2026-09-07 — January window: contracts, loans, and a squad view

Driven by the Head of Recruitment: contract coverage was far below what Transfermarkt
actually publishes, and there was no loan data at all.

**Impect cannot supply either, and this is structural.** 25 API endpoints, all match and
event data; zero contract or transfer fields across 1,482 parquet columns. Impect is an
event-data provider — registration facts are Transfermarkt's domain. Impect CAN say a
player turned out for two clubs (196 did in 25/26) but cannot tell a loan from a transfer.

**Three separate causes of the contract gap, all fixed:**

1. **`identity.match_identity` linked ONLY on name + birth date within one league.** A
   player whose `tm_player_id` we already held, but whose squad-page spelling differed or
   who had moved league, failed the re-match — so a contract sitting in the CSV never
   reached the database. All **128** affected players failed for exactly this reason.
   Now tries the stored id FIRST (a stronger link, established by an earlier match).
2. **The scraper covered four leagues.** Scottish Prem, Scottish Championship and PL2 were
   never scraped, which is the whole explanation for their 2–6%. Added `SC1`, `SC2`,
   `GB21` after verifying a live club page in each carries the full header layout.
   **2,471 → 3,783 scraped rows.**
3. **Identity matched only season 318.** The **293 players who appear ONLY in 26/27** —
   new signings, precisely the January cohort — could never receive a contract date; zero
   had one. Bio is a fact about the person, not a season, so the match now spans every
   season held.

**Result:** contract dates **1,416 → 2,487**; linked players **1,346 → 4,335**;
foot **2,749 → 4,919**; nationality **0 → 5,651**. Scottish Prem contract coverage
**3% → 87%** on the current squad.

**Loans (`player_loans`, migration `c8f1d20a4e65`):** 392 loans, 112 clubs, **100% with
parent club and loan end date**, 290 linked to our players. 53 loans end by Feb 2027;
694 current-squad players are inside 12 months of contract expiry.

**Two bugs found and fixed during the build, both worth recording:**
- The first parser mapped header columns to cell positions and stored every player's
  POSITION as his parent club (392 rows). The page has 6 headers and 9 cells per row.
  Now anchored on the club link's `title`. Same class as the 11 Aug incident.
- The loader DELETEd `season_id 319` while INSERTing Transfermarkt's `2026`, so the delete
  matched nothing and the insert collided on `uq_player_loan`. The transaction rolled back
  and 392 stale rows survived, looking like a successful scrape. Both now pinned by tests.

**New "Squads & loans" page.** The ranked view legitimately shows nothing for 26/27 — a
composite needs 450 minutes and the average player has 69–119 — so it told recruiters to
"try an earlier season". That is the wrong answer to "who is at this club and can I sign
him". The new page answers it with facts that ARE current: 1,822 players, 1,399 contracts,
166 on loan, and each player's **25/26 composite carried across and labelled as such**.
Nothing on it is scored, and the 450 rule is untouched.

**Player card** now shows contract runway ("Contract to Jun 2027 · 9m left", red inside 12
months) and loan status with parent club and end date. Loan status is deliberately NOT
scoped to the season being viewed — whether a player is on loan today is what a January
decision turns on.

**Verified:** 846 tests pass (was 826).

**Known ceiling:** Transfermarkt leaves the contract field blank for ~22% of squad members
— verified as the source's own gap, not a parse failure (those rows carry height 83%, foot
84%, DOB 97%). No engineering gets past it.

### 2026-09-07 (later) — Squads & loans made accurate and usable

**A duplicate that was not the loans.** Yusuf Akhamrich appeared twice under Leyton
Orient. Cause: **116 players hold two 25/26 scorecards** (they played in two leagues), so
the rating join fanned out — 51 duplicated player-club pairs. Fixed by keeping the league
with the most minutes and carrying the other as `alt_rating` rather than discarding it:
3.42 in League Two beside 4.00 in PL2 is the level-step reading, not noise. **1,822 → 1,771
rows, zero duplicates.**

**The loan list was incomplete, and the squad frame could not fix it.** It was built from
`player_metrics_neutral`, which only holds players who have PLAYED — so **135 of 290
linked loanees were missing** (injured, unselected, or not yet in an Impect file). "On loan
only" now reads `player_loans` directly: **all 392 loans, 100% with parent club and end
date**, including those with no appearance yet and those we cannot match to one of our
players (listed with blank details rather than hidden).

**Row click → player profile.** New `session.go_to_player` carries the **player_id**, never
the search label — the label is a formatted string and reconstructing it at a call site
would break silently and could resolve to a different row, which is the class of bug that
opened the wrong player's report once. `resolve_open_player` is pure and unit-tested;
a player with no ranked row (293 appear only this season) produces a message, never
somebody else's profile.

**CSV download** exports exactly the filtered view, so file and screen cannot disagree.

**Every rating names the league it was earned in.** A 3.42 in League Two and a 3.42 in
Premier League 2 are not the same claim, and the table previously showed the number alone.

**UI guidance** came from Streamlit's own bundled skill (`developing-with-streamlit`,
installed from the registry after Node was added): `st.dataframe(on_select=...)` for row
selection, `column_config` for all value formatting, Styler reserved for colour.

**Verified:** 858 tests pass. Row count matches source exactly (1771 = 1771); zero
duplicate player-club pairs; months-left never present without a date; every alternate
rating names its league.

### 2026-09-07 (evening) — stale Impect data found; squad view rebuilt from the scrape

**The 2026/27 data was three weeks old.** The Head of Recruitment observed that League One
clubs had played five matches while the platform showed one. Verified: the 26/27 Impect
files were pulled **17 August** and every League One player showed a maximum `matchShare`
of 1.0. `lofc.ingest.impect` re-pulls the live season correctly on every run — it simply
had not been run. **Nothing runs it automatically; this is the scheduler gap made
concrete.** (Deployment and a server-side scheduler are scheduled for the following week.)

After re-pulling: League One **334 → 491 players, max 5 matches, 514 minutes**. All seven
26/27 iterations refreshed, PL2 gained data it previously had none of.

**2026/27 is now partly scorable: 378 players** cleared 450 minutes (73 Championship,
87 League One, 86 League Two, 111 National League, 21 Scottish Prem).

**A percentile is only as good as its pool, so a guard was added.** Of the 36
position-league pools, **13 hold under five players and 34 players sit in one**. A
composite over three peers is arbitrary, not merely uncertain. `scorecard.pool_is_thin`
(floor of 10) now drives a warning wherever the ranking is read, naming the pool size and
pointing at the completed season.

**The squad view was showing half of each squad.** It was built from
`player_metrics_neutral` — who has PLAYED — so Leyton Orient showed **16 of 33**; Aaron
Connolly, Alex Gilbert and 15 others were registered, their contracts scraped that morning,
and invisible. Impect cannot supply a squad list (it knows a player only once he appears);
Transfermarkt publishes the registered squad. Rebuilt on the scrape with appearances joined
on: **3,783 rows, exactly matching the scrape, zero duplicates.**

Two fan-outs found while rebuilding, both silently listing squad members twice: 36 players
turned out in two leagues this season, and 15 Transfermarkt ids are claimed by two of our
players. The first is deduped by minutes; the second is DROPPED rather than guessed, the
same rule `identity.drop_ambiguous_matches` applies.

**Position falls back to last season, labelled** ("Goalkeeper (last season)") where a
player has not featured — 80% filled against 38% before.

**Verified:** 882 tests pass. 11-point audit clean: row count matches the scrape exactly,
no duplicates, contracts agree with stored values, no rating without its league, no zero
ratings, export free of raw floats.

### 2026-09-10 — loans read from the squad page; Transfermarkt's loans page is incomplete

**Somto Boniface is on loan at Leyton Orient from Ipswich Town, and the platform said he
was not.** Traced to source: Transfermarkt's dedicated loans page
(`leihspielerhistorie`) listed FOUR loanees for Leyton Orient and omitted him. The SQUAD
page carries the loan explicitly, as a title on a club link inside the player cell:
`On loan from Ipswich Town until 31/05/2027`.

`transfermarkt_loans` now reads the SQUAD page — already fetched for every club to get
contracts, so it costs no extra requests — and unions the loans page for the few it adds.
**398 loans across 114 clubs (was 392/112), 100% with parent club and end date, 293 linked
to one of our players.** Parsed by matching the phrase in the title attribute, never by
cell position.

**His height is genuinely absent, from every source.** Impect ships NO height column at
all: the `_CM` columns in the feed are "Centre Midfield" packing zones, not centimetres.
The Impect WEB PLATFORM shows height that the licensed `getPlayerIterationAverages`
endpoint does not — worth asking Impect whether another endpoint carries it. Transfermarkt
has no height for him either, in the live scrape or the static dump. Squad-scrape height
coverage overall is 82%.

**Verified:** 891 tests pass. Squad view: 3,783 rows matching the scrape exactly, zero
duplicate player-club pairs, 293 loans displayed.

### 2026-09-12 — DEPLOYED to DigitalOcean; Transfermarkt cannot be scraped from a server

**Live at https://lofc-recruitment.duckdns.org** — DigitalOcean droplet (Ubuntu 24.04, 1 vCPU,
2 GB + 2 GB swap, London, $12/mo + $2.40 weekly backups), `docker-compose.prod.yml` + Caddy with
an automatic Let's Encrypt certificate. Code in `/opt/lofc`, database restored from a `pg_dump`
(verified identical to the workstation: 11,215 scorecards, 3,783 squad rows, 12 assessments).

**TRANSFERMARKT IS BLOCKED FROM THE SERVER — this will not change.** Transfermarkt is behind
**AWS WAF Bot Control**. A datacentre IP gets HTTP **202 with a JavaScript challenge page**
(`awsWafCookieDomainList`, `gokuProps`, 2.4 KB) instead of the ~200 KB squad page the same
request returns from a home connection. A complete browser header set does not help — it changes
an empty 202 into a challenge-page 202. **Defeating it was declined, deliberately:** it requires
executing their JS to mint a WAF token, which is circumventing bot protection, not a parsing fix.

Handled with `SKIP_TRANSFERMARKT_SCRAPE` (`config.skip_transfermarkt_scrape`), set true on the
server only. It omits `ingest.transfermarkt_efl` and `ingest.transfermarkt_loans` — **without it
the pipeline halts there and scoring, scorecards and shortlists never run.** The LOADERS
(`store.squads`, `store.injuries`) deliberately still run, so a scrape pushed from a workstation
is still ingested. **Operating model: the three Transfermarkt scrapes run on a workstation**, the
CSVs are rsynced to the server, and the loaders pick them up. Registration data moves at transfer
windows, not weekly, so this is adequate rather than a compromise.

**StatsBomb dropped from the pipeline under `impect_only`** (the pipeline half of R4).
`ingest.run`, `aggregate.run` and `store.load` only rebuild `player_season_metrics` from 21 GB of
raw events; every league is Impect-spined under `impect_only`, all 40 composite metrics come from
Impect (32) + SkillCorner (8), and the neutral table's EFL minutes match the StatsBomb spine on
**1 row in 2,940**. Locally the stages were invisible (files present, ingest skips); on a fresh
server they would attempt **~8,900 paid API calls across 4,456 matches**, and the aggregation
raises `FileNotFoundError` without them, halting the run. The TABLE is still read (archetypes,
trajectory, methodology) and comes from the dump. Server pipeline is now **16 steps**.

**Deployment facts worth not rediscovering:**
- **`data/` on the server lives in the `appdata` Docker VOLUME, not `/opt/lofc/data`.** The `app`
  service mounts `appdata:/app/data`, so host files are invisible to it. Load with `docker cp`
  into the container, then `chown -R appuser:appuser /app/data` (the image runs as `appuser`;
  `docker cp` lands as root).
- The `dashboard` service mounts **no data at all** — it works entirely from Postgres. That is
  what the 2026-09-11 squad-scrape-into-Postgres change bought.
- Only **~400 MB** is copied to a server: the dump, `data/raw/impect`, `data/reference`,
  `data/raw/skillcorner`. Never the 21 GB of StatsBomb events.
- macOS ships rsync 2.6.9 — `--info=progress2` is unsupported, use `--progress`.

**Verified:** 961 tests pass. Dashboard live over HTTPS, login works, Players opens on 2025/26.

### 2026-10-12 to 10-15 — card, glossary and reference pages made correct and consistent

**NOT DEPLOYED.** Tests 1,401 → **1,512**. Full list in `plan/2026-10-15-STATE.md`.

**Errors found and fixed (all display, none in stored scores):**
- Card showed physical "season totals" that cannot exist (Dan Happe: top speed 995, metres per
  minute 3,459) and overstated distances (Impect minutes, SkillCorner tracks fewer). Totals now
  only where adding up makes sense (`dashboard/units.py`); value metrics keep 2 dp (0.80, was "1").
- One card showed two percentiles for the same metric (Pressures 20 and 22): "All tracked
  metrics" and Strengths/Watch-outs read the legacy `player_percentiles` table. All now read
  the scorecard percentiles — 13 shared metrics, 0 mismatches.
- Glossary showed Impect's definition of the PARENT metric ("Passes into box" = a successful
  pass) with "(scoped to …)" notes; it now shows what each metric is built from in Impect's own
  names, then Impect's definition verbatim. It also had no physical entries at all.
- Glossary definitions lived in a CSV under `data/`, which the production dashboard cannot read
  (excluded from the image, not mounted) — the live glossary very likely showed "(definition
  not in glossary pull)". Now in Postgres (`impect_definitions`, migration `c7e2a1f4d903`).
- Packing-zone labels "Box", wrong layout, my own metric list: replaced with Impect's names,
  layout from Impect's zone definitions, Impect's tab metrics and per-match unit. Verified:
  Josh Walker CF rows 22/22 against Impect's screen.
- Physical names differed between card, sliders and glossary; a slider stated an unpublished
  15 km/h threshold. One name per metric now, from the glossary.

**SkillCorner also revises finished seasons** (2025/26 since download: PL2 815 players changed,
median 3.0%; National League 607). The 30-day refresh covers it. Re-scored locally 2026-10-15:
**PL2 134 ratings moved >0.1, 45 >0.25 (max 0.86), 173 players 5+ places**; National League 27
>0.1; Scottish Championship 0 (no SkillCorner data — the expected control).

### 2026-10-02 to 10-09 — Head of Recruitment's comments: table cleanup, a physical defect, new data

**NOT DEPLOYED.** Local only, awaiting the Head of Recruitment's review. Tests 1,309 → **1,401**.

**"27% meet our benchmarks" (1,687 / 4,376) was a denominator error, not a scoring one.** 4,376 is
every player with data; 1,147 of them are under 450 minutes and carry no rating. 1,687 of 3,345
ratings = **50.4%**, 48–55% in every league and position, as the median definition requires.
The info bar invited the division, so it now names both counts:
`4,376 players · 3,229 rated (450+ mins) · 7 leagues · 2025/26 season`.

**Players table, at his request:** removed Measured %, Peers, Contract, Months left (the card
states rank, contract and months), Player type and its filter; removed "Money is off by default…"
from the caption. Added **Top speed**. The card's playing-style line and the Player types page are
hidden until P4 is rebuilt.

**PHYSICAL DEFECT — ours, fixed, changes rankings.** SkillCorner `_full_all` values are per
APPEARANCE; we stored them as per 90. Minutes per appearance explained **97%** of "distance per
match" and Physical correlated 0.43 with minutes played. Converted the 15 volume metrics with
`minutes_full_all` (`skillcorner_map.to_per90`). After re-scoring 2025/26 locally: Physical vs
minutes **0.43 → 0.00**, Performance unchanged, **2,716 of 3,345 ratings changed rank** within
their pool (1,327 by 10+). Consequences for the formula meeting: the report's B2 figures are
stale, and distance per 90 is now metres-per-minute × 90 (**r = 1.00**) — both in Physical.

**Metric sliders** (`dashboard/metric_filters.py`): a minimum-percentile slider per scored
Performance metric, and three raw per-90 physical sliders per position (placeholders chosen from
positional demand, pending his list). A slider at its floor filters nobody (verified, 21 sliders).

**Sidebar on Squads & loans** — it applied none of the filters. Age, leagues, foot, contract and
loan now apply through one shared function (`dashboard/sidebar_filters.py`). Left foot:
3,783 → 879. Scout reports, Watchlist and Sign-off still pending a decision.

**New data, display only — never scored** (`player_detail_metrics`, migration `b4d1e7a90c21`,
2.18M rows / 473 MB locally): Impect's own scores (IMPECT, offensive, defensive + 10 more, via
`getPlayerIterationScores`, minutes-weighted across positions); Impect zones (11 packing zones)
and lanes (5) for touches, receptions, defensive actions, ball wins, duels, shots, xG, goals —
already in the landed averages, never used; receptions between the lines / out wide / in the box
/ hold-up; SkillCorner in- and out-of-possession physical (`possession=tip|otip`). On the card:
Impect score tiles, a "Where he plays" pitch map (zones or lanes, per 90 or season total,
coloured by percentile vs league-position peers), and physical by phase plus speed/agility.
Verified: lanes sum to Impect's total touches exactly; zones to 91% for outfielders because
Impect supplies no values for its GK zone (the map says "Not supplied"). The pitch is a
schematic of Impect's zone codes — **geometry to be checked against Impect's platform.**

### 2026-10-01/02 — scout reports and the scoring fixes DEPLOYED; archetype drops repaired

**Everything from the two open threads is now live on the server.** Tests 1,248 → **1,309**.

**Deployed:** the scout-reports integration (459 reports, 309 linked, 0 ambiguous, syncing
every 60 seconds by cron), the percentile fix, and the archetype fix. Server at `f7bd3bc`.

**The Refresh button was doing nothing.** It cleared Streamlit's caches and re-read the same
stored rows, so the "Synced" line never moved — a button labelled Refresh that refreshed
nothing. It now calls the same `sync()` the cron uses, so the two cannot drift. Required
mounting `secrets/` into the DASHBOARD service as well as `app`, and rebuilding its image —
`--force-recreate` recreates from the EXISTING image and does not rebuild.

**ARCHETYPE DROPS DID NOTHING — a real defect, found while building a metrics spreadsheet.**
`performance_metrics_for_archetype` dropped metrics by the CLUB's name for them. Two club
entries can resolve through `CLUB_SUCCESSOR` to the same stored metric, so dropping one left
the twin in place and the measurement survived.

| Archetype | Configured | Actually dropped |
|---|---|---|
| **Winger / Crossing & Creative Threat** | 1 | **0 — inert** |
| Full Back / Attacking | 3 | 2 |

**Winger / "Crossing & Creative Threat" scored all 415 wingers IDENTICALLY to "All Metrics"**
— offered in the interface, stored in the database, and incapable of changing a number.
Fixed by matching drops on the RESOLVED metric. Verified after re-scoring: `All Metrics`
changed for **0 of 7,607** rows, so the ranking is untouched; only the two broken archetype
views moved. Guarded by `tests/test_archetype_drops_take_effect.py` (14), which fails if any
archetype's resolved list equals the full list.

**Delivered to the Head of Recruitment and the Director of Football:**
`How Players Are Scored` (17-page PDF) and `Scoring Metrics by Position` (xlsx, one sheet per
position). Both generated, neither committed — `*.pdf` and `*.xlsx` are now gitignored.

**Three errors in the first draft of the report, all mine, corrected before sending:**
"13 requested metrics" (actually 5 pairs across 18 slots); "lowering Physical to 30% only
reaches 55%" (actually **42%** — estimated, never computed, and it reversed the
recommendation); and "percentiles averaged 3.03" (percentiles averaged 50.8; 3.03 is the band).

**Next:** work through the Head of Recruitment's comments on the report. See
`plan/2026-10-02-STATE.md`.

### 2026-09-30 — percentile scale centred; every peer pool now averages exactly 3.00

**A real defect in the scoring engine, found while preparing the scoring report for the
Head of Recruitment. Fixed, not reported to him — it carries no football judgement.**

`metric_percentiles` used pandas `rank(pct=True)`, which returns **rank / n** with ranks
running 1..n. The percentile scale therefore ran `100/n .. 100` and its mean was
**50 + 50/n — never 50**. Through the club's band formula that lifted every rating, and by
MORE in a small pool:

| pool size | mean band before | after |
|---|---|---|
| 6 | 3.333 | **3.000** |
| 20 | 3.100 | **3.000** |
| 116 | 3.017 | **3.000** |
| 300 | 3.007 | **3.000** |

Measured on 25/26 before the fix: **pools under 30 players averaged 3.14 against 3.01 for
pools of 100+**, with pool size correlating **−0.725** with mean rating. A Scottish
Championship central midfielder (6 in the pool) was scored a third of a band above a League
Two centre back for no footballing reason. That matters because **3.00 is the club's Minimum
Standard, defined as the league median** — a pool whose median player scores 3.30 has moved
the bar the whole framework is anchored on.

**The fix** is the standard mid-rank convention, `(rank − 0.5) / n`.

**A second defect was introduced and caught during the fix.** The first attempt divided by
the POOL size (`transform("size")`) rather than the number of players holding that metric
(`transform("count")`). Physical metrics are absent for 318 outfielders and every
goalkeeper, so this is the ordinary case, not an edge one: four players inside a pool of ten
came out at 5/15/25/35 instead of 12.5/37.5/62.5/87.5 — a band of 1.0 for all four. Caught
by a test written for exactly that case before the code was trusted.

**Verified after re-running `scorecard_run`:**

| | |
|---|---|
| Pools where every player has both dimensions | **14 of 14 average exactly 3.00** |
| Pools where no player has physical | **14 of 14 average exactly 3.00** |
| Mixed pools (some missing physical) | 17 of 28 — residual is the 57/43-vs-100/0 weighting difference, a decision for the club, not a bug |
| Overall mean, 25/26 | 3.0294 → **2.9972** |
| Ratings moving more than 0.1 | 112 of 3,345 |
| **Players whose rank changed within their pool** | **660 of 3,345 (20%), biggest move 4 places** |

Tests 1,226 → **1,248** (`tests/test_percentile_centring.py`, 22).

**Live anchors updated** — CLAUDE.md, the P17 plan's verification query, and register P13's
"every league averages ~3.03" (now 3.00). Historical work-log entries and the frozen
`docs/superpowers/` plans were deliberately NOT rewritten: they record what was true then.

### 2026-09-28 — scout reports: the club's scouting sheet read into the platform

**Phase 1 of the scouting integration, data layer and interface. Read-only throughout.**

Six club scouts file match reports through a JotForm form; JotForm writes them into a
Google Sheet the Head of Recruitment curates across 11 tabs. The platform now READS that
sheet every 60 seconds and joins the reports to its own players, scores, contracts and
injuries — the join that was impossible while the data lived in a spreadsheet.

**Read-only is enforced twice, and neither layer depends on our code.** The service-account
token carries only `spreadsheets.readonly`, and the account is a Viewer on the file.
Verified by attempting a write: Google answered **HTTP 403, "Request had insufficient
authentication scopes"**.

| | |
|---|---|
| Reports stored | **437** from 6 scouts, 350 players |
| Linked to a platform player | **289** (244 distinct), **0 ambiguous** |
| Unlinked — outside our seven leagues | 129, shown in full without a rating |
| Placeholder (`"A New Player"`, 19 rows) | never linked |
| Tests | 1,033 → **1,195** |

**Identity is matched on name + DATE OF BIRTH**, the rule `model/identity.py` already trusts.
Measured: name-only links 279 of 350 **but leaves 13 names claimed by two of our players**;
name+DOB links 200 with zero ambiguity. Dates of birth come from the sheet's own
`Player Names` tab — without that tab this integration would not have been safe to build.

**Three hazards found and pinned by tests:**
- **33% of fixture dates would have been silently wrong.** `Fixture Date` is DD-MM-YYYY;
  pandas defaults to month-first and mis-parses **143 of 437** without raising — Joe Lewis's
  10 February report would have read as 2 October.
- **The Sheets API returns RAGGED ROWS** — `Player Names` sends a 9-column header and 4,598
  rows of 6 columns. A naive `DataFrame(rows, columns=header)` raises outright.
- **`Database` is a byte-identical copy of `Form responses`** (`DataFrame.equals` → True).
  Reading both would double every report. `Teams Watched` is a pivot of `Fixtures Schedule`
  whose stored numbers are **already stale for 21 of 156 clubs** — computed, never imported.

**New:** `ingest/scout_sheets.py` · `ingest/scout_reports.py` · `ingest/scout_lookup.py` ·
`store/scout_reports.py` · `model/scout_report_link.py` · `dashboard/tabs/scout_reports.py` ·
migration `7fce0dc9323f` (3 tables) · `scripts/scout_sync.sh`.

**The interface.** A "Scout reports" page under Scouting, with three views — all reports
(six filters), **where we disagree**, and scout activity. Plus a "Scout reports" section on
the player profile, silent when there are none. `scout_sync` is the first table in the
platform that can state its own freshness, and the page says *"the sync is not updating"*
rather than printing a timestamp the reader has to evaluate — register P14 in miniature.

**The output that justifies it.** Of 54 reports saying "Sign", 22 are on players we can
score: 6 the model also rates highly, **18 reports where the model points the other way**.
Alfie Gilchrist — scout grade B, "Sign"; composite **1.74**. Those are the conversations
nothing surfaced before. *Caveat carried on screen: the composite is 25/26 and the fixtures
are 26/27.*

**Nothing here touches a score.** `objective_composite` is unchanged.

**Presented to the Head of Recruitment the same day; feedback applied immediately.** Now
reading the LIVE sheet (shared with the service account, 11 tabs, same 437 reports). The
report detail was rebuilt as a card -- `st.text_area(disabled=True)` renders grey text on a
grey field, so the scout's own words, the most valuable content on the page, were styled as
the least readable thing on it. Added: a player search, a "Fixture" column that names the
MATCH rather than showing a bare date under that heading, an "In our data / Not in our data"
filter (the second half being the discovery list), and a primary button into the player's
profile via `best_profile_target`. New **"Scouts" column on the Players page**, requested
directly: every scout who watched him said Sign -> **High priority** (23 players), they
disagreed -> **Scouts split** (11), all rejected -> Not recommended (38), otherwise Monitor
(172). Blank for the 96% nobody has watched, which is the honest state. Aggregation only --
it never touches the composite, so next week's formula change cannot break it.

**He also confirmed the model/scout conflict is fine for now** -- the composite formula is
being modified next week.

**Open:** the cron entry, and register **P21** — the platform's own watchlist (5 rows) and
scout assessments (10 rows) against this sheet's 437 reports and 223 players of interest.

### 2026-09-18 — recruiter feedback: loan filter, season labelling, and a 35% profile bug

**A loan-status filter on the Players page**, requested by the recruiters. Sidebar selector:
*Any* (default) · *On loan now* · *Loan ends within 6 months* · *Not on loan*. The horizon
option earns its place — **259 of 293 linked loans run to summer 2027 and only 30 end within
four months**, so a flat on-loan filter buries the players who are actually gettable. Same
reasoning as `contract_mask`, which asks WHEN a contract ends rather than whether one exists.

**Loans are current-season; the Players page shows one selected season.** Filtering therefore
paired a current fact with a previous season's club: measured, **208 of 221 rows named a club
the player had already left**, because the loan is usually what moved him. Ben Brereton Díaz
read "Derby County" (his 2025/26 club) while on loan at Sheffield United from Southampton — all
three facts correct, the row simply silent about where he is. Fixed with an **"On loan at"**
column, shown only when the filter is engaged, carrying the current club and the owner from the
SAME loan row (latest end date, never mixed across two loans).

**A blank-profile bug affecting 35% of squad members — found by one random click.**
`squads.py` carried THIS season's `competition_id` with LAST season's `season_id`, a pair that
often matched no row at all. Phillip Chinedu, at Leyton Orient in 2026/27, resolved to League
One 2025/26 where he has 14 minutes and no rating, so nothing rendered. **Measured: 807 of
2,293 squad players with a rating opened blank.** It hits any player who changed league over
the summer — most of a 2026/27 squad, and exactly the cohort a recruiter cares about.
`best_profile_target` now picks his most recent season WITH a rating and, within it, the league
he played most minutes in — chosen FROM the rows he has rather than constructed from two. No
rating anywhere shows a message instead of an empty page. **Predates the loan work.**

**Age was measured against a FUTURE date for the live season.** `SEASON_REF_DATE[319]` is
2027-01-01, so every 2026/27 player read up to a year too old — Leon Chambers-Parillon showed
25.2 against an actual 24.9 (born 2001-11-05; Transfermarkt says 24). Age is a recruitment
FILTER, so an inflated age pushes a player past a maximum-age threshold he has not reached.
`seasons.age_reference_date` now uses the fixed midpoint for a COMPLETED season (he WAS 24.2
while producing those numbers) and TODAY for the live one. `report/data.py::_age` had a dead
`if False` branch and always used `now()`, so the report and the dashboard disagreed on every
completed season; both now share one function.

**Season labelling — the UX principle this session established.** Every number now states its
own season in a LABEL, not a caption:
- `Composite` → **`Composite · 2025/26`**. It sat directly beneath "Current form — 2026/27" and
  read as a current-season figure; the caption there made it worse by saying "not a rating"
  immediately above a rating.
- The season-output tiles gained **"Season output — 2025/26"**. Two identical sets of
  Goals/Assists/Minutes tiles sat adjacent with only the lower one labelled.
- **Three captions removed**, plus the now-dead `current_form_caption` and its tests.

> **The principle, for future work: a fact belongs in a LABEL or a COLUMN, never in a
> paragraph. Wherever a caption exists to explain an adjacency, the adjacency is the defect.**
> Two hard-coded captions on this page had already gone stale and were contradicting the data
> beside them. A label built from the data cannot. **The Players page still carries ~15
> captions worth auditing on this basis.**

**Also landed:** an **Assessed** column on the ranked list (display only — no reorder, no score
touched); each season's **Score** on the player card's season-by-season table, joined on player
AND league AND season so a loanee's two rows keep their own numbers; a **Position filter** and a
gated **"This season"** rating column on Squads & loans.

**No season-on-season trend or delta is computed, deliberately.** Measured: of 2,184 players
scored in both complete seasons, the mean absolute change is **0.49 for players who never
changed league**, against a population SD of 0.58. A ~0.85 SD swing is the normal amount of
movement, so an "improved/declined" verdict would fire on nearly everyone. Two complete seasons
is a line, not a curve. Worth revisiting at four or five. Pinned by a test.

**Two join-key bugs caught by the display-contract tests**, both the same shape — a key the
source frame does not carry: `load_trajectory` did not SELECT `competition_id`, and the squad
frame carries no `season_id` at all (it is a registered-squad list, not appearances). Both now
pinned.

**The loan scrape was writing to a season key nothing reads.** `transfermarkt_loans.py`'s
`--season-id` defaulted to the TRANSFERMARKT season label (**2026**) rather than the platform's
(**319**), so three consecutive runs wrote 411 fresh loans under `season_id = 2026` while every
reader filtered on 319 and saw the 10 September data. It looked like the scrape was failing
silently; it was succeeding into the wrong place. `resolve_season_id()` now defaults to
`settings.live_season_id` and **raises rather than guessing** when none is configured — guessing
is how this happened. **This is the SECOND bug of this exact shape**: on 2026-09-07 the loader
DELETEd 319 while INSERTing 2026, which that fix corrected without fixing this default.
**Lesson, and it is in the test docstring: check loan data by GROUPING on season, never by
filtering to one — a wrong-key write is invisible to a filtered query.** Orphaned 2026 rows
deleted on both machines. Loans now: **411 scraped 18 Sep, 303 linked** (was 398 / 10 Sep / 293).

**Deployment changes made the same day:** the GitHub repository became **PRIVATE**, which broke
`deploy.sh` at the pull (HTTPS password auth is not supported) — resolved with a **read-only
deploy key** and the remote switched to SSH (register P16, DEPLOY.md §4). And **production now
runs `main`**: the old deployed branch `r3a0-injury-scrape` was 22 commits ahead and 0 behind, so
`main` was a trap for anyone cloning it. Fast-forward merged; the server tracks `main`.

**Verified: 1,033 tests pass.**

**Verified:** 1,028 tests pass (was 965) before the loan-scrape fix below. `objective_composite` unchanged for Defensive Mid
(3.0175) and Attacking Mid (3.0546).

### 2026-09-13 — midfield archetypes resolved; Central Mid gets the club's Box to Box list

**The problem.** `Impect Data - Positional Metrics.xlsx` describes THREE midfielder types on its
**MF tab** (Defensive, Box to Box, Attacking) but gives metric NAMES for only TWO on its **Input
tab** ("Centre Midfield", "Attacking Midfield"). One role therefore had no metric list, and the
platform — which carries three midfield groups, because that is Impect's taxonomy — gave
`Defensive Mid` and `Central Mid` the same 17 metrics. **667 players in 25/26** were scored on a
profile written for one role, with nothing on screen saying so.

**Why the two tabs cannot simply be merged.** The MF tab is capability PROSE, not metrics:
*"Ability to play passes / keep the ball, with and without pressure"*, *"Ability to press in a
mid-block"*. Nothing there is computable. Only the Input tab drives a score.

**The resolution.** The Input tab's "Centre Midfield" row is read as the **DEFENSIVE
midfielder's** list. The label and the contents disagree — the name suggests the box-to-box role
(the 6/8/10 convention) — but the row carries `Aerial Win%` and `PAdj Tackles & Interceptions` and
carries **no** Shots, Dribbles, box touches or crosses, and the MF tab names exactly those four as
what separates Box to Box from Defensive. Reading it as box-to-box would mean the club omitted
every defining attribute of that role while including two defensive ones.

**Matching on the label was considered and rejected** on a practical ground, not a stylistic one:
it leaves `Defensive Mid` and `Central Mid` identical anyway, because that row contains nothing
attacking to strip out. Only one reading actually separates the two groups.

**`Central Mid` therefore becomes the missing Box to Box list** — the defensive metrics plus the
four capabilities the MF tab grants Box to Box and withholds from Defensive:
`shots_p90`, `dribbles_p90`, `dribble_success_pct`, `touches_in_box_p90`,
`successful_box_cross_pct`. **Every one is lifted from the club's own Attacking Midfield row.
Nothing is invented and nothing new is sourced** — which is the whole point, and the line the
retired Style-fit crossed.

**Aerial duels KEPT.** The MF tab lists "Defend aerial duels" for Defensive and Attacking but not
for Box to Box. One omission in a prose list was judged weak evidence against the same tab's
"defend in a low block" and "win 2nd balls", both of which involve contesting aerial balls.
**This is the one judgement call in the mapping**, decided by the owner under delegated authority
from the club, and pinned by a test so it cannot change silently.

**Measured impact:**

| Group | Metrics | Players (25/26) | Re-scored | Average |
|---|---|---|---|---|
| Defensive Mid | 17 (unchanged) | 565 | **0** | 3.0175 → 3.0175 |
| **Central Mid** | **17 → 22** | 102 | **99** | 3.1223 → **3.1252** |
| Attacking Mid | 24 (unchanged) | 236 | **0** | 3.0546 → 3.0546 |

197 of 6,951 scorecards changed platform-wide; largest single move **0.29** (Kyle Turner,
Partick Thistle, 3.26 → 3.55). The average barely moves because a composite is a percentile
within the same pool — adding metrics reshuffles the order rather than inflating it.

**Verified:** 972 tests pass (was 965). Reasoning recorded in `model/club_framework.py` and
`tests/test_midfield_archetypes.py`, not just the outcome.

**Still open on midfield:** nothing. Box-to-Box has no capability of its own in the club's file —
27 of its 36 lines are shared by all three archetypes and every remainder appears in Defensive or
Attacking — so there is no fourth list to build.

## 📋 OPEN TASKS — Head of Recruitment review (started 2026-10-02) — keep this list current

**Decision rule:** I bring every decision to the owner with options and a recommendation. The
owner decides, or batches the football-judgement ones into ONE short list for the Head of
Recruitment. Nothing is assumed. Nothing here is deployed yet.

### Done (local, not deployed)
Info bar counts · Players table cleanup (6 columns out, Top speed in) · metric sliders ·
physical per-90 defect fixed + re-scored · Squads & loans sidebar filters · Impect scores
(offensive/defensive + per position) · packing-zones map (Impect names/layout/units; Josh Walker
CF rows 22/22) · physical in/out of possession · finished seasons refresh monthly · Impect
revisions pulled + re-scored (Scottish Championship 25/26 materially changed) · glossary HTML
fixed, StatsBomb lineage removed · Methodology hidden (flag `SHOW_METHODOLOGY`) · Player type
hidden · profiles spreadsheet deleted by the owner (superseded by the profiles conversation).

### Open — before the Head of Recruitment meeting (owner sets the priority; updated after every task)

**Owner's priority (2026-10-12):** 1 Scout reports: own page filters (NOT the sidebar) → 2 Table: no
sideways scrolling + cleaner look → 3 Reference page → 4 Player card: merge duplicated physical
sections. Proposals for 1 and 2 sent to the owner; build after approval.
**Meeting question added:** "add metrics for each position" = extra table columns, which conflicts
with "no sideways scrolling" in the same sentence — ask what he means. Not built.
| Task | Status |
|---|---|
| Shared droplet safeguards (colleague has docker = root): `.env` chmod 600 · DO backups weekly→daily · nightly pg_dump of our DB (`scripts/db_backup.sh`, 14 kept, verified, count-based retention) · his containers get `mem_limit` · written rule | `.env` **done 2026-10-16**; db_backup built + tested 2026-10-16 (restore to scratch DB: 28/28 tables identical) — **deployed 31ad876, cron 19:30 UTC installed, first dump 63 MB**; DO backups **daily** (owner); his `mem_limit` + rule message pending |
| Glossary: content for every metric shown (physical, packing zones, receptions, Impect scores) | **Done 2026-10-11** — tests pass |
| Glossary: definitions stored in Postgres (prod dashboard cannot read data/; live glossary likely shows "(definition not in glossary pull)") | **Done locally 2026-10-11** — owner to confirm the live symptom |
| Glossary page: complete content on screen (was 45 Impect only) — 4 tabs, search, compact rows, "In rating" tag on the 40 scored metrics | **Built 2026-10-15** — 98 entries, 40 tagged, 0 scored metrics missing; browser check pending |
| Packing-zones hover did not appear (owner) — pitch now in its own frame with a custom tooltip (hover + tap) | **Built 2026-10-15** — hover test page published; browser check on the card pending |
| Table: metrics per position | **Not built — meeting question** (extra columns conflict with "no sideways scrolling") |
| Reference page "What goes into each rating" | **Built 2026-10-12** — from the scoring code; Impect rows in Impect's own names; 21 tests; browser check pending |
| Glossary: Impect's own wording only (owner 2026-10-12) — "Built from (Impect)" + Impect definitions verbatim; "(scoped to…)" noise removed | **Built 2026-10-12** — browser check pending |
| Player card: ONE Physical section (in rating ✓, all phases, in/out of possession, percentile, band) | **Built 2026-10-12** — Dan Happe's 8 rated physical percentiles identical to the old table; browser check pending |
| Season totals only where they make sense (dashboard/units.py): none for speeds, rates, ratios, physical; value metrics to 2 dp | **Built 2026-10-12** — Dan Happe: 8/8 Impect totals = raw; PxT totals 0.43 / 0.80 (were "0" / "1") |
| One percentile per metric on the card: "All tracked metrics" + Strengths/Watch-outs now read the scorecard percentiles (were the legacy table: Pressures 20 vs 22 etc.) | **Built 2026-10-12** — 13 shared metrics, 0 mismatches |
| One name per physical metric across card, sliders, glossary, reference page; unpublished "15–20 km/h" removed from slider labels | **Built 2026-10-12** |
| Card: "Performance — in the rating" + "Physical — in the rating" (8) + "Other physical metrics" — which physical metrics count is now in the headings (owner 2026-10-15) | **Built 2026-10-15** |
| Cron verified on the server 2026-10-15: Mondays 04:15 UTC; last success 2026-10-12 04:20; no failure marker. Stale "not installed" header in weekly_refresh.sh corrected | Done |
| "Top speed" = average of the 5 fastest matches (SkillCorner psv99_top5), per the Head of Recruitment. Was the ALL-match average (psv99) — verified on Onyedinma's 43 match rows (30.84 all-match vs 33.34 top 5 vs 34.60 max). Table, sliders, card, glossary relabelled | **Built 2026-10-16** — display only |
| DECISION (formula meeting): the Physical rating scores BOTH psv99 and psv99_top5; he does not want the all-match average — drop it from scoring? | Open — moves ratings |
| DECISION for owner: metres per minute in/out of possession (125 / 149) exceed the all-phases figure (100) — correct (rate within each phase) but may confuse | Recommended: show "—" for its possession split |
| Packing-zones pitch: larger, pitch markings, club-threshold colours (green ≥70th / grey / red <30th), percentile on hover, legend chips; "no percentile" (under 450 min) shown white + dashed, not grey | **Built 2026-10-15** (owner approved the design) — real output checked: Josh Walker 11/11 zones with percentiles; Tom Blackwell (447 min) 11/11 "no percentile" + chip |
| Players table: page cap removed, "Mins", column widths, ratings coloured by club thresholds; League kept separate; Assessed hidden | **Built 2026-10-12** — browser check pending |
| Player card: Performance-profile bars coloured green ≥70th / grey / red <30th (club thresholds) | **Built 2026-10-12** — browser check pending |
| Scout reports: own League / Max age / Foot filters | **Built 2026-10-12** — tested on real data (Left = 155 = 139 left + 16 both); browser check pending |
| SkillCorner finished seasons: check for revisions | **Done 2026-10-15** — revised (PL2 most); refreshed + re-scored locally; server refreshes on deploy rebuild |
| Browser check | **Done headlessly 2026-10-15** (Streamlit AppTest: glossary, reference, card for 3 players incl. one under 450 min, scout reports — 0 exceptions). Chrome extension disconnected: owner to eyeball |
| Documentation (work log, STATE, CLAUDE.md) | **Done 2026-10-15** — `plan/2026-10-15-STATE.md` |
| Commit + deploy (owner runs the commands) | Open — owner's call whether he sees it live |
| Timing "maximum" sliders | Blocked on his slider list |

### Open — needs a decision (owner first; Head of Recruitment only where football judgement)
| # | Decision |
|---|---|
| 9 | Profiles: his definitions + 1–2 example players per style (24 styles) |
| 10 | His physical sliders per position (3 each, currently placeholders) |
| 11 | Archetype vs profile: A keep both renamed / B merge / C drop archetypes |
| 12 | "Individual threat score": which Impect score (likely PxT) |
| 12b | Table: "add metrics for each position or profile type" — columns by POSITION or by PROFILE? (his words; reading unconfirmed) |
| 14 | Formula meeting: B1–B5, per-90 fix, distance double-count — **last** |

### Open — external
| # | Task |
|---|---|
| 15 | Impect question document (owner sends): BALL_WIN_NUMBER equals DEFENSIVE_TOUCHES for 80–98% of rows |

### Server facts verified 2026-10-16 (feed the pipeline audit)
1 vCPU, 1.9 GB RAM (~970 MB available at rest), 2 GB swap; disk 48 GB — 60% used 2026-10-15,
**66% on 2026-10-16** (growing: likely dangling Docker images from deploys + unlimited container
logs — no /etc/docker/daemon.json). Docker enabled on boot; all services unless-stopped. ufw
INACTIVE; listening only 22/80/443 (Postgres not exposed); DigitalOcean Cloud Firewall unchecked.
DigitalOcean metrics agent present (/opt/digitalocean). No backups (P20).
A colleague's platform may share this droplet: recommended resize to ≥2 vCPU / 4 GB first, our
Caddy routes their subdomain (they must not bind 80/443), their own compose project + Postgres.

### Not in this review's scope (still in the register, untouched)
P12 withdraw an assessment · P14 stale-data indicator · P18 squad positions · P19 architecture doc ·
P20 backups (DO weekly backups exist — corrected 2026-10-16) · P21 watchlist vs Players of Interest.

## 📦 Branching and deployment (changed 2026-09-18)

**Production runs `main`.** Until 2026-09-18 the deployed branch was `r3a0-injury-scrape`,
which had become the trunk in practice — 22 commits ahead of `main`, 0 behind — while `main`
sat at an August state with no Squads & loans, no player report and no peer-pool guard. Anyone
cloning `main` got a platform weeks out of date. The branch was fast-forward merged into `main`
and the server switched to it.

**The rule now:** branch for a piece of work, merge to `main`, deploy `main`. Nothing else is
deployed. The server pulls over **SSH with a read-only deploy key** (register P16) because the
repository is private.

---

## 🔁 RECURRING MANUAL TASKS (nothing automates these — they are a person's job)

The platform is deployed and refreshes itself weekly, but **two things only happen when a human
does them.** Both were established 2026-09-12; see `CLAUDE.md` for the full operating model.

| # | Task | Where | When | Why it cannot be automated |
|---|---|---|---|---|
| M1 | **Transfermarkt scrape** — `transfermarkt_efl --force`, `transfermarkt_loans`, `transfermarkt_injuries`, then rsync `data/reference/transfermarkt/` to the server and re-run the pipeline there | **Workstation only** | Before the January window; occasionally for injuries | Transfermarkt is behind **AWS WAF Bot Control** and blocks datacentre IPs (HTTP 202 + JS challenge). Bypassing it means minting a WAF token by running their JS — **declined deliberately.** The server runs `SKIP_TRANSFERMARKT_SCRAPE=true` |
| M2 | **Resync the workstation database from the server** before any local data work | Workstation | Whenever picking up local development | The server refreshes weekly and the laptop does not, so they drift. On 2026-09-12 the server already held 4,320 injury rows / 1,318 players against the laptop's 3,772 / 1,176. Reasoning about stale local numbers produces phantom "bugs" |

**What DOES run automatically** (server cron, Monday 04:15 UTC, `scripts/weekly_refresh.sh`):
Impect pull, SkillCorner pull, `build_neutral`, position shares, squad loader, scoring, archetypes,
valuation, identity, injury loader, player bio, scorecards, shortlists — 16 steps. Contract, squad,
loan and injury CONTENT only changes when M1 has been run; the loaders simply re-read whatever CSVs
were last pushed.

---

## Pending work register (nothing here is dropped)

**Player report — BUILT 2026-08-28 (register item P7).** A one-page A4-landscape scouting
report for any player in any of the eight position groups, rendered in the dashboard
(Scouting → Report) and downloadable as a self-contained HTML file that prints to a
single-page PDF via `scripts/report_to_pdf.py`. Verified: all 8 positions produce a genuine
one-page PDF. 736 tests; `objective_composite` unchanged at 3.029285 / 6,573.

- **One report, narrative optional.** Four states — no assessment (*Data only*), submitted
  (*Provisional*), signed off (*Final*), and conflicting (Decision 17 — no band shown). The
  club needs reports for fixtures it is about to attend, where no scout has assessed the
  player yet; building a separate "data report" would have duplicated the layout, the charts
  and the export, and two exports drift.
- **The narrative is written by a scout, never generated.** Three optional free-text fields
  (`summary`, `why_sign`, `considerations`) on the assessment form, migration
  `174d3fc1a80c`. Templated prose from percentiles would read as filler to a chairman and
  would repeat the mistake that retired the invented Style-fit.
- **Categories derived from the club's own per-position metrics** (`model/report_categories.py`)
  — Central Mid gets Progression, Creation, Retention, Pressing, Duels. Each is the mean of
  its members' percentiles, renormalised over those present, with lower-is-better metrics
  inverted. A test asserts every member is a metric the scoring layer actually resolves.
- **Percentiles come from `scorecard.metric_percentiles`, not `player_percentiles`.** That
  table holds only 22 legacy metrics and is missing duels, turnovers, pass value and
  counterpressures — two of the five Central Mid categories cannot be computed from it. Using
  the composite's own function means the report's percentiles and the player's bands come
  from one computation and cannot disagree.
- **Charts are hand-built inline SVG** (`report/svg.py`) — self-contained, vector, printing
  sharp, needing no JavaScript and adding no container dependency.
- **Export is HTML + print CSS, converted by headless Chromium on the host.** Whichever engine
  produces the PDF the document is the same HTML and CSS, so this is not a lower-quality path
  — it is the same document from a more capable engine, with automation deferred rather than
  fidelity. `weasyprint` would have required cairo/pango in the image for a worse CSS engine.
- **Honesty rules on the page:** every figure states its comparison set *including the peer
  count* (Central Mid in League One has only 13 rankable peers — a 92nd percentile out of 13
  and out of 117 are different claims); absent data reads as "not recorded" or "not assessed",
  never zero; colour never carries meaning alone; the stamp and the data snapshot date appear
  on the page; advisory flags name the dimension and its band.

**Deliberately NOT built, versus the supplied reference** (`docs/Samson Tovide - Data
Report.pdf`): appearances and starts (the platform holds minutes only); the availability
donut (needs squad involvement, unused-sub, suspensions — register item **P8**); parent club
versus loan club (no loan status anywhere); agency, first academy, birth place, achievements,
last international recognition (held in no ingested source); the cut-out player photograph
(no image pipeline). Where a field is absent the report says so rather than leaving a gap.


**Logged 2026-08-28 — open items from the audit session and new requests:**

| # | Item | Status |
|---|---|---|
| P1 | **Identity-split root cause unfixed.** Two provider-matching paths each mint a new `player_id` when matching fails, so one footballer gets metrics under one id and his Transfermarkt link under another. 76 pairs were merged 2026-08-25; **15 duplicate `tm_player_id` pairs remain** and the split recurs on every pipeline run. In all 15 only one half is scored, and that half holds the contract/injury data, so nothing user-visible is wrong today — but it regenerates. | Open, degrades over time |
| P2 | **One identity pair awaits a decision** — merging it would move two already-scored `player_scorecards` rows between ids. | Needs a human ruling |
| P3 | **Clustering reads the wrong table.** `model/archetypes.py` reads `player_season_metrics` (legacy, four English leagues only) instead of `player_metrics_neutral` (all seven). This — not any methodology objection — is why the Scottish leagues and PL2 have **0% archetype coverage** against 96–100% in the EFL. One-line fix. Data checked: Scottish Premiership 92% physical-complete, PL2 77%, Scottish Championship 0% (that one is a genuine gap). | Open, one line |
| P4 | **The clustering model is weak.** Every position resolves to k=2 with silhouettes 0.16–0.31, and four positions produce the same "pressing vs passing" split — one latent axis rediscovered per position, not a playing-style taxonomy. Feature set is the Performance metrics, which measure *quality*; style clustering needs tendency/proportion features normalised for volume. Only Centre Forward yields three genuinely distinct groups. | Open, needs redesign not a re-run. **2026-10-04: hidden from the UI** (table column, filter, card line, Player types page). Rebuild from the Head of Recruitment's named profiles (FB attacking/defending/inside; CB aerial/ball-playing/aggressive; DM & CM destroyer/playmaker/box-to-box; AM box-to-box/runner/pocket; W in behind/pocket/wide/1v1/creator; CF target/in behind/presser/scorer) on the Impect zone and availability data now in `player_detail_metrics`. Definitions need his sign-off. |
| P5 | **Injury panel heading is wrong for current-season spells.** The panel groups "In the scored window" vs "Earlier seasons", but the window is the last two *completed* seasons, so the 20 spells from 26/27 — the current season — are labelled "Earlier". Heading should read "Outside the scored window". | Open, small |
| P6 | **The legacy `player_season_metrics` table has now caused three separate defects** (watchlist blanks, clustering coverage, cross-table disagreement). Frozen, incomplete, still read in several places. Retiring it properly is its own task. | Open |
| P7 | **Player report feature** — a per-player report for the Head of Recruitment, chairman and manager, modelled on the supplied reference. See the spec. | Requested 2026-08-28 |
| P12 | **No way to withdraw or correct an assessment.** `store/assessments.py` has INSERT-only `save()` plus `sign_off()` and `reject()` — **no update of the prose and no delete, anywhere in the UI or CLI.** A typo, a summary written about the wrong player, or a test entry is PERMANENT and keeps rendering on the profile and on the one-page report stamped "Final". Revising means submitting a whole new assessment, with the wrong one left visible beside it forever. Found 2026-09-12 after test rows ("Testing scout summary") were discovered signed-off on a real player in production and had to be cleared by hand with SQL. **This is not what Decision 17 requires:** that decision forbids OVERWRITING someone's judgement silently, not withdrawing one's own mistake. `reject()` already proves the pattern — mark it, keep the row, stop it scoring. Proposed: a `withdraw` action available to an assessment's own AUTHOR while it is unsigned (and to a sign-off holder afterwards), setting `status='withdrawn'` with a reason; the row stays on record, attributed, and never scores. Needs a migration (status value), `resolve_bands` to ignore it, and a button on the profile. | Open — real gap, small design |
| P13 | **The platform supports CONFIRMATION better than DISCOVERY — owner's central concern, raised 2026-09-12.** *"Recruiters are using it to check players they already know, rather than let the data help them discover players."* The design currently reinforces that: the default view is ONE position at a time sorted by composite (so you must already know what you are shopping for); search is BY NAME (a player you have already thought of); the watchlist only holds players someone already chose; and there is no surface anywhere that answers "show me something I don't know". Per-match alerting (P11) would INHERIT this flaw if scoped to the watchlist — it would tell a recruiter more about players they had already picked. **Deliberately NOT designed yet.** The owner's own view is that it "will need proper planning and a few iterations of the design to get right", and a first design here is likely to be wrong. Recorded as the problem statement and the evidence, not a proposed solution. Any discovery surface must respect the platform's existing honesty rules: no cross-league ordering without a league-strength adjustment (register: every league's mean composite is 3.00 BY CONSTRUCTION), and no composite from a peer pool below `MIN_PEERS_FOR_RANKING`. | Open — the most valuable open question on the platform |
| P17 | **108 of 411 loans are invisible on Squads & loans — the data is held, the join drops it.** `squads.py:74` joins `player_loans` on `player_id` ONLY (`LEFT JOIN player_loans l ON l.player_id = n.player_id`). 303 of 411 loan rows carry a `player_id`; the other **108 carry only `tm_player_id`** — a real Transfermarkt player we hold no internal id for. The squad frame itself is built from `transfermarkt_squads`, which is **keyed on `tm_player_id`**, so joining on that key as well would recover all 108. **Verified case: Joel Catesby** — Transfermarkt shows him at Accrington Stanley on loan from Everton FC U21 until 31/05/2027; we hold that exact row in `player_loans` (`tm_player_id 1083709`, `parent_club 'Everton FC U21'`, `loan_ends 2027-05-31`) and the page renders "On loan from" **blank**. His contract DOES show (8 months left), so the row is half-populated from two different joins. **This is the class of defect recruiters notice and lose confidence over — the platform claiming nothing is there when Transfermarkt shows it plainly.** Fix: add `OR l.tm_player_id = <the squad row's tm_player_id>` to the join, or join the loans frame on `tm_player_id` first and fall back to `player_id`. | **DONE 2026-09-28** (not yet deployed) — see `plan/2026-09-28-P17-P18-squads-joins.md`. The cited line was wrong: `squads.py:74` is the fallback frame; the rendered one is `registered_squad_frame`, which filtered `WHERE player_id IS NOT NULL` before merging. `attach_loans` now prefers `player_id` and falls back to `tm_player_id`; `resolve_loan_player_ids` does the same for the Loans table and DROPS a `tm_player_id` claimed by two of our players (David Kamara, 1076889 → 445315 + 2000224875 — a plain join returned 412 rows for 411 loans). Squad frame 3,783 rows, loans attached 303 → **409**. |
| P17b | **"On loan only" silently discarded the Position filter.** Owner-reported 2026-09-28: set Position to Centre Forward on Squads, contracts and loans, click "On loan only", and every position comes back. "On loan only" does not filter the squad view — it REPLACES it with a separately built loans frame (135 linked loanees have not appeared in league data and are absent from the squad frame). League and Club were re-applied to the replacement; **Position never was**. Fixing only that would have caused a second complaint: `loans_frame` sourced position from the current season alone with no `"(last season)"` fallback, and `filter_by_position` excludes rows with no position — so the filter would have dropped 131 of 411 loanees whose position the platform knows. Both fixed together: `loan_view` re-applies all three filters, `with_last_season_position` gives the Loans table the same three position tiers as the squad table. Position present on loans 280 → **379 of 411**. | **DONE 2026-09-28** (not yet deployed) |
| P21 | **The platform's own scouting features are effectively unused, and duplicate the club's spreadsheet.** Measured 2026-09-28 across **22 registered users**: platform `watchlist` **5 rows**, `scout_assessments` **10 rows** (7 signed off, 2 rejected, 1 submitted, some of it test data). Against that, the club's JotForm/Sheet workflow holds **437 reports from 6 scouts**, filed daily, and a **223-row "Players of Interest" list**. Two distinct problems. (a) DUPLICATION — watchlist and Players of Interest answer the same question, "who are we interested in"; the spreadsheet's version is 45x bigger and is the one people maintain. (b) CONTRADICTION — an assessment scores a player-season and moves `assessed_composite`; a scout report is a per-match verdict. A player can be signed off at 4.5 and carry a "Don't sign" report, and nothing on screen says which is the club's view. **Do not delete either — FREEZE both** (stop investing) until the workflow is written down. Note `assessed_composite` is currently a scored feature fed by ten rows. Proposed ownership rule: *every piece of data has exactly one owning system; the platform owns what it COMPUTES, the scouting workflow owns what a human OBSERVED or DECIDED.* | Open — needs a written workflow, then a decision |
| P19 | **`docs/architecture.md` needs a rewrite — it is stale and teaches nothing.** Its own status block says `STATUS (2026-08-25): current` while claiming "1,771 players" for 2026/27 against the server's **3,351**. No diagrams. Organised by code MODULE, which is the right axis for maintaining a file and the wrong one for understanding a system. Rewrite structured **by flow**: topology → physical placement → pipeline DAG → data model → identity → DB-to-screen → scheduling → failure modes → an end-to-end trace of one player → a decisions-and-alternatives table. Mermaid diagrams (render on GitHub). Concept sidebars for generic ideas, marked, so the reference spine stays clean. **Do not create a second doc** — two files describing one system drift within a month. Driver: a second engineer joins the codebase w/c 2026-10-05. | Open — deferred 2026-09-28 |
| P20 | **[CORRECTED 2026-10-16: DigitalOcean weekly Backups ARE enabled on the droplet — the check below looked only at the server. Nightly pg_dump deferred by the owner.]** **NO AUTOMATED BACKUP of the production database.** Found 2026-09-28 while gathering facts for P19. `crontab -l` on the droplet holds only the Monday refresh; `/opt/lofc/backups` does not exist; DEPLOY.md:232 says "Snapshot it (or `pg_dump`) regularly" and nothing does. Every other table can be rebuilt by re-running the pipeline — **`scout_assessments` cannot.** It is human judgement, it exists in exactly one place (the `pgdata` Docker volume on one droplet), and a volume loss destroys it permanently. Fix: a nightly `pg_dump -Fc` to a second location with rotation, and a documented restore drill. | Open — found 2026-09-28 |
| P18 | **518 squad members show no position, though the scrape has one for all 3,783.** The Position column uses IMPECT's position (derived from minutes played), falling back to last season's Impect position labelled "(last season)" — 2,650 observed, 615 fallback, **518 blank**. `transfermarkt_squads.position` is populated for **100% of rows** and is never read. So a registered player who has appeared in neither season reads as position-unknown while the scrape says e.g. "Left Winger". Joel Catesby again shows the mismatch from the other side: the scrape says **Left Winger**, the page shows **Centre Forward** (Impect's, from 144 minutes). Fix: fall back to `transfermarkt_squads.position` as a third tier, labelled by source so an inferred position is never mistaken for an observed one — the same honesty rule "(last season)" already follows. **Decide first** whether Impect's minutes-based position should still win where both exist; it probably should, since it reflects where he actually played. | Open — fills 518 blanks |
| P15 | **~15 captions on the Players page assert facts that nothing re-checks.** Two have already gone stale and contradicted the data beside them: the current-form caption claimed no composite existed while one sat above it, and the ranked-list caption named 450 minutes as the only exclusion after the peer-pool gate added a second. Both are fixed; the class is not. **The principle established 2026-09-18: a fact belongs in a LABEL or a COLUMN, never in a paragraph — wherever a caption explains an adjacency, the adjacency is the defect.** A label built from the data cannot drift; a hard-coded sentence can. Worth a deliberate audit pass rather than fixing one at a time as they are noticed. | Open — UX debt |
| P16 | **The GitHub repository is now PRIVATE, which broke server deploys.** It was public when the droplet was provisioned, so `git clone`/`git pull` worked anonymously over HTTPS; after it was made private the server had no credentials and `deploy.sh` failed at the pull with "Password authentication is not supported". Resolved 2026-09-18 with a **read-only deploy key** (`/root/.ssh/id_ed25519` on the server, registered under the repo's Deploy keys, write access NOT granted) and the remote switched from HTTPS to SSH. **`DEPLOY.md` documents this now** — a rebuilt server needs the same steps or it cannot pull. | Resolved, documented |
| P14 | **STALE DATA IS INVISIBLE — no freshness date on screen, and nobody is told when a refresh fails.** Two distinct failures, both costly, logged together because both end as "the platform confidently shows old numbers". **(a) PASSIVE:** nothing on the dashboard says when the scoring data was last refreshed. Only CONTRACT dates carry an "as of" (`tabs/players.py:766` via `seasons.contract_data_date`). Verified 2026-09-12: `transfermarkt_squads.scraped_at`, `player_loans.scraped_at` and `player_injuries.created_at` all exist — so the MANUALLY refreshed data can report its age — while `player_metrics_neutral` and `player_scorecards`, which every score is built on and which refresh WEEKLY AND AUTOMATICALLY, carry **no timestamp at all**. **(b) ACTIVE:** `scripts/weekly_refresh.sh` writes `data/ops/last_failure` on failure and **nothing reads it**. A failed Monday cron leaves the dashboard serving last week's data, looking entirely normal. **This has already happened once:** on 2026-09-07 the 26/27 Impect data was three weeks stale while every figure computed from it was correct, and it was caught only because the Head of Recruitment noticed League One clubs had played five matches while the platform showed one — on a laptop, where someone at least knew when they last ran it. On a self-running server nobody holds that mental model. **Fix needs a decision, not just code:** one "last refreshed" date would itself be misleading, because Impect/SkillCorner now refresh weekly and automatically while Transfermarkt refreshes only when a human scrapes (M1) — so the date must be PER SOURCE. Impect/SkillCorner have no timestamp to read, so this needs a `pipeline_runs` record (stage, finished_at, rows) written by the pipeline. **Do before January**: that is when it matters most and when it will be watched least. | Open — do before the January window |
| P11 | **Per-MATCH performance and physical tracking** (owner-flagged 2026-09-12 as "a big and important step"). Everything today is SEASON-AGGREGATED: Impect via `getPlayerIterationAverages`, SkillCorner via `get_physical(group_by="player")` — "one row per player already aggregated to the season". A season average is a LAGGING signal by construction: one exceptional match barely moves it, so it cannot answer "what changed this week", which is what watchlist alerting needs ("he hit a new top speed on Saturday", "three goals in two games"). **Both providers already expose the per-match layer under the current licences — verified 2026-09-12:** Impect `getPlayerMatchsums` / `getPlayerMatchScores` / `getMatches`; SkillCorner `get_physical` accepts a match-level `group_by` (and `get_match_*` endpoints exist). So this is a BUILD, not a licence or data-availability question. Needs: new tables at player×match grain, an ingest stage per provider, and a decision on retention/pull-time (one row per player per match rather than per season is a large multiple of today's volume — size it before building). **Scoring must not read it**: the composite is a season-level percentile and adding match noise would change what it measures. | Open — needs its own design |
| P9 | **Transfermarkt scrape is workstation-only** — AWS WAF blocks datacentre IPs (2026-09-12). The server runs with `SKIP_TRANSFERMARKT_SCRAPE=true`; the three scrapes must be run locally and the CSVs pushed. Not fixable by engineering, and deliberately not bypassed. | Permanent constraint |
| P10 | **`store/load.py` has an unguarded `DELETE`** of `player_season_metrics` with no volume guard, unlike `store/injuries.py` and `store/squads.py`. Unreachable under `impect_only`, but fires if anyone runs `python -m lofc.store.load` by hand. | Open, small |
| P8 | **Availability report** (per the supplied Kabia reference) — games available, squad involvement, apps/starts/sub/unused-sub, injured, suspended, not-in-squad. **Not currently possible**: the platform holds injury spells and minutes but no squad-involvement, suspension or appearance breakdown. Needs a Transfermarkt appearance scrape, previously assessed as brittle. | Blocked on new data |


**Gaps recorded honestly ahead of real staff access (2026-08-24) — none of these block
using the platform, but recruitment staff and whoever signs off deployment should see them
stated plainly, not discovered:**

| # | Gap | Detail |
|---|---|---|
| G1 | **Deployment has not happened.** | The platform has only ever run locally via `docker compose up`. A hosting-requirements document exists (`data/exports/LOFC_Platform_Hosting_Requirements.pdf`) but is gitignored, not in the repo, and not yet acted on. The platform needs to be reachable from anywhere, i.e. a public HTTPS endpoint — `DEPLOY.md` sketches a Caddy-based setup, but nobody has stood one up |
| G2 | ✅ **RESOLVED (merged to `main`).** | `r3a0-injury-scrape` was merged into `main`; both are level at `1dcba41` with nothing unpushed. `main`'s `app.py` now carries the same login gate (`require_login`, checked before `st.navigation(...)` is even constructed) as the branch did — verified directly against `main`. The earlier risk (anything deployed straight from `main` would have been unauthenticated) no longer applies; a deployer cloning `main` today gets the authenticated app. **Still open, separately:** no public endpoint actually exists yet — see G1 |
| G3 | **No real scout has used the platform end to end yet.** | **Updated 2026-08-25:** `scout_assessments` now holds 2 rows (one signed-off, one rejected Psychological entry, same author) rather than 0, but `assessed_composite` is still NULL for every player — neither entry has a paired Medical score, so weight coverage never clears the threshold. Still true: every check beyond those 2 rows has been automated tests and scripted browser walkthroughs (Streamlit's `AppTest`), not sustained use by recruitment staff. Treat the interface as effectively unvalidated by its actual users until that happens |
| G4 | **15 `tm_player_id` values are each claimed by two different `players` rows on this database.** | Found 2026-08-25 while checking the "76 split identities merged" / "3 shared Transfermarkt ids cleared" claims (register row R11). Contract/foot/height totals matched the reported merge exactly, so the merge itself is credible, but there is no merge log or canonical-id column to say whether these 15 pairs are the *expected*, harmless result of a no-delete merge (both rows legitimately pointing at one real person) or genuine unresolved duplicates like the ones R7 fixed by hand. Needs a human with Transfermarkt access to check, the same way R7 was resolved |
| G5 | **The weekly-refresh scheduler exists but is not installed anywhere.** | `scripts/weekly_refresh.sh` (locking, rotated logs, success/failure markers) and `scripts/test_weekly_refresh.sh` are written and documented (`cli_commands.txt`, `DEPLOY.md`), but the crontab line that would actually run it has not been added to any server — there is no server yet (see G1). Refresh is still manual (S1 below) until deployment happens |

Two further gaps already tracked below, restated here for visibility: **no loan status is
captured anywhere** (R3a-gap1 — a loanee's parent-club contract is not the club he is playing
for, and no table models the distinction), and **Transfermarkt contract-date coverage is thin
outside the top three English tiers** — roughly 55% in the Championship/League One/League
Two, 28% in the National League, 2–5% in the Scottish leagues and Premier League 2 (see the
2026-08-14 note above and R6 below); Transfermarkt is the only source, so extending the squad
scrape to the Scottish leagues and PL2 is the only fix.

**Blocked on an outside party — recheck, do not forget:**

| # | Item | Blocked by | What to do when unblocked |
|---|---|---|---|
| B1 | ✅ **DONE (11 Aug 2026)** — recovery scrape completed; contract/foot/height data restored | — (resolved) | Database now holds 1,363 contract dates, 1,606 feet, 1,635 heights (was 20 / 23 / 24 immediately after the incident). Full incident record and recovery outcome directly below. |
| B2 | ✅ **DONE (2026-09-13) — Central Mid now uses the club's Box to Box metric list.** The workbook describes THREE midfielder types on its MF tab (Defensive, Box to Box, Attacking) but gives metric NAMES for only TWO on its Input tab ("Centre Midfield", "Attacking Midfield"), so `Defensive Mid` and `Central Mid` shared one 17-metric list — 667 players in 25/26 scored on a profile written for one role. **Resolved by reading the Input tab's "Centre Midfield" row as the DEFENSIVE midfielder**: it carries `Aerial Win%` and `PAdj Tackles & Interceptions` and carries NO Shots, Dribbles, box touches or crosses, and the MF tab names exactly those four as what separates Box to Box from Defensive. Matching on the label instead was considered and rejected — it leaves the two groups identical anyway, because that row contains nothing attacking to remove. `Central Mid` became the missing Box to Box list: the same metrics **plus** `shots_p90`, `dribbles_p90`, `dribble_success_pct`, `touches_in_box_p90`, `successful_box_cross_pct` — every one lifted from the club's own Attacking Midfield row, none invented. **Aerial duels KEPT** against the MF tab's omission for Box to Box (the same tab has him defending a low block and winning second balls); the one judgement call, pinned by a test. Decided by the owner under delegated authority from the club. **Measured:** `Defensive Mid` (17 metrics) and `Attacking Mid` (24) byte-identical, 0 players moved; `Central Mid` 17 → 22 metrics, 99 of 102 players re-scored, position average 3.1223 → 3.1252, largest single move 0.29; 197 of 6,951 scorecards changed platform-wide. 972 tests pass. See `tests/test_midfield_archetypes.py` for the reasoning. | — (resolved) | — |
| B3 | **Real financial models** | needs the club's real wage framework CSV | drop-in replaces the modelled wage grid; makes the money layer decision-grade |

**B1 incident — contract/foot/height data destroyed, 11 Aug 2026 — RESOLVED, recovered the same day:**

- **Cause:** the 11 Aug scrape ran `transfermarkt_efl --force` against a **stale hard-coded
  season** (`TM_SEASON = 2025`). That season had already ended, so Transfermarkt served the squad
  page as *history* — a page layout that replaces the `Contract` column with `Current club` and
  shifts every later column one position right. The parser read fields by **fixed cell position**
  rather than by column header, so it silently produced **blanks** for `contract_until`, `foot`
  and `height_cm` on all 4,014 rows scraped — and still printed a success line, because nothing
  checked fill rate at the time. `identity.py` and `valuation.py` then wrote those blanks straight
  over the database (there was no COALESCE protection on those writers at the time).
- **Effect:** **1,381 contract expiry dates were destroyed**, along with `foot` and `height_cm`,
  dropping the database to **20** contract dates, **23** feet and **24** heights against 5,626
  players. Market values were unaffected (**2,526** present), because that field is located by
  CSS selector rather than by cell position.
- **Backup:** a full database backup was taken before any repair —
  `data/backups/lofc-20260811-103912.sql.gz`.
- **Code status: fixed and reviewed.** The scraped season is now derived from today's date
  instead of hard-coded; the squad-page parser reads columns by header name instead of position;
  a fill-rate/volume guard aborts a degraded pull before it touches the CSV; and every writer to
  `players` (`identity.py`, `valuation.py`, `store/load.py`) now uses COALESCE so a blank incoming
  value can never overwrite a value already on file.
- **Data status: ✅ RESTORED.** The recovery scrape ran successfully on 2026-08-11 using the fixed
  code. It pulled **2,437** players with **1,882** contract dates, **2,187** feet and **2,199**
  heights. `valuation` matched **1,380** players; `identity` linked **1,346**. The database now
  holds **1,363** contract dates, **1,606** feet and **1,635** heights, against 5,626 players — up
  from the incident's 20 / 23 / 24. These figures reflect **2026/27 squads**: a player who featured
  in 2025/26 but has since left the four English leagues will have no contract date, which is why
  the recovered totals do not match the pre-incident 542 / 822 / 447 contract-band figures exactly
  — correct behaviour for recruitment (you want live contract positions), not a shortfall.
- **Recovery procedure, three commands in order (as run):**
  1. `transfermarkt_efl --force --allow-degraded`
  2. `valuation`
  3. `identity`

  `--allow-degraded` was required because the volume guard compared the recovery run's **2,437**
  current-squad rows against the corrupt 4,014-row file, which was still its comparison baseline.
  That corrupt baseline is now replaced by the clean recovery CSV, so the flag should not be needed
  on future runs.

**Injury scrape capability — landed and complete (11 Aug 2026):**

The Transfermarkt injury-history scraper, categoriser, `player_injuries` table, CSV→Postgres
loader (`lofc.store.injuries`) and the Medical-dimension `availability()` calculation are all
built, tested and wired into the pipeline (runs immediately after the Identity step, since the
loader joins on `players.tm_player_id`). **The real scrape has finished and is loaded:**

- **Scrape (final run, against the refreshed player list):** 3,930 injury rows written to
  `data/reference/transfermarkt/injuries.csv`, **0 failed**, 3,507 player pages fetched.
- **Loaded into Postgres:** **3,766 rows for 1,176 players** (the gap to 3,930 is rows whose
  Transfermarkt id matches no player we hold metrics for — dropped, not guessed). All rows
  carry `source = 'transfermarkt'` (the loader always clears existing `source = 'transfermarkt'`
  rows before inserting, so the earlier 5-player smoke-test load has been replaced).
- **Coverage stays EFL only** (Championship, League One, League Two, National League — the four
  leagues with a `SCHEDULED_GAMES` constant), and only players carrying a `tm_player_id`.
- **`tm_player_id` coverage, 2025/26 season** (this is what makes a Medical figure computable):

  | League | Coverage | % |
  |---|---|---|
  | Championship | 730 / 748 | 98% |
  | League Two | 714 / 745 | 96% |
  | League One | 715 / 749 | 95% |
  | National League | 711 / 769 | 92% |
  | Premier League 2 | 182 / 1,141 | 16% |
  | Scottish Premiership | 28 / 385 | 7% |
  | Scottish Championship | 8 / 284 | 3% |

  The last three rows are not usable for injuries today (no `SCHEDULED_GAMES` constant either —
  see R6); they are recorded here because the same `tm_player_id` link also feeds B1's contract
  data.
- **Completeness check:** of 2,701 linked EFL players in 2025/26, **2,701 had their injury page
  fetched — zero were never fetched.** An unfetched player would otherwise silently read as 100%
  available; there is now no such ambiguity for the EFL.
- **Injury category distribution** (3,766 rows), with average matches missed / average days out:

  | Category | Rows | Avg matches missed | Avg days out |
  |---|---|---|---|
  | other | 1,534 | 7.0 | 53 |
  | knee_ligament | 634 | 17.4 | 135 |
  | hamstring | 494 | 10.2 | 69 |
  | ankle | 371 | 9.6 | 70 |
  | muscular | 303 | 6.8 | 45 |
  | groin | 195 | 7.0 | 52 |
  | calf | 162 | 7.6 | 51 |
  | hip | 73 | 9.3 | 64 |

  The clinical ordering is a sanity signal — knee-ligament injuries cost by far the most time,
  as expected if parsing is correct. The `other` bucket is dominated by phrasings genuinely
  outside the club's named categories ("unknown injury" 301, "Knock" 153, "Ill" 85, "Corona
  virus" 68, "Foot injury" 66, "Shoulder injury" 61) — honestly uncategorised, not mis-parsed;
  category does **not** affect availability, which counts matches missed regardless of category.
- **Availability, validated end to end on real data:** computed for **2,870** player-season rows
  across the four EFL leagues; **77 fall below the club's stated 60% bar**; the most affected are
  recognisable long-term-injured players. **NB these figures pre-date R9** — they were computed before overlapping injury spells were merged, so they overstate the worst cases. Charlie Wyke, the most affected, read as 128 matches missed / availability 0.0 then; after the R9 fix he is **64 matches missed, availability ~0.30**. The 2,870 and 77 counts have not been recomputed since — treat them as indicative, not current.
- **Design question, now resolved (Decision 12, 2026-08-14):** an earlier design considered the
  band formula `band = 3 + 5 × (availability − 0.60)` to score Medical automatically; under it
  **2,201 of 2,870 (77%)** would have scored the maximum Medical band of 5.0, because they had no
  injuries in the two-season window — a *risk* dimension awarding three-quarters of players an
  identical maximum. Medical carries 13.6% of the outfield composite weight (Financial/Resale
  included) or a share of the 86%-weight `assessed_composite` (Financial/Resale excluded, see
  R3a-1 in the register below). Decision 12 resolved this: Medical is now a **human-entered
  band**; this availability figure is evidence shown to the assessor, never a score by formula.
  **The scoring machinery (`assessed_composite`) is built, and the interface to populate it
  (R3a-2) is now also built (2026-08-17)** — see the Current state note above.

Full detail: `docs/DATA_ARCHITECTURE.md` §5.

**Task 0 identity fix (landed 2026-08-10):** `load_efl_values()` was discarding a player's
Transfermarkt id, birth date, foot and contract date whenever he had no market value on file.
A separate identity matcher (`model/identity.py`) now runs over the full scrape instead,
matching on birth date + name, league-scoped. **National League `tm_player_id` coverage rose
from 60 of 769 players to 567 of 769** (8% → ~74%) on that fix alone; combined with the
refreshed scrape above, National League now stands at **711 / 769 (92%)**. The three EFL
divisions above it improved too, not fallen (they were already matched via market value, and now
also pick up players the value-filtered path missed). This is what made the injury scrape usable for the National League —
previously only 8% of that league could be joined at all. (The same `tm_player_id` link also
carries B1's contract/foot/height data — see the B1 incident above, now recovered.)

**In-season operating model (2026/27 — LIVE from August 2026):**

The 2026/27 iterations for all seven leagues are configured (`DEFAULT_IMPECT_TARGETS`,
season_id **319**), and `config.LIVE_SEASON_ID = 319` makes the ingest **always re-pull** that
season — Impect returns season-to-date aggregates, so skip-if-exists (correct for a finished
season) would have frozen the data after the first in-season pull. A season with no matches yet
is skipped cleanly, not treated as an error. **Update `LIVE_SEASON_ID` each August.**

- **Refresh cadence: weekly** (both endpoints are cumulative, so per-match polling buys nothing):
  `python -m lofc.ingest.impect` → `python -m lofc.ingest.skillcorner_api` →
  `python -m lofc.model.build_neutral --write` → `python -m lofc.pipeline`.
- **The live-season rule covers both providers** (Impect events + SkillCorner physical) from the
  single `LIVE_SEASON_ID`, so they can never disagree about which season is still accumulating.
- **Verified live on 2026-08-04:** the Scottish Premiership + Championship 2026/27 are already
  underway (184 / 151 players, **1 matchweek**, **0 rankable**); the English leagues and PL2
  correctly reported "no data yet" and skipped.
- **Expect an empty-looking 2026/27 until ~October.** `rankable` needs 450 minutes (5 full
  matches), so early-season players are stored and visible but not ranked. **Keep 2025/26 as the
  default scouting season** (complete, 46 games) and switch when 2026/27 matures.

| # | Pending in-season item | Note |
|---|---|---|
| S1 | **Weekly refresh** — script written, not installed | `scripts/weekly_refresh.sh` wraps `python -m lofc.pipeline` with a lock, rotated logs and success/failure markers (`data/ops/`); it is not scheduled anywhere because there is no server to schedule it on yet (G1/G5). Manual for now |
| S2 | ✅ **DONE (by 2026-08-24) — season 319 built into the DB** | six leagues now have data (Premier League 2 is the one hold-out — not yet started): **1,771 players, average 85 minutes, nobody near the 450-minute rankable threshold**. Shown on the profile as "Current form" (plain facts, not a rating) — no 2026/27 composite exists or should until the threshold is cleared, realistically once more of the season has been played |
| S3 | ✅ **SkillCorner 2026/27 editions (DONE 2026-08-10)** | six editions added (Championship 1569, League One 1574, League Two 1575, National League 1576, PL2 1578, Scottish Premiership **1683** — SkillCorner labels it just "Premiership"). The **Scottish Championship is deliberately excluded**: the competition exists but holds **zero** physical data (0 rows for 24/25 and 25/26 vs 358 for the Scottish Prem), so configuring it would emit a false "no data" warning every week. The live-season rule now covers **both** providers off one `LIVE_SEASON_ID`. Verified live: Scottish Prem 26/27 already returning **146 players**; the English leagues skipped cleanly (they would have **crashed** the run before this fix) |
| S4 | **Show "current club" — deferred until after the interface (owner's decision, 2026-08-14)** | the Players list shows the club a player played for *in that season* (by design). Why it matters now: contract dates come from Transfermarkt's 2026/27 squad pages and are current, but the **club name displayed comes from `player_metrics_neutral.team_name`, which is Impect 2025/26 data** — so a player who moved this summer shows his old club beside a current contract date. Transfermarkt's scrape already carries the correct current club in `efl_values.csv`'s `club_name` column, and **nothing reads it**. The fix is to join that column through and display it as "Current club" alongside the season club |

**Ready to do (not blocked):**

| # | Item | Why |
|---|---|---|
| R1 | **Full pipeline re-run** (`python -m lofc.pipeline`) | a clean end-to-end recompute; now covers the new scorecard stage. NB it *fetches nothing* — every ingest step skips existing files, so it is a recompute, not a refresh |
| R2 | ✅ **Refactor `dashboard/app.py` (DONE 2026-08-10)** | 2,560 lines → **191**, split into 15 focused modules (`theme` · `labels` · `charts` · `seasons` · `loaders` · `controls` + `tabs/` one per tab), dependencies strictly one-way so there are no import cycles. **337 lines of dead code deleted** (`_club_scorecard`, `_scorecard_player_detail`, `_profile`, `_render_score_composition`, `percentile_vector`, `_dimension_metric_labels`) plus the retired Style-fit helpers `score_composition`/`load_fit_profiles` and their 3 tests. Done in verified phases against a captured behaviour snapshot: **the final output is byte-for-byte identical to before the refactor**; 191 tests passed at the time — that had grown to 301 by the 2026-08-03 audit, and stands at **365 now** (2026-08-14), after the scout-assessment branch added tests |
| R3a-0 | ✅ **DONE (branch `r3a0-injury-scrape`, not pushed) — Transfermarkt injury data** | scraper (`ingest/transfermarkt_injuries.py`), loader (`store/injuries.py`), `player_injuries` table, `model/medical.py` availability with honest `MEASURED`/`CONFIRMED_BY_MINUTES`/`UNKNOWN` states (never a confident 1.0 for an unknown record). **3,766 injury rows for 1,176 players** loaded. See R8/R9 above for the two evidence-quality fixes made on top of this |
| R3a-1 | ✅ **DONE (same branch) — scout-assessment foundation, 5 tasks** | `model/club_criteria.py` (club's per-position Psychological/Medical criteria, transcribed verbatim), `users`/`scout_assessments`/`scout_criterion_scores` tables (migration `a3fd42bcb2c2`), `dashboard/auth.py` (scrypt hashing) + `admin.py` (`create-user` CLI, at `src/lofc/admin.py`), `model/scout_scores.py` (`resolve_bands()`), `assessed_composite`/`assessed_weight_covered`/`psychological_band`/`medical_band` on `player_scorecards` (migration `5e80ab6fe191`). Design settled at the time: `docs/superpowers/specs/2026-08-10-scout-assessment-design.md` (up to Decision 16; Decision 17 followed with R3a-2). **At this point `assessed_composite` was NULL for every player and `scout_assessments` was empty — no UI existed yet to create one. Superseded by R3a-2 below, which built that UI.** |
| R3a-2 | ✅ **DONE (2026-08-17) — the scout-assessment user interface** | login gate (`dashboard/session.py`), assessment form (`dashboard/tabs/assess.py`), evidence panel (`dashboard/evidence.py` — injury data + screening-criteria warnings, which warn but never override per Decision 13), status badges (`dashboard/badges.py`: 🟠 assessed / 🟢 signed off / ⚪ conflict — colour **and** words), a sign-off queue (`dashboard/tabs/signoff.py`) that also resolves conflicts (Decision 17, new — replaced the earlier "most recent submitted wins" tiebreak: a signed-off assessment is never in conflict, two or more unsigned ones score nothing until someone decides), watchlist integration, and an opt-in "Rank on assessed composite" toggle on the Players list. Navigation rebuilt from `st.tabs` to `st.navigation` so "Assess this player" carries the player across pages. Auth gaps closed alongside it: password strength (12-char minimum, length-only), login throttling (5 attempts / 15-minute lock), session expiry (12 hours); `set-password`/`list-users` added to `lofc.admin`. **Still no self-service or email password reset** (`users` holds no email — an admin resets in person) — **superseded 2026-08-24 below (R3a-3): deactivate/reactivate is now built** |
| R3a-3 | ✅ **DONE (2026-08-24) — reject, admin user management, regrouped navigation, live-but-unscored 2026/27** | Sign-off queue gained **reject** (`store/assessments.py::reject`, migration `19ac464d556d` — nullable `rejection_reason`, the reason is optional). New **Users admin page** (`dashboard/tabs/users.py`, gated on `manage_users`) plus `deactivate-user`/`reactivate-user` on the `lofc.admin` CLI (`model/user_admin.py::guard_deactivate` stops an admin locking themselves out); accounts are never deleted (assessments reference `users.id`). Navigation regrouped into Scouting/Assessment/Analysis/Reference + Admin section headers. Chrome: slim info bar + top-right signed-in identity/sign-out (`theme.py`, `session.py::topbar_identity`), replacing the sidebar identity block. Scorecard-reading caches shortened to 60s so a saved assessment appears in the assessed ranking promptly. **2026/27 (season 319) is loaded — 1,771 players, 6 leagues (PL2 not started), 85 min average — and deliberately not scored**; the profile shows it as a "Current form" plain-facts section (`loaders.load_current_form`) beside the 2025/26 scored season. Five bugs fixed: Assess page losing its selected player on every widget interaction; watchlist blank club/position/age for Scottish/PL2 players; injury source reading "Scraped" instead of "Transfermarkt"; mid-season transfers showing the wrong club (now picked by total minutes per squad, not per-position match share); the "not yet rankable" banner appearing on every page instead of only the ones the season selector drives. **604 tests pass** (was 511) |
| R3c | **NOT STARTED — player report export** | export gated on sign-off (Decision 14: sign-off is non-blocking for scoring, but gates what may be exported as final) |
| R3a-review | **NOT RUN — final whole-branch review** | each commit on `r3a0-injury-scrape` (including R3a-2) was reviewed individually as it landed; the cross-cutting review across the whole branch has not happened |
| R3a-gap1 | **No loan status captured anywhere** | affects how a contract date should be read (a loanee's parent-club contract is not the club he is playing for); not modelled by any table today |
| R3a-gap2 | **Two metrics are empty for every player in every league:** `pressured_pass_pct` and `xg_buildup_p90` (0 of 9,451 `player_metrics_neutral` rows for both, verified) | StatsBomb-era leftovers with no Impect equivalent; harmless to the composite because bands renormalise over the metrics actually present, but the columns and their `DATA_ARCHITECTURE.md` entries are dead weight |
| R4 | **Full StatsBomb retirement** (roadmap #6) | seed identity from Impect, delete the ingest + ~21 GB raw events + 22 dead all-NULL columns |
| R5 | **Playing-style clusters: season split + move onto Impect** (roadmap #8) | the last season-mixing and last StatsBomb read; style label only, never touches the composite |
| R6 | **Extend the Transfermarkt squad scrape to Scottish Premiership, Scottish Championship and Premier League 2** | those three leagues carry **low Transfermarkt coverage today** — 2025/26 `tm_player_id` coverage is **Premier League 2 182/1,141 (16%), Scottish Premiership 28/385 (7%), Scottish Championship 8/284 (3%)** — so almost no market value, contract-expiry data, or injury history (the injury loader only ever sees players with a `tm_player_id`, and none of the three has a `SCHEDULED_GAMES` constant for availability either way). Needs a squad-page scrape built for those competitions (`transfermarkt_efl`-equivalent); not started |
| R7 | ✅ **DONE (11 Aug 2026) — four duplicate Transfermarkt ids resolved** | Each of `118779`, `390687`, `948958`, `967296` was claimed by two players. Resolved against Transfermarkt's own profile pages: 118779 = **Marlon Pack** (not Scott Malone), 390687 = **Alex Newby** (not Elliot), 948958 = **Kyreece Lisbie** (not Kyrell), 967296 = **Josh Ayres** (not Joe Bauress). Two pairs were twins, two were birth-date coincidences the fuzzy name match let through. **No contamination had occurred** — every injury record was already on the correct player. The incorrect link was cleared from the four wrong claimants; zero duplicate ids remain. **Still open:** the matcher can create new duplicates — it needs an exact first-name requirement when birth dates collide (twins), and a stricter name-similarity bar (`Malone`/`Pack` should never have matched) |
| R8 | ✅ **DONE (14 Aug 2026) — "never injured" vs "never checked" now distinguishable in `model/medical.py`** | a player with no injury rows used to read as a clean record. Fixed with `availability_with_evidence()`, which returns an explicit `AvailabilityStatus` (`MEASURED` / `CONFIRMED_BY_MINUTES` / `UNKNOWN`) alongside the value — `UNKNOWN` returns `None`, never a false `1.0`. `CONFIRMED_BY_MINUTES` uses `MINUTES_CONFIRM_AVAILABILITY_PER_SEASON = 2000` (a player with 2,000+ minutes in a season was demonstrably available whatever Transfermarkt says), which resolves ~37% of blank records at a rate consistent across leagues (34/39/37/36%). The old `availability()` is unchanged (still no non-test caller) and its docstring now warns not to use it directly for anything shown to a human. **Still open:** `model/medical.py` has no production caller yet — wiring this into the evidence panel is the scout-assessment plan's job, not done here |
| R9 | ✅ **DONE (14 Aug 2026) — overlapping injury spells merged in `model/medical.py`** | Transfermarkt lists concurrent diagnoses as separate rows. Charlie Wyke carried "Ankle injury" **and** "Broken leg", both 26 Oct 2024 → 30 Jan 2026, 462 days and 64 matches **each** — so he read as **128 matches missed against an actual 64**. Affected **73 spells across 54 players (5% of those with an injury record)**, concentrated in the severe cases where the evidence matters most. Fixed: `games_missed_in_window()` now merges overlapping/touching date ranges via `_merge_overlapping_spells()` and takes the **max** `games_missed` per merged group (not the sum) — deliberately conservative on genuine partial overlaps, since this feeds a human judgement, not a score. A NULL `date_until` (ongoing injury) extends the merge indefinitely rather than crashing or being dropped; see the sentinel's comment in `model/medical.py` for the one known limitation (a NULL from missing/unscraped data, rather than a genuinely open injury, would also absorb — and understate — a real later absence). Verified against the real Wyke case: 64, not 128 |

| R10 | ✅ **DONE (25 Aug 2026) — security-and-correctness audit** | Traceback suppression (`showErrorDetails = "none"`), an XSS sweep of every `unsafe_allow_html` site (`html.escape` on the identity chrome and status badges), `hide_parameters=True` on both dashboard engines plus a caught username-race `IntegrityError`, and a behaviour-based (not IP-based) login-spray throttle (`dashboard/login_throttle.py`). The season-pooling percentile bug in four functions (`normalise.compute_percentiles_wide`, `score.compute_scores`, `wage_check.build_squad_estimates`, `constrain/filters.build_candidates`) is fixed; `objective_composite` verified unaffected (6,573 rows, 3.029285, unchanged), `shortlists` re-verified at 909 rows. Goalkeeper-only metrics masked for outfield rows at display (`loaders.GOALKEEPER_ONLY_METRICS`); 12 dead StatsBomb metrics removed from `labels.LABELS`; the veto advisory now names the tripped dimension (`tabs/players._veto_reasons`). Injury loader rewritten to merge, not replace (`store/injuries.py::merge_transfermarkt_rows`) — verified 3,772 rows / 1,176 players. Interface: cookie-persisted logins (`dashboard/cookie_auth.py`), per-cell table styling removed, a global player search (`dashboard/search.py`), watchlist enrichment (current form, injury status, contract countdown, real composite replacing the retired "Quality" column), and a shared `dashboard/formatting.py` fixing roughly two dozen sites where a missing value rendered as literal "None"/"nan". **694 tests pass** (was 604) — collected and run directly against this checkout. Full detail: the 2026-08-25 note in Current state above |
| R11 | **REPORTED, PARTLY UNVERIFIABLE (25 Aug 2026) — 76 split player identities merged; 3 shared Transfermarkt ids cleared** | Reported: two provider-matchers minting independent ids on failure had split some players' data across two rows; merged with no deletions, one pair left for a human decision. Separately, 3 players sharing a Transfermarkt id (twins/namesakes) had it cleared. **Verified:** contract/foot/height totals (1,412/1,660/1,689) match the reported after-figures exactly. **Not verifiable from the repo:** no script, migration or log implements either fix — both are one-off manual database repairs, same pattern as R7. **Contradiction found:** this database currently holds 15 `tm_player_id` values shared by two `players` rows each, not zero — see gap G4 above. Root cause (independent id-minting on match failure) is **unfixed**, so new splits can recur on the next identity refresh |

**Small leftovers (cheap, opportunistic):**

- **SkillCorner per-90 labelling** — physical metrics are per-full-match (~95 min) but suffixed
  `_p90`. Rankings unaffected (percentile-based); displayed absolute numbers overstate ~5–11%.
  Either rescale or relabel "per match".
- **Adopt Impect's `leg` for preferred foot** — Impect has it at ~97% across all seven leagues;
  we currently take foot from the EFL-only Transfermarkt scrape. (Impect has birth date and
  birthplace too, but **no contract date and no height** — verified against the API.)
- **Stale reference files** — `data/reference/impect_metric_map.csv` and some
  `metric_registry.py` comments still say 41 Impect metrics; the live count is 45.
- **Persist per-metric percentiles** — `load_scorecard_percentiles` is still computed live (player
  detail + Compare only). Only worth doing if opening player cards feels slow.
- **Optional polish** — fold the Player-types and Physical tabs into the Players workspace.

---

## Roadmap

**Done** (Phases 0–11 core):
- ✅ Phases 0–9 (demo build) · Phase 10 (real EFL data + SkillCorner) · panel demo
- ✅ Phase 11 (Impect migration): provider-neutral metric layer, EFL flipped to Impect-only,
  6 new leagues added, Impect's exact definitions displayed
- ✅ Club recruitment scorecard (1–5 composite) built and made the primary ranking; Style-fit
  retired; 4 club-framework metrics added (91 total); physical extended to PL2 + Scottish Prem
- ✅ Within-season scoring (Season selector); archetype lens for Full Back + Winger;
  UX fixes (season-specific "Players analysed", all-round shown alongside archetype composite,
  excluded archetype metrics struck through, clickable scorecard rows, clear-selection buttons)
- ✅ Documentation reorganised (this hub + frozen history + deep-dive spokes)
- ✅ Scout-assessment foundation, R3a-0 + R3a-1 (branch `r3a0-injury-scrape`, not pushed):
  Transfermarkt injury data, the club's Psychological/Medical criteria, `users`/
  `scout_assessments`/`scout_criterion_scores` tables, auth + scoring resolution,
  `assessed_composite` on `player_scorecards` (schema — see register R3a-1)
- ✅ Scout-assessment interface, R3a-2 (same branch, 2026-08-17): login gate, assessment form,
  evidence panel, status badges, sign-off queue (with Decision 17 conflict resolution),
  watchlist integration, opt-in assessed-composite ranking — see register R3a-2
- ✅ Reject, admin user management, regrouped navigation, R3a-3 (same branch, 2026-08-24):
  sign-off reject with an optional reason, an admin Users page + CLI deactivate/reactivate,
  `st.navigation` grouped into Scouting/Assessment/Analysis/Reference/Admin, top-right signed-in
  identity, 60s scorecard caches, 2026/27 loaded (not scored) with a "Current form" profile
  section, five UI bugs fixed — see register R3a-3
- ✅ Security-and-correctness audit, R10 (same branch, 2026-08-25): traceback suppression, an
  XSS sweep, engine `hide_parameters`, a behaviour-based login-spray throttle, the season-
  pooling percentile bug fixed in four functions (composite ranking verified unaffected),
  goalkeeper-metric masking, 12 dead metrics removed, the veto advisory naming its dimension,
  the injury loader rewritten to merge instead of replace, cookie-persisted logins, a global
  player search, watchlist enrichment, and a formatting fix for ~24 "None"/"nan" display
  defects — see register R10. Also reported (not independently verifiable from the repo): 76
  split player identities merged — see register R11 and gap G4

**Next** (in rough priority order):

1. ✅ **Unified "Players" workspace (DONE)** — merged the three overlapping tabs (Shortlist +
   Club scorecard + Player profile) into ONE master-detail workspace: a composite-ranked list
   (objective composite default, within-season) with Minutes + dimension bands + Measured %, and
   on click/search a full player detail (bio + score tiles + trajectory + the club-framework
   **grand table**: Source · Season total · Per-90 · Percentile · 1–5 Band, archetype-aware +
   charts re-pointed to the club per-position/archetype metrics + an "all tracked metrics"
   expander). **Money is an opt-in secondary layer** ("Show affordability (modelled)", off by
   default) — never affects the default ranking. Dead code left for the app.py refactor (#7):
   the old `_shortlist`/`_club_scorecard`/`_profile`/`_scorecard_player_detail` functions.
   *Follow-up polish:* fold Player-types/Physical into the workspace if wanted (deferred).

2. ✅ **Persist scorecards to the database (DONE)** — a `player_scorecards` table written by a new
   pipeline stage (`model/scorecard_run.py`, runs after Valuation, before the shortlist).
   One row per player-season **per archetype** ('All Metrics' for everyone + the Full Back /
   Winger lenses), storing both composites in separate columns. **This retired Style-fit from the
   offline path:** `constrain/filters.py` now ranks the `shortlists` table on
   `objective_composite` (was `fit_score`), and the old identity-profile "on-profile" gate no
   longer excludes anyone — matching the dashboard. The dashboard now **reads** the stored table
   (with a live-compute fallback if it is empty), so every consumer sees identical numbers.
   Verified: stored == live to 0.0, writer idempotent, 160 tests pass.
3. **Midfield archetypes** (DM / Box-to-Box / AM) — await the club's per-archetype metric lists
   (the workbook doesn't fully specify them; not fabricated).
4. ✅ **Scout-entry fields (DONE 2026-08-17).** Both the foundation (R3a-0 injury data + R3a-1
   club criteria/tables/auth/scoring resolution) and the interface (R3a-2: login, assessment
   form, evidence panel, badges, sign-off queue, watchlist integration) are built — see register
   R3a-0/R3a-1/R3a-2. `assessed_composite` fills in as staff assess players. **Still
   outstanding:** the player-report export (R3c) and the final whole-branch review.
5. **Real financial models (deferred, a separate workstream):** the club's real **wage framework**
   (CSV drop-in) + a better **valuation model**. The current wage grid (±10% vs payrolls) and
   valuation regression (CV R² ~0.75, but ±40% median error within league) are honest *screening*
   placeholders, not decision-grade — fine to defer; they firm up the money layer when ready.
6. **Full StatsBomb retirement** — seed player identity from Impect, then delete the StatsBomb
   ingest and its ~21 GB of raw events.
7. ✅ **Refactor `dashboard/app.py` (DONE 2026-08-10)** — 2,560 lines → 191, split into 15
   focused modules with one-way dependencies; 337 lines of dead code removed. See register R2.
8. **Playing-style clusters: split by season + move off StatsBomb** — the k-means (`model/archetypes.py`)
   currently pools 2024/25 + 2025/26 and reads the StatsBomb-era `player_season_metrics` with `ROLE_METRICS`.
   It should cluster within season on the Impect neutral layer. Style label only (never touches the
   composite), so low priority — but it is the last season-mixing and StatsBomb-read in the app.

**Data re-runs:** a full data *fetch* is only needed for a new season or a new league — EXCEPT the
season currently being played, which is always re-pulled (`config.LIVE_SEASON_ID`, see the in-season
model above). Everything else (metric or formula changes) is a fast local rebuild from data already
on disk — no fetch.

---

## Working principles

- **Objective and honest:** verify facts against primary sources; label every modelled input;
  never present a stand-in as real. Where a metric substitutes another, name it for what it
  truly is (see the Glossary).
- **Reproducible:** everything runs in Docker (Python 3.11) against Postgres 16; config via
  `lofc.config.settings`; schema changes via Alembic migrations; `pytest` green before done.
- **Confidential data stays local:** the club documents (`docs/*.xlsx`, `*.docx`) and licensed
  feeds (Impect, SkillCorner, Transfermarkt pulls) are gitignored and never published.

(Claude-specific session rules — including the git-commit policy — live in `CLAUDE.md`, which
is local-only and not part of the repository.)
