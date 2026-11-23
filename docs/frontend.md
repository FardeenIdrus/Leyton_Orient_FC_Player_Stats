# Web front end — how it is built

> **What this is.** The brief every builder of the web front end follows: layers, shared
> helpers, rules, testing. **Current state:** live on the main address since 2026-11-10
> (FastAPI + Jinja + plain JavaScript, design = mockup v5, `club_docs/design/mockup_v5.html`,
> local only). The old Streamlit site is a fallback until it is retired (`plan/TASKS.md` X1).
> Assess and Sign-off show "Currently building". Keep this file current.

## Shape

| Layer | What | Where |
|---|---|---|
| Data + ratings | **Unchanged.** The existing Python (`lofc.dashboard.loaders`, `compare_tables`, `report.data`, `model.*`, …) is the only source of numbers | `src/lofc/...` |
| Shared page logic | Pure functions per page (`players_pool`, `card`, `compare`, `report_page`, `squads`, `squad`, `scout_reports_page`, `watchlist_page`, `physical_page`, `club_vs_league`, `infobar`); where Streamlit has the same page it calls the same function, so both show identical numbers | `src/lofc/core/` |
| API | FastAPI app: JSON endpoints under `/api/`, HTML page shells, login | `src/lofc/web/` |
| Front end | Plain HTML + CSS + JavaScript (ES modules). **No Node, no build step, no framework download.** Jinja2 templates for the page shell; JS fetches JSON and renders, like the mockup | `src/lofc/web/templates/`, `src/lofc/web/static/` |

Production: `web-blue` / `web-green` in `docker-compose.prod.yml` (no reloader, one worker),
switched by `scripts/web_switch.sh` once `/readyz` reports the warm-up done; details in DEPLOY.md
("The web front end on the server").

Run locally: the `web` service in `docker-compose.yml` → **http://localhost:8600**
(`docker compose up -d db app web`; code reloads on save; capped at 1.5 CPUs). Same database
as Streamlit. Resync the local database from the server before judging any number (DEPLOY.md).

## Foundation (built) -- what page builders use

| Thing | Where |
|---|---|
| App factory `create_app(users=, secret=, info_items=, clock=)`; `app` is built on first access and refuses to start without `SESSION_SECRET` | `src/lofc/web/app.py` |
| Nav + page registry (`PAGES`, `nav_for`); every route is generated from it. To replace a placeholder, register a real route/template for the same `key` and extend `page.html` | `src/lofc/web/pages.py`, `templates/` |
| Dependencies: `current_user` (page -> 303 `/login`, `/api/` -> 401; pending password change -> `/change-password` / 403), `write_user` (session AND header `X-LOFC-Request: 1`, else 403) | `src/lofc/web/security.py` |
| Cookie `lofc_web` (signed, HttpOnly, SameSite=Strict, Secure on https, 12 h absolute); role/active/must-change re-read from the live row each request | `security.py` |
| Extra routes: `/healthz`, `/readyz`, `/login`, `POST /logout`, `/change-password`, `POST /api/change-password` | `app.py` |
| Info bar (top bar): counts (`infobar_count_items`, `headline_counts`, `league_count`, `latest_season_id`) and the last successful Impect / SkillCorner pull dates from `pipeline_runs` (`pull_dates`, `pull_date_items`) | `src/lofc/core/infobar.py` |
| JS (ES module `/static/js/common.js`): `esc`, `num`, `dash`, `roundHalfUp`, `fmtInt`, `chip`, `pcol`, `pctNum`, `bar`, `thead`, `pills`, `radar`, `api`, `readState`, `writeState`, `onStateChange` | `static/js/common.js` |
| Remembered settings (owner 2026-11-13): `rememberState(page)` saves the page's query string in that browser (`localStorage`, key `lofc.<page>.last`); `restoreState(page)` reopens it when the URL is bare (the nav link). A URL with settings wins. Storage off = nothing remembered, page works as before. Used by Players, Physical, Squads, Scout reports, Watchlist, Compare, Club vs League One, Report | `static/js/common.js` |
| Report: preview and downloads are the same sheet; the download is built in the browser (`Blob`), authored or data-only; drafts kept in that browser (`lofc.report.draft.*`); the photo is never stored | `static/js/report.js`, `report_draft.js`, `report_search.js` |
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

1. **Never recompute a number in JavaScript or in new Python.** Call the existing function. New
   page logic goes in `src/lofc/core/` as a pure function the API calls; where Streamlit shows
   the same thing it calls the same function.
2. **Parity:** where a Streamlit page still exists, the API's numbers equal it for the same
   inputs (existing parity tests stay green on the real database). Calculations use exact
   values; rounding is display-only.
3. **Nothing on a page disappears silently** (`club_docs/design/inventory.md` lists what the
   Streamlit pages had). Every change is shown to the owner as quoted "before → after" and
   logged in `plan/TASKS.md`.
4. Owner rules: blanks show "—" (never None/nan/NaN/undefined), minutes/goals round half-up,
   no StatsBomb in UI text, short labels, provider definitions, no league-weighting caveats,
   `objective_composite` is the ranking and scout input never changes it, thin peer pools
   (< `MIN_PEERS_FOR_RANKING`) are never shown as a rating: every percentile and band is "—" and
   one line says why ("Not rated: only N <Position>s in <League> with 450+ minutes (needs 10)");
   a midfielder rated in the combined midfield pool is tagged "Rated against all midfielders"
   and gets no rank. Strengths / Watch-outs: strongest = top ceil(n/2), at most 3; weakest = the
   rest, at most 3; a metric is never in both (`core/card.split_strong_weak`).
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

## Pages (navigation from `web/pages.py`)

| Group | Page | Status | Core / API |
|---|---|---|---|
| Find | Players + player card | Live. Players: one tab per chosen league, each ranked within its league (owner 2026-11-20; `league=` in the URL; CSV one block per league with "League" and "Rank in league"). Card: "vs ours" columns (incl. All tracked and Other physical), Strengths / Watch-outs, "Against our <position>" (ratings compared only with ours rated in his league that season, owner 2B; "Every metric, player by player" and "vs ours" are RAW values for every target, green best / red worst, owner 2026-11-20; rows at the card's position only). Players "More filters": 4-column grid + "Reset filters" (owner 2026-11-20) | `core/players_pool.py`, `core/card.py`, `core/squad.py` · `api/players.py`, `api/card.py` |
| Assess a player (nav, owner 2026-11-20) | Similar players `/similar` (Season + player search) and `/similar/<p>/<c>/<s>` | The card's list + filters, one match broken down, Open in Compare; the card's "How these are matched →" / "Why" open it on a player. JSON `/api/similar/<p>/<c>/<s>`; the card section uses `/api/card/<p>/<c>/<s>/similar` | `core/similar.py` · `api/similar.py` |
| Find | Squads & loans | Live; rebuilt 2026-11-16: League → Club → squad (Impect minutes at the club + Transfermarkt-registered), views Squad / Loans in / Loans out, CSV | `core/squad_lists.py` · `api/squads.py` |
| Assess a player | Compare | Live; up to 3 players, each with his own season (`a_season=`; owner 2026-11-20) — when leagues/seasons differ: no best/worst colours, no deltas, one line "Ratings and percentiles are within each player's own league and season."; Orient line only beside League One players of its season, from ours rated in League One; opening picks from one league; remembers the last comparison; download | `core/compare.py` · `api/compare.py` |
| Assess a player | Scout reports | Live; Data vs scout and Squad role filters; Refresh reads the sheet | `core/scout_reports_page.py` · `api/scout_reports.py` |
| Decide | Watchlist | Live; CSV download (redesign parked) | `core/watchlist_page.py` · `api/watchlist.py` |
| Decide | Report | Live; one wide sheet; authored / data-only downloads made in the browser; photo; availability rows; scout verdicts; drafts in the browser; search lists every player A–Z | `core/report_page.py` · `api/report.py` |
| Decide | Assess, Sign-off | **"Currently building"** (`templates/page.html`); still on the Streamlit fallback | — |
| Analysis | Physical | Live; leaders; Two metrics (medians, "Better on both", top 5, min-minutes slider, find list, lower-is-better axes reversed); Orient squad Physical \| Performance + Excel | `core/physical_page.py` · `api/physical.py` |
| Analysis | Club vs League One | Live; rules in `docs/methodology.md` | `core/club_vs_league.py` · `api/club_vs_league.py` |
| Reference | What goes into each rating (Excel download) · How playing styles work · Glossary | Live | `api/reference.py` |
| Admin | Users | Live (admins only) | `api/users.py` |

Not rebuilt: Methodology (hidden on Streamlit), Style lab (workstation-only tool).

## Testing (every page, before it is called done)

| Layer | Tool | Rule |
|---|---|---|
| Unit + API | pytest + FastAPI TestClient, in the `app` container (`nice -n 15`) | test first |
| Parity | pytest on the real DB | API numbers = Streamlit's where both exist |
| JS rules | `node --test tests/js/` on the Mac (node is not in the container) | pure helpers (remembered settings, report search) |
| Browser | `scripts/web_check.py` (Playwright, Python, driving the Mac's installed Chrome — `channel="chrome"`, no browser download) | logs in, clicks every control on every page, fails on any console error, failed request, visible "None/nan/undefined", overflow beyond a card, or a click > 1 s warm; saves screenshots at 1440×900 to `club_docs/design/web_shots/` |
| Old site | `scripts/smoke_test.py` (Streamlit AppTest + SQL checks; does not open the web pages) | must still pass after any `core/` change while Streamlit exists |

## Resource rules (the owner works on this Mac)

One heavy job at a time (full suite, smoke, browser run). Docker Desktop 4 CPUs / 6 GB;
containers `app` 2 CPUs, `web` 1.5, `db` 1.5 (DEPLOY.md → "Working on the Mac"). Tests run in
the capped `app` container with `docker compose exec` and `nice -n 15` (never `docker compose
run`); the harness runs on the host under `nice -n 15`. A timing failure on a busy Mac is re-run
when quiet before it counts. No large downloads beyond the `playwright` Python package. Never
touch the live server, git commits, or `.env`.

## Browser harness — how page builders use it

- Setup once (host, not Docker): venv at the session scratchpad `webvenv` with `playwright` +
  `pytest` (no browser download; drives the Mac's Chrome). Run:
  `nice -n 15 <venv>/bin/python scripts/web_check.py --pages <page> --quick` while building;
  `--only <scenario>[,<scenario>]` runs just those scenarios (no layout pass, no exerciser) to
  iterate on one fix; all pages without `--quick` before calling work done. Other options:
  `--widths 1280,1440,1920`, `--role`, `--max-actions`, `--base` (localhost only). Exit 1 = a failure; screenshots + `results.json` in
  `club_docs/design/web_shots/`.
- It logs in with a throwaway `webcheck_<hex>` account it creates and deletes in the LOCAL
  database (never a real password). Write buttons are skipped unless `--allow-writes` (Mac only);
  Scout reports "Refresh" (reads the club's Google sheet) is never pressed (`is_external`).
- Make controls discoverable: clickable rows/cards need `data-href` or `data-action`; give
  every control a visible label or `aria-label` (scenarios find controls by label).
- Each page builder corrects its own entry in `scripts/web_check_pages.py` (`PAGES` paths and
  scenario labels) and adds that page's scenarios (e.g. Players: position → season → open →
  back keeps filters; back/forward; shareable URL).
