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
> _Last updated: 2026-08-25._

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
| **`plan/BUILD_PLAN.md`** (this file) | Current state, doc index, roadmap | Always first — the entry point |
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
| P4 | **The clustering model is weak.** Every position resolves to k=2 with silhouettes 0.16–0.31, and four positions produce the same "pressing vs passing" split — one latent axis rediscovered per position, not a playing-style taxonomy. Feature set is the Performance metrics, which measure *quality*; style clustering needs tendency/proportion features normalised for volume. Only Centre Forward yields three genuinely distinct groups. | Open, needs redesign not a re-run |
| P5 | **Injury panel heading is wrong for current-season spells.** The panel groups "In the scored window" vs "Earlier seasons", but the window is the last two *completed* seasons, so the 20 spells from 26/27 — the current season — are labelled "Earlier". Heading should read "Outside the scored window". | Open, small |
| P6 | **The legacy `player_season_metrics` table has now caused three separate defects** (watchlist blanks, clustering coverage, cross-table disagreement). Frozen, incomplete, still read in several places. Retiring it properly is its own task. | Open |
| P7 | **Player report feature** — a per-player report for the Head of Recruitment, chairman and manager, modelled on the supplied reference. See the spec. | Requested 2026-08-28 |
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
| B2 | **Midfield archetypes** (DM / Box-to-Box / AM) | needs the club's per-archetype metric lists | encode into `ARCHETYPE_DROPS`; deliberately not fabricated |
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
