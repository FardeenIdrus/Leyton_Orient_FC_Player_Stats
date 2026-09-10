"""Fill players.foot and players.nationality, from the best source for each field.

WHY A PRIORITY LIST AND NOT A GENERIC "WATERFALL":
only two fields actually have two sources. Height and contract expiry exist ONLY in
Transfermarkt -- Impect ships neither, verified across all 1,482 parquet columns and all
25 API endpoints. So the useful thing here is not machinery, it is a DECLARED, auditable
order per field:

  foot        Transfermarkt -> Impect   TM is a squad-page fact about a registered player;
                                        Impect infers it from play. TM first where scraped,
                                        Impect fills the rest (85-99% in every league).
  nationality Impect -> Transfermarkt   Impect carries it at ~100% in every league and the
                                        column has never been written by anything at all.

THE STORED VALUE ALWAYS WINS over both. This fills gaps; it never corrects. Only 16
players have a foot value from two sources and they agree on 13 -- far too small a sample
to justify overwriting values a scrape already established.

Read-only except `apply`.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import bindparam, func, update

from lofc.store.models import Player

# Impect ships LEG as an upper-case enum; the stored convention is lowercase, and
# dashboard/app.py filters with .isin([choice.lower(), "both"]). An upper-case value would
# silently exclude every Impect-sourced player from the preferred-foot filter.
IMPECT_FOOT = {"LEFT": "left", "RIGHT": "right", "BOTH": "both"}
TM_FOOT = {"left": "left", "right": "right", "both": "both"}

BIO_COLUMNS = ["player_id", "foot", "nationality", "contract_until"]

# Contracts come from the live squad scrape, which reads CURRENT squad pages. A player who
# has since left our seven leagues has no current squad page, so no contract -- Miguel
# Freckleton played 3,541 minutes in the 25/26 Scottish Premiership and left St Mirren, so
# the platform held nothing while Transfermarkt's own profile page shows his contract to
# 31 May 2027. The static reference dump DOES carry him. It is a snapshot roughly a year
# old, so it is a FALLBACK only: it never overwrites a live scrape, and any date that has
# already passed is discarded rather than presented as current.


def _first_present(frames: list[pd.DataFrame], column: str) -> pd.Series:
    """Per player_id, the first non-null value across `frames`, in the order given.

    This IS the waterfall: order of the list is the source priority, stated by the caller
    rather than buried in merge logic.
    """
    out = pd.Series(dtype="object")
    for frame in frames:
        if frame is None or frame.empty or column not in frame.columns:
            continue
        s = (frame.dropna(subset=[column]).drop_duplicates("player_id")
                  .set_index("player_id")[column])
        out = out.combine_first(s) if len(out) else s
    return out


def combine_sources(transfermarkt: pd.DataFrame | None,
                    impect: pd.DataFrame | None) -> pd.DataFrame:
    """One row per player_id, each field taken from its own priority order."""
    tm = transfermarkt if transfermarkt is not None else pd.DataFrame()
    im = impect if impect is not None else pd.DataFrame()
    foot = _first_present([tm, im], "foot")               # TM first
    nationality = _first_present([im, tm], "nationality")  # Impect first
    contract = _first_present([tm], "contract_until")      # Transfermarkt only
    ids = sorted(set(foot.index) | set(nationality.index) | set(contract.index))
    if not ids:
        return pd.DataFrame(columns=BIO_COLUMNS)
    out = pd.DataFrame({"player_id": ids})
    out["foot"] = out["player_id"].map(foot)
    out["nationality"] = out["player_id"].map(nationality)
    out["contract_until"] = out["player_id"].map(contract)
    out = out.dropna(subset=["foot", "nationality", "contract_until"], how="all")
    return out[BIO_COLUMNS].reset_index(drop=True)


def bio_fill_stmt():
    """UPDATE players, filling ONLY where the column is empty.

    Note the COALESCE direction: `COALESCE(column, :incoming)` -- the STORED value wins.
    This is deliberately the opposite of identity.py and valuation.py, which are
    `COALESCE(:incoming, column)` so a fresh scrape can CORRECT a value. This module is a
    gap-filler, not a corrector; do not harmonise the two directions.
    """
    table = Player.__table__
    return (update(table)
            .where(table.c.player_id == bindparam("pid"))
            .values(foot=func.coalesce(table.c.foot, bindparam("ft")),
                    nationality=func.coalesce(table.c.nationality, bindparam("nat")),
                    contract_until=func.coalesce(table.c.contract_until,
                                                 bindparam("con"))))


def collect_transfermarkt(engine) -> pd.DataFrame:
    """foot + nationality from Transfermarkt, keyed to OUR player_id.

    Two files, in confidence order: the live squad scrape (current, and the same rows the
    contract dates come from), then the static reference dump as a fallback for players the
    scrape never saw. The static file is a snapshot roughly a year old, so it fills gaps
    and never leads.
    """
    from pathlib import Path
    from lofc.config import settings

    tmdir = Path(settings.reference_data_dir) / "transfermarkt"
    ours = pd.read_sql("SELECT player_id, tm_player_id FROM players "
                       "WHERE tm_player_id IS NOT NULL", engine)
    frames = []
    live = tmdir / "efl_values.csv"
    if live.exists():
        d = pd.read_csv(live)
        d["nationality"] = None                    # the squad page carries a flag, not a name
        d["contract_until"] = pd.to_datetime(d.get("contract_until"), errors="coerce")
        frames.append(d[["tm_player_id", "foot", "nationality", "contract_until"]])
    static = tmdir / "players.csv"
    if static.exists():
        d = pd.read_csv(static, usecols=["player_id", "foot", "country_of_citizenship",
                                         "contract_expiration_date"])
        d = d.rename(columns={"player_id": "tm_player_id",
                              "country_of_citizenship": "nationality",
                              "contract_expiration_date": "contract_until"})
        d["contract_until"] = pd.to_datetime(d["contract_until"], errors="coerce")
        # An expired date is worse than none: it would read as a current fact and send a
        # recruiter after a player whose deal lapsed a year ago. 16,249 of the file's
        # 31,328 dates have already passed.
        d.loc[d["contract_until"] < pd.Timestamp.today(), "contract_until"] = pd.NaT
        frames.append(d[["tm_player_id", "foot", "nationality", "contract_until"]])
    if not frames:
        return pd.DataFrame(columns=BIO_COLUMNS)

    tm = pd.concat(frames, ignore_index=True)
    tm["foot"] = tm["foot"].str.lower().map(TM_FOOT)
    by_id = ours.merge(tm, on="tm_player_id", how="inner")[BIO_COLUMNS]

    # Second route: NAME + DATE OF BIRTH, for players we never linked to a Transfermarkt
    # id. Contracts come from CURRENT squad pages, so a player who has left our seven
    # leagues has none -- Miguel Freckleton played 3,541 minutes in the 25/26 Scottish
    # Premiership, left St Mirren, and held no tm_player_id, so neither route by id could
    # reach him although the static dump carries his contract to 31 May 2027.
    #
    # Name+DOB is a weaker key than an id, so it is used ONLY for players with no id at
    # all, and both parts must match exactly -- the 54-namesake audit showed a name alone
    # is not safe enough to write an identity from.
    static = tmdir / "players.csv"
    by_name = pd.DataFrame(columns=BIO_COLUMNS)
    if static.exists():
        unlinked = pd.read_sql(
            "SELECT player_id, player_name, birth_date FROM players "
            "WHERE tm_player_id IS NULL AND birth_date IS NOT NULL", engine)
        ref = pd.read_csv(static, usecols=["name", "date_of_birth", "foot",
                                           "country_of_citizenship",
                                           "contract_expiration_date"])
        ref = ref.rename(columns={"country_of_citizenship": "nationality",
                                  "contract_expiration_date": "contract_until"})
        ref["contract_until"] = pd.to_datetime(ref["contract_until"], errors="coerce")
        ref.loc[ref["contract_until"] < pd.Timestamp.today(), "contract_until"] = pd.NaT
        ref["foot"] = ref["foot"].str.lower().map(TM_FOOT)
        ref["_k"] = (ref["name"].str.lower().str.strip() + "|"
                     + pd.to_datetime(ref["date_of_birth"], errors="coerce")
                       .dt.date.astype(str))
        unlinked["_k"] = (unlinked["player_name"].str.lower().str.strip() + "|"
                          + unlinked["birth_date"].astype(str))
        # A key claimed by more than one Transfermarkt row is ambiguous; drop it rather
        # than pick one, the same rule identity.drop_ambiguous_matches applies.
        ref = ref.drop_duplicates("_k", keep=False)
        by_name = unlinked.merge(ref, on="_k", how="inner")[BIO_COLUMNS]

    return pd.concat([by_id, by_name], ignore_index=True)


def collect_impect(engine) -> pd.DataFrame:
    """foot + nationality from Impect, keyed to OUR player_id.

    The linkage is NOT re-derived: it comes from position_shares._linked_ids, which uses
    the same two functions the metric build uses. A bio row can therefore never attach to
    a different identity than the player's metrics did.
    """
    from lofc.config import settings
    from lofc.ingest import impect as landing
    from lofc.ingest.impect_translate import translate_target
    from lofc.model.position_shares import _linked_ids

    frames = []
    for target in settings.impect_targets:
        if not landing.averages_path(target.iteration_id).exists():
            continue
        ids = _linked_ids(engine, target)
        if ids is None:
            continue
        t = translate_target(target)
        if "foot" not in t.columns and "nationality" not in t.columns:
            continue
        keep = t.reindex(columns=["playerId", "foot", "nationality"]).copy()
        keep["player_id"] = keep["playerId"].map(ids)
        # Impect ships no contract data at all -- 25 API endpoints, none of them
        # registration. The column is declared empty so the frame matches BIO_COLUMNS and
        # the source priority can be expressed uniformly.
        keep["contract_until"] = pd.NaT
        frames.append(keep.dropna(subset=["player_id"])[BIO_COLUMNS])
    if not frames:
        return pd.DataFrame(columns=BIO_COLUMNS)
    out = pd.concat(frames, ignore_index=True)
    out["player_id"] = out["player_id"].astype("int64")
    return out


def apply(engine, bio: pd.DataFrame) -> dict[str, int]:
    """Write the fill, counting how many rows actually GAINED each field.

    Counted by comparing before and after rather than by counting statements: every row is
    updated, but most are no-ops because the value is already stored.
    """
    if bio.empty:
        return {"foot": 0, "nationality": 0, "contract_until": 0}
    before = pd.read_sql(
        "SELECT player_id, foot, nationality, contract_until FROM players", engine)
    rows = [{"pid": int(r.player_id),
             "ft": r.foot if pd.notna(r.foot) else None,
             "nat": r.nationality if pd.notna(r.nationality) else None,
             "con": (pd.Timestamp(r.contract_until).date()
                     if pd.notna(r.contract_until) else None)}
            for r in bio.itertuples()]
    with engine.begin() as conn:
        conn.execute(bio_fill_stmt(), rows)
    after = pd.read_sql(
        "SELECT player_id, foot, nationality, contract_until FROM players", engine)
    m = before.merge(after, on="player_id", suffixes=("_b", "_a"))
    return {c: int((m[f"{c}_b"].isna() & m[f"{c}_a"].notna()).sum())
            for c in ("foot", "nationality", "contract_until")}


def main() -> None:
    from lofc.store.load import get_engine
    engine = get_engine()
    for col in ("foot", "nationality", "contract_until"):
        n = pd.read_sql(f"SELECT count(*) n FROM players WHERE {col} IS NOT NULL",
                        engine).n[0]
        print(f"before: {col} on {n} players")
    tm, im = collect_transfermarkt(engine), collect_impect(engine)
    print(f"sources: transfermarkt {len(tm)} rows, impect {len(im)} rows")
    filled = apply(engine, combine_sources(tm, im))
    print(f"filled: foot +{filled['foot']}, nationality +{filled['nationality']}, "
          f"contract +{filled['contract_until']}")


if __name__ == "__main__":
    main()
