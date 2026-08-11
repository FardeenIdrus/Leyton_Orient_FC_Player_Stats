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


def test_player_injuries_table_shape():
    from lofc.store.models import PlayerInjury

    columns = {c.name for c in PlayerInjury.__table__.columns}
    assert {"player_id", "tm_player_id", "season_label", "injury_category",
            "days_out", "games_missed", "source"} <= columns
    # Provenance defaults to the scraper; manual rows override it (plan 2).
    assert PlayerInjury.__table__.c.source.server_default.arg == "transfermarkt"


def test_upsert_only_updates_the_columns_it_was_given():
    """A partial upsert must not null the columns it does not carry.

    `excluded.<column>` for a column absent from the INSERT is that column's DEFAULT,
    i.e. NULL. `load_players_and_metrics` supplies only player_id/player_name/birth_date,
    so updating every column wiped the Transfermarkt bio (foot, contract_until,
    height_cm, tm_player_id) off every player on each run -- the same class of silent
    loss as the 11 Aug 2026 scrape incident.
    """
    from sqlalchemy.dialects import postgresql

    from lofc.store.load import _upsert_stmt
    from lofc.store.models import Player

    rows = [{"player_id": 1, "player_name": "X", "birth_date": "1998-05-14"}]
    sql = str(_upsert_stmt(Player.__table__, rows, ["player_id"])
              .compile(dialect=postgresql.dialect()))
    assert "player_name = excluded.player_name" in sql
    assert "birth_date = excluded.birth_date" in sql
    for untouched in ("foot", "contract_until", "height_cm", "tm_player_id", "nationality"):
        assert f"{untouched} = excluded.{untouched}" not in sql


def test_upsert_still_updates_every_column_of_a_full_row():
    from sqlalchemy.dialects import postgresql

    from lofc.store.load import _upsert_stmt
    from lofc.store.models import Player

    rows = [{c.name: None for c in Player.__table__.columns}]
    sql = str(_upsert_stmt(Player.__table__, rows, ["player_id"])
              .compile(dialect=postgresql.dialect()))
    for column in ("foot", "contract_until", "height_cm", "tm_player_id", "nationality"):
        assert f"{column} = excluded.{column}" in sql


def test_upsert_of_key_columns_only_does_nothing_on_conflict():
    # No non-key column to set: ON CONFLICT DO UPDATE with an empty SET is invalid SQL.
    from sqlalchemy.dialects import postgresql

    from lofc.store.load import _upsert_stmt
    from lofc.store.models import Player

    sql = str(_upsert_stmt(Player.__table__, [{"player_id": 1}], ["player_id"])
              .compile(dialect=postgresql.dialect()))
    assert "DO NOTHING" in sql
