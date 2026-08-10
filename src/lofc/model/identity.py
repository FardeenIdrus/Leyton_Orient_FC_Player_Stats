"""Player identity from the Transfermarkt squad scrape -- independent of valuation.

WHY THIS EXISTS: `valuation.load_efl_values()` drops every scraped row without a market
value before matching, which also throws away that player's Transfermarkt id, birth date,
foot and contract date. Transfermarkt prices only 15 of 596 National League players, so
that league ended up with a TM id for 8% of players against 68-78% in the divisions above.

A Transfermarkt id is an IDENTITY fact; a market value is a COMMERCIAL one. One must not
gate the other. This module matches identity over the FULL scrape.

`valuation.match_players_efl` is deliberately left untouched -- it still owns valuation,
and this runs alongside it. The name-normalisation helpers are imported rather than copied
so the two matchers cannot drift apart.

Run:  python -m lofc.model.identity
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pandas as pd
from sqlalchemy import bindparam, create_engine, update

from lofc.config import settings
from lofc.model.valuation import (
    EFL_LEAGUE_IDS,
    EFL_SEASON_ID,
    _dob_name_match,
    _norm,
    _tmdir,
)
from lofc.store.models import Player

IDENTITY_COLUMNS = ["player_id", "tm_player_id", "birth_date", "foot",
                    "contract_until", "height_cm"]


def load_efl_identity(path: Path | None = None) -> pd.DataFrame:
    """Every scraped squad row that carries a Transfermarkt id and a birth date.

    Deliberately does NOT filter on market_value_eur -- that is the bug this fixes.
    """
    path = path or (_tmdir() / "efl_values.csv")
    frame = pd.read_csv(path)
    frame["nname"] = frame["player_name"].map(_norm)
    frame["birth_date"] = pd.to_datetime(frame["date_of_birth"], errors="coerce")
    frame["tm_player_id"] = pd.to_numeric(frame["tm_player_id"], errors="coerce")
    frame = frame.dropna(subset=["birth_date", "tm_player_id"])
    return frame.reset_index(drop=True)


def match_identity(ours: pd.DataFrame, squad: pd.DataFrame) -> pd.DataFrame:
    """Link our players to their Transfermarkt row on exact birth date + name,
    within the same league.

    `ours` needs columns: player_id, player_name, birth_date, competition_id.
    Birth date is required on both sides -- a name-only match is not safe enough to
    write an identity, as the 54-namesake audit showed.
    """
    by_dob: dict[tuple[int, object], list[int]] = defaultdict(list)
    for i, row in enumerate(squad.itertuples()):
        by_dob[(row.competition_id, row.birth_date.date())].append(i)

    rows = []
    for r in ours.itertuples():
        if pd.isna(r.birth_date):
            continue
        dob = pd.to_datetime(r.birth_date).date()
        i = _dob_name_match(_norm(r.player_name),
                            by_dob.get((r.competition_id, dob), []), squad)
        if i is None:
            continue

        def cell(name, cast=None):
            if name not in squad.columns:
                return None
            value = squad.at[i, name]
            if pd.isna(value) or value == "":
                return None
            return cast(value) if cast else value

        rows.append({
            "player_id": int(r.player_id),
            "tm_player_id": int(squad.at[i, "tm_player_id"]),
            "birth_date": dob,
            "foot": cell("foot"),
            "contract_until": cell("contract_until"),
            "height_cm": cell("height_cm", int),
        })
    return pd.DataFrame(rows, columns=IDENTITY_COLUMNS)


def main() -> None:
    path = _tmdir() / "efl_values.csv"
    if not path.exists():
        print(f"{path} not found -- run lofc.ingest.transfermarkt_efl first")
        return

    engine = create_engine(settings.database_url)
    ours = pd.read_sql(
        "SELECT DISTINCT n.player_id, p.player_name, p.birth_date, n.competition_id "
        "FROM player_metrics_neutral n JOIN players p ON p.player_id = n.player_id "
        f"WHERE n.season_id = {EFL_SEASON_ID} "
        f"AND n.competition_id IN ({','.join(str(c) for c in sorted(EFL_LEAGUE_IDS))})",
        engine)

    matched = match_identity(ours, load_efl_identity(path))
    if matched.empty:
        print("no identity matches")
        return

    stmt = (update(Player.__table__)
            .where(Player.__table__.c.player_id == bindparam("pid"))
            .values(tm_player_id=bindparam("tm"), foot=bindparam("ft"),
                    contract_until=bindparam("cu"), height_cm=bindparam("hc")))
    with engine.begin() as conn:
        conn.execute(stmt, [
            {"pid": int(r.player_id), "tm": int(r.tm_player_id),
             "ft": r.foot if pd.notna(r.foot) else None,
             "cu": r.contract_until if pd.notna(r.contract_until) else None,
             "hc": int(r.height_cm) if pd.notna(r.height_cm) else None}
            for r in matched.itertuples()])
    print(f"identity: linked {len(matched)} players to Transfermarkt")


if __name__ == "__main__":
    main()
