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
