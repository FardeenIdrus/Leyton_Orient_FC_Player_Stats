"""Coverage report for the SkillCorner platform pulls (read-only).

Answers, per edition: how many players did we land, and how many tie to a player
already in our database (birth date + name, the same technique the Transfermarkt
and Impect matching use). For the leagues we track as event data (the EFL), a high
match rate means physical data is available for those candidates; for leagues we do
not yet hold as players (Scottish/PL2/Irish), a low rate is expected until those
players are ingested.

Writes nothing to the database.

Run with:  python -m lofc.model.skillcorner_check
"""

from __future__ import annotations

import pandas as pd

from lofc.config import SkillCornerTarget, settings
from lofc.ingest import skillcorner_api
from lofc.model.valuation import _dob_name_match, _norm
from lofc.store.load import get_engine


def match_to_ours(physical: pd.DataFrame, ours: pd.DataFrame,
                  league_name_index: dict[str, int] | None = None) -> pd.DataFrame:
    """Attach our player_id to each SkillCorner row via birth date + name.

    SkillCorner carries its own player ids only, so matching is birth date +
    fuzzy name at the EFL cutoff, plus the same two rescues as the Impect matcher:
    the DAY/MONTH-SWAP rescue (SkillCorner lists Luke Harris as 04 Mar where
    StatsBomb has 03 Apr), and — when `league_name_index` is supplied — the
    EXACT-NAME-WITHIN-LEAGUE rescue for genuine provider birth-date disagreements
    (unique name on both sides within one league season). Unmatched rows keep
    player_id_ours NaN.
    """
    from lofc.model.impect_check import (_dob_surname_rescue, _exact_name_league_rescue,
                                          _swapped_date_match)
    ours = ours.copy()
    ours["birth_date"] = pd.to_datetime(ours["birth_date"], errors="coerce")
    ours["nname"] = ours["player_name"].map(_norm)   # _dob_name_match reads this

    result = physical.copy()
    result["birth_date"] = pd.to_datetime(result["player_birthdate"], errors="coerce")
    result["player_id"] = pd.NA

    by_dob: dict = {}
    for i, row in enumerate(ours.itertuples()):
        if pd.notna(row.birth_date):
            by_dob.setdefault(row.birth_date.date(), []).append(i)

    for idx, row in result.iterrows():
        if pd.notna(row["birth_date"]):
            nname = _norm(row["player_name"])
            i = _dob_name_match(nname, by_dob.get(row["birth_date"].date(), []), ours)
            if i is None:
                i = _swapped_date_match(nname, row["birth_date"], by_dob, ours)
            if i is not None:
                result.at[idx, "player_id"] = ours.at[i, "player_id"]

    _dob_surname_rescue(result, "player_name", by_dob, ours)
    if league_name_index:
        _exact_name_league_rescue(result, "player_name", league_name_index)
    # keep the historic column name the callers expect
    return result.rename(columns={"player_id": "player_id_ours"})


def check_target(target: SkillCornerTarget, ours: pd.DataFrame) -> dict:
    path = skillcorner_api.physical_path(target.edition_id)
    if not path.exists():
        return {"label": target.label, "status": "NOT PULLED"}
    physical = pd.read_parquet(path)
    matched = match_to_ours(physical, ours)
    tracked = target.competition_id is not None
    return {
        "label": target.label,
        "status": "OK",
        "tracked_league": tracked,
        "players": physical["player_id"].nunique(),
        "matched_pct": float(matched["player_id_ours"].notna().mean() * 100),
        "matched_n": int(matched["player_id_ours"].notna().sum()),
    }


def main() -> None:
    engine = get_engine()
    ours = pd.read_sql("SELECT player_id, player_name, birth_date FROM players", engine)
    print("SkillCorner coverage report (read-only)")
    print("=" * 72)
    for target in settings.skillcorner_targets:
        r = check_target(target, ours)
        if r["status"] != "OK":
            print(f"\n[{r['label']}] {r['status']}")
            continue
        tag = "tracked league" if r["tracked_league"] else "not-yet-tracked (few matches expected)"
        print(f"\n[{r['label']}] {r['players']} players | {tag}")
        print(f"  tie to a player already in our DB: {r['matched_pct']:.1f}% ({r['matched_n']})")
    print("\nDone. For the EFL editions a high match rate means physical data is now "
          "available for those candidates (the squad-only limitation is lifted).")


if __name__ == "__main__":
    main()
