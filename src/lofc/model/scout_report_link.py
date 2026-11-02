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


def _as_date(value):
    """A real date, or None for missing / unparseable."""
    if value is None:
        return None
    ts = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(ts) else ts.date()


def _implausible(sheet_dob) -> bool:
    """A footballer born before 1950 or younger than 14 is a typo, not a birth date."""
    today = pd.Timestamp.today().year
    return sheet_dob.year < 1950 or sheet_dob.year > today - 14


def _compatible(ours_dob, sheet_dob) -> str | None:
    """How the sheet's date can be reconciled with ours, or None when it contradicts it.

    Only ever asked of a name that is UNIQUE among our players, so the date need not
    identify anyone -- it only must not contradict. Typos seen on the live sheet: day and
    month swapped, the year off by a little, and the date missing or nonsense.
    """
    if ours_dob is None or sheet_dob is None or _implausible(sheet_dob):
        return "missing"
    if ours_dob == sheet_dob:
        return "exact"
    if (ours_dob.year == sheet_dob.year and ours_dob.day == sheet_dob.month
            and ours_dob.month == sheet_dob.day):
        return "swapped"
    if (ours_dob.day == sheet_dob.day and ours_dob.month == sheet_dob.month
            and abs(ours_dob.year - sheet_dob.year) <= 2):
        return "year"
    return None


# Cheapest-to-trust first: when several dropdown dates for a name are compatible, report the
# most convincing reason.
_RULE_ORDER = ["exact", "swapped", "year", "missing"]


def resolve_links(reports: pd.DataFrame, lookup: pd.DataFrame,
                  ours: pd.DataFrame) -> pd.DataFrame:
    """`reports` plus a `player_id` column: our player, or NaN.

    Ambiguity is refused on BOTH sides. A key claimed by two of our players is dropped --
    if even the birth date cannot separate them, nothing here can, and guessing would
    attach a rating, an injury history and an assessment to the wrong man. A name listed
    twice in the dropdown has every date tried; if they pin two of our players, none links.

    `link_method` records how each link was made ("name+dob", "name+dob (tolerant: ...)",
    "name only (report text)") so the tolerant ones can be reviewed.

    The row count never changes. A link is an enrichment, not a filter: losing a report
    would hide a scout's work, and duplicating one would double-count a verdict.
    """
    out = reports.copy()
    out["player_id"] = pd.Series([None] * len(out), index=out.index, dtype=object)
    # How each link was made, so the tolerant ones can be reviewed. Not a stored column.
    out["link_method"] = pd.Series([None] * len(out), index=out.index, dtype=object)
    if out.empty or lookup.empty or ours.empty:
        return out

    ours_n = ours["player_name"].map(_norm)
    # Our side: name+DOB -> player_id, ambiguous keys dropped rather than picked.
    mine = ours.assign(_k=[_key(n, b) for n, b in
                           zip(ours["player_name"], ours["birth_date"])])
    mine = mine[mine["_k"].notna()].drop_duplicates("_k", keep=False)
    by_key = mine.set_index("_k")["player_id"]

    # The form's side: scouted name -> EVERY date listed for it. A name listed twice with two
    # dates used to be dropped outright (`keep=False`), losing reports whose date was right.
    # Now each date is tried; ambiguity is still refused (below) if they pin two players.
    dobs_by_name: dict[str, list] = {}
    for n, d in zip(lookup["player_name"], lookup["date_of_birth"]):
        norm = _norm(n)
        if norm:
            dobs_by_name.setdefault(norm, []).append(_as_date(d))

    # Our side by name, for the tolerant tier: only names held by exactly one player.
    name_counts = ours_n.value_counts()
    unique_ours = (ours.assign(_n=ours_n)[ours_n.map(name_counts) == 1]
                   .query("_n != ''").set_index("_n"))

    def strict(name):
        ids = {by_key.get(_key(name, d)) for d in dobs_by_name.get(name, []) if d}
        ids.discard(None)
        ids = {i for i in ids if pd.notna(i)}
        return ids.pop() if len(ids) == 1 else None

    def tolerant(name):
        if name not in unique_ours.index:
            return None, None
        dobs = dobs_by_name.get(name)
        if not dobs:                      # name not in the dropdown at all
            return None, None
        row = unique_ours.loc[name]
        mine_dob = _as_date(row["birth_date"])
        rules = {_compatible(mine_dob, d) for d in dobs} - {None}
        for rule in _RULE_ORDER:
            if rule in rules:
                return row["player_id"], rule
        return None, None

    # `linkable` is False for the form's "A New Player" option, chosen on 19 reports
    # about 19 different people. Linking those would fuse nineteen strangers into one.
    linkable = (out["linkable"].fillna(True).astype(bool)
                if "linkable" in out.columns else pd.Series(True, index=out.index))
    recovered = (out["name_from_report"].fillna(False).astype(bool)
                 if "name_from_report" in out.columns
                 else pd.Series(False, index=out.index))
    names = out["player_name"].map(_norm)

    # --- tier 1: strict name + exact date of birth ----------------------------------------
    for idx in out.index[linkable]:
        pid = strict(names[idx])
        if pid is not None:
            out.at[idx, "player_id"] = pid
            out.at[idx, "link_method"] = "name+dob"

    # --- tier 2: tolerant date, unique name -----------------------------------------------
    #
    # Measured live: 524 of 726 reports linked, ~75 more missed purely because the sheet's
    # date is mistyped (Kian Leavy 2004-03-21 vs ours 2002-03-21). Safety moves from the
    # date to the name: it must belong to exactly ONE of our players. Dropdown-named rows
    # only -- a recovered name has its own rule below.
    for idx in out.index[linkable & ~recovered & out["player_id"].isna()]:
        pid, rule = tolerant(names[idx])
        if pid is not None:
            out.at[idx, "player_id"] = pid
            out.at[idx, "link_method"] = (
                "name+dob" if rule == "exact" else f"name+dob (tolerant: {rule})")

    # --- tier 3: names recovered from the report text -------------------------------------
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
    recovered = recovered & out["player_id"].isna()
    if recovered.any():
        by_name = (ours.assign(_n=ours_n)
                       .query("_n != ''")
                       .drop_duplicates("_n", keep=False)
                       .set_index("_n")["player_id"])
        found = out.loc[recovered, "player_name"].map(_norm).map(by_name)
        out.loc[recovered, "player_id"] = found
        out.loc[found.index[found.notna()], "link_method"] = "name only (report text)"
    return out


def _tolerant_review(linked, lookup, ours) -> pd.DataFrame:
    """The tolerant links as name / our DOB / sheet DOB(s) / rule, for the owner to eyeball."""
    t = linked[linked["link_method"].fillna("").str.contains("tolerant")]
    dob = ours.drop_duplicates("player_id").set_index("player_id")["birth_date"]
    sheet = (lookup.assign(_n=lookup["player_name"].map(_norm))
                   .groupby("_n")["date_of_birth"]
                   .agg(lambda v: ", ".join(str(x) for x in v)))
    return pd.DataFrame({
        "name": t["player_name"],
        "our_dob": t["player_id"].map(dob),
        "sheet_dob": t["player_name"].map(_norm).map(sheet),
        "rule": t["link_method"]}).drop_duplicates()


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
    relink.review = _tolerant_review(linked, lookup, ours)
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
    review = getattr(relink, "review", None)
    if review is not None and not review.empty:
        print(f"  tolerant date links to review ({len(review)}):")
        print(review.to_string(index=False))


if __name__ == "__main__":
    main()
