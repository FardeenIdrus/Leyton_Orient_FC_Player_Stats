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
