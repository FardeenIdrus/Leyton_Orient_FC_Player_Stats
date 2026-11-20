"""Minutes per CLUB, from the Impect averages files already landed (`model/squad_minutes.py`).

`player_metrics_neutral` holds one row per player per league-season: his minutes in the league
and the club he played MOST for. A January mover therefore shows at one club only, with the
minutes of both. Impect's averages file holds one row per player x squad x position, with the
squadId, so the minutes at each club are already on disk -- no API call. Players are linked to
ours through `position_shares._linked_ids` (the linkage build_neutral uses), never minted here.
Display only: nothing in scoring reads the table."""
import pandas as pd
import pytest

from lofc import pipeline
from lofc.model import squad_minutes as sm


def _avg(*rows):
    """(playerId, squadId, squadName, position, minutes) -> an averages-file frame."""
    return pd.DataFrame([{"playerId": p, "squadId": s, "squadName": n, "position": pos,
                          "playDuration": m * 60.0} for p, s, n, pos, m in rows])


def test_a_mover_has_one_row_per_club_with_his_minutes_at_each():
    frame = _avg((7, 966, "Leyton Orient", "CENTER_FORWARD", 600),
                 (7, 958, "Oxford United", "CENTER_FORWARD", 300),
                 (7, 958, "Oxford United", "RIGHT_WINGER", 90))
    out = sm.per_squad(frame).set_index("squadId")
    assert out.loc[966, "minutes"] == pytest.approx(600)
    assert out.loc[958, "minutes"] == pytest.approx(390)
    assert out.loc[958, "squadName"] == "Oxford United"
    # the position he played most AT THAT CLUB
    assert out.loc[958, "position_group"] == "Centre Forward"


def test_minutes_at_each_club_add_up_to_his_league_minutes():
    frame = _avg((1, 10, "A", "GOALKEEPER", 900), (2, 10, "A", "CENTRAL_DEFENDER", 450),
                 (2, 11, "B", "LEFT_WINGBACK_DEFENDER", 200), (2, 11, "B", "CENTRAL_DEFENDER", 100))
    out = sm.per_squad(frame)
    assert out.groupby("playerId")["minutes"].sum().to_dict() == pytest.approx({1: 900, 2: 750})
    b = out[(out.playerId == 2) & (out.squadId == 11)].iloc[0]
    assert b["position_group"] == "Full Back"


def test_an_unmapped_position_leaves_the_group_blank_never_guessed():
    out = sm.per_squad(_avg((1, 10, "A", "SOMETHING_NEW", 90)))
    assert out["minutes"].iloc[0] == pytest.approx(90) and pd.isna(out["position_group"].iloc[0])


def test_link_keeps_our_ids_only_and_never_mints():
    per = sm.per_squad(_avg((7, 966, "Leyton Orient", "CENTER_FORWARD", 600),
                            (8, 966, "Leyton Orient", "GOALKEEPER", 90)))
    out = sm.link(per, pd.Series({7: 72298}), competition_id=4, season_id=319)
    assert out.to_dict("records") == [{
        "player_id": 72298, "impect_squad_id": 966, "team_name": "Leyton Orient",
        "competition_id": 4, "season_id": 319, "minutes": pytest.approx(600),
        "position_group": "Centre Forward"}]


def test_two_impect_records_of_one_player_at_one_club_are_summed():
    per = sm.per_squad(_avg((7, 966, "Leyton Orient", "CENTER_FORWARD", 600),
                            (9, 966, "Leyton Orient", "GOALKEEPER", 30)))
    out = sm.link(per, pd.Series({7: 1, 9: 1}), competition_id=4, season_id=319)
    assert len(out) == 1 and out["minutes"].iloc[0] == pytest.approx(630)
    assert out["position_group"].iloc[0] == "Centre Forward"


def test_empty_inputs_give_the_columns():
    assert list(sm.link(sm.per_squad(_avg()), pd.Series(dtype="int64"), 4, 319).columns) == sm.COLUMNS


def test_the_pipeline_fills_it_after_current_club():
    names = [name for name, _ in pipeline.build_steps()]
    cur = next(i for i, n in enumerate(names) if n.startswith("Current club"))
    mins = next(i for i, n in enumerate(names) if n.startswith("Squad minutes"))
    assert mins == cur + 1
    cmd = dict(pipeline.build_steps())[names[mins]]
    assert cmd[-2:] == ["-m", "lofc.model.squad_minutes"]


def test_the_table_is_in_the_schema_and_tracked_by_the_web_caches():
    from lofc.dashboard import loaders
    from lofc.store.models import ImpectSquadMinutes
    cols = set(ImpectSquadMinutes.__table__.columns.keys())
    assert set(sm.COLUMNS) | {"updated_at"} <= cols
    assert "impect_squad_minutes" in loaders._WEB_TABLES


def test_the_season_flag_picks_the_targets():
    class T:
        def __init__(self, s): self.season_id = s
    ts = [T(318), T(319)]
    assert [t.season_id for t in sm.pick_targets(ts, None)] == [318, 319]
    assert [t.season_id for t in sm.pick_targets(ts, 319)] == [319]
