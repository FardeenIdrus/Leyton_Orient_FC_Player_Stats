"""The info bar's numbers: which dataset am I looking at. Lifted out of the Streamlit
loaders/players page so the web front end shows exactly the same counts."""

from __future__ import annotations

import pandas as pd

from lofc.aggregate.player_season import RANKABLE_MINUTES


def infobar_count_items(players: int, rated: int) -> list[str]:
    """The info bar's two player counts: everyone with data, and the rated subset the table
    lists. Both are shown so neither is read as the denominator of the other."""
    return [
        f"<b>{players:,}</b> players",
        f"<b>{rated:,}</b> rated ({RANKABLE_MINUTES}+ mins)",
    ]


def headline_counts(engine, season_id: int | None = None) -> tuple[int, int, int]:
    """Top-level counts for the KPI strip, for ONE season (from the combined table, so all 7
    leagues — not the EFL-only spine): (players with any data, players with a rating, leagues).

    Both player counts are returned because they differ by everyone under the minutes floor
    (4,376 vs 3,229 on 2025/26), and the Players table lists only the rated ones. Showing the
    wider count alone led a reader to divide a table count by it."""
    where = f"WHERE season_id = {int(season_id)}" if season_id is not None else ""
    players = pd.read_sql(
        f"SELECT COUNT(DISTINCT player_id) AS c FROM player_metrics_neutral {where}", engine)["c"][0]
    rated_where = (f"{where} AND" if where else "WHERE") + (
        " archetype = 'All Metrics' AND objective_composite IS NOT NULL")
    rated = pd.read_sql(
        f"SELECT COUNT(DISTINCT player_id) AS c FROM player_scorecards {rated_where}", engine)["c"][0]
    leagues = pd.read_sql(
        f"SELECT COUNT(DISTINCT competition_id) AS c FROM player_metrics_neutral {where}", engine)["c"][0]
    return int(players), int(rated), int(leagues)


def league_count(engine) -> int:
    """Leagues present in the combined table across every season (what the Streamlit strip
    shows as `len(league_names())`: one name per distinct competition_id)."""
    ids = pd.read_sql("SELECT DISTINCT competition_id FROM player_metrics_neutral", engine)
    return int(len(ids))


def latest_season_id(engine) -> int | None:
    """The season the Players page opens on (`seasons.default_season_id` = the newest held)."""
    value = pd.read_sql("SELECT MAX(season_id) AS s FROM player_metrics_neutral", engine)["s"][0]
    return int(value) if pd.notna(value) else None


# The main per-league pull steps (`ingest.impect` / `ingest.skillcorner_api` record one row per
# league). The pipeline's whole-step rows ("Pull Impect player data", "Pull SkillCorner physical
# data (platform)") end with "partial" when any league failed, so they would hide a pull that did
# land for most leagues.
PULL_STEPS = {"Impect": "Pull Impect", "SkillCorner": "Pull SkillCorner"}


def pull_dates(engine) -> dict:
    """Provider -> date of the latest SUCCESSFUL main pull (None if never, or no table)."""
    out = {k: None for k in PULL_STEPS}
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT step, MAX(finished_at) FROM pipeline_runs WHERE status = 'success' "
                "AND step IN ('Pull Impect', 'Pull SkillCorner') GROUP BY step")).fetchall()
    except Exception:                                           # noqa: BLE001 (not migrated)
        return out
    by_step = {s: w for s, w in rows}
    for name, step in PULL_STEPS.items():
        when = by_step.get(step)
        if when is not None:
            out[name] = pd.Timestamp(when).date()
    return out


def pull_date_items(dates: dict) -> list[str]:
    """["Impect <b>13 Nov</b>", "SkillCorner <b>13 Nov</b>"]; "—" for a provider never pulled."""
    return [f"{name} <b>{'—' if d is None else f'{d.day} {d:%b}'}</b>"
            for name, d in ((k, dates.get(k)) for k in PULL_STEPS)]
