# Scaling and growth path

> **STATUS (reviewed 2026-08-10):** the biggest growth step named here — richer data sources —
> is now underway. Phase 11 is integrating **Impect** (primary event data), the
> **StatsBomb advanced feed**, and the **SkillCorner physical platform** (physical data
> for recruitment targets, not just our squad). See **`docs/DATA_ARCHITECTURE.md`** for
> the four-source metric layer. The playbooks below (adding a league, deployment) still
> apply.

This documents what was deliberately left out of v1 and the conditions that would
justify adding it, plus the concrete playbooks for the growth steps that are already
foreseeable (adding a league, deploying off the laptop, richer valuation inputs).
The judgement throughout: keep v1 lean and honest, and add infrastructure only when
data volume or scope earns it, not before.

## Deliberately excluded from v1

### MongoDB
- **Why not now:** the working dataset is player-season metrics, thousands of
  structured rows. StatsBomb returns JSON, but it aggregates down to clean numbers. A
  second database is operational cost for no v1 benefit; a Postgres `JSONB` column
  covers any raw-JSON need.
- **When to add:** many leagues of raw event payloads wanted queryable in their
  unaggregated form, or semi-structured scouting notes that do not fit relational
  tables.

### MinIO / object storage
- **Why not now:** raw pulls (24 GB for the 8 EFL league-seasons) sit fine on the
  filesystem for a single-club build, and they are reproducible from source.
- **When to add:** raw data spanning many leagues and seasons needing a shared,
  versioned store across machines or a deployed cluster, rather than one server's
  disk.

### Power BI / Tableau
- **Why not now:** visualisation layers over an existing data model. They do not
  build the valuation model, which is the actual deliverable. Streamlit ships the
  model and UI as one unit with no licensing tie to the club server.
- **When to add:** when the commercial, academy or board side wants self-serve
  reporting over the same warehouse. A BI tool then sits alongside the recruitment
  app, not instead of it.
- **In this build:** a **Metabase** instance is included (open-source,
  http://localhost:3000) as a working demonstration of exactly that layer over the
  same Postgres warehouse, kept deliberately separate from the recruitment app.

## Playbook: adding a league

Most of the system is league-agnostic; three places carry league knowledge. Adding a
league (say the Scottish Premiership, which the licence covers) means:

1. **Ingest** — add `competition_id:season_id:label` to `SB_COMPETITIONS` in `.env`
   and re-up the containers. Ingest, aggregation, percentiles, scores and styles need
   **no code change**: percentiles are computed within whatever leagues exist.
2. **Market values** — add the league to the scraper's `LEAGUES` map in
   `ingest/transfermarkt_efl.py` (Transfermarkt league code + slug). One dict entry;
   the scrape, matching and valuation pick it up. Check TM's value coverage first —
   below ~50% coverage the league should follow the National League precedent
   (scores and styles yes, valuation no).
3. **Wages** — add league anchors to `store/reference_data.py` (sourced, like the
   existing four), then **re-run the payroll reconciliation**
   (`python -m lofc.model.wage_check`) and correct any anchor it flags. This
   validation step is not optional; it caught a 30% error in the Championship anchor.

One honest constraint: continental leagues run calendar-season (spring–autumn), so
their "current season" does not align with the EFL winter season; the season-id
targeting handles it, but cross-league season comparisons need care. This is why
they were deferred rather than bolted on before the demo.

## Playbook: deployment (when the club wants it off a laptop)

The stack is a compose file, so deployment is a lift, not a rebuild:

1. **A rented VM** (any provider) with Docker; `git clone`, restore `.env`
   (credentials never leave `.env`), `docker compose up -d`.
2. **Reverse proxy** (Caddy: two lines per service, automatic TLS) exposing the
   dashboard; pgAdmin/Metabase stay internal or behind the same auth.
3. **Access control** — the simplest honest options are Cloudflare Access (email
   allowlist in front of the domain) or Tailscale (the dashboard only exists on the
   club's private network). Streamlit itself has no user accounts; do not expose it
   bare.
4. **Refresh** — a weekly cron running `python -m lofc.pipeline` (every step is
   idempotent, so a failed run is re-runnable), timed after match weekends. The TM
   scrape stays rate-limited and infrequent.
5. **Backups** — nightly `pg_dump`. The only unreproducible data is the watchlist
   (user data) and the reference CSVs; everything else rebuilds from source.

Single shared Postgres; the watchlist becomes multi-user by adding a `user_id`
column + auth in front (the table design anticipates it).

## Richer valuation inputs (the measured next step)

The reliability analysis (see `methodology.md` §5) shows the valuation's ceiling is
**feature relevance, not data volume**: contract situation, potential and reputation
drive prices and are absent. The club has granted access to the **FM Database** and
**Impect** data, which carry exactly those feature classes (contract length,
potential ratings, richer positional metrics). The intended path: interrogate the new
sources first (coverage, join keys, honesty of the ratings), then trial features into
the valuation model one class at a time, measuring the within-league error each step
— the same measure-then-trust loop used for the wage anchors. This is deliberately
iterative work, not a one-shot integration.

## Triggers for the next step

| Trigger | Action |
|---|---|
| Club provides its wage framework / identity profile | Replace the CSVs in `data/reference/`; reload. No code change. |
| Real player wages available | Replace `wage_estimates` with the club's salary data; the wage gate becomes exact. |
| New target league | Follow the adding-a-league playbook above. |
| Tool wanted by staff day-to-day | Follow the deployment playbook above. |
| Point-estimate accuracy matters (fee negotiations) | FM DB / Impect feature integration; contract length first. |
| Candidate tracking data purchasable | SkillCorner (or similar) for target leagues would unlock physical scoring of candidates — the one thing the current data honestly refuses. |
| Many leagues / seasons of raw data | Move raw landing to object storage; consider a document store for unaggregated JSON. |
| Cross-league percentile comparison required | Add a league-strength adjustment; today the valuation model is where league level is handled. |
| Commercial / academy reporting demand | Grow the Metabase layer over the same warehouse. |

## The wider BI platform

The recruitment engine is the first chapter. The same Postgres warehouse and Docker
deployment generalise to:

- **Player development analytics** — the same per-90 + percentile machinery applied
  to academy and first-team progression over time (the two-season trajectory view is
  the seed of this).
- **Commercial intelligence** — attendance, revenue and ticketing on the same store,
  surfaced through the Metabase layer.
- **Academy pathways** — style and valuation models pointed at youth data (PL2 is
  already on the licence).
- **Sister-club / multi-club** — multiple clubs' data in one warehouse; the league
  dimension the schema already carries extends to a club dimension.

Each is an additive workstream on the same foundation, which is why v1 keeps the
foundation clean rather than over-building for a future that has not arrived.
