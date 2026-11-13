"""The squad workbook (owner R5) shows the numbers the player card shows, on the REAL database
(skipped without one). Read-only."""
import io

import openpyxl
import pytest
from sqlalchemy import create_engine

from lofc.config import settings


@pytest.fixture(scope="module")
def engine():
    try:
        e = create_engine(settings.database_url)
        e.connect().close()
    except Exception:
        pytest.skip("no database")
    return e


@pytest.fixture(scope="module")
def sheet(engine):
    from lofc.web.api import physical
    data, _ = physical.squad_workbook("319")
    ws = openpyxl.load_workbook(io.BytesIO(data)).active
    head = [c.value for c in ws[1]]
    return [dict(zip(head, (c.value for c in r))) for r in ws.iter_rows(min_row=2)]


def test_one_row_per_current_orient_player(sheet):
    from lofc.core import squad
    ours = squad.squad()
    assert sorted(r["Player"] for r in sheet) == sorted(str(n) for n in ours["player_name"])


def test_rated_players_equal_their_card(engine, sheet):
    from lofc.core import card, squad
    rows = squad.rated_rows(319)
    ids = dict(zip(squad.squad()["player_name"], squad.squad()["player_id"]))
    rated = [r for r in sheet if r["Overall"] is not None]
    assert len(rated) >= 2
    checked = 0
    for r in rated[:4]:
        pid = int(ids[r["Player"]])
        cid = int(rows.loc[pid, "competition_id"])
        d = card.build_card(engine, pid, cid, 319)
        rating = d["rating"]
        assert r["Overall"] == round(rating["overall"]["value"], 2)
        assert r["Performance"] == round(rating["performance"]["value"], 2)
        if rating["physical"]["value"] is not None:
            assert r["Physical"] == round(rating["physical"]["value"], 2)
        if cid == 4:
            assert rating["overall"]["rank_text"].split(" of ")[1].split()[0] == \
                r["League One rank (position)"].split(" of ")[1]
            assert rating["overall"]["rank_text"].startswith(
                r["League One rank (position)"].split(" of ")[0])
        tiles = (d["availability"]["tiles"] or [])
        shown = tiles[0]["value"] if tiles else "—"
        assert (f"{r['Availability']:.0%}" if r["Availability"] is not None else "—") == shown
        mins = next(x["value"] for x in d["header"]["register"] if x["label"] == "Minutes")
        assert f"{r['Minutes']:,}" == mins
        checked += 1
    assert checked >= 2
