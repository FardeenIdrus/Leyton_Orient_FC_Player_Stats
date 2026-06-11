"""Estimate each player's fair market value, then flag those priced below it.

Two market-value sources, one per data era, each era trained as its own model so
price levels a decade apart never mix:
  - Demo era (2015/16 trio): the dcaribou dataset, matched by name scoped to league
    appearance records (Transfermarkt's league tag is unreliable).
  - EFL era (paid feed): squad-page values scraped by lofc.ingest.transfermarkt_efl,
    matched by birth date (from the paid lineups) plus name, league-scoped. Only the
    current season is valued: the scrape is a snapshot, earlier seasons would pair
    old output with today's prices.

Both eras then follow the same path: train a Ridge regression to predict log market
value from performance + age + minutes + position + league, cross-validated so every
fair value comes from a model that did NOT train on that player. Undervaluation =
fair value minus actual value (positive = bargain).

Run with:  python -m lofc.model.valuation
"""

from __future__ import annotations

import datetime
import difflib
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import RidgeCV
from sklearn.model_selection import KFold, cross_val_predict, cross_val_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sqlalchemy import bindparam, delete, update

from lofc.config import settings
from lofc.model.normalise import DISPLAY_METRICS, compute_percentiles_wide
from lofc.store.load import _records, _upsert, get_engine
from lofc.store.models import Player, Valuation

# 2015/16 reference points. Age is measured at the season midpoint; the market value is
# the latest one on or before season end, provided the player was active in this era.
REFERENCE_DATE = datetime.date(2016, 1, 1)
SEASON_START = "2015-07-01"
SEASON_END = "2016-06-30"
ERA_START = "2015-01-01"
MODEL_VERSION = "ridgecv-v1"
FUZZY_CUTOFF = 0.80
# A high-minutes top-league regular outside this age range is almost always a name
# mismatch (a short name matched to a same-named older/younger player), so we reject it.
PLAUSIBLE_AGE = (16.0, 38.0)

# Our competition_id -> Transfermarkt domestic-league code. Used to scope name matching
# to players who actually appeared in that league in 2015/16 (the valuation league tag
# is unreliable, but appearance records are not).
LEAGUE_CODE = {2: "GB1", 11: "ES1", 12: "IT1"}

# --- EFL real-data era (paid feed + scraped Transfermarkt squad pages) ---------------
# Scraped values are a current snapshot, so only the season just played is era-matched
# and eligible for valuation. Earlier seasons keep scores and archetypes (trajectory)
# but get no fair value: pricing 2024/25 output with 2026 values would be dishonest.
EFL_LEAGUE_IDS = {3, 4, 5, 65}
EFL_SEASON_ID = 318  # 2025/26
EFL_REFERENCE_DATE = datetime.date(2026, 1, 1)  # season midpoint, for age
EFL_MODEL_VERSION = "ridgecv-v2-efl"
# With identical birth dates a weaker name agreement is safe; without a birth date we
# require the same high bar as the demo path.
DOB_NAME_CUTOFF = 0.55


def _norm(name: str) -> str:
    """Lowercase, strip accents and punctuation, collapse spaces."""
    stripped = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", stripped.lower())).strip()


def _tmdir() -> Path:
    return Path(settings.reference_data_dir) / "transfermarkt"


def load_market_values() -> pd.DataFrame:
    """One 2015/16 market value and birth date per Transfermarkt player."""
    players = pd.read_csv(_tmdir() / "players.csv")
    valuations = pd.read_csv(_tmdir() / "player_valuations.csv")

    # Latest value on or before season end; keep only players active in the 2015/16 era.
    in_window = valuations[valuations["date"] <= SEASON_END].sort_values("date")
    latest = in_window.groupby("player_id").tail(1)
    latest = latest[latest["date"] >= ERA_START]

    tm = latest.merge(players[["player_id", "name", "date_of_birth"]], on="player_id", how="left")
    tm = tm.dropna(subset=["name"]).rename(columns={"market_value_in_eur": "value_eur"})
    tm["nname"] = tm["name"].map(_norm)
    tm["tokens"] = tm["nname"].str.split().map(set)
    tm["birth_date"] = pd.to_datetime(tm["date_of_birth"], errors="coerce")
    return tm.reset_index(drop=True)


def load_league_players() -> dict[int, set[int]]:
    """For each of our leagues, the Transfermarkt player_ids that appeared there in 2015/16."""
    appearances = pd.read_csv(_tmdir() / "appearances.csv",
                              usecols=["player_id", "date", "competition_id"])
    season = appearances[(appearances["date"] >= SEASON_START) & (appearances["date"] <= SEASON_END)]
    return {comp_id: set(season[season["competition_id"] == code]["player_id"])
            for comp_id, code in LEAGUE_CODE.items()}


def _build_index(tm: pd.DataFrame):
    """Exact-name lookup plus a token inverted index for fuzzy fallback."""
    exact: dict[str, int] = {}
    token_index: dict[str, set[int]] = defaultdict(set)
    for i, row in enumerate(tm.itertuples()):
        # On a rare exact-name collision, keep the higher-valued (more prominent) player.
        if row.nname not in exact or tm.at[i, "value_eur"] > tm.at[exact[row.nname], "value_eur"]:
            exact[row.nname] = i
        for token in row.tokens:
            token_index[token].add(i)
    return exact, token_index


def _match_one(name: str, tm: pd.DataFrame, exact, token_index) -> int | None:
    """Return the Transfermarkt row index for a player name, or None if no good match."""
    normed = _norm(name)
    if normed in exact:
        return exact[normed]

    our_tokens = set(normed.split())
    candidates: set[int] = set()
    for token in our_tokens:
        candidates |= token_index.get(token, set())

    sorted_ours = " ".join(sorted(our_tokens))
    best_score, best_i = 0.0, None
    for i in candidates:
        tm_tokens = tm.at[i, "tokens"]
        if our_tokens <= tm_tokens or tm_tokens <= our_tokens:
            score = 0.9 + 0.1 * len(our_tokens & tm_tokens) / max(len(our_tokens | tm_tokens), 1)
        else:
            score = difflib.SequenceMatcher(None, sorted_ours, " ".join(sorted(tm_tokens))).ratio()
        if score > best_score:
            best_score, best_i = score, i
    return best_i if best_score >= FUZZY_CUTOFF else None


def match_players(metrics: pd.DataFrame, tm: pd.DataFrame,
                  league_players: dict[int, set[int]]) -> tuple[pd.DataFrame, list[str]]:
    """Attach a market value, age and birth date to each rankable player.

    Matching is scoped per league: a Premier League player is only matched against
    Transfermarkt players who actually appeared in the Premier League that season.
    """
    # One name index per league, built from only that league's players.
    league_index = {}
    for comp_id, player_ids in league_players.items():
        subset = tm[tm["player_id"].isin(player_ids)].reset_index(drop=True)
        league_index[comp_id] = (subset, *_build_index(subset))

    rows, unmatched = [], []
    for r in metrics[metrics["rankable"]].itertuples():
        if r.competition_id not in league_index:
            unmatched.append(r.player_name)
            continue
        subset, exact, token_index = league_index[r.competition_id]
        i = _match_one(r.player_name, subset, exact, token_index)
        if i is None:
            unmatched.append(r.player_name)
            continue
        birth = subset.at[i, "birth_date"]
        age = (REFERENCE_DATE - birth.date()).days / 365.25 if pd.notna(birth) else None
        # Reject implausible ages: these are name mismatches, not real players.
        if age is not None and not (PLAUSIBLE_AGE[0] <= age <= PLAUSIBLE_AGE[1]):
            unmatched.append(f"{r.player_name} (rejected: implausible age {age:.0f})")
            continue
        rows.append({
            "player_id": r.player_id,
            "competition_id": r.competition_id,
            "season_id": r.season_id,
            "position_group": r.position_group,
            "minutes": r.minutes,
            "market_value_eur": float(subset.at[i, "value_eur"]),
            "age": round(age, 1) if age is not None else None,
            "birth_date": birth.date() if pd.notna(birth) else None,
        })
    return pd.DataFrame(rows), unmatched


def load_efl_values() -> pd.DataFrame:
    """Scraped squad-page values for the EFL leagues, one row per player.

    Alongside the market value, the squad pages carry foot, contract end date and
    height; they ride the same match and land on the players table.
    """
    efl = pd.read_csv(_tmdir() / "efl_values.csv")
    efl = efl.dropna(subset=["market_value_eur"]).rename(columns={"market_value_eur": "value_eur"})
    efl["nname"] = efl["player_name"].map(_norm)
    efl["tokens"] = efl["nname"].str.split().map(set)
    efl["birth_date"] = pd.to_datetime(efl["date_of_birth"], errors="coerce")
    for column in ("foot", "contract_until", "height_cm", "tm_player_id"):
        if column not in efl.columns:  # older CSV from before the detailed scrape
            efl[column] = None
    return efl.reset_index(drop=True)


def load_efl_fallback() -> pd.DataFrame | None:
    """Values for players the squad scrape misses: loanees from outside the four
    leagues and January movers, present in the dcaribou players file.

    Only rows whose value was maintained this season are kept; older entries are
    last-known-at-coverage-time and would price players years out of date.
    """
    path = _tmdir() / "players.csv"
    if not path.exists():
        return None
    fb = pd.read_csv(path, usecols=["player_id", "name", "date_of_birth",
                                    "market_value_in_eur", "last_season"])
    fb = fb[(fb["last_season"] >= 2025) & fb["market_value_in_eur"].notna()]
    # The dataset's player_id IS the Transfermarkt id, so fallback matches get links too.
    fb = fb.rename(columns={"market_value_in_eur": "value_eur", "name": "player_name",
                            "player_id": "tm_player_id"})
    fb["nname"] = fb["player_name"].map(_norm)
    fb["birth_date"] = pd.to_datetime(fb["date_of_birth"], errors="coerce")
    fb = fb.dropna(subset=["birth_date"])
    return fb.reset_index(drop=True)


def _dob_name_match(nname: str, candidates: list[int], frame: pd.DataFrame) -> int | None:
    """Best same-birth-date candidate whose name agrees enough, else None."""
    best_score, best_i = 0.0, None
    sorted_ours = " ".join(sorted(nname.split()))
    for i in candidates:
        score = difflib.SequenceMatcher(
            None, sorted_ours, " ".join(sorted(frame.at[i, "nname"].split()))).ratio()
        if score > best_score:
            best_score, best_i = score, i
    return best_i if best_i is not None and best_score >= DOB_NAME_CUTOFF else None


def match_players_efl(metrics: pd.DataFrame, efl: pd.DataFrame,
                      fallback: pd.DataFrame | None = None) -> tuple[pd.DataFrame, list[str]]:
    """Attach a market value to each rankable EFL player of the valuation season.

    Three stages: birth date + name within the league's squad scrape, then the
    demo-era name matching within the same league, then birth date + name against
    the fallback file (loanees from outside the four leagues, January movers).
    """
    eligible = metrics[
        metrics["rankable"]
        & metrics["competition_id"].isin(EFL_LEAGUE_IDS)
        & (metrics["season_id"] == EFL_SEASON_ID)
    ]

    # (league, birth date) -> TM row indices, for the primary DOB join.
    by_dob: dict[tuple[int, datetime.date], list[int]] = defaultdict(list)
    for i, row in enumerate(efl.itertuples()):
        if pd.notna(row.birth_date):
            by_dob[(row.competition_id, row.birth_date.date())].append(i)
    league_index = {}
    for comp_id in efl["competition_id"].unique():
        subset = efl[efl["competition_id"] == comp_id].reset_index()
        league_index[comp_id] = (subset, *_build_index(subset))
    fb_by_dob: dict[datetime.date, list[int]] = defaultdict(list)
    if fallback is not None:
        for i, row in enumerate(fallback.itertuples()):
            fb_by_dob[row.birth_date.date()].append(i)

    def _bio(frame: pd.DataFrame, i: int) -> dict:
        """Foot / contract / height / TM id, taking whichever columns the source has
        (squad pages carry all four; the fallback dataset only the TM id)."""
        def column(name, cast=None):
            if name not in frame.columns:
                return None
            value = frame.at[i, name]
            if pd.isna(value):
                return None
            return cast(value) if cast else value
        return {"foot": column("foot"), "contract_until": column("contract_until"),
                "height_cm": column("height_cm", int), "tm_player_id": column("tm_player_id", int)}

    rows, unmatched = [], []
    n_fallback = 0
    for r in eligible.itertuples():
        our_dob = pd.to_datetime(r.birth_date).date() if pd.notna(r.birth_date) else None
        nname = _norm(r.player_name)
        value_eur, tm_birth, bio = None, None, _bio(pd.DataFrame(), -1)

        if our_dob is not None:
            i = _dob_name_match(nname, by_dob.get((r.competition_id, our_dob), []), efl)
            if i is not None:
                value_eur, tm_birth = float(efl.at[i, "value_eur"]), efl.at[i, "birth_date"]
                bio = _bio(efl, i)

        if value_eur is None and r.competition_id in league_index:
            subset, exact, token_index = league_index[r.competition_id]
            sub_i = _match_one(r.player_name, subset, exact, token_index)
            if sub_i is not None:
                tm_dob = subset.at[sub_i, "birth_date"]
                # A name match contradicting a known birth date is a different player.
                if our_dob is not None and pd.notna(tm_dob) and tm_dob.date() != our_dob:
                    sub_i = None
            if sub_i is not None:
                value_eur, tm_birth = float(subset.at[sub_i, "value_eur"]), subset.at[sub_i, "birth_date"]
                bio = _bio(subset, sub_i)

        if value_eur is None and our_dob is not None and fb_by_dob:
            i = _dob_name_match(nname, fb_by_dob.get(our_dob, []), fallback)
            if i is not None:
                value_eur, tm_birth = float(fallback.at[i, "value_eur"]), fallback.at[i, "birth_date"]
                bio = _bio(fallback, i)
                n_fallback += 1

        if value_eur is None:
            unmatched.append(f"{r.player_name} ({r.competition_name})")
            continue

        best_birth = our_dob or (tm_birth.date() if pd.notna(tm_birth) else None)
        age = ((EFL_REFERENCE_DATE - best_birth).days / 365.25) if best_birth else None
        if age is not None and not (PLAUSIBLE_AGE[0] <= age <= PLAUSIBLE_AGE[1]):
            unmatched.append(f"{r.player_name} (rejected: implausible age {age:.0f})")
            continue
        rows.append({
            "player_id": r.player_id,
            "competition_id": r.competition_id,
            "season_id": r.season_id,
            "position_group": r.position_group,
            "minutes": r.minutes,
            "market_value_eur": value_eur,
            "age": round(age, 1) if age is not None else None,
            "birth_date": best_birth,
            **bio,
        })
    if n_fallback:
        print(f"  (fallback file matched {n_fallback} players the squad scrape missed)")
    return pd.DataFrame(rows), unmatched


def build_features(metrics: pd.DataFrame, matched: pd.DataFrame):
    """Feature matrix X and target y (log market value) for the matched players."""
    keys = ["player_id", "competition_id", "season_id"]
    wide = compute_percentiles_wide(metrics).reset_index()
    wide[DISPLAY_METRICS] = wide[DISPLAY_METRICS].fillna(50.0)  # neutral for undefined metrics

    data = matched.merge(wide.drop(columns=["position_group"]), on=keys, how="left")
    # Age is the only feature that can be missing (no birth date); fill with the median.
    data["age"] = data["age"].fillna(data["age"].median())

    features = data[DISPLAY_METRICS + ["age", "minutes"]].copy()
    features = features.join(pd.get_dummies(data["position_group"], prefix="pos"))
    features = features.join(pd.get_dummies(data["competition_id"], prefix="league"))

    target = np.log1p(data["market_value_eur"].to_numpy())
    return features.astype(float), target, data


def value_players(features: pd.DataFrame, target: np.ndarray):
    """Cross-validated fair values (out-of-fold) plus honest accuracy metrics."""
    model = make_pipeline(StandardScaler(), RidgeCV(alphas=[0.1, 1.0, 10.0, 100.0]))
    folds = KFold(n_splits=5, shuffle=True, random_state=42)

    oof_log = cross_val_predict(model, features, target, cv=folds)
    r2 = cross_val_score(model, features, target, cv=folds, scoring="r2").mean()

    fair_value = np.expm1(oof_log)
    actual = np.expm1(target)
    mae = float(np.mean(np.abs(fair_value - actual)))
    median_ae = float(np.median(np.abs(fair_value - actual)))
    return fair_value, {"r2_log": round(float(r2), 3), "mae_eur": mae, "median_ae_eur": median_ae}


def _value_era(metrics: pd.DataFrame, matched: pd.DataFrame, model_version: str) -> pd.DataFrame:
    """Train, cross-validate and report one era's valuation model."""
    features, target, data = build_features(metrics, matched)
    fair_value, report = value_players(features, target)
    print(f"  [{model_version}] cross-validated R2 (log scale): {report['r2_log']}")
    print(f"  [{model_version}] mean abs error: EUR {report['mae_eur']:,.0f} | "
          f"median abs error: EUR {report['median_ae_eur']:,.0f}")

    data["fair_value_eur"] = fair_value.round(0)
    data["undervaluation_eur"] = (data["fair_value_eur"] - data["market_value_eur"]).round(0)
    data["undervaluation_pct"] = (data["undervaluation_eur"] / data["fair_value_eur"]).round(3)
    data["model_version"] = model_version
    return data


def main() -> None:
    engine = get_engine()
    # Lineup birth dates live on players, not the metrics table; the EFL match needs them.
    metrics = pd.read_sql(
        "SELECT m.*, p.birth_date FROM player_season_metrics m "
        "LEFT JOIN players p ON p.player_id = m.player_id", engine)

    # Each era trains its own model: price levels a decade apart must never mix.
    eras: list[pd.DataFrame] = []

    demo_rows = metrics[metrics["competition_id"].isin(LEAGUE_CODE)]
    if not demo_rows.empty and (_tmdir() / "players.csv").exists():
        tm = load_market_values()
        league_players = load_league_players()
        matched, unmatched = match_players(demo_rows, tm, league_players)
        rankable = int(demo_rows["rankable"].sum())
        print(f"[demo 2015/16] matched {len(matched)}/{rankable} rankable players "
              f"({100 * len(matched) / rankable:.1f}%); {len(unmatched)} unmatched")
        if not matched.empty:
            eras.append(_value_era(metrics, matched, MODEL_VERSION))

    efl_rows = metrics[metrics["competition_id"].isin(EFL_LEAGUE_IDS)]
    if not efl_rows.empty and (_tmdir() / "efl_values.csv").exists():
        excluded = int((efl_rows["rankable"] & (efl_rows["season_id"] != EFL_SEASON_ID)).sum())
        if excluded:
            print(f"[EFL] {excluded} rankable rows from earlier seasons keep scores but get "
                  "no valuation (scraped values are a current snapshot)")
        matched, unmatched = match_players_efl(metrics, load_efl_values(), load_efl_fallback())
        eligible = int((efl_rows["rankable"] & (efl_rows["season_id"] == EFL_SEASON_ID)).sum())
        if eligible:
            print(f"[EFL 2025/26] matched {len(matched)}/{eligible} rankable players "
                  f"({100 * len(matched) / eligible:.1f}%); {len(unmatched)} unmatched")
        if not matched.empty:
            eras.append(_value_era(metrics, matched, EFL_MODEL_VERSION))

    if not eras:
        raise SystemExit("no valuation source available for the configured competitions")
    data = pd.concat(eras, ignore_index=True)

    columns = ["player_id", "competition_id", "season_id", "position_group", "age",
               "market_value_eur", "fair_value_eur", "undervaluation_eur",
               "undervaluation_pct", "model_version"]
    # Clear first: this table is fully derived, and the matched set can shrink between
    # runs (e.g. rejected mismatches), so a plain upsert would leave stale rows behind.
    with engine.begin() as conn:
        conn.execute(delete(Valuation.__table__))
    n = _upsert(engine, Valuation.__table__, _records(data[columns]),
                ["player_id", "competition_id", "season_id"])
    print(f"valuations: wrote {n}")

    # Backfill bio facts learned during the match (birth date, and from the squad
    # pages: foot, contract end, height, Transfermarkt id) into the players table.
    for column in ("foot", "contract_until", "height_cm", "tm_player_id"):
        if column not in data.columns:  # demo era only: no squad-page bio
            data[column] = None
    bio = data.dropna(subset=["birth_date"])
    if not bio.empty:
        stmt = (update(Player.__table__)
                .where(Player.__table__.c.player_id == bindparam("pid"))
                .values(birth_date=bindparam("bd"), foot=bindparam("ft"),
                        contract_until=bindparam("cu"), height_cm=bindparam("hc"),
                        tm_player_id=bindparam("tm")))
        with engine.begin() as conn:
            conn.execute(stmt, [
                {"pid": int(r.player_id), "bd": r.birth_date,
                 "ft": r.foot if pd.notna(r.foot) else None,
                 "cu": r.contract_until if pd.notna(r.contract_until) else None,
                 "hc": int(r.height_cm) if pd.notna(r.height_cm) else None,
                 "tm": int(r.tm_player_id) if pd.notna(r.tm_player_id) else None}
                for r in bio.itertuples()])
        print(f"backfilled bio (birth date, foot, contract, height, TM id) for {len(bio)} players")

    _spot_check(data)


def _spot_check(data: pd.DataFrame) -> None:
    """Show the biggest bargains: high performers priced well below their fair value."""
    engine = get_engine()
    names = pd.read_sql("SELECT player_id, competition_id, season_id, player_name, team_name "
                        "FROM player_season_metrics", engine)
    named = data.merge(names, on=["player_id", "competition_id", "season_id"], how="left")
    top = named[named["minutes"] > 1500].sort_values("undervaluation_pct", ascending=False).head(10)
    show = top[["player_name", "team_name", "position_group", "age",
                "market_value_eur", "fair_value_eur", "undervaluation_pct"]]
    print("\nBiggest bargains (fair value well above market value):")
    print(show.to_string(index=False))


if __name__ == "__main__":
    main()
