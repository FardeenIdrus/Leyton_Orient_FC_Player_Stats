"""Find similar players (owner-approved 2026-11-16; method revised 2026-11-20): the player card's
"Similar players" section and the "Similar players" page (/similar/...).

THE METHOD (docs/methodology.md 6c has a worked example)
  Pool      Same season, same position group, RATED players only (an Overall from a pool of at
            least MIN_PEERS_FOR_RANKING, so 450+ minutes), never the player himself (any row of
            his that season). "Same league" (default) or "All leagues".
  Measures  The position's rating measures: Performance (the club's list, stored names) and
            Physical (SkillCorner), exactly the ones the scorecard rates him on.
  z-score   Per measure z = (value - mean) / sd (population sd) WITHIN league + season +
            position -- the pool he was rated in, so a thin midfield group uses all midfielders
            of the league, as his rating does (scorecard.pool_assignment). Lower-is-better
            measures are sign-flipped (higher z = better); |z| clipped at 3. Being standardised
            inside his own league is what makes "All leagues" honest: no league is placed above
            another, only shapes are compared.
  Weights   Each measure's share of Overall (club_vs_league.overall_weights: its weight inside
            its dimension x the dimension's share, read from club_framework at run time, so the
            65 : 35 split is never hard-coded here).
  Correlation  R = the measures' correlation matrix on the season's position pool (all leagues,
            z-scores): Ledoit-Wolf shrinkage (sklearn) fitted on the rows that have every measure,
            turned into a correlation matrix. Under LW_ROWS_PER_MEASURE x (number of measures)
            such rows: the pairwise correlation (pairs with CORR_MIN_PERIODS+ rows, else 0)
            shrunk toward identity by the Ledoit-Wolf intensity of the rows with gaps filled by
            0. Eigenvalues floored at EIG_FLOOR (positive definite), diagonal kept at 1.
  Distance  Weighted Mahalanobis over the measures BOTH players have (shared set S):
            d^2 = delta_S' D_S inv(R_SS) D_S delta_S / sum(w_S), delta = z gap,
            D = diag(sqrt(w)). With R = identity this is the weighted Euclidean
            sum(w delta^2) / sum(w); measures that move together are no longer counted twice.
            Needs at least 70% of the target's own Overall weight shared, else the player is
            left out: an outfielder with physical data is never matched with one without
            (Physical is 35% of Overall), while a player with no physical data -- most
            non-English leagues -- is compared on the performance measures he has.
  Similarity The % of all pairs of players at that position and season (all leagues, pairs
            meeting the 70% rule against the LARGER of the two players' own weight) that are
            further apart than this pair. Whole number, .5 up; identical = 100.
  Order     By similarity only -- never by Overall across leagues. Overall is shown as rated in
            his own league.
  Filters   League (All leagues only), Max age, Min minutes, Contract expiring: they narrow the
            candidates; the similarity number never changes.

Pure functions first; the database half (cached per data version) at the bottom.
"""
from __future__ import annotations

import datetime
import math
import urllib.parse
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from lofc.core import webcache
from lofc.model import club_framework as cf

Z_CLIP = 3.0
LINK_R = 0.8                       # "linked" tag on the page (descriptive only)
CORR_MIN_PERIODS = 20
LW_ROWS_PER_MEASURE = 3
EIG_FLOOR = 1e-6
MIN_COVERAGE = 0.70
TOP_N = 10
SCOPES = ("league", "all")
AGE_OPTIONS = (21, 23, 25, 28, 31)
MIN_MINUTES_OPTIONS = (900, 1350, 1800)
CONTRACT_OPTIONS = ((6, "Under 6 months"), (12, "Under 12 months"))
MIDFIELD_POSITIONS = ("Defensive Mid", "Central Mid", "Attacking Mid")

ALL_LEAGUES_NOTE = "Measures are compared within each player's own league."
MIDFIELD_NOTE = "Measures set against all midfielders in his league, as in his rating."
NO_PHYSICAL_NOTE = "No physical data for him: compared on performance only."
NOT_RATED = "Not rated this season, so no comparison."
NO_MATCH = "No rated player matches."
DIFF_HELP = ("His two largest gaps, in standard deviations within each player's own league. "
             "+ = he is better.")
BREAKDOWN_NOTE = "Score uses every measure together, allowing for measures that move together."
LINKED_HELP = "Moves with: {}"
DASH = "—"


def similarity_help(position: str) -> str:
    return f"More alike than this % of all {position} pairs."


# --- weights -----------------------------------------------------------------------------------
def measure_weights(position: str) -> dict[str, float]:
    """metric -> its share of Overall (sums to 1), read from club_framework at call time."""
    from lofc.core.club_vs_league import overall_weights
    return overall_weights(position)


# --- z-scores ----------------------------------------------------------------------------------
def standardise(frame: pd.DataFrame, measures: list[str], keys: list[str]) -> pd.DataFrame:
    """z per measure within `keys` groups (population sd), lower-is-better flipped, clipped at
    Z_CLIP. A group with fewer than 2 values or no spread gives NaN (no z can be formed)."""
    out = pd.DataFrame(index=frame.index)
    by = [frame[k] for k in keys]
    for m in measures:
        v = (pd.to_numeric(frame[m], errors="coerce") if m in frame.columns
             else pd.Series(np.nan, index=frame.index)).astype(float)
        g = v.groupby(by, sort=False)
        mean = g.transform("mean")
        sd = np.sqrt(((v - mean) ** 2).groupby(by, sort=False).transform("mean"))
        n = g.transform("count")
        z = (v - mean) / sd.where((sd > 1e-12) & (n >= 2))
        if m in cf.LOWER_IS_BETTER:
            z = -z
        out[m] = z.clip(-Z_CLIP, Z_CLIP)
    return out


# --- correlation ------------------------------------------------------------------------------
def make_pd(R: np.ndarray, floor: float = EIG_FLOOR) -> np.ndarray:
    """Symmetric, eigenvalues at least `floor`, unit diagonal. A matrix already positive definite
    beyond the floor is returned unchanged (bar symmetry)."""
    R = np.asarray(R, dtype=float)
    R = (R + R.T) / 2.0
    if R.size == 0:
        return R
    vals, vecs = np.linalg.eigh(R)
    if vals.min() < floor:
        R = (vecs * np.maximum(vals, floor)) @ vecs.T
        d = np.sqrt(np.diag(R))
        R = R / np.outer(d, d)
        R = (R + R.T) / 2.0
    np.fill_diagonal(R, 1.0)
    return R


def correlation_matrix(Z: np.ndarray) -> np.ndarray:
    """The measures' correlation matrix (see the module docstring for the rule)."""
    Z = np.asarray(Z, dtype=float)
    n, k = Z.shape
    if k < 2 or n < 2:
        return np.eye(k)
    complete = ~np.isnan(Z).any(axis=1)
    if complete.sum() >= LW_ROWS_PER_MEASURE * k:
        from sklearn.covariance import LedoitWolf
        cov = LedoitWolf().fit(Z[complete]).covariance_
        sd = np.sqrt(np.diag(cov))
        sd = np.where(sd > 1e-12, sd, np.inf)            # a constant measure: linked to nothing
        R = cov / np.outer(sd, sd)
        np.fill_diagonal(R, 1.0)
    else:
        from sklearn.covariance import ledoit_wolf_shrinkage
        C = pd.DataFrame(Z).corr(min_periods=CORR_MIN_PERIODS).to_numpy()
        C = np.nan_to_num(C, nan=0.0)
        np.fill_diagonal(C, 1.0)
        lam = float(ledoit_wolf_shrinkage(np.nan_to_num(Z, nan=0.0)))
        R = (1.0 - lam) * C + lam * np.eye(k)
    return make_pd(R)


def linked_measures(R: np.ndarray, measures: list[str], r: float = LINK_R) -> dict[str, list[str]]:
    """measure -> the measures it moves with (|r| >= `r`), only measures that have any."""
    out: dict[str, list[str]] = {}
    for i, m in enumerate(measures):
        partners = [measures[j] for j in range(len(measures))
                    if j != i and abs(R[i, j]) >= r - 1e-12]
        if partners:
            out[m] = partners
    return out


# --- distance, similarity ----------------------------------------------------------------------
def _whitener(R, w: np.ndarray, mask: np.ndarray, cache: dict | None = None):
    """(indices of S, A, sum of w over S) with ||A delta_S||^2 = delta_S' D inv(R_SS) D delta_S:
    A = inv(L) D_S, L the Cholesky factor of R_SS (the marginal of R, never re-estimated)."""
    key = mask.tobytes()
    if cache is not None and key in cache:
        return cache[key]
    idx = np.flatnonzero(mask)
    sw = np.sqrt(w[idx])
    if R is None:
        A = np.diag(sw)
    else:
        L = np.linalg.cholesky(np.asarray(R, float)[np.ix_(idx, idx)])
        A = np.linalg.solve(L, np.diag(sw))
    got = (idx, A, float(w[idx].sum()))
    if cache is not None:
        cache[key] = got
    return got


def distances(target: np.ndarray, Z: np.ndarray, w: np.ndarray, R: np.ndarray | None = None,
              min_coverage: float = MIN_COVERAGE, cov_w: np.ndarray | None = None,
              cache: dict | None = None) -> tuple[np.ndarray, np.ndarray]:
    """(distance, coverage) from `target` to every row of Z. Coverage = Overall weight
    (`cov_w`, default `w`) of the measures both have / of the measures the target has; under
    `min_coverage` -> NaN distance. R None = identity (weighted Euclidean)."""
    target = np.asarray(target, dtype=float)
    Z = np.asarray(Z, dtype=float)
    w = np.asarray(w, dtype=float)
    cw = w if cov_w is None else np.asarray(cov_w, dtype=float)
    t_ok = ~np.isnan(target)
    both = t_ok[None, :] & ~np.isnan(Z)
    wsum = np.where(both, w[None, :], 0.0).sum(axis=1)
    own = float(cw[t_ok].sum())
    cov = np.where(both, cw[None, :], 0.0).sum(axis=1) / own if own > 0 else np.zeros(len(Z))
    d = np.full(len(Z), np.nan)
    ok = np.flatnonzero((wsum > 0) & (cov >= min_coverage - 1e-9))
    if len(ok):
        masks, inv = np.unique(both[ok], axis=0, return_inverse=True)
        inv = np.asarray(inv).reshape(-1)
        for u, mask in enumerate(masks):
            rows = ok[inv == u]
            idx, A, ws = _whitener(R, w, mask, cache)
            Y = (Z[np.ix_(rows, idx)] - target[idx][None, :]) @ A.T
            d[rows] = np.sqrt((Y * Y).sum(axis=1) / ws)
    return d, cov


def pair_distances(Z: np.ndarray, w: np.ndarray, R: np.ndarray | None = None,
                   cov_w: np.ndarray | None = None, chunk: int = 512) -> np.ndarray:
    """Every pair of rows (i < j) whose shared measures carry at least MIN_COVERAGE of the
    larger of the two players' own Overall weight (`cov_w`, default `w`): their distance,
    sorted (float32). Rows are grouped by which measures they have, so each shared set's
    inverse is worked out once."""
    Z = np.asarray(Z, dtype=float)
    w = np.asarray(w, dtype=float)
    cw = w if cov_w is None else np.asarray(cov_w, dtype=float)
    if len(Z) < 2:
        return np.array([], dtype=np.float32)
    ok = ~np.isnan(Z)
    Zf = np.nan_to_num(Z)
    pats, inv = np.unique(ok, axis=0, return_inverse=True)
    inv = np.asarray(inv).reshape(-1)
    members = [np.flatnonzero(inv == p) for p in range(len(pats))]
    own = pats.astype(float) @ cw
    parts = []
    for a in range(len(pats)):
        for b in range(a, len(pats)):
            S = pats[a] & pats[b]
            if not S.any():
                continue
            ws, cs = float(w[S].sum()), float(cw[S].sum())
            if ws <= 0 or cs < MIN_COVERAGE * max(own[a], own[b]) - 1e-9:
                continue
            idx, A, ws = _whitener(R, w, S)
            Ya = Zf[np.ix_(members[a], idx)] @ A.T
            Yb = Ya if a == b else Zf[np.ix_(members[b], idx)] @ A.T
            nb = (Yb * Yb).sum(axis=1)
            for s in range(0, len(Ya), chunk):
                y = Ya[s:s + chunk]
                d2 = (y * y).sum(axis=1)[:, None] + nb[None, :] - 2.0 * (y @ Yb.T)
                if a == b:
                    i = np.arange(s, s + len(y))[:, None]
                    d2 = d2[np.arange(len(Yb))[None, :] > i]
                else:
                    d2 = d2.ravel()
                parts.append(np.sqrt(np.maximum(d2, 0.0) / ws).astype(np.float32))
    out = np.concatenate(parts) if parts else np.array([], dtype=np.float32)
    out.sort()
    return out


def similarity_pct(d: float, ref: np.ndarray) -> int | None:
    """The % of the reference pairs (`ref`, sorted) further apart than `d`, half up to a whole
    number; identical = 100; None for no distance or no reference."""
    if d is None or not np.isfinite(d) or ref is None or len(ref) == 0:
        return None
    if d <= 1e-12:
        return 100
    greater = len(ref) - int(np.searchsorted(ref, d, side="right"))
    return int(math.floor(100.0 * greater / len(ref) + 0.5))


def biggest_differences(target, row, w, measures: list[str], labels: dict, n: int = 2) -> list[dict]:
    """The `n` measures with the largest weight x |z gap| (both present); z = his minus the
    target's, so + = he is better on it."""
    target, row = np.asarray(target, float), np.asarray(row, float)
    both = ~np.isnan(target) & ~np.isnan(row)
    gap = np.where(both, row - target, 0.0)
    score = np.where(both, np.asarray(w) * np.abs(gap), -1.0)
    order = sorted(range(len(measures)), key=lambda k: (-score[k], k))
    return [{"measure": measures[k], "label": labels.get(measures[k], measures[k]),
             "z": round(float(gap[k]), 2)} for k in order[:n] if both[k]]


def _signed(z: float) -> str:
    v = round(abs(float(z)) + 1e-9, 1)
    return f"{'−' if z < 0 and v > 0 else '+'}{v:.1f}"


def differences_text(diffs: list[dict]) -> str:
    """"Sprints +1.2 · Pass accuracy −0.9" (z units)."""
    return " · ".join(f"{d['label']} {_signed(d['z'])}" for d in diffs)


# --- the pool ----------------------------------------------------------------------------------
def _label(m: str) -> str:
    try:
        from lofc.dashboard.glossary_data import PHYSICAL
        from lofc.dashboard.labels import metric_label
        return PHYSICAL[m][0] if m in PHYSICAL else metric_label(m)
    except Exception:                                           # noqa: BLE001
        return m


META = ["player_id", "competition_id", "season_id", "position_group", "peer_pool", "player_name",
        "team_name", "league", "age", "minutes", "objective_composite", "contract_until"]


@dataclass
class Pool:
    position: str
    measures: list[str]
    base_weights: dict[str, float]
    w: np.ndarray                     # Overall weights (distance and the 70% coverage rule)
    Z: np.ndarray                     # z-scores (players x measures)
    X: np.ndarray                     # the stored values (player_metrics_neutral), for the page
    R: np.ndarray                     # the measures' correlation matrix (Ledoit-Wolf)
    meta: pd.DataFrame
    ref: np.ndarray                   # every eligible pair's distance, sorted (the % scale)
    labels: dict = field(default_factory=dict)
    linked: dict = field(default_factory=dict)
    whiten: dict = field(default_factory=dict, repr=False)   # shared set -> its inverse, once


def build_pool(rows: pd.DataFrame, position: str, label=None) -> Pool:
    """The season's z-matrix for one position. `rows` = the season's RATED rows (every position:
    a thin midfield group needs the league's other midfielders), with META columns + measures."""
    label = label or _label
    base = measure_weights(position)
    measures = list(base)
    rows = rows.reset_index(drop=True)
    for m in measures:
        if m not in rows.columns:
            rows[m] = np.nan
    keys = ["competition_id", "season_id", "position_group"]
    sub = rows[rows["position_group"] == position]
    z = standardise(sub, measures, keys)
    if position in MIDFIELD_POSITIONS and "peer_pool" in sub.columns:
        fallback = sub["peer_pool"].astype(str) == "midfield"
        if fallback.any():
            mids = rows[rows["position_group"].isin(MIDFIELD_POSITIONS)]
            zm = standardise(mids, measures, ["competition_id", "season_id"])
            z.loc[fallback[fallback].index] = zm.loc[fallback[fallback].index, measures]
    Z = z[measures].to_numpy(dtype=float)
    X = sub[measures].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    w = np.array([base[m] for m in measures], dtype=float)
    R = correlation_matrix(Z)
    meta = sub.reindex(columns=META).reset_index(drop=True)
    return Pool(position=position, measures=measures, base_weights=base, w=w, Z=Z, X=X, R=R,
                meta=meta, ref=pair_distances(Z, w, R),
                labels={m: label(m) for m in measures}, linked=linked_measures(R, measures))


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _months_left(until: pd.Series, today: datetime.date) -> np.ndarray:
    """Whole calendar months to each date (seasons.calendar_months_left); NaN when unknown."""
    t = pd.to_datetime(until, errors="coerce")
    return ((t.dt.year - today.year) * 12 + (t.dt.month - today.month)).to_numpy(dtype=float)


def _target(pool: Pool, player_id: int, competition_id: int) -> int | None:
    meta = pool.meta
    hit = np.flatnonzero((meta["player_id"].to_numpy() == int(player_id))
                         & (meta["competition_id"].to_numpy() == int(competition_id)))
    return int(hit[0]) if len(hit) else None


def league_options(pool: Pool) -> list[list]:
    """[[competition_id, league name], ...] of the leagues in the pool, by name."""
    m = pool.meta[["competition_id", "league"]].drop_duplicates("competition_id")
    m = m.assign(name=m["league"].fillna(m["competition_id"].astype(str)).astype(str))
    return [[int(c), n] for c, n in sorted(zip(m["competition_id"], m["name"]), key=lambda x: x[1])]


def _distances_from(pool: Pool, t: int) -> np.ndarray:
    d, _cov = distances(pool.Z[t], pool.Z, pool.w, R=pool.R, cache=pool.whiten)
    return d


def find_similar(pool: Pool, player_id: int, competition_id: int, scope: str = "league",
                 max_age: float | None = None, league: int | None = None,
                 min_minutes: float | None = None, contract: int | None = None,
                 n: int = TOP_N, today: datetime.date | None = None) -> dict:
    """The closest `n` players to one in the pool, ordered by similarity only. The filters
    (league -- only with All leagues --, max age, min minutes, contract months) narrow the
    candidates; they never change a similarity."""
    scope = scope if scope in SCOPES else "league"
    league = int(league) if (league is not None and scope == "all") else None
    base = {"available": False, "scope": scope, "max_age": max_age, "league": league,
            "min_minutes": min_minutes, "contract": contract,
            "note": ALL_LEAGUES_NOTE if scope == "all" else None, "pool_note": None,
            "physical_note": None, "rows": [], "empty": NOT_RATED,
            "league_options": league_options(pool) if len(pool.meta) else []}
    meta = pool.meta
    t = _target(pool, player_id, competition_id)
    if t is None:
        return base
    target = pool.Z[t]
    d = _distances_from(pool, t)
    keep = (meta["player_id"].to_numpy() != int(player_id)) & np.isfinite(d)
    comp = meta["competition_id"].to_numpy()
    if scope == "league":
        keep &= comp == int(competition_id)
    elif league is not None:
        keep &= comp == league
    if max_age is not None:
        age = pd.to_numeric(meta["age"], errors="coerce").to_numpy(dtype=float)
        keep &= np.nan_to_num(age, nan=np.inf) <= float(max_age)
    if min_minutes is not None:
        mins = pd.to_numeric(meta["minutes"], errors="coerce").to_numpy(dtype=float)
        keep &= np.nan_to_num(mins, nan=-np.inf) >= float(min_minutes)
    if contract is not None:
        left = _months_left(meta["contract_until"], today or datetime.date.today())
        keep &= np.nan_to_num(left, nan=np.inf) < float(contract)
    idx = np.flatnonzero(keep)
    names = meta["player_name"].astype(str).to_numpy()
    idx = sorted(idx, key=lambda i: (d[i], names[i]))[:n]
    rows = []
    for i in idx:
        r = meta.iloc[i]
        diffs = biggest_differences(target, pool.Z[i], pool.w, pool.measures, pool.labels)
        pid, cid, sid = int(r["player_id"]), int(r["competition_id"]), int(r["season_id"])
        rows.append({"player_id": pid, "competition_id": cid, "season_id": sid,
                     "key": f"{pid}-{cid}", "href": f"/player/{pid}/{cid}/{sid}",
                     "name": str(r["player_name"]), "club": None if pd.isna(r["team_name"]) else str(r["team_name"]),
                     "league": None if pd.isna(r["league"]) else str(r["league"]),
                     "age": _num(r["age"]), "minutes": _num(r["minutes"]),
                     "overall": _num(r["objective_composite"]),
                     "similarity": similarity_pct(d[i], pool.ref),
                     "differences": diffs, "differences_text": differences_text(diffs)})
    phys = [k for k, m in enumerate(pool.measures) if m in cf.PHYSICAL_METRICS.get(pool.position, [])]
    out = dict(base, available=True, rows=rows, empty=None if rows else NO_MATCH)
    if str(meta.iloc[t].get("peer_pool")) == "midfield":
        out["pool_note"] = MIDFIELD_NOTE
    if phys and np.isnan(target[phys]).all():
        out["physical_note"] = NO_PHYSICAL_NOTE
    return out


# --- the page: one match broken down -----------------------------------------------------------
def _fmt(measure: str, v) -> str:
    from lofc.dashboard.compare_tables import format_value
    return format_value(measure, v)


def _z(v) -> float | None:
    return None if v is None or not np.isfinite(v) else round(float(v), 2)


def breakdown(pool: Pool, t: int, i: int) -> dict:
    """One row per measure in the score: weight (% of Overall), both stored values, both z,
    the gap (match - him, z), whether it is used (both have it) and what it moves with. Used
    rows by weight x |gap|, largest first; the rest after."""
    d = distances(pool.Z[t], pool.Z[i:i + 1], pool.w, R=pool.R, cache=pool.whiten)[0][0]
    rows = []
    for k, m in enumerate(pool.measures):
        hz, mz = _z(pool.Z[t, k]), _z(pool.Z[i, k])
        used = hz is not None and mz is not None
        rows.append({"measure": m, "label": pool.labels.get(m, m),
                     "weight_pct": round(100.0 * float(pool.w[k]), 1),
                     "him": _fmt(m, pool.X[t, k]), "match": _fmt(m, pool.X[i, k]),
                     "him_z": hz, "match_z": mz,
                     "diff": round(mz - hz, 2) if used else None, "used": used,
                     "linked": [pool.labels.get(x, x) for x in pool.linked.get(m, [])]})
    order = sorted(range(len(rows)), key=lambda k: (
        not rows[k]["used"],
        -(pool.w[k] * abs(rows[k]["diff"])) if rows[k]["used"] else 0.0, k))
    return {"similarity": similarity_pct(d, pool.ref), "rows": [rows[k] for k in order],
            "note": BREAKDOWN_NOTE}


def parse_key(v) -> tuple[int, int] | None:
    """"39154-5" -> (39154, 5); anything else -> None."""
    try:
        p, c = str(v).split("-")
        return (int(p), int(c)) if p.isdigit() and c.isdigit() else None
    except (TypeError, ValueError):
        return None


def compare_href(season_id: int, position: str, a: str, b: str) -> str:
    return "/compare?" + urllib.parse.urlencode(
        [("season", int(season_id)), ("position", position), ("a", a), ("b", b)])


def page_data(pool: Pool, player_id: int, competition_id: int, season_id: int,
              scope: str = "league", max_age: float | None = None, league: int | None = None,
              min_minutes: float | None = None, contract: int | None = None,
              match: str | None = None, today: datetime.date | None = None) -> dict:
    """The page's list (as the card's) + the selected match (`match` = "pid-cid", else the
    first row) broken down, and the Compare link."""
    out = find_similar(pool, player_id, competition_id, scope, max_age, league, min_minutes,
                       contract, today=today)
    out.update(player=None, selected=None, breakdown=None, compare_href=None)
    t = _target(pool, player_id, competition_id)
    if t is None:
        return out
    r = pool.meta.iloc[t]
    out["player"] = {"name": str(r["player_name"]),
                     "club": None if pd.isna(r["team_name"]) else str(r["team_name"]),
                     "league": None if pd.isna(r["league"]) else str(r["league"]),
                     "position": pool.position, "key": f"{int(player_id)}-{int(competition_id)}",
                     "href": f"/player/{int(player_id)}/{int(competition_id)}/{int(season_id)}"}
    i = None
    got = parse_key(match)
    if got and got[0] != int(player_id):
        j = _target(pool, *got)
        if j is not None and np.isfinite(distances(pool.Z[t], pool.Z[j:j + 1], pool.w,
                                                   R=pool.R, cache=pool.whiten)[0][0]):
            i = j
    if i is None and out["rows"]:
        i = _target(pool, out["rows"][0]["player_id"], out["rows"][0]["competition_id"])
    if i is None:
        return out
    m = pool.meta.iloc[i]
    key = f"{int(m['player_id'])}-{int(m['competition_id'])}"
    out["selected"] = key
    out["match"] = {"name": str(m["player_name"]), "key": key,
                    "href": f"/player/{int(m['player_id'])}/{int(m['competition_id'])}/{int(season_id)}"}
    out["breakdown"] = breakdown(pool, t, i)
    out["compare_href"] = compare_href(season_id, pool.position, out["player"]["key"], key)
    return out


# --- the database half (cached per data version) -----------------------------------------------
@webcache.versioned(maxsize=4)
def season_rows(season_id: int) -> pd.DataFrame:
    """The season's rated rows (archetype "All Metrics", an Overall, a pool of 10+), with every
    position's measures from player_metrics_neutral, age, contract and league name."""
    from sqlalchemy import text

    from lofc.core import card as card_core
    from lofc.dashboard import loaders as L
    from lofc.model.scorecard import MIN_PEERS_FOR_RANKING, peer_pool_sizes
    engine = L.get_engine()
    cols = pd.read_sql("SELECT * FROM player_metrics_neutral LIMIT 0", engine).columns
    measures = sorted({m for p in cf.DIMENSION_WEIGHTS for m in measure_weights(p)} & set(cols))
    sel = ", ".join(f"n.{m}" for m in measures)
    sc = pd.read_sql(text(
        "SELECT s.player_id, s.competition_id, s.season_id, s.position_group, s.objective_composite, "
        "s.peer_pool, s.peer_pool_size, n.player_name, n.team_name, n.minutes"
        + (", " + sel if sel else "") +
        " FROM player_scorecards s JOIN player_metrics_neutral n ON n.player_id = s.player_id "
        "AND n.competition_id = s.competition_id AND n.season_id = s.season_id "
        "WHERE s.archetype = 'All Metrics' AND s.season_id = :s AND s.objective_composite IS NOT NULL"),
        engine, params={"s": int(season_id)})
    if sc.empty:
        return sc
    sizes = peer_pool_sizes(sc)
    keys = list(zip(sc["competition_id"], sc["season_id"], sc["position_group"]))
    sc = sc[[sizes.get(k, 0) >= MIN_PEERS_FOR_RANKING for k in keys]].copy()
    cand = card_core._season_frame("load_candidates", 1.0, int(season_id))
    k3 = ["player_id", "competition_id", "season_id"]
    extra = [c for c in ("age", "contract_until") if c in cand.columns] if len(cand) else []
    if extra:
        sc = sc.merge(cand[k3 + extra].drop_duplicates(k3), on=k3, how="left")
    for c in ("age", "contract_until"):
        if c not in sc.columns:
            sc[c] = np.nan
    sc["league"] = sc["competition_id"].map(L.competition_name_by_id())
    return sc.reset_index(drop=True)


@webcache.versioned(maxsize=32)
def pool_for(season_id: int, position: str) -> Pool:
    return build_pool(season_rows(int(season_id)), position)


def _head(position: str | None) -> dict:
    return {"heading": "Similar players",
            "scope_options": [["league", "Same league"], ["all", "All leagues"]],
            "age_options": list(AGE_OPTIONS), "min_minutes_options": list(MIN_MINUTES_OPTIONS),
            "contract_options": [list(o) for o in CONTRACT_OPTIONS],
            "similarity_help": similarity_help(position) if position else None,
            "diff_help": DIFF_HELP}


def _not_rated(scope, max_age, league, min_minutes, contract) -> dict:
    return {**_head(None), "available": False, "scope": scope, "max_age": max_age,
            "league": None, "min_minutes": min_minutes, "contract": contract, "sub": None,
            "note": None, "pool_note": None, "physical_note": None, "rows": [],
            "league_options": [], "empty": NOT_RATED}


def _sub(position: str, out: dict, own_league, season_id: int) -> str:
    from lofc.dashboard.seasons import season_name_for
    if out["scope"] == "league":
        where = f"in {own_league}" if isinstance(own_league, str) else "in his league"
    elif out.get("league") is not None:
        name = dict((c, n) for c, n in out.get("league_options", [])).get(out["league"])
        where = f"in {name}" if name else "in every league"
    else:
        where = "in every league"
    return f"Closest {position}s {where}, {season_name_for(int(season_id))}, on the measures in his rating."


def _me(player_id: int, competition_id: int, season_id: int):
    rows = season_rows(int(season_id))
    if not len(rows):
        return None
    me = rows[(rows["player_id"] == int(player_id)) & (rows["competition_id"] == int(competition_id))]
    return None if me.empty else me.iloc[0]


def section(player_id: int, competition_id: int, season_id: int, scope: str = "league",
            max_age: float | None = None, league: int | None = None,
            min_minutes: float | None = None, contract: int | None = None) -> dict:
    """The card section's JSON: texts + the list."""
    scope = scope if scope in SCOPES else "league"
    me = _me(player_id, competition_id, season_id)
    if me is None:
        return _not_rated(scope, max_age, league, min_minutes, contract)
    position = str(me["position_group"])
    out = find_similar(pool_for(int(season_id), position), player_id, competition_id, scope,
                       max_age, league, min_minutes, contract)
    out["sub"] = _sub(position, out, me["league"], season_id)
    return {**_head(position), **out}


def page(player_id: int, competition_id: int, season_id: int, scope: str = "league",
         max_age: float | None = None, league: int | None = None,
         min_minutes: float | None = None, contract: int | None = None,
         match: str | None = None) -> dict:
    """The Similar players page's JSON: the card section's list + the selected match's
    breakdown + the Compare link."""
    from lofc.dashboard.seasons import season_name_for
    scope = scope if scope in SCOPES else "league"
    me = _me(player_id, competition_id, season_id)
    if me is None:
        return {**_not_rated(scope, max_age, league, min_minutes, contract), "player": None,
                "selected": None, "breakdown": None, "compare_href": None,
                "season": season_name_for(int(season_id))}
    position = str(me["position_group"])
    out = page_data(pool_for(int(season_id), position), player_id, competition_id, season_id,
                    scope, max_age, league, min_minutes, contract, match)
    out["sub"] = _sub(position, out, me["league"], season_id)
    out["season"] = season_name_for(int(season_id))
    return {**_head(position), **out}


def card_stub(reason: str) -> dict:
    """What the card's own JSON says about the section (the list loads on its own)."""
    return {"available": reason == "ok", "heading": "Similar players"}
