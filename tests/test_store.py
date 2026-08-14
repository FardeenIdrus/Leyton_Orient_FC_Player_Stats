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


def _full_row(table, partial: dict) -> dict:
    """Fill every other NOT NULL column with 0 so the fixture survives the schema."""
    row = dict(partial)
    for column in table.columns:
        if column.name not in row and not column.nullable and column.name != "id":
            row[column.name] = 0
    return row


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
    for untouched in ("foot", "contract_until", "height_cm", "tm_player_id", "nationality"):
        assert f"{untouched} = excluded.{untouched}" not in sql


def test_players_upsert_never_nulls_a_stored_birth_date():
    """birth_date IS supplied by the loader -- as None for players whose parquet row
    has no date of birth -- so dropping unsupplied columns is not enough to protect it.

    A nulled birth date is self-reinforcing: identity.match_identity skips any player
    without one, so that player can never regain a tm_player_id, foot, height or
    contract date. It is the incident's mechanism, one column over.
    """
    from sqlalchemy.dialects import postgresql

    from lofc.store.load import PLAYER_PRESERVE_COLUMNS, _upsert_stmt
    from lofc.store.models import Player

    rows = [{"player_id": 1, "player_name": "X", "birth_date": None}]
    sql = str(_upsert_stmt(Player.__table__, rows, ["player_id"],
                           preserve_when_null=PLAYER_PRESERVE_COLUMNS)
              .compile(dialect=postgresql.dialect()))
    assert "birth_date = coalesce(excluded.birth_date, players.birth_date)" in sql
    # player_name is NOT NULL, so it is not preserved and still overwrites.
    assert "player_name = excluded.player_name" in sql


def test_the_players_loader_asks_for_that_protection(monkeypatch):
    """The guard is worthless if load_players_and_metrics does not pass it."""
    import pandas as pd
    from sqlalchemy import create_engine

    from lofc.store import load as store_load
    from lofc.store.models import Base, PlayerSeasonMetric

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    # The loader slices df by the full metric column list, so the frame needs all of them.
    row = {c.name: 0 for c in PlayerSeasonMetric.__table__.columns if c.name != "id"}
    row.update({"player_id": 1, "player_name": "X", "minutes": 90.0, "birth_date": None})
    frame = pd.DataFrame([row])

    calls = []

    def fake_upsert(engine, table, rows, conflict_cols, preserve_when_null=()):
        calls.append((table.name, list(preserve_when_null)))
        return len(rows)

    monkeypatch.setattr(pd, "read_parquet", lambda *a, **k: frame)
    monkeypatch.setattr(store_load, "_upsert", fake_upsert)
    store_load.load_players_and_metrics(engine)

    players_call = next(c for c in calls if c[0] == "players")
    assert "birth_date" in players_call[1]


def test_preserving_is_opt_in_so_other_callers_are_unchanged():
    from sqlalchemy.dialects import postgresql

    from lofc.store.load import _upsert_stmt
    from lofc.store.models import Player

    rows = [{"player_id": 1, "player_name": "X", "birth_date": None}]
    sql = str(_upsert_stmt(Player.__table__, rows, ["player_id"])
              .compile(dialect=postgresql.dialect()))
    assert "birth_date = excluded.birth_date" in sql
    assert "coalesce" not in sql


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


def test_scout_assessment_table_shape():
    from lofc.store.models import ScoutAssessment

    columns = {c.name for c in ScoutAssessment.__table__.columns}
    assert {"player_id", "competition_id", "season_id", "dimension", "author_id",
            "band", "status", "approved_by", "approved_at", "screening_failed"} <= columns
    # A new assessment is a draft until someone submits it.
    assert ScoutAssessment.__table__.c.status.server_default.arg == "draft"


def test_users_table_stores_a_hash_not_a_password():
    from lofc.store.models import User

    columns = {c.name for c in User.__table__.columns}
    assert "password_hash" in columns
    assert "password" not in columns, "never store a plaintext password"
    assert User.__table__.c.username.unique


def test_criterion_scores_carry_either_a_score_or_a_pass_flag():
    from lofc.store.models import ScoutCriterionScore

    columns = {c.name for c in ScoutCriterionScore.__table__.columns}
    assert {"assessment_id", "criterion_key", "score", "passed"} <= columns
    # Psychological uses `score`, medical screening uses `passed`; both nullable.
    assert ScoutCriterionScore.__table__.c.score.nullable
    assert ScoutCriterionScore.__table__.c.passed.nullable


def test_player_injuries_gained_entered_by():
    from lofc.store.models import PlayerInjury

    assert "entered_by" in {c.name for c in PlayerInjury.__table__.columns}
    assert PlayerInjury.__table__.c.entered_by.nullable


def test_scout_assessments_has_no_unique_constraint_on_player_competition_season_dimension():
    # Guard rail, not incidental: unlike every other player/competition/season-keyed table
    # in this file, scout_assessments is DELIBERATELY not unique on this combination, because
    # several people may assess the same player-season on the same dimension and all of their
    # rows must be kept so disagreement between assessors stays visible. A well-meaning cleanup
    # that "fixes" this by adding the constraint back would break nothing in the current suite
    # while silently destroying the multi-assessor workflow -- hence this test.
    from sqlalchemy import UniqueConstraint

    from lofc.store.models import ScoutAssessment

    key = {"player_id", "competition_id", "season_id", "dimension"}
    unique_constraints = [
        c for c in ScoutAssessment.__table__.constraints
        if isinstance(c, UniqueConstraint)
    ]
    for constraint in unique_constraints:
        covered = {col.name for col in constraint.columns}
        assert not key <= covered, (
            "scout_assessments must stay non-unique on player/competition/season/dimension "
            "so multiple assessors' rows are all retained"
        )
