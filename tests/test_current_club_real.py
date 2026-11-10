"""Current club on the REAL landed Impect files and database (skipped without them).
Owner, 2026-11-09: Jack Currie's currentSquadId says Leyton Orient in every list, but he played
for Oxford United in 2026/27 -- corrected by the committed override file. Lemar Gordon and
Oliver Dovin (no minutes this season) are Orient's and stay Orient's. Nothing else changes."""
import pandas as pd
import pytest

from lofc.model import current_club as cc

CURRIE, GORDON, DOVIN = 72298, 2000109108, 42948
ORIENT, OXFORD = 966, 958


@pytest.fixture(scope="module")
def both():
    try:
        from lofc.config import settings
        from lofc.ingest import impect as landing
        from lofc.model.position_shares import _linked_ids
        from lofc.store.load import get_engine
        engine = get_engine()
        engine.connect().close()
    except Exception:
        pytest.skip("no database")
    frames = []
    for t in settings.impect_targets:
        path = landing.players_path(t.iteration_id)
        if not path.exists() or not landing.averages_path(t.iteration_id).exists():
            continue
        frames.append((t.season_id, pd.read_parquet(path), _linked_ids(engine, t)))
    if not frames:
        pytest.skip("no landed Impect files")
    plain = cc.resolve(frames, cc.load_names())
    if CURRIE not in set(plain["player_id"]):
        pytest.skip("League One files not landed")
    fixed, n = cc.apply_overrides(plain, cc.load_overrides())
    return plain.set_index("player_id"), fixed.set_index("player_id"), n


def test_currie_is_at_oxford_gordon_and_dovin_stay_orient(both):
    plain, fixed, _ = both
    assert plain.loc[CURRIE, "impect_squad_id"] == ORIENT          # Impect's stale club
    assert fixed.loc[CURRIE, "impect_squad_id"] == OXFORD
    assert fixed.loc[CURRIE, "club_name"] == "Oxford United"
    for pid in (GORDON, DOVIN):
        assert fixed.loc[pid, "impect_squad_id"] == ORIENT


def test_exactly_one_player_differs(both):
    plain, fixed, n = both
    assert n == 1
    diff = (plain["impect_squad_id"] != fixed["impect_squad_id"]) | (
        plain["club_name"].fillna("") != fixed["club_name"].fillna(""))
    assert list(plain.index[diff]) == [CURRIE]
