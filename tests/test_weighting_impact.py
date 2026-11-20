"""scripts/weighting_impact.py: the read-only impact report of the rating weights
change, Performance 57% -> 65%, Physical 43% -> 35% (owner 2026-11-16).

Loaded by path (scripts/ is not a package). In the app container scripts/ is not mounted, so
copy it in first:  docker cp scripts/weighting_impact.py <app>:/app/scripts/weighting_impact.py
"""
import importlib.util
import io
import sys
from pathlib import Path

import pandas as pd
import pytest

from lofc.model import club_framework as cf
from lofc.model import scorecard

_CANDIDATES = [Path(__file__).resolve().parents[1] / "scripts" / "weighting_impact.py",
               Path("/app/scripts/weighting_impact.py")]
_PATH = next((p for p in _CANDIDATES if p.exists()), None)
if _PATH is None:
    pytest.skip("scripts/weighting_impact.py not reachable (container: docker cp it to /app/scripts)",
                allow_module_level=True)
_spec = importlib.util.spec_from_file_location("weighting_impact", _PATH)
wi = importlib.util.module_from_spec(_spec)
sys.modules["weighting_impact"] = wi          # dataclasses look the module up
_spec.loader.exec_module(wi)

BANDS = [round(1 + i / 100, 2) for i in range(401)]          # every 2-dp band, 1.00 .. 5.00


def _legacy_objective(p, h):
    """The objective composite exactly as the live (pre-2026-11-16) code computed it:
    DIMENSION_WEIGHTS rounded to 4 dp (0.3636, 0.2727) and Python's round()."""
    w = {"p": round(0.40 / 1.10, 4), "h": round(0.30 / 1.10, 4)}
    if h is None:
        return round(p * w["p"] / w["p"], 2)
    return round((p * w["p"] + h * w["h"]) / (w["p"] + w["h"]), 2)


def test_old_split_reproduces_the_stored_composite_for_every_possible_band_pair():
    """The comparison is exact: for every pair of 2-dp bands a player can have, the report's
    40:30 recompute equals what the live scoring stored."""
    for p in BANDS:
        assert wi.composite(p, None, wi.OLD) == _legacy_objective(p, None)
        for h in BANDS:
            assert wi.composite(p, h, wi.OLD) == _legacy_objective(p, h), (p, h)


def test_new_split_is_exactly_what_the_rescore_will_store():
    w = cf.DIMENSION_WEIGHTS["Winger"]
    dims = [cf.PERFORMANCE, cf.PHYSICAL]
    for p in BANDS[::3]:
        assert wi.composite(p, None, wi.NEW) == scorecard._composite({cf.PERFORMANCE: p}, w, dims)[0]
        for h in BANDS:
            assert wi.composite(p, h, wi.NEW) == scorecard._composite(
                {cf.PERFORMANCE: p, cf.PHYSICAL: h}, w, dims)[0], (p, h)


def test_goalkeepers_and_no_physical_keep_performance():
    assert wi.composite(3.47, None, wi.NEW) == 3.47
    assert wi.composite(3.47, None, wi.OLD) == 3.47


def _cards():
    rows = []
    # 12 League One wingers in season 319 (a rankable pool), physical present
    for i in range(12):
        rows.append(dict(player_id=100 + i, competition_id=4, season_id=319, position_group="Winger",
                         performance_band=round(2.0 + i * 0.1, 2), physical_band=round(4.4 - i * 0.15, 2),
                         objective_composite=None, peer_pool="position", peer_pool_size=12))
    # 3 goalkeepers (thin pool -> no rank)
    for i in range(3):
        rows.append(dict(player_id=200 + i, competition_id=4, season_id=319, position_group="Goalkeeper",
                         performance_band=3.0 + i * 0.1, physical_band=None,
                         objective_composite=None, peer_pool="position", peer_pool_size=3))
    # last season, 10 centre backs
    for i in range(10):
        rows.append(dict(player_id=300 + i, competition_id=4, season_id=318, position_group="Centre Back",
                         performance_band=3.0, physical_band=2.5 + i * 0.1,
                         objective_composite=None, peer_pool="position", peer_pool_size=10))
    df = pd.DataFrame(rows)
    df["objective_composite"] = [wi.composite(p, None if pd.isna(h) else h, wi.OLD)
                                 for p, h in zip(df["performance_band"], df["physical_band"])]
    return df


def _neutral(cards):
    out = cards[["player_id", "competition_id", "season_id"]].copy()
    out["minutes"] = 900.0
    out["team_name"] = ["Leyton Orient" if pid in (100, 200) else f"Club {pid % 7}" for pid in out["player_id"]]
    out["player_name"] = [f"Player {pid}" for pid in out["player_id"]]
    return out


def test_compare_old_new_change_and_ranks():
    cards = _cards()
    f = wi.compare(cards, _neutral(cards))
    w = f[f["player_id"] == 100].iloc[0]                 # perf 2.0, phys 4.4
    assert w["old"] == pytest.approx(3.03) and w["new"] == pytest.approx(2.84)
    assert w["change"] == pytest.approx(-0.19)
    assert w["old_rank"] == 1 and w["new_rank"] == 12      # most physical winger falls
    gk = f[f["player_id"] == 200].iloc[0]
    assert gk["change"] == 0 and pd.isna(gk["old_rank"])   # thin pool: no rank
    assert f["stored_matches"].all()


def test_league_summary_one_row_per_listed_league_then_all():
    cards = _cards()
    rows = wi.league_summary(wi.compare(cards, _neutral(cards)), 319, {4: "League One"})
    assert [r["League"] for r in rows] == wi.LEAGUES + ["All 1 leagues"]
    l1 = rows[0]
    assert l1["Rated players"] == 12                     # thin GK pool and last season not counted
    assert l1["Rose"] + l1["Fell"] <= 12 and l1["Fell"] > 0
    assert l1["Biggest fall"] < 0
    assert rows[1]["Rated players"] == 0 and rows[1]["Biggest rise"] is None   # no League Two data


def test_movers_are_one_league_sorted_by_size():
    cards = _cards()
    f = wi.compare(cards, _neutral(cards))
    down = wi.movers(f, 319, 4, rising=False)
    assert down and all(r["Change"] < 0 for r in down)
    assert [r["Change"] for r in down] == sorted(r["Change"] for r in down)
    assert wi.movers(f, 319, 5, rising=True) == []


def test_main_writes_only_the_workbook_to_stdout():
    """Run as `... python - < scripts/weighting_impact.py > file.xlsx`: stdout must carry the
    .xlsx bytes and nothing else; anything a library prints goes to stderr."""
    cards = _cards()

    def noisy_cards():
        print("noise from a library")
        return cards

    src = wi.Sources(cards=noisy_cards, neutral=lambda seasons: _neutral(cards),
                     squad=lambda: pd.DataFrame({"player_id": [100, 200, 999],
                                                 "player_name": ["Player 100", "Player 200", "Unrated"],
                                                 "position_group": ["Winger", "Goalkeeper", "Winger"]}),
                     league_names=lambda: {4: "League One"},
                     season_name=lambda s: {319: "2026/27", 318: "2025/26"}[s])
    out, err = io.BytesIO(), io.StringIO()
    real = sys.stdout
    wi.main(src, out=out, err=err)
    assert sys.stdout is real
    data = out.getvalue()
    assert data[:2] == b"PK"                               # an .xlsx (zip), nothing before it
    assert "noise from a library" in err.getvalue()
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(data))
    assert wb.sheetnames == ["Summary"] + wi.LEAGUES + ["Leyton Orient"]
    text = " ".join(str(c.value) for ws in wb.worksheets for row in ws.iter_rows() for c in row
                    if c.value is not None)
    assert "40:30" not in text and "65:35" not in text and "Top-6" not in text
    assert "Performance 57% \u2192 65%, Physical 43% \u2192 35%" in text
    assert "matches the live site for 15 of 15 players" in text
    orient = wb["Leyton Orient"]
    names = {orient.cell(r, 1).value for r in range(1, orient.max_row + 1)}
    assert {"Player 100", "Player 200", "Unrated"} <= names


def test_a_change_of_zero_is_written_without_colour():
    from openpyxl import Workbook
    ws = Workbook().active
    wi._table(ws, 1, ["Player", wi.CHANGE], [{"Player": "Keeper", wi.CHANGE: 0.0}])
    assert ws.cell(2, 2).value == 0.0


def test_a_league_with_no_physical_data_says_so():
    cards = _cards()
    cards.loc[cards["player_id"].between(100, 111), ["competition_id", "physical_band"]] = [902, None]
    cards["objective_composite"] = [wi.composite(p, None if pd.isna(h) else h, wi.OLD)
                                    for p, h in zip(cards["performance_band"], cards["physical_band"])]
    rows = wi.league_summary(wi.compare(cards, _neutral(cards)), 319,
                             {4: "League One", 902: "Scottish Championship"})
    sc = next(r for r in rows if r["League"] == "Scottish Championship")
    assert sc["Rated players"] == 12 and sc["Note"] == "No physical data: no change"
    assert rows[0]["Note"] is None
