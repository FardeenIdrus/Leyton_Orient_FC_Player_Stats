"""Estimate each player's fair market value, then flag those priced below it.

Pipeline:
  1. Load Transfermarkt 2015/16 market values (the target) and player birth dates.
  2. Match them to our players by name (Transfermarkt's league tag is unreliable, so we
     match on name globally, not by league).
  3. Train a Ridge regression to predict value from performance + age + minutes +
     position + league. Value is log-scaled because it is heavily skewed.
  4. Use cross-validation so every player's fair value comes from a model that did NOT
     train on them. Undervaluation = fair value minus actual value (positive = bargain).

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


def main() -> None:
    engine = get_engine()
    metrics = pd.read_sql("SELECT * FROM player_season_metrics", engine)

    tm = load_market_values()
    league_players = load_league_players()
    matched, unmatched = match_players(metrics, tm, league_players)
    rankable_total = int(metrics["rankable"].sum())
    print(f"matched {len(matched)}/{rankable_total} rankable players "
          f"({100 * len(matched) / rankable_total:.1f}%); {len(unmatched)} unmatched")

    features, target, data = build_features(metrics, matched)
    fair_value, report = value_players(features, target)
    print(f"cross-validated R2 (log scale): {report['r2_log']}")
    print(f"mean abs error: EUR {report['mae_eur']:,.0f} | median abs error: EUR {report['median_ae_eur']:,.0f}")

    data["fair_value_eur"] = fair_value.round(0)
    data["undervaluation_eur"] = (data["fair_value_eur"] - data["market_value_eur"]).round(0)
    data["undervaluation_pct"] = (data["undervaluation_eur"] / data["fair_value_eur"]).round(3)
    data["model_version"] = MODEL_VERSION

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

    # Backfill birth dates we learned from Transfermarkt into the players table.
    births = data.dropna(subset=["birth_date"])[["player_id", "birth_date"]]
    if not births.empty:
        stmt = (update(Player.__table__)
                .where(Player.__table__.c.player_id == bindparam("pid"))
                .values(birth_date=bindparam("bd")))
        with engine.begin() as conn:
            conn.execute(stmt, [{"pid": int(r.player_id), "bd": r.birth_date} for r in births.itertuples()])
        print(f"backfilled birth dates for {len(births)} players")

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
