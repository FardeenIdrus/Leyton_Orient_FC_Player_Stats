"""Tests for the database integrity check. Pure parts need no database; one test uses the
local Postgres and skips cleanly when it is unreachable."""

import pandas as pd
import pytest
from sqlalchemy import text

from lofc.store import integrity


def test_orphan_sql_targets_non_null_ids_missing_from_players():
    sql = integrity.orphan_sql("player_style_signals")
    assert "player_style_signals" in sql
    assert "player_id IS NOT NULL" in sql
    assert "NOT EXISTS" in sql and "players" in sql


def test_orphan_sql_rejects_tables_not_in_the_list():
    with pytest.raises(ValueError):
        integrity.orphan_sql("users; DROP TABLE players")


def test_checked_tables_are_the_four_unconstrained_ones():
    assert set(integrity.PLAYER_KEYED_TABLES) == {
        "player_metrics_neutral", "player_detail_metrics",
        "player_style_signals", "player_loans"}


def test_key_duplicate_sqls_are_named_and_grouped():
    sqls = integrity.key_duplicate_sqls()
    assert sqls and all("GROUP BY" in s and "HAVING" in s for s in sqls.values())


def test_normalise_name_folds_accents_case_and_punctuation():
    assert integrity.normalise_name("  Zoë O'Brien-Smith ") == integrity.normalise_name("zoe obriensmith")


def test_find_duplicate_identities_needs_same_name_and_birth_date():
    players = pd.DataFrame({
        "player_id": [1, 2, 3, 4, 5, 6],
        "player_name": ["José Núñez", "Jose Nunez", "Jose Nunez", "A B", "A B", "C D"],
        "birth_date": ["2000-01-01", "2000-01-01", "1999-05-05", None, None, "2001-01-01"],
    })
    pairs = integrity.find_duplicate_identities(players)
    assert [(p.player_id_a, p.player_id_b) for p in pairs.itertuples()] == [(1, 2)]


def test_exit_code_fails_on_orphans_or_duplicates_but_not_on_namesakes():
    assert integrity.exit_code({"a": 0}, {"b": 0}) == 0
    assert integrity.exit_code({"a": 1}, {"b": 0}) == 1
    assert integrity.exit_code({"a": 0}, {"b": 2}) == 1


def test_format_report_lists_every_check_with_status():
    out = integrity.format_report({"player_loans": 3}, {"players.tm_player_id": 0}, 5)
    assert "player_loans" in out and "3" in out and "FAIL" in out
    assert "players.tm_player_id" in out and "OK" in out
    assert "WARNING" in out and "5" in out


def test_functions_return_ints_on_the_local_database():
    from lofc.store.load import get_engine
    engine = get_engine()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("database unreachable")
    orphans = integrity.orphan_counts(engine)
    assert set(orphans) == set(integrity.PLAYER_KEYED_TABLES)
    assert all(isinstance(v, int) for v in orphans.values())
    dups = integrity.key_duplicates(engine)
    assert dups and all(isinstance(v, int) for v in dups.values())
    assert isinstance(integrity.possible_duplicate_identities(engine), int)
