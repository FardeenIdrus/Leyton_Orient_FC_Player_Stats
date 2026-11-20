"""Transfermarkt club name -> Impect squad, for clubs whose names differ.

Transfermarkt says "Reading FC", Impect "FC Reading"; "Rangers FC" / "Glasgow Rangers". The
Squads & loans page joins the Transfermarkt squad list (contracts, loans) to Impect's clubs
(minutes), so every Transfermarkt club needs its Impect squad. An exact name needs nothing; the
others are listed in `reference/club_crosswalk.csv`, seeded by a normalised-name match (drop
FC / AFC / CF, fold accents) and finished by hand. Never guessed: two Impect squads with one
normalised name are left for a hand-made row, and a clash fails loudly.

Run with:  python -m lofc.model.club_crosswalk           (report unmatched clubs)
           python -m lofc.model.club_crosswalk --seed    (rewrite the list; hand rows kept)
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pandas as pd

PATH = Path(__file__).resolve().parents[1] / "reference" / "club_crosswalk.csv"
COLUMNS = ["tm_club_name", "impect_squad_id", "impect_team_name", "match", "note"]
_DROP = {"fc", "afc", "cf"}


def normalise(name) -> str:
    """Lower case, accents folded, punctuation dropped, FC / AFC / CF removed."""
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    words = [w for w in re.split(r"[^a-z0-9]+", text) if w and w not in _DROP]
    return " ".join(words)


def seed(tm_clubs, squads: dict, existing: pd.DataFrame | None = None) -> pd.DataFrame:
    """The list's rows: hand-made rows in `existing` are kept; every other Transfermarkt club
    whose exact name is not an Impect squad is matched by `normalise` when exactly one squad
    shares its key. `squads`: Impect squad id -> name."""
    names = set(squads.values())
    keep = (existing[existing["match"] == "manual"] if existing is not None and len(existing)
            else pd.DataFrame(columns=COLUMNS))
    by_key: dict[str, list] = {}
    for sid, name in squads.items():
        by_key.setdefault(normalise(name), []).append((int(sid), name))
    rows = []
    for club in sorted(set(tm_clubs)):
        if club in names or club in set(keep["tm_club_name"]):
            continue
        hits = by_key.get(normalise(club), [])
        if len(hits) == 1:
            rows.append({"tm_club_name": club, "impect_squad_id": hits[0][0],
                         "impect_team_name": hits[0][1], "match": "normalised", "note": ""})
    out = pd.concat([keep[COLUMNS], pd.DataFrame(rows, columns=COLUMNS)], ignore_index=True)
    return out.sort_values("tm_club_name").reset_index(drop=True)


def _check(walk: pd.DataFrame, where: str) -> None:
    dup = walk.loc[walk["tm_club_name"].duplicated(), "tm_club_name"].tolist()
    if dup:
        raise ValueError(f"{where}: Transfermarkt club listed more than once: {dup}")
    clash = walk[walk["impect_team_name"].duplicated(keep=False)]
    if len(clash):
        raise ValueError(f"{where}: two Transfermarkt clubs name one Impect squad: "
                         f"{sorted(clash['tm_club_name'])}")


def load(path: Path = PATH) -> pd.DataFrame:
    """The committed list. A missing column, a blank Impect name, a club listed twice or two
    clubs on one Impect squad fail loudly: a wrong join puts players at the wrong club."""
    if not Path(path).exists():
        return pd.DataFrame(columns=COLUMNS)
    walk = pd.read_csv(path, dtype={"tm_club_name": str, "impect_team_name": str,
                                    "match": str, "note": str}, keep_default_na=False)
    missing = [c for c in COLUMNS if c not in walk.columns]
    if missing:
        raise ValueError(f"{path}: missing column(s) {missing}")
    walk["tm_club_name"] = walk["tm_club_name"].str.strip()
    walk["impect_team_name"] = walk["impect_team_name"].str.strip()
    if (walk["impect_team_name"] == "").any() or (walk["tm_club_name"] == "").any():
        raise ValueError(f"{path}: every row needs tm_club_name and impect_team_name")
    _check(walk, str(path))
    return walk[COLUMNS]


def resolve(tm_clubs, impect_names, walk: pd.DataFrame) -> dict[str, str]:
    """{Transfermarkt club: Impect squad name} for every club that has one -- its own name when
    Impect uses it, else the list's. Two Transfermarkt clubs on one Impect squad fail loudly."""
    names = set(impect_names)
    listed = dict(zip(walk["tm_club_name"], walk["impect_team_name"])) if len(walk) else {}
    out = {}
    for club in dict.fromkeys(tm_clubs):
        if club in listed:
            out[club] = listed[club]
        elif club in names:
            out[club] = club
    seen: dict[str, str] = {}
    for club, squad in out.items():
        if squad in seen:
            raise ValueError(f"two Transfermarkt clubs name one Impect squad ({squad}): "
                             f"{sorted([seen[squad], club])}")
        seen[squad] = club
    return out


def unmatched(tm_clubs, squads: dict, walk: pd.DataFrame) -> list[str]:
    """Transfermarkt clubs with no Impect squad, exact or listed."""
    got = resolve(tm_clubs, squads.values(), walk)
    return sorted(set(tm_clubs) - set(got))


def impect_names(engine) -> list[str]:
    """Every Impect squad name the database holds (per-club minutes, current clubs, the
    combined table)."""
    frame = pd.read_sql(
        "SELECT team_name AS n FROM impect_squad_minutes UNION "
        "SELECT club_name FROM player_current_club WHERE club_name IS NOT NULL UNION "
        "SELECT DISTINCT team_name FROM player_metrics_neutral", engine)
    return sorted(set(frame["n"].dropna()))


def main(argv=None) -> None:
    import argparse
    import json
    from lofc.store.load import get_engine
    from lofc.ingest.impect import squad_names_path

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seed", action="store_true", help="rewrite the list (hand rows kept)")
    args = ap.parse_args(argv)
    engine = get_engine()
    tm = pd.read_sql("SELECT DISTINCT club_name FROM transfermarkt_squads UNION "
                     "SELECT DISTINCT club_name FROM player_loans UNION "
                     "SELECT DISTINCT parent_club FROM player_loans "
                     "WHERE parent_club IS NOT NULL", engine)["club_name"].tolist()
    squads = {}
    path = squad_names_path()
    if path.exists():
        squads = {int(k): v for k, v in json.loads(path.read_text()).items()}
    walk = load()
    if args.seed:
        walk = seed(tm, squads, walk)
        _check(walk, "seeded list")
        walk.to_csv(PATH, index=False)
        print(f"{PATH.name}: {len(walk)} rows written")
    squad_clubs = pd.read_sql("SELECT DISTINCT club_name FROM transfermarkt_squads",
                              engine)["club_name"].tolist()
    left = unmatched(squad_clubs, {i: n for i, n in enumerate(
        set(squads.values()) | set(impect_names(engine)))}, walk)
    print(f"Transfermarkt squad clubs with no Impect squad: {left or 'none'}")


if __name__ == "__main__":
    main()
