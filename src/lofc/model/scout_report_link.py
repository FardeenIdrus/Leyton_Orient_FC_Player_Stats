"""Attach each scout report to one of our players, on name + DATE OF BIRTH.

Pure: frames in, frame out. The stage that writes the result is `main` at the bottom.

WHY NAME + DATE OF BIRTH, measured on the live data:

    name only      279 of 350 matched -- but 13 names are claimed by TWO of our players
    name + club    183 matched, 0 ambiguous  (club naming differs badly across sources)
    name + DOB     200 matched, 0 AMBIGUOUS  <- chosen

Name-only links 79 more reports and carries thirteen chances to attach one man's verdict
to another. A scout report is a judgement about a specific human being, and a wrong link
is worse than no link because a wrong one is invisible -- it reads as a fact. This is the
same trade `model/identity.py` made after the 54-namesake audit.

Dates of birth come from the form's own `Player Names` tab: the report itself carries only
a name.

NOT MATCHING IS A NORMAL OUTCOME. 152 of the 350 scouted players are outside the seven
leagues the platform holds data for -- non-league and academy players scouts are sent to
watch deliberately. Their reports are stored and displayed in full; they simply carry no
`player_id`, and no rating is invented for them.

A `player_id` IS NEVER MINTED for a scouted player. Twelve tables carry a foreign key to
`players`, and a row with no metrics would reach the ranking, the peer pools and the
scorecards -- a display feature would have changed the ranking.

Run:  python -m lofc.model.scout_report_link
"""

from __future__ import annotations

import re
import unicodedata

import pandas as pd


def _norm(name) -> str:
    """A name reduced to comparable letters: accents folded, case dropped, punctuation out.

    Safe here only because the birth date still has to agree. Normalising a name ALONE is
    what produces the thirteen namesake collisions this module exists to avoid.
    """
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return ""
    folded = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z ]", "", folded.lower()).strip()


def _key(name, birth_date) -> str | None:
    """The join key, or None when either half is missing.

    No date, no key. Falling back to the name alone is exactly the risk being avoided,
    and 1,694 of the 4,598 dropdown entries have no date.
    """
    normalised = _norm(name)
    if not normalised or birth_date is None or pd.isna(birth_date):
        return None
    return f"{normalised}|{pd.Timestamp(birth_date).date()}"


def resolve_links(reports: pd.DataFrame, lookup: pd.DataFrame,
                  ours: pd.DataFrame) -> pd.DataFrame:
    """`reports` plus a `player_id` column: our player, or NaN.

    Ambiguity is refused on BOTH sides. A key claimed by two of our players is dropped --
    if even the birth date cannot separate them, nothing here can, and guessing would
    attach a rating, an injury history and an assessment to the wrong man. A key claimed
    by two dropdown entries is dropped for the same reason.

    The row count never changes. A link is an enrichment, not a filter: losing a report
    would hide a scout's work, and duplicating one would double-count a verdict.
    """
    out = reports.copy()
    out["player_id"] = pd.Series([None] * len(out), index=out.index, dtype=object)
    if out.empty or lookup.empty or ours.empty:
        return out

    # Our side: name+DOB -> player_id, ambiguous keys dropped rather than picked.
    mine = ours.assign(_k=[_key(n, b) for n, b in
                           zip(ours["player_name"], ours["birth_date"])])
    mine = mine[mine["_k"].notna()].drop_duplicates("_k", keep=False)
    by_key = mine.set_index("_k")["player_id"]

    # The form's side: scouted name -> that same key.
    listed = lookup.assign(_k=[_key(n, b) for n, b in
                               zip(lookup["player_name"], lookup["date_of_birth"])])
    listed = listed[listed["_k"].notna()]
    listed["_n"] = listed["player_name"].map(_norm)
    listed = listed.drop_duplicates("_n", keep=False)
    name_to_key = listed.set_index("_n")["_k"]

    # `linkable` is False for the form's "A New Player" option, chosen on 19 reports
    # about 19 different people. Linking those would fuse nineteen strangers into one.
    linkable = (out["linkable"].fillna(True).astype(bool)
                if "linkable" in out.columns else pd.Series(True, index=out.index))
    keys = out.loc[linkable, "player_name"].map(_norm).map(name_to_key)
    out.loc[linkable, "player_id"] = keys.map(by_key)

    # --- second tier: names recovered from the report text --------------------------------
    #
    # The form's dropdown and OUR players table are DIFFERENT LISTS. A scout who could not
    # find a player in the dropdown may well have watched someone we hold full data on --
    # measured on the live sheet, 9 of the 20 recovered names are players we have, mostly
    # Premier League 2. Leaving them unlinked meant their report opened nothing.
    #
    # They cannot go through the strict path: there is no date of birth for them, which is
    # precisely why they were missing from the dropdown. So they match on NAME ALONE, and
    # the safety comes from refusing ambiguity rather than from a second field -- a name
    # held by more than one of our players links to none of them. On the live data that
    # rule produced 9 matches and 0 ambiguous.
    #
    # This tier is reached ONLY by a recovered name. A dropdown-named player HAS a date of
    # birth available and must never be downgraded to name-only matching, which across the
    # platform leaves 13 names claimed by two people.
    recovered = (out["name_from_report"].fillna(False).astype(bool)
                 if "name_from_report" in out.columns
                 else pd.Series(False, index=out.index))
    recovered = recovered & out["player_id"].isna()
    if recovered.any():
        by_name = (ours.assign(_n=ours["player_name"].map(_norm))
                       .query("_n != ''")
                       .drop_duplicates("_n", keep=False)
                       .set_index("_n")["player_id"])
        out.loc[recovered, "player_id"] = (
            out.loc[recovered, "player_name"].map(_norm).map(by_name))
    return out


def relink(engine) -> int:
    """Resolve every stored report's player and write the ids back. Returns how many linked.

    Callable, so the sync stage and the dashboard's Refresh button both reach it without
    going through the command line.
    """
    from sqlalchemy import update

    from lofc.store.models import ScoutReport

    reports = pd.read_sql(
        "SELECT submission_id, player_name, linkable, name_from_report "
        "FROM scout_reports", engine)
    if reports.empty:
        return 0
    lookup = pd.read_sql(
        "SELECT player_name, date_of_birth FROM scout_player_lookup", engine)
    # No birth-date filter. The strict path ignores a player without one anyway (`_key`
    # returns None), and the recovered-name path needs to see EVERY player -- both to find
    # a match and, just as importantly, to notice that a name is held by two of them.
    ours = pd.read_sql("SELECT player_id, player_name, birth_date FROM players", engine)

    linked = resolve_links(reports, lookup, ours)
    table = ScoutReport.__table__
    written = 0
    with engine.begin() as conn:
        for row in linked.to_dict("records"):
            player_id = row["player_id"]
            conn.execute(update(table)
                         .where(table.c.submission_id == row["submission_id"])
                         .values(player_id=None if pd.isna(player_id) else int(player_id)))
            written += int(pd.notna(player_id))
    return written


def main() -> None:
    """Resolve every stored report's player, and write the ids back."""
    from lofc.store.load import get_engine

    engine = get_engine()
    written = relink(engine)
    total = pd.read_sql("SELECT count(*) n FROM scout_reports", engine).n[0]
    via = pd.read_sql("SELECT count(*) n FROM scout_reports WHERE name_from_report "
                      "AND player_id IS NOT NULL", engine).n[0]
    players = pd.read_sql("SELECT count(DISTINCT player_id) n FROM scout_reports "
                          "WHERE player_id IS NOT NULL", engine).n[0]
    print(f"scout reports linked: {written} of {total} ({players} distinct players); "
          f"{total - written} unlinked")
    print(f"  of which matched on a name read from the report text: {via}")


if __name__ == "__main__":
    main()
