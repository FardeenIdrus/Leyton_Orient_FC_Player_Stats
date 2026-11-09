# New front end (TASKS 2.36) — how it is built

Owner decision 2026-11-08: replace the Streamlit pages with a web front end that looks and
behaves like **mockup v5** (`club_docs/design/mockup_v5.html`, local only), page by page.
Streamlit stays the live site until the owner switches. This file is the single brief every
builder follows; keep it current.

## Shape

| Layer | What | Where |
|---|---|---|
| Data + ratings | **Unchanged.** The existing Python (`lofc.dashboard.loaders`, `compare_tables`, `report.data`, `model.*`, …) is the only source of numbers | `src/lofc/...` |
| Shared page logic | Pure functions lifted out of Streamlit page code when the API needs them (e.g. building the Players pool from filters). Streamlit then calls the same function, so both show identical numbers | `src/lofc/core/` |
| API | FastAPI app: JSON endpoints under `/api/`, HTML page shells, login | `src/lofc/web/` |
| Front end | Plain HTML + CSS + JavaScript (ES modules). **No Node, no build step, no framework download.** Jinja2 templates for the page shell; JS fetches JSON and renders, like the mockup | `src/lofc/web/templates/`, `src/lofc/web/static/` |

Production: `web-blue` / `web-green` in `docker-compose.prod.yml` (no reloader, one worker),
switched by `scripts/web_switch.sh` once `/readyz` reports the warm-up done; details in DEPLOY.md
("The new web front end"). Assess and Sign-off show "Currently building".

Run locally: the `web` service in `docker-compose.yml` → **http://localhost:8600**
(`docker compose up -d web`; code reloads on save; CPU capped). Same database as Streamlit.

## Foundation (built) -- what page builders use

| Thing | Where |
|---|---|
| App factory `create_app(users=, secret=, info_items=, clock=)`; `app` is built on first access and refuses to start without `SESSION_SECRET` | `src/lofc/web/app.py` |
| Nav + page registry (`PAGES`, `nav_for`); every route is generated from it. To replace a placeholder, register a real route/template for the same `key` and extend `page.html` | `src/lofc/web/pages.py`, `templates/` |
| Dependencies: `current_user` (page -> 303 `/login`, `/api/` -> 401; pending password change -> `/change-password` / 403), `write_user` (session AND header `X-LOFC-Request: 1`, else 403) | `src/lofc/web/security.py` |
| Cookie `lofc_web` (signed, HttpOnly, SameSite=Strict, Secure on https, 12 h absolute); role/active/must-change re-read from the live row each request | `security.py` |
| Extra routes: `/healthz`, `/login`, `POST /logout`, `/change-password`, `POST /api/change-password` | `app.py` |
| Info bar counts (shared with Streamlit): `infobar_count_items`, `headline_counts`, `league_count`, `latest_season_id` | `src/lofc/core/infobar.py` |
| JS (ES module `/static/js/common.js`): `esc`, `num`, `dash`, `roundHalfUp`, `fmtInt`, `chip`, `pcol`, `bar`, `thead`, `pills`, `radar`, `api`, `readState`, `writeState`, `onStateChange` | `static/js/common.js` |
| One stylesheet (mockup v5 tokens + responsive rules); CSP forbids inline scripts, so page code is a module in `static/js/` loaded via `{% block scripts %}` | `static/css/app.css` |
| Test fakes (no DB, no real passwords): `FakeStore`, `make()`, `login()` | `tests/web_fakes.py` |
| Web caches: `@webcache.versioned` keeps a value in process until `loaders.web_data_version()` changes (scorecards, detail metrics, scout reports, scout assessments, Transfermarkt squads tracked; the token also rolls over daily); never a TTL, never a pickle copy -- callers must not mutate. Card detail rows: `detail_store.player_rows` (= `detail_section._player_rows`, precomputed per league-season) | `src/lofc/core/webcache.py`, `core/detail_store.py` |
| Radar: `radar(axes, series, {league})` returns a placeholder drawn at its real pixel width (true-size labels, wrapped, collision-free), redrawn on resize; legend click toggles a line, points show "Name / Metric · value · P72", wheel-after-click or pinch zooms the viewBox, drag pans, double-click resets. Colours `RADAR` (players ink/orange/teal, Orient median blue dashed via `orientSeries`, league median red dotted). Any element with `data-tip` gets the same instant tooltip (packing zones) | `static/js/common.js` |
| Table + radar sections: `.row.tr2` (50/50, equal height, stacks < 1100 px) with the radar card `.card.rcard` > `.rbody` | `static/css/app.css` |
| Re-warm after a data change: each page calls `webcache.register_warmup(key, fn)` in `mount`; a watcher (`webcache.rewarm_on_change`, started once all start-up warm-ups finish) re-runs them one after another whenever `web_data_version()` moves | `src/lofc/core/webcache.py`, `web/app.py` |
| Home `/` (crest + page links); logo served from `static/img/logo.png` (a 256 px copy of `assets/logo.png`) | `templates/home.html` |
| Static files: templates link `{{ static_url('js/x.js') }}` → `/static/v/<content hash>/js/x.js` (immutable, one year; only the current hash is served); JS modules import each other relatively (`./common.js`), never `/static/...` | `web/static_version.py`, `web/app.py` |
| gzip for responses over 1 KB (Starlette GZipMiddleware) | `web/app.py` |
| Card prefetch: pointer rest ~80 ms / touch on a `/player/...` link sends `GET /api/card/...` with `X-LOFC-Prefetch: 1`; the server keeps the built answer (single use, 30 s, cleared on watchlist writes) for the card's own request | `static/js/common.js`, `web/prefetch.py`, `web/api/card.py` |
| Tables: chip columns are centred (heading + cells) and numeric headings right-aligned automatically; `th[title]` / tile help becomes the instant tooltip with ⓘ (focus shows it) | `static/js/common.js` |
| Physical page "Tracked matches": `skillcorner_match_counts` (SkillCorner `count_match`), written by `build_neutral` | `core/physical_page.py`, `web/api/physical.py` |
| Warm-up order at start: loaders -> Players -> card (one after the other), then `gc.freeze()`; logs "card warm-up done in N s". Time clicks only after that line. Every response has `Server-Timing: app;dur=`; answers > 0.5 s log "slow GET ..." | `web/api/players.py`, `web/api/card.py`, `web/app.py` |

## Rules (non-negotiable)

1. **Never recompute a number in JavaScript or in new Python.** Call the existing function. If
   the logic is buried in a Streamlit page, lift it into `src/lofc/core/` as a pure function,
   make the Streamlit page call it, and prove the Streamlit output is unchanged (its tests +
   `scripts/smoke_test.py`).
2. **Parity test for every endpoint:** the API's numbers equal what the Streamlit page shows for
   the same inputs (same function, same filters), on the real database.
3. **Everything that exists on today's page exists on the new page** (`club_docs/design/inventory.md`
   lists every element with file:line). Anything changed is logged in TASKS 2.36 as
   "before → after" for the owner.
4. Owner rules: blanks show "—" (never None/nan/NaN/undefined), minutes/goals round half-up,
   no StatsBomb in UI text, short labels, provider definitions, no league-weighting caveats,
   `objective_composite` is the ranking and scout input never changes it, thin peer pools
   (< `MIN_PEERS_FOR_RANKING`) are never shown as a rating.
5. Security: every provider string is escaped when rendered (build DOM with `textContent`, or
   the shared `esc()` helper); session cookie HttpOnly + SameSite=Strict (+ Secure over https);
   every write is a POST that requires the session AND the header `X-LOFC-Request: 1`;
   permissions use `lofc.dashboard.auth.can(role, action)` exactly as Streamlit does.
6. Login reuses the existing accounts and rules: `store.users.authenticate` (scrypt, lockout 5
   tries / 15 min), `login_throttle`, 12-hour absolute session (`auth.SESSION_TTL_MINUTES`),
   forced password change, deactivated account = signed out on the next request.

## Text on the page (owner 2026-11-09, pass/fail)

Minimal text. A number may get a short label or one line. Never several sentences or paragraphs to explain a basic point; cut any caption or note longer than one line.

## Radar and layout (owner 2026-11-09, pass/fail)

- Legend click hides/shows a line; the legend shows each line's colour AND style (solid/dashed) next to its short name; clearly different colours; hover shows the value; smooth zoom/pan (wheel/pinch, drag, double-click resets); labels wrapped, spaced, never overlapping.
- Table + radar sections: 50/50 side by side, equal height; the radar stays round, never stretched; stack below 1100 px.
- Smooth: page transitions without a white flash or layout jump (reserve space, skeletons, no full-page re-render on a click); no lag.

## Look and feel (owner feedback on the Streamlit attempt, 2026-11-08 — pass/fail)

- Mockup v5 is the design: dark navigation rail (#14161B, groups Find / Assess a player /
  Decide / Analysis / Reference / Admin), page #F1F2F4, white cards radius 12, Orient red
  #C8102E as the single accent, Orient comparison line #1F5FA8, rating chips c4–c0, percentile
  bars green ≥70 / grey 30–69 / red <30. Copy the mockup's CSS tokens into
  `static/css/app.css`; one stylesheet for every page.
- Players: ONE compact filter row (search, Season, Position, Leagues, Rank as, "More filters",
  "Metric filters" fold-outs); the ranking is visible without scrolling on a 1440×900 screen.
- Nothing overflows its card at 1280, 1440 and 1920 widths; key numbers large (rating chips in
  tiles ≥ 22px); no large empty gaps; important text larger, never tiny.
- Radar labels never overlap: alternate long/short label distance on charts with more than
  10 axes, wrap long labels (mockup v4/v5 `radar()` function — reuse it).
- Report: percentile bars and playing-style rows get vertical room (not crowded); no large
  empty area.
- Clicks never reload the whole page: JS fetches and re-renders only what changed. Browser
  back/forward and shareable URLs work (filters + open player in the URL query).
- Every warm click < 1 s (measured), first load of a page < 3 s warm.

## Pages (mockup v5 view id → today's Streamlit page)

Build order: Players + Player card (+ "Against our <position>", TASKS 2.32) → Compare → Report →
Squads & loans → Scout reports → Watchlist → Assess → Sign-off → Physical → What goes into each
rating → How playing styles work → Glossary → Users. Not rebuilt: Methodology (hidden), Style lab
(workstation-only tool).

"Against our <position>" logic exists, tested, in the set-aside Streamlit work:
`club_docs/streamlit_v2_archive/src/lofc/dashboard/squad_fit.py` (+ its tests). Move its pure
functions into `src/lofc/core/squad.py` and reuse them.

## Testing (every page, before it is called done)

| Layer | Tool | Rule |
|---|---|---|
| Unit + API | pytest + FastAPI TestClient, in the `app` container | test first |
| Parity | pytest on the real DB | API numbers = Streamlit's |
| Browser | `scripts/web_check.py` (Playwright, Python, driving the Mac's installed Chrome — `channel="chrome"`, no browser download) | logs in, clicks every control on every page, fails on any console error, failed request, visible "None/nan/undefined", overflow beyond a card, or a click > 1 s warm; saves screenshots at 1440×900 to `club_docs/design/web_shots/` |
| Old site | `scripts/smoke_test.py` | must still pass after any `core/` extraction |

## Resource rules (the owner works on this Mac)

One heavy job at a time (full suite, smoke, browser run). Tests run in the capped `app`
container with `docker compose exec` (never `docker compose run`). No large downloads beyond the
`playwright` Python package. Never touch the live server, git commits, or `.env`.

## Browser harness — how page builders use it

- Setup once (host, not Docker): venv at the session scratchpad `webvenv` with `playwright` +
  `pytest` (no browser download; drives the Mac's Chrome). Run:
  `<venv>/bin/python scripts/web_check.py --pages <page> --quick` while building, without
  `--quick` before calling a page done. Exit 1 = a failure; screenshots + `results.json` in
  `club_docs/design/web_shots/`.
- It logs in with a throwaway `webcheck_<hex>` account it creates and deletes in the LOCAL
  database (never a real password). Write buttons are skipped unless `--allow-writes` (Mac only);
  Scout reports "Refresh" (reads the club's Google sheet) is never pressed (`is_external`).
- Make controls discoverable: clickable rows/cards need `data-href` or `data-action`; give
  every control a visible label or `aria-label` (scenarios find controls by label).
- Each page builder corrects its own entry in `scripts/web_check_pages.py` (`PAGES` paths and
  scenario labels) and adds that page's scenarios (e.g. Players: position → season → open →
  back keeps filters; back/forward; shareable URL).
