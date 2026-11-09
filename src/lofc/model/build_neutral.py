"""Merge the four data sources into ONE combined metric table per player.

The assembly step of the provider-neutral layer (Phase 11 Step 1). For one league
season it produces one wide row per player carrying all 87 registry metrics, each
taken from its single designated source:

    spine (player_season_metrics)  -> identity + minutes + the 15 event-computed metrics
    Impect (translated + matched)  -> its 36 metrics
    StatsBomb advanced endpoint    -> its 12 metrics
    SkillCorner platform           -> its 24 physical metrics (2025/26 only)

Which metric comes from which source is decided ONCE, in metric_registry (with
overlaps resolved there, not at runtime): this module only selects and joins. The
spine defines the player universe, so a player missing from a source keeps the row
with blanks for that source's columns (the physical columns for 2024/25, for
example, are blank by design — SkillCorner starts at 2025/26).

Default run is a read-only coverage report. With --write, the combined table is
loaded into `player_metrics_neutral` (clear-then-insert per league season, the
same idempotent pattern as every other derived table). The LIVE tables
(player_season_metrics, scores, shortlists) are never touched here: scoring is
re-pointed at the neutral table in a later, explicit step.

Run with:  python -m lofc.model.build_neutral            (report only)
           python -m lofc.model.build_neutral --write    (load into the database)
"""

from __future__ import annotations

import pandas as pd

from lofc.config import settings
from lofc.ingest import skillcorner_api
from lofc.ingest.skillcorner_map import SKILLCORNER_MAP, to_per90
from lofc.ingest.statsbomb_season import stats_path, translate_competition
from lofc.ingest.impect import averages_path
from lofc.ingest.impect_translate import translate_target
from lofc.model import metric_registry as reg
from lofc.store.load import get_engine

SPINE_IDENTITY = ["player_id", "competition_id", "season_id", "player_name",
                  "team_name", "position_group", "minutes", "rankable"]


def combine(spine: pd.DataFrame,
            impect: pd.DataFrame | None,
            sb_advanced: pd.DataFrame | None,
            skillcorner: pd.DataFrame | None) -> pd.DataFrame:
    """Pure merge: registry-driven column selection + left joins on player_id.

    Every input except the spine is optional (None = source unavailable for this
    league season; its columns come out blank). Each source contributes ONLY the
    columns the registry assigns to it, so there are no collisions by construction.
    The result always has exactly one row per spine row (asserted).
    """
    out = spine[SPINE_IDENTITY + reg.names_for(reg.SB_COMPUTED)].copy()

    for frame, source in ((impect, reg.IMPECT),
                          (sb_advanced, reg.SB_ADVANCED),
                          (skillcorner, reg.SKILLCORNER)):
        wanted = reg.names_for(source)
        if frame is None:
            for c in wanted:
                out[c] = pd.NA
            continue
        cols = ["player_id"] + [c for c in wanted if c in frame.columns]
        slim = frame[cols].drop_duplicates("player_id")
        out = out.merge(slim, on="player_id", how="left")
        for c in wanted:                      # a source can miss a column entirely
            if c not in out.columns:
                out[c] = pd.NA

    assert len(out) == len(spine), (
        f"merge fanned out: {len(spine)} spine rows became {len(out)}")
    ordered = SPINE_IDENTITY + [s.name for s in reg.REGISTRY]
    return out[ordered]


# --- loaders (thin; all read-only) -------------------------------------------

def load_spine(engine, competition_id: int, season_id: int) -> pd.DataFrame:
    cols = ", ".join(SPINE_IDENTITY + reg.names_for(reg.SB_COMPUTED))
    return pd.read_sql(
        f"SELECT {cols} FROM player_season_metrics "
        f"WHERE competition_id = {competition_id} AND season_id = {season_id}", engine)


def _league_name_index(engine, competition_id: int, season_id: int) -> dict:
    """Unique-name -> player_id map for OUR players in this league season (spine)."""
    from lofc.model.impect_check import unique_league_name_index
    spine = pd.read_sql(
        "SELECT player_id, player_name FROM player_season_metrics "
        f"WHERE competition_id = {competition_id} AND season_id = {season_id}", engine)
    return unique_league_name_index(spine)


def load_impect(engine, competition_id: int, season_id: int) -> pd.DataFrame | None:
    """Translated Impect metrics matched onto OUR player ids, or None if not pulled."""
    target = next((t for t in settings.impect_targets
                   if t.sb_competition_id == competition_id
                   and t.sb_season_id == season_id), None)
    if target is None or not averages_path(target.iteration_id).exists():
        return None
    from lofc.model.impect_check import load_overrides, match_to_ours
    translated = translate_target(target)
    ours = pd.read_sql("SELECT player_id, player_name, birth_date, tm_player_id FROM players", engine)
    matched = match_to_ours(translated.assign(tm_player_id=pd.NA), ours,
                            league_name_index=_league_name_index(engine, competition_id, season_id),
                            overrides=load_overrides())
    matched = matched.dropna(subset=["player_id"])
    # If two Impect records match one player, keep the one with more minutes.
    return (matched.sort_values("minutes", ascending=False)
                   .drop_duplicates("player_id"))


def load_sb_advanced(competition_id: int, season_id: int) -> pd.DataFrame | None:
    comp = next((c for c in settings.competitions
                 if c.competition_id == competition_id and c.season_id == season_id), None)
    if comp is None or not stats_path(competition_id, season_id).exists():
        return None
    return translate_competition(comp)


def load_skillcorner(engine, competition_id: int, season_id: int) -> pd.DataFrame | None:
    target = next((t for t in settings.skillcorner_targets
                   if t.competition_id == competition_id and t.season_id == season_id), None)
    if target is None or not skillcorner_api.physical_path(target.edition_id).exists():
        return None
    from lofc.model.skillcorner_check import match_to_ours
    physical = pd.read_parquet(skillcorner_api.physical_path(target.edition_id))
    ours = pd.read_sql("SELECT player_id, player_name, birth_date FROM players", engine)
    matched = match_to_ours(physical, ours,
                            league_name_index=_league_name_index(engine, competition_id, season_id)
                            ).dropna(subset=["player_id_ours"])
    renames = {m.source: m.name for m in SKILLCORNER_MAP}
    # Volumes arrive per APPEARANCE; scoring compares per 90 (see skillcorner_map).
    matched = to_per90(matched.rename(columns=renames))
    matched["player_id"] = matched["player_id_ours"]
    return (matched.sort_values("minutes_full_all", ascending=False)
                   .drop_duplicates("player_id"))


def build_for(engine, competition_id: int, season_id: int) -> pd.DataFrame:
    """The combined 87-metric table for one StatsBomb-spined league season."""
    return combine(load_spine(engine, competition_id, season_id),
                   load_impect(engine, competition_id, season_id),
                   load_sb_advanced(competition_id, season_id),
                   load_skillcorner(engine, competition_id, season_id))


def build_for_impect_league(engine, target) -> pd.DataFrame:
    """The combined table for an IMPECT-SPINED league (no StatsBomb data at all).

    Identity (player_id, minutes, position_group, rankable) is derived from Impect via
    impect_spine; the StatsBomb-sourced columns are blank; SkillCorner joins if an
    edition is mapped to this league. Minted players (Impect-only, not already in our
    database) are registered in `players` so downstream scoring's foreign keys resolve.
    """
    from lofc.model.impect_check import load_overrides
    from lofc.model.impect_spine import build_spine, new_players

    translated = translate_target(target)
    ours = pd.read_sql("SELECT player_id, player_name, birth_date, tm_player_id FROM players", engine)
    # No league_name_index: an Impect-only league has no OUR-players roster to key on;
    # matching leans on tm id / dob+name / dob+surname / the override list, and mints
    # the rest. (The exact-name-in-league rescue only makes sense within our own leagues.)
    spine, impect_metrics = build_spine(translated, ours, overrides=load_overrides())
    spine["competition_id"] = target.competition_id
    spine["season_id"] = target.season_id
    for c in reg.names_for(reg.SB_COMPUTED):     # StatsBomb-sourced: blank for this league
        spine[c] = pd.NA

    _register_minted_players(engine, new_players(spine, translated, set(ours["player_id"])))
    skillcorner = load_skillcorner(engine, target.competition_id, target.season_id)
    return combine(spine, impect_metrics, None, skillcorner)


def _register_minted_players(engine, minted: pd.DataFrame) -> int:
    """Insert Impect-only players into `players` (ON CONFLICT DO NOTHING, never overwrites)."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from lofc.store.models import Player
    if minted.empty:
        return 0
    rows = [{"player_id": int(r.player_id), "player_name": str(r.player_name),
             "birth_date": r.birth_date.date() if pd.notna(r.birth_date) else None}
            for r in minted.itertuples()]
    with engine.begin() as conn:
        conn.execute(pg_insert(Player.__table__).on_conflict_do_nothing(
            index_elements=["player_id"]), rows)
    return len(rows)


DETAIL_COLUMNS = ["player_id", "competition_id", "season_id", "metric", "value_p90", "total"]


def key_detail(long: pd.DataFrame, ids: pd.DataFrame, provider_key: str,
               competition_id: int, season_id: int) -> pd.DataFrame:
    """Long detail rows keyed by a provider id -> keyed by OUR player_id for one league season.

    `ids` maps provider id -> player_id with a `minutes` column. Unmatched provider ids are
    dropped; where two provider ids resolve to one player, the higher-minutes one is kept --
    the rule build_spine and load_skillcorner apply -- so no metric lands twice."""
    best = (ids.dropna(subset=["player_id"]).sort_values("minutes", ascending=False)
               .drop_duplicates("player_id")[[provider_key, "player_id"]])
    out = long.merge(best, on=provider_key, how="inner")
    out["player_id"] = out["player_id"].astype("int64")
    out["competition_id"] = competition_id
    out["season_id"] = season_id
    return out[DETAIL_COLUMNS]


def build_detail_for_impect_league(engine, target) -> pd.DataFrame:
    """Display-only detail for one league season: Impect zones, lanes, availability and
    scores, plus SkillCorner in/out-of-possession physical. Never read by scoring."""
    from lofc.ingest import impect_detail
    from lofc.ingest.impect import scores_path
    from lofc.ingest.skillcorner_map import SPLIT_PHASES, split_to_long
    from lofc.model.impect_check import load_overrides
    from lofc.model.impect_spine import attach_identity

    cid, sid = target.competition_id, target.season_id
    parts = []

    # Impect: the same identity match build_spine uses, so ids agree with the neutral row.
    averages = pd.read_parquet(averages_path(target.iteration_id))
    ours = pd.read_sql("SELECT player_id, player_name, birth_date, tm_player_id FROM players",
                       engine)
    ident = attach_identity(translate_target(target), ours, overrides=load_overrides())
    ids = ident[["playerId", "player_id", "minutes"]]
    parts.append(key_detail(impect_detail.translate_detail(averages), ids, "playerId", cid, sid))
    if scores_path(target.iteration_id).exists():
        scores = pd.read_parquet(scores_path(target.iteration_id))
        parts.append(key_detail(impect_detail.translate_scores(scores), ids, "playerId",
                                cid, sid))

    # SkillCorner: the same match load_skillcorner uses.
    sc_target = next((t for t in settings.skillcorner_targets
                      if t.competition_id == cid and t.season_id == sid), None)
    if sc_target is not None and skillcorner_api.physical_path(sc_target.edition_id).exists():
        from lofc.model.skillcorner_check import match_to_ours
        full = pd.read_parquet(skillcorner_api.physical_path(sc_target.edition_id))
        bio = pd.read_sql("SELECT player_id, player_name, birth_date FROM players", engine)
        # match_to_ours overwrites SkillCorner's player_id with ours, so keep a copy.
        matched = match_to_ours(full.assign(sc_player_id=full["player_id"]), bio,
                                league_name_index=_league_name_index(engine, cid, sid))
        sc_ids = (matched.dropna(subset=["player_id_ours"])
                         .rename(columns={"player_id_ours": "player_id",
                                          "minutes_full_all": "minutes"})
                  [["sc_player_id", "player_id", "minutes"]])
        for phase in SPLIT_PHASES:
            path = skillcorner_api.split_path(sc_target.edition_id, phase)
            if path.exists():
                long = split_to_long(pd.read_parquet(path), full, phase)
                parts.append(key_detail(long, sc_ids, "sc_player_id", cid, sid))

    parts = [p for p in parts if not p.empty]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=DETAIL_COLUMNS)


MATCH_COUNT_COLUMNS = ["player_id", "competition_id", "season_id", "matches"]


def match_counts(matched: pd.DataFrame | None, competition_id: int, season_id: int) -> pd.DataFrame:
    """Matches SkillCorner tracked per player (`count_match`), from the rows `load_skillcorner`
    matched to our players. Display only (skillcorner_match_counts)."""
    if matched is None or "count_match" not in matched.columns:
        return pd.DataFrame(columns=MATCH_COUNT_COLUMNS)
    m = matched[["player_id", "count_match"]].dropna()
    out = pd.DataFrame({"player_id": m["player_id"].astype("int64").values,
                        "competition_id": int(competition_id), "season_id": int(season_id),
                        "matches": m["count_match"].round().astype("int64").values})
    return out.drop_duplicates("player_id").reset_index(drop=True)[MATCH_COUNT_COLUMNS]


def write_match_counts(engine, frame: pd.DataFrame, competition_id: int, season_id: int) -> int:
    """Clear-then-insert one league season into skillcorner_match_counts."""
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM skillcorner_match_counts WHERE "
                          "competition_id = :c AND season_id = :s"),
                     {"c": competition_id, "s": season_id})
        if len(frame):
            frame.to_sql("skillcorner_match_counts", conn, if_exists="append", index=False)
    return len(frame)


def write_detail_for(engine, frame: pd.DataFrame, competition_id: int, season_id: int) -> int:
    """Clear-then-insert one league season into player_detail_metrics."""
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM player_detail_metrics WHERE "
                          "competition_id = :c AND season_id = :s"),
                     {"c": competition_id, "s": season_id})
        frame.to_sql("player_detail_metrics", conn, if_exists="append", index=False,
                     chunksize=20_000, method="multi")
    return len(frame)


def write_for(engine, table: pd.DataFrame, competition_id: int, season_id: int) -> int:
    """Clear-then-insert one league season into player_metrics_neutral."""
    from sqlalchemy import text
    frame = table.copy()
    # Metric columns can be object-dtype pd.NA when a whole source was absent;
    # coerce to float so they land as SQL NULLs.
    for c in [s.name for s in reg.REGISTRY]:
        frame[c] = pd.to_numeric(frame[c], errors="coerce")
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM player_metrics_neutral WHERE "
                          "competition_id = :c AND season_id = :s"),
                     {"c": competition_id, "s": season_id})
        frame.to_sql("player_metrics_neutral", conn, if_exists="append", index=False)
    return len(frame)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true",
                        help="load the combined table into player_metrics_neutral")
    parser.add_argument("--match-counts", action="store_true",
                        help="only (re)write skillcorner_match_counts from the landed "
                             "SkillCorner files; no other table is touched, no API call")
    args = parser.parse_args()

    engine = get_engine()
    if args.match_counts:
        total = 0
        for t in settings.skillcorner_targets:
            if not skillcorner_api.physical_path(t.edition_id).exists():
                print(f"  [{t.competition_id}/{t.season_id}] no landed file: skipped")
                continue
            counts = match_counts(load_skillcorner(engine, t.competition_id, t.season_id),
                                  t.competition_id, t.season_id)
            n = write_match_counts(engine, counts, t.competition_id, t.season_id)
            total += n
            print(f"  [{t.competition_id}/{t.season_id}] tracked-match counts: {n}")
        print(f"skillcorner_match_counts: wrote {total} rows.")
        return
    mode = "load into player_metrics_neutral" if args.write else "read-only report"
    print(f"Combined neutral-layer build ({mode})")
    print("=" * 78)

    # Every league season to build, and how its identity spine is sourced:
    #   StatsBomb-spined  (EFL, from settings.competitions)
    #   Impect-spined     (Scottish / PL2, from the impect targets flagged spine_source=impect)
    # Phase C: with settings.impect_only, the EFL is built from Impect too (its Impect
    # targets carry the same competition/season keys), so StatsBomb is not needed at all.
    if settings.impect_only:
        jobs: list[tuple[str, int, int, str, object]] = [
            (t.label, t.competition_id, t.season_id, "impect", t)
            for t in settings.impect_targets if averages_path(t.iteration_id).exists()]
    else:
        jobs = [(c.label, c.competition_id, c.season_id, "statsbomb", None)
                for c in settings.competitions]
        jobs += [(t.label, t.competition_id, t.season_id, "impect", t)
                 for t in settings.impect_targets if t.spine_source == "impect"
                 and averages_path(t.iteration_id).exists()]

    from lofc.store import runs
    totals = {"rows": 0}

    def one(job) -> int:
        label, competition_id, season_id, spine_source, target = job
        table = (build_for_impect_league(engine, target) if spine_source == "impect"
                 else build_for(engine, competition_id, season_id))
        rankable = table[table["rankable"]]
        line = [f"[{label}] {len(table)} players ({len(rankable)} rankable) [{spine_source} spine]"]
        for source in (reg.IMPECT, reg.SB_ADVANCED, reg.SB_COMPUTED, reg.SKILLCORNER):
            cols = reg.names_for(source)
            cov = rankable[cols].notna().any(axis=1).mean() * 100 if len(rankable) else 0
            line.append(f"{source.split('_')[-1]}: {cov:.0f}%")
        if args.write:
            totals["rows"] += write_for(engine, table, competition_id, season_id)
            line.append("written")
            counts = match_counts(load_skillcorner(engine, competition_id, season_id),
                                  competition_id, season_id)
            line.append(f"tracked-match counts {write_match_counts(engine, counts, competition_id, season_id)}")
            if spine_source == "impect":
                detail = build_detail_for_impect_league(engine, target)
                line.append(f"detail {write_detail_for(engine, detail, competition_id, season_id):,}")
        print("  " + " | ".join(line))
        return len(table)

    # A league that fails keeps last week's rows; the others are rebuilt (owner, 2026-10-26).
    failures = runs.for_each_league("Build combined table", jobs, label=lambda j: j[0],
                                    keys=lambda j: (j[1], j[2]), fn=one)
    total = totals["rows"]
    if args.write:
        print(f"\nplayer_metrics_neutral: wrote {total} rows across {len(jobs)} league seasons.")
    print("\nCoverage = % of rankable players with at least one value from that source.")
    print("Impect-spined leagues have 0% StatsBomb (computed/advanced) by design.")
    runs.finish_step("Build combined table", failures)


if __name__ == "__main__":
    main()
