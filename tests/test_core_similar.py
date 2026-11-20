"""Find similar players (owner-approved 2026-11-16): the pure method in `lofc.core.similar`.

Per measure a z-score within league + season + position (the pool he was rated in), sign
flipped for lower-is-better measures, clipped at 3; weights = each measure's share of Overall
(read from club_framework at run time); weighted Mahalanobis distance over the measures both
players have (correlation matrix: Ledoit-Wolf on the position pool; 70% of the target's weight
needed); similarity = the % of all pairs at the position (all leagues) that are further apart."""
import math

import numpy as np
import pandas as pd
import pytest

from lofc.core import similar as S
from lofc.model import club_framework as cf

POS = "Full Back"


def _rows(n_per_league=30, leagues=(4, 3), seed=1, position=POS):
    """Rated rows for one season: random per-90 values for every measure of `position`."""
    rng = np.random.default_rng(seed)
    ms = list(S.measure_weights(position))
    out, pid = [], 1000
    for comp in leagues:
        for i in range(n_per_league):
            pid += 1
            r = {"player_id": pid, "competition_id": comp, "season_id": 319,
                 "position_group": position, "peer_pool": "position",
                 "objective_composite": 3.0, "player_name": f"P{pid}", "team_name": f"Club{i % 5}",
                 "league": f"L{comp}", "age": 20 + (i % 15), "minutes": 500 + 50 * i,
                 "contract_until": pd.Timestamp("2027-06-30") + pd.DateOffset(months=i % 24)}
            for m in ms:
                r[m] = float(rng.normal(10, 2))
            out.append(r)
    return pd.DataFrame(out)


def _structured_rows(n_per_league=80, seed=5):
    """As _rows, but every measure shares one factor (real measures are correlated, so
    Ledoit-Wolf shrinks little) and High-speed running distance tracks High-speed runs."""
    rows = _rows(n_per_league=n_per_league)
    rng = np.random.default_rng(seed)
    f = rng.normal(size=len(rows))
    for m in S.measure_weights(POS):
        rows[m] = 10 + 2 * (0.75 * f + 0.66 * rng.normal(size=len(rows)))
    rows["hsr_distance_p90"] = rows["hsr_count_p90"] * 20 + rng.normal(0, 0.5, len(rows))
    return rows


# --- z-scores --------------------------------------------------------------------------------
def test_z_is_within_league_and_lower_is_better_is_flipped():
    f = pd.DataFrame({"competition_id": [1, 1, 1, 2, 2, 2],
                      "position_group": [POS] * 6,
                      "a": [1.0, 2.0, 3.0, 10.0, 20.0, 30.0],
                      "turnovers_p90": [1.0, 2.0, 3.0, 1.0, 2.0, 3.0]})
    z = S.standardise(f, ["a", "turnovers_p90"], ["competition_id", "position_group"])
    sd = np.std([1.0, 2.0, 3.0])                     # population sd within the league
    assert z["a"].tolist() == pytest.approx([-1 / sd, 0, 1 / sd] * 2)
    assert "turnovers_p90" in cf.LOWER_IS_BETTER
    assert z["turnovers_p90"].tolist() == pytest.approx([1 / sd, 0, -1 / sd] * 2)


def test_z_is_clipped_at_three():
    vals = [0.0] * 30 + [100.0]
    f = pd.DataFrame({"competition_id": 1, "position_group": POS, "a": vals})
    z = S.standardise(f, ["a"], ["competition_id", "position_group"])
    assert z["a"].max() == pytest.approx(S.Z_CLIP) == 3.0
    assert z["a"].iloc[0] > -3.0


def test_z_missing_when_the_league_has_no_spread_or_the_value_is_missing():
    f = pd.DataFrame({"competition_id": [1, 1, 2, 2], "position_group": POS,
                      "a": [5.0, 5.0, 1.0, np.nan]})
    z = S.standardise(f, ["a"], ["competition_id", "position_group"])
    assert z["a"].isna().all()


# --- weights ---------------------------------------------------------------------------------
def test_weights_are_overall_shares_read_from_club_framework():
    from lofc.core.club_vs_league import overall_weights
    w = S.measure_weights(POS)
    assert w == overall_weights(POS)
    assert sum(w.values()) == pytest.approx(1.0)
    phys = cf.PHYSICAL_METRICS[POS]
    d = cf.DIMENSION_WEIGHTS[POS]
    share = d[cf.PHYSICAL] / (d[cf.PHYSICAL] + d[cf.PERFORMANCE])
    assert sum(w[m] for m in phys) == pytest.approx(share)


def test_weights_change_when_club_framework_changes(monkeypatch):
    before = S.measure_weights(POS)
    new = dict(cf.DIMENSION_WEIGHTS[POS])
    new[cf.PERFORMANCE], new[cf.PHYSICAL] = 0.5, 0.5
    monkeypatch.setitem(cf.DIMENSION_WEIGHTS, POS, new)
    after = S.measure_weights(POS)
    phys = cf.PHYSICAL_METRICS[POS]
    assert sum(after[m] for m in phys) == pytest.approx(0.5)
    assert after != before


def test_goalkeeper_weights_have_no_physical():
    w = S.measure_weights("Goalkeeper")
    assert not set(w) & set(cf.PHYSICAL_METRICS[POS])
    assert sum(w.values()) == pytest.approx(1.0)


# --- distance, similarity --------------------------------------------------------------------
def test_distance_uses_only_measures_both_have_and_needs_70pct_of_the_weight():
    w = np.array([0.5, 0.3, 0.2])
    target = np.array([0.0, 0.0, 0.0])
    Z = np.array([[1.0, 1.0, 1.0],          # all present
                  [2.0, np.nan, 0.0],       # 70% of the weight present -> kept
                  [np.nan, 1.0, 1.0]])      # 50% -> excluded
    d, cov = S.distances(target, Z, w)
    assert d[0] == pytest.approx(1.0)
    assert cov[1] == pytest.approx(0.7)
    assert d[1] == pytest.approx(math.sqrt(0.5 * 4 / 0.7))
    assert math.isnan(d[2]) and cov[2] == pytest.approx(0.5)


def test_coverage_is_against_the_targets_own_measures():
    """A player with no physical data (most non-English leagues) is compared on what he has."""
    w = np.array([0.6, 0.4])
    target = np.array([0.0, np.nan])
    d, cov = S.distances(target, np.array([[1.0, 2.0], [1.0, np.nan]]), w)
    assert cov.tolist() == [1.0, 1.0]
    assert d.tolist() == pytest.approx([1.0, 1.0])


def test_biggest_differences_are_the_largest_weighted_gaps_signed():
    w = np.array([0.1, 0.5, 0.4])
    target = np.array([0.0, 0.0, 0.0])
    row = np.array([2.0, -0.9, 1.0])                    # weight x |gap|: 0.2, 0.45, 0.4
    got = S.biggest_differences(target, row, w, ["a", "b", "c"], {"a": "A", "b": "B", "c": "C"})
    assert [g["label"] for g in got] == ["B", "C"]
    assert got[0]["z"] == pytest.approx(-0.9)
    assert S.differences_text(got[:1]) == "B −0.9"
    assert S.differences_text([{"label": "Sprints", "z": 1.24}]) == "Sprints +1.2"


# --- the search ------------------------------------------------------------------------------
def _pool(rows=None, position=POS):
    rows = _rows() if rows is None else rows
    return S.build_pool(rows, position)


def test_the_player_himself_is_excluded_and_same_league_is_one_league():
    rows = _rows()
    pool = _pool(rows)
    out = S.find_similar(pool, 1001, 4, scope="league")
    ids = [r["player_id"] for r in out["rows"]]
    assert 1001 not in ids
    assert len(ids) == S.TOP_N == 10
    assert {r["competition_id"] for r in out["rows"]} == {4}
    sims = [r["similarity"] for r in out["rows"]]
    assert sims == sorted(sims, reverse=True)


def test_all_leagues_includes_other_leagues_and_says_so():
    pool = _pool()
    out = S.find_similar(pool, 1001, 4, scope="all")
    assert {r["competition_id"] for r in out["rows"]} >= {3}
    assert out["note"] == S.ALL_LEAGUES_NOTE == "Measures are compared within each player's own league."
    assert S.find_similar(pool, 1001, 4, scope="league")["note"] is None


def test_his_row_in_another_league_the_same_season_is_excluded():
    rows = _rows()
    twin = rows[rows["player_id"] == 1001].copy()
    twin["competition_id"] = 3
    pool = _pool(pd.concat([rows, twin], ignore_index=True))
    out = S.find_similar(pool, 1001, 4, scope="all")
    assert 1001 not in [r["player_id"] for r in out["rows"]]


def test_a_near_copy_ranks_first_and_same_shape_half_level_ranks_low():
    """The cosine pitfall: a player with the same SHAPE but half the level is not similar."""
    rows = _rows(n_per_league=60, leagues=(4,))
    ms = list(S.measure_weights(POS))
    mean = rows[ms].mean()
    target = rows.iloc[0].copy()
    for m in ms:
        target[m] = mean[m] + 2.0 * (rows[m].std() if m not in cf.LOWER_IS_BETTER else -rows[m].std())
    target["player_id"] = 1
    copy = target.copy(); copy["player_id"] = 2
    for m in ms:
        copy[m] = target[m] * 1.01
    half = target.copy(); half["player_id"] = 3
    for m in ms:
        half[m] = mean[m] + (target[m] - mean[m]) / 2      # same direction, half the distance
    rows = pd.concat([rows, pd.DataFrame([target, copy, half])], ignore_index=True)
    pool = S.build_pool(rows, POS)
    out = S.find_similar(pool, 1, 4, scope="league", n=100)
    order = [r["player_id"] for r in out["rows"]]
    assert order[0] == 2
    sim = {r["player_id"]: r["similarity"] for r in out["rows"]}
    assert sim[2] == 100 and sim[3] <= sim[2]
    d = S.distances(pool.Z[-3], pool.Z, pool.w, R=pool.R)[0]
    assert d[-1] > 10 * d[-2]                           # half the level: far further than the copy


def test_max_age_filter():
    pool = _pool()
    out = S.find_similar(pool, 1001, 4, scope="all", max_age=23)
    assert out["rows"] and all(r["age"] <= 23 for r in out["rows"])


def test_unrated_or_unknown_player_has_no_list():
    pool = _pool()
    out = S.find_similar(pool, 999999, 4)
    assert out["available"] is False and out["rows"] == []


def test_rows_carry_link_overall_and_differences():
    out = S.find_similar(_pool(), 1001, 4, scope="league")
    r = out["rows"][0]
    assert r["href"] == f"/player/{r['player_id']}/{r['competition_id']}/319"
    assert set(r) >= {"name", "club", "league", "age", "minutes", "overall", "similarity",
                      "differences", "differences_text"}
    assert len(r["differences"]) == 2


def test_midfield_fallback_is_standardised_against_all_midfielders_and_compared_within_his_position():
    rng = np.random.default_rng(9)
    rows = []
    pid = 0
    for pos, n, pool in (("Central Mid", 4, "midfield"), ("Defensive Mid", 20, "position"),
                         ("Attacking Mid", 12, "position")):
        for i in range(n):
            pid += 1
            r = {"player_id": pid, "competition_id": 4, "season_id": 319, "position_group": pos,
                 "peer_pool": pool, "objective_composite": 3.0, "player_name": f"M{pid}",
                 "team_name": "C", "league": "L", "age": 25, "minutes": 1000}
            for m in set(S.measure_weights("Central Mid")) | set(S.measure_weights("Defensive Mid")) \
                    | set(S.measure_weights("Attacking Mid")):
                r[m] = float(rng.normal(10, 2))
            rows.append(r)
    rows = pd.DataFrame(rows)
    pool = S.build_pool(rows, "Central Mid")
    # z of a Central Mid against every midfielder of the league, not his 4-man group
    m = "ball_wins_p90"
    allmid = rows[m]
    expect = (rows.loc[0, m] - allmid.mean()) / allmid.std(ddof=0)
    j = pool.measures.index(m)
    assert pool.Z[0, j] == pytest.approx(expect)
    out = S.find_similar(pool, 1, 4)
    assert {r["player_id"] for r in out["rows"]} == {2, 3, 4}
    assert out["pool_note"] == S.MIDFIELD_NOTE




# --- correlation matrix (Ledoit-Wolf) ---------------------------------------------------------
def _corr_data(n=400, seed=11):
    rng = np.random.default_rng(seed)
    a = rng.normal(size=n)
    return np.column_stack([a, a + rng.normal(scale=0.2, size=n),        # r ~ 0.98
                            rng.normal(size=n), 0.5 * a + rng.normal(size=n)])


def test_correlation_is_ledoit_wolf_on_complete_rows_as_a_correlation_matrix():
    from sklearn.covariance import LedoitWolf
    Z = _corr_data()
    Z[:30, 2] = np.nan                                   # incomplete rows are left out of the fit
    R = S.correlation_matrix(Z)
    cov = LedoitWolf().fit(Z[~np.isnan(Z).any(axis=1)]).covariance_
    sd = np.sqrt(np.diag(cov))
    assert R == pytest.approx(cov / np.outer(sd, sd), abs=1e-9)
    assert np.diag(R) == pytest.approx(np.ones(4))
    assert R == pytest.approx(R.T)
    assert 0.9 < R[0, 1] < 0.99                          # shrunk a little toward 0


def test_too_few_complete_rows_falls_back_to_pairwise_correlation_shrunk_toward_identity():
    """Under 3 x (number of measures) complete rows: pairwise correlation (pairs of measures with
    CORR_MIN_PERIODS+ rows; else 0), shrunk toward identity by the Ledoit-Wolf intensity of the
    rows with the gaps filled by 0 (each z is centred within its league)."""
    from sklearn.covariance import ledoit_wolf_shrinkage
    Z = _corr_data(n=200)
    Z[::2, 0] = np.nan
    Z[1::2, 2] = np.nan                                  # no row has all four measures
    R = S.correlation_matrix(Z)
    C = pd.DataFrame(Z).corr(min_periods=S.CORR_MIN_PERIODS).to_numpy()
    C = np.nan_to_num(C, nan=0.0)
    np.fill_diagonal(C, 1.0)
    lam = ledoit_wolf_shrinkage(np.nan_to_num(Z, nan=0.0))
    assert 0 < lam < 1
    assert R == pytest.approx((1 - lam) * C + lam * np.eye(4), abs=1e-9)


def test_correlation_with_almost_no_rows_is_identity():
    assert S.correlation_matrix(np.array([[1.0, 2.0, 3.0]])).tolist() == np.eye(3).tolist()
    assert S.correlation_matrix(np.empty((0, 2))).tolist() == np.eye(2).tolist()


def test_correlation_matrix_is_positive_definite_even_with_a_duplicated_measure():
    Z = _corr_data(n=20)
    Z = np.column_stack([Z, Z[:, 0], Z[:, 0]])            # exact copies: singular sample corr
    R = S.correlation_matrix(Z)
    assert np.linalg.eigvalsh(R).min() > 0
    np.linalg.cholesky(R)                                # no LinAlgError
    bad = np.array([[1.0, 1.0, 0.0], [1.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    fixed = S.make_pd(bad)
    assert np.linalg.eigvalsh(fixed).min() > 0 and np.diag(fixed) == pytest.approx(np.ones(3))


def test_linked_measures_are_pairs_at_r_point_eight_or_more():
    R = np.array([[1.0, 0.85, 0.1], [0.85, 1.0, -0.82], [0.1, -0.82, 1.0]])
    assert S.linked_measures(R, ["a", "b", "c"]) == {"a": ["b"], "b": ["a", "c"], "c": ["b"]}


# --- Mahalanobis distance ---------------------------------------------------------------------
def _brute_d(t, z, w, R):
    S_ = ~np.isnan(t) & ~np.isnan(z)
    D = np.diag(np.sqrt(w[S_]))
    dz = (z - t)[S_]
    return math.sqrt(dz @ D @ np.linalg.inv(R[np.ix_(S_, S_)]) @ D @ dz / w[S_].sum())


def test_with_identity_correlation_it_is_exactly_the_weighted_euclidean_distance():
    rng = np.random.default_rng(21)
    w = np.array([0.4, 0.3, 0.2, 0.1])
    t = rng.normal(size=4)
    Z = rng.normal(size=(6, 4))
    Z[2, 3] = np.nan
    d_id, _ = S.distances(t, Z, w, R=np.eye(4))
    d_none, _ = S.distances(t, Z, w)
    for i in range(6):
        both = ~np.isnan(Z[i])
        old = math.sqrt((w[both] * (Z[i, both] - t[both]) ** 2).sum() / w[both].sum())
        assert d_id[i] == pytest.approx(old, rel=1e-12)
        assert d_none[i] == pytest.approx(old, rel=1e-12)


def test_distance_is_the_weighted_mahalanobis_over_the_shared_measures():
    rng = np.random.default_rng(22)
    w = np.array([0.35, 0.25, 0.25, 0.15])
    R = S.correlation_matrix(_corr_data())
    t = rng.normal(size=4)
    Z = rng.normal(size=(8, 4))
    Z[1, 2] = np.nan                                     # shared set = the other three
    d, _ = S.distances(t, Z, w, R=R)
    for i in range(8):
        assert d[i] == pytest.approx(_brute_d(t, Z[i], w, R), rel=1e-10)


def test_a_duplicated_measure_counts_once():
    """Measure a, and an exact copy a', each weight w; b weight wb; correlation(a, a') = rho.
    x = D.delta = (sqrt(w) da, sqrt(w) da, sqrt(wb) db) and x' R^-1 x = 2 w da^2 / (1 + rho) +
    wb db^2 -- so as rho -> 1 the pair adds w da^2: ONE copy's worth (weighted Euclidean would
    add 2 w da^2). The divisor is still the weight used, 2w + wb."""
    w_, wb, da, db = 0.3, 0.4, 1.5, -0.5
    w = np.array([w_, w_, wb])
    for rho in (0.5, 0.9, 0.999999):
        R = np.array([[1, rho, 0], [rho, 1, 0], [0, 0, 1.0]])
        d, _ = S.distances(np.zeros(3), np.array([[da, da, db]]), w, R=R)
        expect = (2 * w_ * da ** 2 / (1 + rho) + wb * db ** 2) / (2 * w_ + wb)
        assert d[0] ** 2 == pytest.approx(expect, rel=1e-6)
    d_euc, _ = S.distances(np.zeros(3), np.array([[da, da, db]]), w)
    assert d[0] ** 2 * (2 * w_ + wb) == pytest.approx(w_ * da ** 2 + wb * db ** 2, rel=1e-5)
    assert d_euc[0] ** 2 * (2 * w_ + wb) == pytest.approx(2 * w_ * da ** 2 + wb * db ** 2)


def test_a_duplicated_measure_with_r_estimated_from_the_pool_counts_once():
    """Copy measure a (weights 0.25 + 0.25) with R estimated from the pool: the numerator stays
    near that of a single a at weight 0.25 (one copy) -- the old "group counts once" rule --
    while weighted Euclidean adds both copies. Divisors: 1.0 with the copy, 0.75 without."""
    rng = np.random.default_rng(23)
    base = rng.normal(size=(300, 3))
    dup = np.column_stack([base[:, 0], base[:, 0] + rng.normal(scale=0.01, size=300), base[:, 1:]])
    w1, w2 = np.array([0.25, 0.3, 0.2]), np.array([0.25, 0.25, 0.3, 0.2])
    d1, _ = S.distances(base[0], base[1:], w1, R=S.correlation_matrix(base))
    d2, _ = S.distances(dup[0], dup[1:], w2, R=S.correlation_matrix(dup))
    de, _ = S.distances(dup[0], dup[1:], w2)
    once = d1 ** 2 * 0.75
    assert np.median(np.abs(d2 ** 2 * 1.0 / once - 1)) < 0.05
    assert np.median(np.abs(de ** 2 * 1.0 / once - 1)) > 0.2


def test_coverage_rule_is_unchanged_under_mahalanobis():
    w = np.array([0.5, 0.3, 0.2])
    R = np.array([[1, 0.5, 0.2], [0.5, 1, 0.1], [0.2, 0.1, 1.0]])
    Z = np.array([[2.0, np.nan, 0.0], [np.nan, 1.0, 1.0]])
    d, cov = S.distances(np.zeros(3), Z, w, R=R)
    assert cov.tolist() == pytest.approx([0.7, 0.5])
    assert np.isfinite(d[0]) and math.isnan(d[1])


# --- pair rank: the similarity % --------------------------------------------------------------
def test_pair_distances_are_every_pair_meeting_the_rule_sorted():
    rng = np.random.default_rng(31)
    Z = rng.normal(size=(14, 4))
    Z[3, 1] = np.nan
    Z[5:8, 3] = np.nan
    Z[9, :3] = np.nan                                    # 10% of anyone's weight: in no pair
    w = np.array([0.4, 0.3, 0.2, 0.1])
    R = S.correlation_matrix(_corr_data())
    brute = []
    for i in range(14):
        for j in range(i + 1, 14):
            ok_i, ok_j = ~np.isnan(Z[i]), ~np.isnan(Z[j])
            shared = w[ok_i & ok_j].sum()
            if shared > 0 and shared >= 0.7 * max(w[ok_i].sum(), w[ok_j].sum()) - 1e-9:
                brute.append(_brute_d(Z[i], Z[j], w, R))
    got = S.pair_distances(Z, w, R=R)
    assert len(got) == len(brute)
    assert np.asarray(got, float) == pytest.approx(np.sort(brute), rel=1e-5)


def test_similarity_is_the_share_of_pairs_further_apart():
    ref = np.array([0.2, 0.4, 0.5, 0.9, 1.2])
    assert S.similarity_pct(0.465, ref) == 60            # 0.5, 0.9, 1.2 are further apart
    assert S.similarity_pct(0.0, ref) == 100             # identical
    assert S.similarity_pct(1.2, ref) == 0               # the farthest pair
    assert S.similarity_pct(5.0, ref) == 0
    assert S.similarity_pct(0.4, ref) == 60              # ties are not "further apart"
    assert S.similarity_pct(float("nan"), ref) is None
    assert S.similarity_pct(0.3, np.array([])) is None
    eight = np.arange(1, 9) / 10                         # 8 pairs: 1 of 8 = 12.5 -> 13 (half up)
    assert S.similarity_pct(0.75, eight) == 13
    sims = [S.similarity_pct(d, np.sort(np.random.default_rng(1).gamma(4, 0.3, 500)))
            for d in np.linspace(0, 3, 40)]
    assert sims == sorted(sims, reverse=True)            # monotone in distance


def test_the_methodology_worked_example():
    """docs/methodology.md 6c: A 0.5, B 0.3, C 0.2; r(A, B) = 0.6."""
    w = np.array([0.5, 0.3, 0.2])
    t, z = np.array([1.0, 0.0, -0.5]), np.array([[0.5, 0.4, np.nan]])
    d0, cov = S.distances(t, z, w)
    assert cov[0] == pytest.approx(0.8) and d0[0] == pytest.approx(0.465, abs=5e-4)
    R = np.array([[1, 0.6, 0], [0.6, 1, 0], [0, 0, 1.0]])
    d, _ = S.distances(t, z, w, R=R)
    assert d[0] == pytest.approx(0.721, abs=5e-4)
    assert S.similarity_pct(d[0], np.array([0.3, 0.6, 0.8, 1.0, 1.4])) == 60


# --- the pool and the filters -----------------------------------------------------------------
def test_pool_keeps_correlation_reference_pairs_and_raw_values():
    rows = _structured_rows()
    pool = S.build_pool(rows, POS)
    k = len(pool.measures)
    assert pool.R.shape == (k, k) and np.linalg.eigvalsh(pool.R).min() > 0
    assert "hsr_distance_p90" in pool.linked["hsr_count_p90"]
    n = len(pool.meta)
    assert len(pool.ref) == n * (n - 1) // 2 and np.all(np.diff(pool.ref) >= 0)
    assert pool.X.shape == (n, k)
    assert pool.X[0, pool.measures.index("hsr_count_p90")] == pytest.approx(rows.iloc[0]["hsr_count_p90"])
    assert not hasattr(pool, "groups") and not hasattr(pool, "d_ref")


def test_coverage_uses_overall_weights_so_no_physical_never_matches_a_physical_player():
    """Physical is 35% of a Full Back's Overall: a candidate with no physical data covers 65% of
    a physical player's weight (< 70%) and is left out. The reverse search compares on
    performance only."""
    rows = _rows()
    phys = cf.PHYSICAL_METRICS[POS]
    rows.loc[rows["competition_id"] == 3, phys] = np.nan          # league 3 has no tracking
    pool = S.build_pool(rows, POS)
    out = S.find_similar(pool, 1001, 4, scope="all", n=100)
    assert out["rows"] and {r["competition_id"] for r in out["rows"]} == {4}
    assert out["physical_note"] is None
    no_phys = int(rows[rows["competition_id"] == 3].iloc[0]["player_id"])
    back = S.find_similar(pool, no_phys, 3, scope="all", n=100)
    assert {r["competition_id"] for r in back["rows"]} == {3, 4}
    assert back["physical_note"] == S.NO_PHYSICAL_NOTE


def _sims(out):
    return {r["player_id"]: r["similarity"] for r in out["rows"]}


def test_league_filter_needs_all_leagues_and_never_changes_the_number():
    pool = _pool()
    every = _sims(S.find_similar(pool, 1001, 4, scope="all", n=100))
    only3 = S.find_similar(pool, 1001, 4, scope="all", league=3, n=100)
    assert only3["rows"] and {r["competition_id"] for r in only3["rows"]} == {3}
    assert all(every[p] == s for p, s in _sims(only3).items())
    same = S.find_similar(pool, 1001, 4, scope="league", league=3)     # ignored with Same league
    assert {r["competition_id"] for r in same["rows"]} == {4}
    assert only3["league"] == 3 and same["league"] is None


def test_min_minutes_filter_narrows_without_changing_the_number():
    pool = _pool()
    every = _sims(S.find_similar(pool, 1001, 4, scope="all", n=100))
    got = S.find_similar(pool, 1001, 4, scope="all", min_minutes=1350, n=100)
    assert got["rows"] and all(r["minutes"] >= 1350 for r in got["rows"])
    assert len(got["rows"]) < len(every)
    assert all(every[p] == s for p, s in _sims(got).items())


def test_contract_filter_is_months_left_under_n_unknown_left_out():
    import datetime
    rows = _rows()
    rows.loc[rows["player_id"] == 1005, "contract_until"] = pd.NaT
    rows.loc[rows["player_id"] == 1006, "contract_until"] = pd.Timestamp("2026-01-31")  # expired
    pool = S.build_pool(rows, POS)
    today = datetime.date(2026, 11, 20)
    every = _sims(S.find_similar(pool, 1001, 4, scope="all", n=100, today=today))
    for months in (6, 12):
        got = S.find_similar(pool, 1001, 4, scope="all", contract=months, n=100, today=today)
        until = rows.set_index("player_id")["contract_until"]
        ids = {r["player_id"] for r in got["rows"]}
        assert ids and 1005 not in ids
        for p in ids:
            end = until[p]
            assert (end.year - 2026) * 12 + (end.month - 11) < months
        assert all(every[p] == s for p, s in _sims(got).items())
    assert 1006 in {r["player_id"] for r in S.find_similar(
        pool, 1001, 4, scope="all", contract=6, n=100, today=today)["rows"]}


def test_filters_still_give_the_top_ten_with_no_cut_off():
    out = S.find_similar(_pool(), 1001, 4, scope="all", min_minutes=900)
    assert len(out["rows"]) == S.TOP_N
    assert [r["similarity"] for r in out["rows"]] == sorted((r["similarity"] for r in out["rows"]), reverse=True)


def test_league_options_are_the_leagues_in_the_pool():
    out = S.find_similar(_pool(), 1001, 4, scope="all")
    assert out["league_options"] == [[3, "L3"], [4, "L4"]]


# --- the page: the breakdown of one match -----------------------------------------------------
def test_page_selects_the_first_row_by_default_and_breaks_it_down():
    pool = _pool()
    p = S.page_data(pool, 1001, 4, 319, scope="all")
    first = p["rows"][0]
    assert p["selected"] == f"{first['player_id']}-{first['competition_id']}"
    b = p["breakdown"]
    assert b["similarity"] == first["similarity"]
    assert [r["measure"] for r in b["rows"]] != [] and {r["measure"] for r in b["rows"]} == set(pool.measures)
    used = [r for r in b["rows"] if r["used"]]
    key = [pool.base_weights[r["measure"]] * abs(r["diff"]) for r in used]
    assert key == sorted(key, reverse=True)
    assert sum(r["weight_pct"] for r in b["rows"]) == pytest.approx(100, abs=0.05 * len(b["rows"]))
    r = used[0]
    assert r["diff"] == pytest.approx(r["match_z"] - r["him_z"], abs=0.011)
    assert p["compare_href"] == (f"/compare?season=319&position=Full+Back&a=1001-4"
                                 f"&b={first['player_id']}-{first['competition_id']}")
    assert p["player"]["href"] == "/player/1001/4/319" and p["player"]["name"] == "P1001"
    assert b["note"] == S.BREAKDOWN_NOTE


def test_page_match_picks_that_player_and_junk_falls_back_to_the_first():
    pool = _pool()
    p0 = S.page_data(pool, 1001, 4, 319, scope="league")
    second = p0["rows"][1]
    key = f"{second['player_id']}-{second['competition_id']}"
    p = S.page_data(pool, 1001, 4, 319, scope="league", match=key)
    assert p["selected"] == key and p["breakdown"]["similarity"] == second["similarity"]
    for junk in ("", "abc", "1-2-3", "999999-4", "1001-4"):
        assert S.page_data(pool, 1001, 4, 319, scope="league", match=junk)["selected"] == p0["selected"]


def test_breakdown_marks_a_measure_one_of_them_lacks_as_not_used_and_shows_raw_values():
    rows = _rows()
    phys = cf.PHYSICAL_METRICS[POS][0]
    rows.loc[rows["player_id"] == 1002, phys] = np.nan
    pool = S.build_pool(rows, POS)
    p = S.page_data(pool, 1001, 4, 319, scope="league", match="1002-4")
    assert p["selected"] == "1002-4"
    row = next(r for r in p["breakdown"]["rows"] if r["measure"] == phys)
    assert row["used"] is False and row["match"] == "—" and row["match_z"] is None
    assert p["breakdown"]["rows"][-1]["measure"] == phys          # not-used rows go last
    m = next(r for r in p["breakdown"]["rows"] if r["used"])
    from lofc.dashboard.compare_tables import format_value
    j = pool.measures.index(m["measure"])
    assert m["him"] == format_value(m["measure"], rows.iloc[0][m["measure"]])


def test_breakdown_lists_linked_partners():
    rows = _structured_rows()
    pool = S.build_pool(rows, POS)
    p = S.page_data(pool, 1001, 4, 319, scope="league")
    row = next(r for r in p["breakdown"]["rows"] if r["measure"] == "hsr_count_p90")
    assert pool.labels["hsr_distance_p90"] in row["linked"]


def test_unknown_player_page_has_no_list():
    p = S.page_data(_pool(), 999999, 4, 319)
    assert p["available"] is False and p["breakdown"] is None and p["rows"] == []


def test_similarity_help_names_the_position():
    assert S.similarity_help("Full Back") == "More alike than this % of all Full Back pairs."
