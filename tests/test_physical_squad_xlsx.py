"""Physical page: "Download squad (Excel)" (owner R5). The workbook is our current squad, one row
per player, from the same frames the page and the card read (no second calculation).

Pure core tests + the endpoint over faked sources; real-database parity with the card is in
test_physical_squad_xlsx_parity.py."""
import io

import openpyxl
import pandas as pd
import pytest

from lofc.core import physical_page as core

COLS = ["Player", "Position", "Age", "Contract until", "Minutes", "Overall", "Performance",
        "Physical", "League One rank (position)", "Availability"]


def _frames():
    squad = pd.DataFrame({
        "player_id": [1, 2, 3, 4, 5],
        "player_name": ["Keeper", "Striker Low", "Striker High", "Back", "No Row"],
        "position_group": ["Goalkeeper", "Centre Forward", "Centre Forward", "Centre Back",
                           "Winger"],
        "birth_date": pd.to_datetime(["1995-01-01", "2000-06-01", "1999-01-01", None,
                                      "2004-01-01"]),
        "contract_until": pd.to_datetime(["2027-06-30", None, "2028-06-30", "2026-06-30", None])})
    rows = pd.DataFrame({
        "player_id": [1, 2, 3, 4],
        "competition_id": [4, 4, 4, 5],
        "position_group": ["Goalkeeper", "Centre Forward", "Centre Forward", "Centre Back"],
        "minutes": [3000.0, 900.0, 2000.0, 1500.0],
        "objective_composite": [3.456, 2.1, 3.987, 3.3],
        "performance_band": [3.0, 2.0, 4.111, 3.1],
        "physical_band": [None, 2.5, 3.6, 3.2],
        "thin": [False, False, False, False]}).set_index("player_id")
    return squad, rows


def _rank(pid, comp, pos):
    return {1: (5, 62), 2: (40, 51), 3: (2, 51)}.get(pid, (None, 0))


def _avail(pid, comp, minutes):
    return {1: 0.95, 3: 0.875}.get(pid)


def test_columns_order_and_values():
    squad, rows = _frames()
    out = core.squad_export_rows(squad, rows, _rank, _avail, age_of=lambda b: 30.0)
    assert core.EXPORT_COLUMNS == COLS
    # position order GK, CB, FB, MF, W, CF; then Overall high to low
    assert [r["Player"] for r in out] == ["Keeper", "Back", "No Row", "Striker High",
                                          "Striker Low"]
    k = out[0]
    assert k == {"Player": "Keeper", "Position": "Goalkeeper", "Age": 30.0,
                 "Contract until": pd.Timestamp("2027-06-30").date(), "Minutes": 3000,
                 "Overall": 3.46, "Performance": 3.0, "Physical": None,
                 "League One rank (position)": "5 of 62", "Availability": 0.95}
    back = out[1]
    assert back["League One rank (position)"] is None        # rated in League Two, not One
    no_row = out[2]
    assert no_row["Position"] == "Winger" and no_row["Minutes"] is None
    assert no_row["Overall"] is None and no_row["Availability"] is None
    assert out[3]["Performance"] == 4.11 and out[3]["League One rank (position)"] == "2 of 51"


def test_thin_pool_has_no_rating_and_no_rank():
    squad, rows = _frames()
    rows.loc[3, ["objective_composite", "performance_band", "physical_band"]] = None
    rows.loc[3, "thin"] = True
    out = {r["Player"]: r for r in core.squad_export_rows(squad, rows, _rank, _avail,
                                                          age_of=lambda b: None)}
    hi = out["Striker High"]
    assert hi["Overall"] is None and hi["League One rank (position)"] is None


def test_workbook_layout():
    squad, rows = _frames()
    data = core.squad_xlsx(core.squad_export_rows(squad, rows, _rank, _avail,
                                                  age_of=lambda b: 30.0))
    wb = openpyxl.load_workbook(io.BytesIO(data))
    assert wb.sheetnames == ["Leyton Orient squad"]
    ws = wb.active
    assert [c.value for c in ws[1]] == COLS
    assert all(c.font.bold for c in ws[1])
    assert ws.freeze_panes == "A2"
    assert ws.max_row == 6
    r2 = {COLS[i]: c for i, c in enumerate(ws[2])}
    assert r2["Player"].value == "Keeper"
    assert r2["Overall"].value == 3.46 and r2["Overall"].number_format == "0.00"
    assert r2["Minutes"].value == 3000 and isinstance(r2["Minutes"].value, int)
    assert r2["Availability"].value == 0.95 and r2["Availability"].number_format == "0%"
    assert r2["Contract until"].is_date
    assert ws.column_dimensions["A"].width >= 15


# --- the endpoint (faked sources) ----------------------------------------------------------
@pytest.fixture
def fake(monkeypatch):
    import test_web_physical as twp
    from lofc.web.api import physical as api
    src = twp.install_fake(monkeypatch)
    squad, rows = _frames()
    src.squad = lambda: squad
    src.rated_rows = lambda s: rows
    src.l1_rank = lambda pid, comp, pos, s: _rank(pid, comp, pos) if comp == 4 else (None, 0)
    src.availability = lambda pid, comp, s, minutes: _avail(pid, comp, minutes)
    yield src
    api.clear()


def _client():
    from web_fakes import FakeStore, login, make
    s = FakeStore()
    s.add(username="u", full_name="Ann Scout", role="scout", password="correct-horse-1")
    c, *_ = make(s)
    login(c, "u", "correct-horse-1")
    return c


def test_endpoint_needs_login():
    from web_fakes import FakeStore, make
    c, *_ = make(FakeStore())
    assert c.get("/api/physical/squad.xlsx").status_code == 401


def test_endpoint_returns_the_workbook_for_the_season(fake):
    r = _client().get("/api/physical/squad.xlsx?season=319")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert 'filename="Leyton Orient squad 2026-27.xlsx"' in r.headers["content-disposition"]
    ws = openpyxl.load_workbook(io.BytesIO(r.content)).active
    assert [c.value for c in ws[1]] == COLS
    assert [ws.cell(row=i, column=1).value for i in range(2, ws.max_row + 1)] == [
        "Keeper", "Back", "No Row", "Striker High", "Striker Low"]


def test_page_has_the_download_button(fake):
    html = _client().get("/physical").text
    assert 'id="sq-xlsx"' in html and "⬇ Download squad (Excel)" in html
