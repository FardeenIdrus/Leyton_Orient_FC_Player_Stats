"""Database integrity check: broken links between tables, caught instead of shown as blanks.

CHECK ONLY. It reads, never writes, and adds no constraints. Run with
`python -m lofc.store.integrity`; exits 1 if any orphan or key duplicate exists.
"""

from __future__ import annotations

import sys

import pandas as pd
from sqlalchemy import text

from lofc.model.scout_report_link import _norm

# Tables keyed on player_id with NO foreign key to players(player_id), so nothing in the
# database stops a row pointing at a player that does not exist. The platform then shows a
# blank where a rating or injury history should be.
PLAYER_KEYED_TABLES = (
    "player_metrics_neutral",  # every score and percentile is read from here
    "player_detail_metrics",   # long-format detail metrics behind the player card
    "player_style_signals",    # inputs to the playing-style labels
    "player_loans",            # Transfermarkt loans; player_id may be NULL (tm_player_id only)
)


def orphan_sql(table: str) -> str:
    """Count rows of `table` whose non-NULL player_id has no row in `players`.

    Protects against ingest writing metrics for a player the identity step never created.
    NULL ids are excluded: player_loans legitimately holds loans matched only by tm_player_id.
    """
    if table not in PLAYER_KEYED_TABLES:  # table names cannot be bound parameters
        raise ValueError(f"not a checked table: {table}")
    return (f"SELECT count(*) FROM {table} t WHERE t.player_id IS NOT NULL "
            f"AND NOT EXISTS (SELECT 1 FROM players p WHERE p.player_id = t.player_id)")


def key_duplicate_sqls() -> dict[str, str]:
    """Queries for one-row-per-key rules that NO unique constraint enforces.

    The metric/signal/detail tables have unique constraints on their full key, so they are
    left out. Still unguarded:
    """
    return {
        # Two player ids sharing one Transfermarkt id: injuries, loans and contracts joined
        # on tm_player_id would then attach to both men.
        "players.tm_player_id": (
            "SELECT count(*) FROM (SELECT tm_player_id FROM players "
            "WHERE tm_player_id IS NOT NULL GROUP BY tm_player_id HAVING count(*) > 1) d"),
        # uq_player_loan is on tm_player_id; the squads page joins on player_id, so one player
        # with two rows for the same club and season would be shown twice.
        "player_loans (player_id, club, season)": (
            "SELECT count(*) FROM (SELECT player_id FROM player_loans "
            "WHERE player_id IS NOT NULL GROUP BY player_id, club_name, season_id "
            "HAVING count(*) > 1) d"),
    }


def normalise_name(name) -> str:
    """Lower-case, accent-folded, punctuation-free name (shared with the scout-report linker)."""
    return _norm(name).replace(" ", "")


def find_duplicate_identities(players: pd.DataFrame) -> pd.DataFrame:
    """Pairs of different player_ids with the same normalised name AND non-NULL birth date.

    One footballer under two ids is the main risk when new leagues add players. Namesakes
    born the same day exist, so callers treat this as a warning.
    """
    cols = ["player_id_a", "player_id_b", "player_name", "birth_date"]
    df = players.dropna(subset=["birth_date"]).copy()
    df["_n"] = df["player_name"].map(normalise_name)
    df = df[df["_n"] != ""]
    rows = []
    for (_, bd), grp in df.groupby(["_n", "birth_date"]):
        ids = sorted(grp["player_id"])
        name = grp.iloc[0]["player_name"]
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                rows.append((a, b, name, bd))
    return pd.DataFrame(rows, columns=cols)


def orphan_counts(engine) -> dict[str, int]:
    with engine.connect() as conn:
        return {t: int(conn.execute(text(orphan_sql(t))).scalar()) for t in PLAYER_KEYED_TABLES}


def key_duplicates(engine) -> dict[str, int]:
    with engine.connect() as conn:
        return {k: int(conn.execute(text(q)).scalar()) for k, q in key_duplicate_sqls().items()}


def possible_duplicate_identity_rows(engine) -> pd.DataFrame:
    with engine.connect() as conn:
        players = pd.read_sql(text("SELECT player_id, player_name, birth_date FROM players"), conn)
    return find_duplicate_identities(players)


def possible_duplicate_identities(engine) -> int:
    return len(possible_duplicate_identity_rows(engine))


def exit_code(orphans: dict[str, int], dups: dict[str, int]) -> int:
    """1 if any orphan or key duplicate exists. Duplicate identities never fail the run."""
    return 1 if any(orphans.values()) or any(dups.values()) else 0


def format_report(orphans: dict[str, int], dups: dict[str, int], identities: int) -> str:
    lines = [f"{'check':<45}{'count':>8}  status", "-" * 62]
    for label, n in orphans.items():
        lines.append(f"{'orphans: ' + label:<45}{n:>8}  {'FAIL' if n else 'OK'}")
    for label, n in dups.items():
        lines.append(f"{'duplicates: ' + label:<45}{n:>8}  {'FAIL' if n else 'OK'}")
    lines.append(f"{'possible duplicate identities':<45}{identities:>8}  "
                 f"{'WARNING' if identities else 'OK'}")
    return "\n".join(lines)


def main() -> int:
    from lofc.store.load import get_engine
    engine = get_engine()
    orphans, dups = orphan_counts(engine), key_duplicates(engine)
    pairs = possible_duplicate_identity_rows(engine)
    print(format_report(orphans, dups, len(pairs)))
    if len(pairs):
        print("\nFirst 10 possible duplicate identities (same name + birth date):")
        print(pairs.head(10).to_string(index=False))
    return exit_code(orphans, dups)


if __name__ == "__main__":
    sys.exit(main())
