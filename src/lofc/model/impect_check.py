"""Validate landed Impect data before anything downstream is allowed to use it.

Two questions, answered per iteration and overall:

1. MATCHING — can Impect players be tied to the players we already hold?
   Primary: the Transfermarkt id Impect carries vs players.tm_player_id (exact,
   no guessing). Fallback: birth date + fuzzy name, the same technique (and the
   same 0.55 cutoff) the Transfermarkt value match uses. Both rates reported.

2. CORRECTNESS — do Impect's numbers agree with reality? For iterations mapped
   to a StatsBomb league season we already validated against published tables,
   compare per-player season GOAL totals (exact-match %, within-one %) and the
   xG correlation. Impect covers league fixtures only while our StatsBomb
   totals include playoffs, so a small tail of +1/+2 differences on playoff
   scorers is expected and reported rather than hidden.

Season totals from Impect averages: KPI columns are averages per
full-match-equivalent, so total = average * matchShare summed over the player's
position rows (verified: Ballard 0.6131 * 37.52 = 23.00, his real total).

Read-only: prints a report, writes nothing to the database.

Run with:  python -m lofc.model.impect_check
"""

from __future__ import annotations

import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from lofc.config import ImpectTarget, settings
from lofc.ingest import impect as impect_landing
from lofc.model.valuation import DOB_NAME_CUTOFF, _dob_name_match, _norm
from lofc.store.load import get_engine

# Identity columns: everything else in the landed frame is treated as a KPI.
TOTAL_KPIS = ["GOALS", "ASSISTS", "SHOT_XG"]

OVERRIDES_PATH = Path(settings.reference_data_dir) / "impect_player_overrides.csv"


def load_overrides() -> pd.DataFrame:
    """The curated our_player_id <-> impect_player_id override list, or empty.

    Each row is a HUMAN-VERIFIED same-player call for a case none of the automatic
    stages could safely make (evidence documented per row: DOB disagreement +
    matching club, transliteration, double-surname convention, etc — see
    analysis/step3/STEP3_REPORT.md for how these were derived). Never auto-generated:
    a wrong entry here silently corrupts real data, so every row was checked against
    club affiliation, not birth date alone.
    """
    if not OVERRIDES_PATH.exists():
        return pd.DataFrame(columns=["our_player_id", "impect_player_id"])
    df = pd.read_csv(OVERRIDES_PATH)
    return df[["our_player_id", "impect_player_id"]]


def aggregate_players(frame: pd.DataFrame) -> pd.DataFrame:
    """One row per player: identity + season totals + the dominant position.

    The landed frame has one row per player per position; totals are
    average * matchShare summed across those rows, and the dominant position is
    the one holding the most matchShare.
    """
    frame = frame.copy()
    for kpi in TOTAL_KPIS:
        frame[f"total_{kpi}"] = frame[kpi] * frame["matchShare"]

    def _one(group: pd.DataFrame) -> pd.Series:
        top = group.loc[group["matchShare"].idxmax()]
        out = {
            "player_name": top["playerName"],
            "squad_name": top["squadName"],
            "birth_date": top["birthdate"],
            "tm_player_id": top["transfermarktId"],
            "dominant_position": top["position"],
            "match_share": group["matchShare"].sum(),
        }
        for kpi in TOTAL_KPIS:
            out[f"total_{kpi.lower()}"] = group[f"total_{kpi}"].sum()
        return pd.Series(out)

    players = frame.groupby("playerId").apply(_one, include_groups=False).reset_index()
    players["birth_date"] = pd.to_datetime(players["birth_date"], errors="coerce")
    players["tm_player_id"] = pd.to_numeric(players["tm_player_id"], errors="coerce")
    return players


def match_to_ours(impect_players: pd.DataFrame, ours: pd.DataFrame,
                  league_name_index: dict[str, int] | None = None,
                  overrides: pd.DataFrame | None = None) -> pd.DataFrame:
    """Attach our player_id to each Impect player row where a safe match exists.

    Stage 1: exact Transfermarkt id join (players.tm_player_id, backfilled by the
    valuation match for ~1,600 players). Stage 2: CURATED OVERRIDE — a hand-verified
    our_player_id <-> impect_player_id pair (see load_overrides); used for cases no
    automatic rule can safely make (e.g. Rob/Robert Apter: club affiliation matches
    across three separate season-rows but the DOB disagrees and the forename is
    abbreviated — strong evidence, but only a human should bless it). Stage 3: birth
    date + fuzzy name at the EFL cutoff. Stage 4: DAY/MONTH-SWAP rescue — providers
    occasionally invert a birth date (Impect/SkillCorner list Luke Harris as 04 Mar
    where StatsBomb has 03 Apr); an IDENTICAL normalised name whose swapped date
    matches ours matches too (fuzzy names NOT allowed here — the date evidence is
    weaker, so the name must be exact). Stage 5: DOB+SURNAME rescue — an exact birth
    date plus an identical surname, but ONLY when that (DOB, surname) pair is unique
    on both sides, which recovers nickname/known-as/abbreviation cases the fuzzy
    name test misses (Isaac "Tanto" Olaofe, Oluwafemi -> Femi Ilesanmi) while
    refusing siblings who share both (see _dob_surname_rescue). Stage 6 (optional):
    EXACT-NAME-WITHIN-LEAGUE rescue — providers genuinely disagree on some birth
    dates (Ethan Pye: we have 2002-11-07, Impect 2003-11-27), so when
    `league_name_index` is supplied (a name -> player_id map of OUR players in THIS
    league season, restricted to names that are unique there) an exact normalised-
    name match is safe even with no date agreement, because two different
    footballers with the identical full name in the same division and season is
    beyond credible. It is applied only to Impect names that are ALSO unique among
    the still-unmatched rows, so no ambiguous name is ever auto-matched. Unmatched
    rows keep player_id NaN; `matched_via` records the stage.
    """
    ours = ours.copy()
    ours["nname"] = ours["player_name"].map(_norm)
    ours["birth_date"] = pd.to_datetime(ours["birth_date"], errors="coerce")

    result = impect_players.copy()
    result["player_id"] = pd.NA
    result["matched_via"] = pd.NA

    if overrides is not None and not overrides.empty and "playerId" in result.columns:
        ov = dict(zip(overrides["impect_player_id"], overrides["our_player_id"]))
        for idx, row in result.iterrows():
            pid = ov.get(row["playerId"])
            if pid is not None:
                result.at[idx, "player_id"] = pid
                result.at[idx, "matched_via"] = "override"

    by_tm = (ours.dropna(subset=["tm_player_id"])
                 .drop_duplicates("tm_player_id").set_index("tm_player_id")["player_id"])
    by_dob: dict = {}
    for i, row in enumerate(ours.itertuples()):
        if pd.notna(row.birth_date):
            by_dob.setdefault(row.birth_date.date(), []).append(i)

    for idx, row in result.iterrows():
        if pd.notna(row["player_id"]):
            continue                                    # already set by the override stage
        if pd.notna(row["tm_player_id"]) and row["tm_player_id"] in by_tm.index:
            result.at[idx, "player_id"] = by_tm[row["tm_player_id"]]
            result.at[idx, "matched_via"] = "tm_id"
            continue
        if pd.notna(row["birth_date"]):
            bd = pd.to_datetime(row["birth_date"])
            i = _dob_name_match(_norm(row["player_name"]),
                                by_dob.get(bd.date(), []), ours)
            if i is not None:
                result.at[idx, "player_id"] = ours.at[i, "player_id"]
                result.at[idx, "matched_via"] = "dob_name"
                continue
            i = _swapped_date_match(_norm(row["player_name"]), bd, by_dob, ours)
            if i is not None:
                result.at[idx, "player_id"] = ours.at[i, "player_id"]
                result.at[idx, "matched_via"] = "dob_swap"

    _dob_surname_rescue(result, "player_name", by_dob, ours)
    if league_name_index:
        _exact_name_league_rescue(result, "player_name", league_name_index)
    return result


def _surname(nname: str) -> str:
    """Last normalised token of a name (empty string if none)."""
    toks = nname.split()
    return toks[-1] if toks else ""


def _dob_surname_rescue(result: pd.DataFrame, name_col: str, by_dob: dict,
                        ours: pd.DataFrame) -> None:
    """In place: match still-unmatched rows on EXACT birth date + surname.

    Fires only when the (birth date, surname) pair identifies exactly ONE player on
    BOTH sides — one of our same-DOB players carries that surname, and the provider
    row is the only still-unmatched one with that (DOB, surname). This double
    uniqueness is what makes it safe against SIBLINGS, who share a birth date and
    surname (twins Michael & Matthew Craig, Kyrell & Kyreece Lisbie exist in the
    data): a twin pair is non-unique on our side, so BOTH are refused and left NULL
    rather than merged. It rescues the common case where an exact DOB agrees but the
    forename is a nickname/known-as/abbreviation the fuzzy name test misses
    (Isaac "Tanto" Olaofe, Oluwafemi -> Femi Ilesanmi). Tagged "dob_surname".
    """
    unmatched = result[result["player_id"].isna()].copy()
    if unmatched.empty:
        return
    unmatched["_dob"] = pd.to_datetime(unmatched["birth_date"], errors="coerce").dt.date
    unmatched["_sur"] = unmatched[name_col].map(lambda n: _surname(_norm(n)))
    # Provider-side uniqueness: refuse any (DOB, surname) that appears more than once.
    pair_freq = unmatched.groupby(["_dob", "_sur"]).size()
    for idx, row in unmatched.iterrows():
        dob, sur = row["_dob"], row["_sur"]
        if dob is None or not sur or pair_freq.get((dob, sur), 0) != 1:
            continue
        # Our-side uniqueness: exactly one same-DOB player carries that surname.
        cands = [i for i in by_dob.get(dob, []) if _surname(ours.at[i, "nname"]) == sur]
        if len(cands) == 1:
            result.at[idx, "player_id"] = ours.at[cands[0], "player_id"]
            result.at[idx, "matched_via"] = "dob_surname"


def _exact_name_league_rescue(result: pd.DataFrame, name_col: str,
                              league_name_index: dict[str, int]) -> None:
    """In place: match still-unmatched rows by exact name unique in the league.

    league_name_index already contains ONLY names unique among our league-season
    players; here we additionally require the name to be unique among the rows
    still unmatched, so a name appearing twice on either side is never matched.
    """
    unmatched = result[result["player_id"].isna()].copy()
    unmatched["_nn"] = unmatched[name_col].map(_norm)
    freq = unmatched["_nn"].value_counts()
    for idx, row in unmatched.iterrows():
        nn = row["_nn"]
        if freq.get(nn, 0) == 1 and nn in league_name_index:
            result.at[idx, "player_id"] = league_name_index[nn]
            result.at[idx, "matched_via"] = "name_league"


def unique_league_name_index(spine: pd.DataFrame) -> dict[str, int]:
    """name -> player_id for OUR players in one league season, unique names only."""
    tmp = spine.copy()
    tmp["_nn"] = tmp["player_name"].map(_norm)
    counts = tmp["_nn"].value_counts()
    keep = tmp[tmp["_nn"].map(counts) == 1]
    return dict(zip(keep["_nn"], keep["player_id"]))


def _swapped_date_match(nname: str, birth_date, by_dob: dict, ours: pd.DataFrame):
    """Index in `ours` matching an EXACT name under a day/month-swapped date, else None."""
    if pd.isna(birth_date) or birth_date.day > 12:
        return None                     # day can't be a month: no valid swap exists
    swapped = datetime.date(birth_date.year, birth_date.day, birth_date.month)
    for i in by_dob.get(swapped, []):
        if ours.at[i, "nname"] == nname:
            return i
    return None


def compare_goals(matched: pd.DataFrame, sb: pd.DataFrame) -> dict:
    """Per-player goal totals, Impect vs StatsBomb, for one league season.

    Returns exact/within-one rates and the xG correlation. StatsBomb totals
    include playoffs and Impect's league iteration does not, so within-one is
    the operative agreement measure; the exact rate is still reported.
    """
    # Only the numeric columns are needed from StatsBomb; the display name comes
    # from the Impect side, so no column-name collision and no suffix surprises.
    sb_cols = sb[["player_id", "goals", "xg"]]
    joined = matched.dropna(subset=["player_id"]).merge(sb_cols, on="player_id", how="inner")
    if joined.empty:
        return {"players_compared": 0}
    goal_diff = (joined["total_goals"].round() - joined["goals"]).abs()
    xg_ok = joined[["total_shot_xg", "xg"]].dropna()
    return {
        "players_compared": len(joined),
        "goals_exact_pct": float((goal_diff == 0).mean() * 100),
        "goals_within_one_pct": float((goal_diff <= 1).mean() * 100),
        "goals_mean_abs_diff": float(goal_diff.mean()),
        "xg_correlation": float(np.corrcoef(xg_ok["total_shot_xg"], xg_ok["xg"])[0, 1])
        if len(xg_ok) > 2 else None,
        "worst_disagreements": joined.assign(diff=goal_diff)
            .nlargest(3, "diff")[["player_name", "total_goals", "goals", "diff"]]
            .to_dict(orient="records"),
    }


def check_target(target: ImpectTarget, engine) -> dict:
    """Run the full check for one iteration; returns the report dict."""
    path = impect_landing.averages_path(target.iteration_id)
    if not path.exists():
        return {"label": target.label, "status": "NOT PULLED"}
    frame = pd.read_parquet(path)
    players = aggregate_players(frame)

    ours = pd.read_sql(
        "SELECT player_id, player_name, birth_date, tm_player_id FROM players", engine)
    matched = match_to_ours(players, ours)

    report = {
        "label": target.label,
        "status": "OK",
        "impect_players": len(players),
        "matched_total_pct": float(matched["player_id"].notna().mean() * 100),
        "matched_via_tm_id": int((matched["matched_via"] == "tm_id").sum()),
        "matched_via_dob_name": int((matched["matched_via"] == "dob_name").sum()),
        "tm_id_present_pct": float(players["tm_player_id"].notna().mean() * 100),
    }

    if target.sb_competition_id is not None:
        sb = pd.read_sql(
            "SELECT player_id, player_name, goals, xg FROM player_season_metrics "
            f"WHERE competition_id = {target.sb_competition_id} "
            f"AND season_id = {target.sb_season_id}", engine)
        report["goals_check"] = compare_goals(matched, sb)
    return report


def main() -> None:
    engine = get_engine()
    print("Impect validation report (read-only)")
    print("=" * 72)
    for target in settings.impect_targets:
        r = check_target(target, engine)
        print(f"\n[{r['label']}] {r['status']}")
        if r["status"] != "OK":
            continue
        print(f"  players: {r['impect_players']}  |  TM id present: {r['tm_id_present_pct']:.0f}%")
        print(f"  matched to our DB: {r['matched_total_pct']:.1f}% "
              f"(tm_id {r['matched_via_tm_id']}, dob+name {r['matched_via_dob_name']})")
        gc = r.get("goals_check")
        if gc:
            if gc["players_compared"]:
                print(f"  goals vs StatsBomb ({gc['players_compared']} players): "
                      f"exact {gc['goals_exact_pct']:.1f}%, within one {gc['goals_within_one_pct']:.1f}%, "
                      f"mean abs diff {gc['goals_mean_abs_diff']:.2f}")
                if gc["xg_correlation"] is not None:
                    print(f"  xG correlation (Impect SHOT_XG vs StatsBomb xG): {gc['xg_correlation']:.3f}")
                for w in gc["worst_disagreements"]:
                    print(f"    biggest gap: {w['player_name']}: "
                          f"impect {w['total_goals']:.0f} vs sb {w['goals']} (diff {w['diff']:.0f})")
            else:
                print("  goals vs StatsBomb: no overlapping players (check matching)")
    print("\nDone. This report gates Phase B: do not build on Impect until "
          "matching and goal agreement look healthy for the EFL iterations.")


if __name__ == "__main__":
    main()
