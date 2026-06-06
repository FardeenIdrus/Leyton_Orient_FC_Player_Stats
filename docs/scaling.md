# Scaling and growth path

This documents what was deliberately left out of v1 and the conditions that would justify
adding it. The judgement throughout: keep v1 lean and honest, and add infrastructure only
when data volume or scope earns it, not before.

## Deliberately excluded from v1

### MongoDB
- **Why not now:** the working dataset is player-season metrics, a few thousand structured
  rows. StatsBomb returns JSON, but it aggregates down to clean numbers. A second database is
  operational cost for no v1 benefit; a Postgres `JSONB` column covers any raw-JSON need.
- **When to add:** if we land many leagues of raw event payloads and want a document store for
  the unaggregated JSON, or semi-structured scouting notes that do not fit relational tables.

### MinIO / object storage
- **Why not now:** raw pulls (a few GB) sit fine on the filesystem for a single-club build, and
  they are reproducible from source.
- **When to add:** when raw data spans many leagues and seasons and needs a shared, versioned
  store across machines or a deployed cluster, rather than one server's disk.

### Power BI / Tableau / Metabase
- **Why not now:** these are visualisation layers over an existing data model. They do not build
  the valuation model, which is the actual deliverable. Streamlit ships the model and UI as one
  unit with no licensing tie to the club server.
- **When to add:** when the commercial, academy or board side wants self-serve reporting over the
  same warehouse. A BI tool then sits alongside the recruitment app, not instead of it.

The narrative: these tools are known and were used on prior work; the call was to keep v1 lean
with a documented path to add them when the data volume justifies it.

## Triggers for the next step

| Trigger | Action |
|---|---|
| Paid StatsBomb licence granted | Set `USE_OPEN_DATA=false` + credentials in `.env`; point `config.py` at League One and target leagues. Pipeline is otherwise unchanged. |
| Need League One market values | Add a GB3 source (the same Transfermarkt scraper schema) alongside the existing values. |
| Club provides its wage framework / identity profile | Replace the CSVs in `data/reference/`; reload. No code change. |
| Real player wages available | Replace `wage_estimates` with the club's salary data; the wage gate becomes exact. |
| Many leagues / seasons of raw data | Move raw landing to object storage; consider a document store for unaggregated JSON. |
| Cross-league comparison required | Add a league-strength adjustment so percentiles are comparable across divisions. |
| Commercial / academy reporting demand | Add a BI tool over the warehouse for self-serve dashboards. |

## The wider BI platform

The recruitment engine is the first chapter. The same Postgres warehouse and Docker deployment
generalise to:

- **Player development analytics** — the same per-90 + percentile machinery applied to academy
  and first-team progression over time.
- **Commercial intelligence** — attendance, revenue and ticketing on the same store, surfaced
  through a BI tool.
- **Academy pathways** — archetype and valuation models pointed at youth data.
- **Sister-club / multi-club** — multiple clubs' data in one warehouse; the league dimension
  the schema already carries extends to a club dimension.

Each is an additive workstream on the same foundation, which is why v1 keeps the foundation
clean rather than over-building for a future that has not arrived.
