"""Tests for the reference data builders. Pure functions, no database needed."""

from lofc.store import reference_data as ref
from lofc.store.models import PlayerSeasonMetric


def test_wage_framework_is_complete_grid():
    wage = ref.build_wage_framework()
    # 8 position groups x 5 age bands.
    assert len(wage) == 40
    assert set(wage["age_band"]) == {"U21", "21-24", "25-29", "30-32", "33+"}


def test_wage_peaks_in_prime_years():
    wage = ref.build_wage_framework()
    for position in wage["position_group"].unique():
        by_band = wage[wage["position_group"] == position].set_index("age_band")["weekly_wage_ceiling_gbp"]
        # The 25-29 prime band should be the highest ceiling for every position.
        assert by_band["25-29"] == by_band.max()
        # U21 should be the cheapest.
        assert by_band["U21"] == by_band.min()


def test_identity_weights_sum_to_one_per_position():
    identity = ref.build_identity_profiles()
    sums = identity.groupby("position_group")["weight"].sum().round(3)
    assert (sums == 1.0).all(), sums.to_dict()


def test_identity_metrics_reference_real_columns():
    # Every metric in the profiles must be a real column, or Phase 4 scoring breaks.
    valid = {c.name for c in PlayerSeasonMetric.__table__.columns}
    identity = ref.build_identity_profiles()
    unknown = set(identity["metric"]) - valid
    assert not unknown, f"identity profiles reference unknown columns: {unknown}"


def test_all_eight_positions_have_a_profile():
    identity = ref.build_identity_profiles()
    wage = ref.build_wage_framework()
    assert set(identity["position_group"]) == set(wage["position_group"])
    assert len(set(identity["position_group"])) == 8
