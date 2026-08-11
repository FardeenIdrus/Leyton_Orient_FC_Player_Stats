"""Parser tests for the EFL Transfermarkt scrape. Pure functions, no network."""

import datetime

import pytest

from lofc.ingest import transfermarkt_efl as tm
from lofc.ingest.transfermarkt_efl import (
    MIN_FILL_RATE,
    current_tm_season,
    degraded_fields,
    parse_birth_date,
    parse_foot,
    parse_height_cm,
    parse_squad,
    parse_value,
)

# The live layout, verified against transfermarkt.com on the current season.
CURRENT_HEADERS = ["#", "Player", "Date of birth/Age", "Nat.", "Height", "Foot",
                   "Joined", "Signed from", "Contract", "Market value"]
# The layout Transfermarkt serves for a season that has ENDED: `Current club`
# appears and `Contract` disappears. This is what caused the incident.
HISTORIC_HEADERS = ["#", "Player", "Date of birth/Age", "Nat.", "Current club", "Height",
                    "Foot", "Joined", "Signed from", "Market value"]

PLAYER_CELL = (
    '<td class="posrela"><table class="inline-table">'
    '<tr><td rowspan="2"><img/></td>'
    '<td class="hauptlink"><a href="/mads-hermansen/profil/spieler/12345">'
    'Mads Hermansen</a></td></tr>'
    '<tr><td>Goalkeeper</td></tr></table></td>'
)
CELL_HTML = {
    "#": '<td class="zentriert">1</td>',
    "Player": PLAYER_CELL,
    "Date of birth/Age": '<td class="zentriert">11/07/2000 (26)</td>',
    "Nat.": '<td class="zentriert"></td>',
    "Current club": '<td class="zentriert">West Ham United</td>',
    "Height": '<td class="zentriert">1,87m</td>',
    "Foot": '<td class="zentriert">right</td>',
    "Joined": '<td class="zentriert">09/08/2025</td>',
    "Signed from": '<td class="zentriert"></td>',
    "Contract": '<td class="zentriert">30/06/2030</td>',
    "Market value": '<td class="rechts hauptlink">€15.00m</td>',
}


def squad_html(headers: list[str]) -> str:
    """A one-row squad table in the given column order.

    The header text is written out verbatim (so a test can make it noisy) but the cell
    body is looked up on a case/whitespace-folded key.
    """
    cells = {" ".join(k.split()).lower(): v for k, v in CELL_HTML.items()}
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join(cells[" ".join(h.split()).lower()] for h in headers)
    return (f'<html><body><table class="items"><thead><tr>{head}</tr></thead>'
            f'<tbody><tr class="odd">{body}</tr></tbody></table></body></html>')


def parse(headers: list[str]) -> list[dict]:
    return parse_squad(squad_html(headers), "West Ham United", "GB2", 3)


# --------------------------------------------------------------------------
# Existing pure parsers.
# --------------------------------------------------------------------------

def test_parse_value_units():
    assert parse_value("€1.50m") == 1_500_000
    assert parse_value("€900k") == 900_000
    assert parse_value("€32.00m") == 32_000_000
    assert parse_value("-") is None
    assert parse_value("") is None


def test_parse_height_formats():
    assert parse_height_cm("1,91m") == 191
    assert parse_height_cm("1.85 m") == 185
    assert parse_height_cm("-") is None
    assert parse_height_cm("") is None


def test_parse_foot_values():
    assert parse_foot("right") == "right"
    assert parse_foot(" Left ") == "left"
    assert parse_foot("both") == "both"
    assert parse_foot("-") is None
    assert parse_foot("") is None


def test_parse_birth_date_formats():
    # Transfermarkt serves either format depending on locale negotiation.
    assert parse_birth_date("17/05/2003 (23)") == "2003-05-17"
    assert parse_birth_date("May 17, 2003 (23)") == "2003-05-17"
    assert parse_birth_date("Jan 28, 2000 (26)") == "2000-01-28"
    assert parse_birth_date("unknown") is None


# --------------------------------------------------------------------------
# D1 -- the season is derived, never a frozen constant.
# --------------------------------------------------------------------------

def test_current_tm_season_is_the_starting_year_of_the_english_season():
    # Transfermarkt labels a season by its starting year; English seasons start in August.
    assert current_tm_season(datetime.date(2026, 7, 1)) == 2026
    assert current_tm_season(datetime.date(2026, 12, 31)) == 2026
    assert current_tm_season(datetime.date(2027, 1, 15)) == 2026
    assert current_tm_season(datetime.date(2026, 6, 30)) == 2025


def test_current_tm_season_defaults_to_today():
    today = datetime.date.today()
    expected = today.year if today.month >= 7 else today.year - 1
    assert current_tm_season() == expected


# --------------------------------------------------------------------------
# D2 -- fields are read by header name, never by column position.
# --------------------------------------------------------------------------

def test_squad_row_parses_the_current_layout():
    rows = parse(CURRENT_HEADERS)
    assert len(rows) == 1
    row = rows[0]
    assert row["player_name"] == "Mads Hermansen"
    assert row["tm_player_id"] == "12345"
    assert row["position"] == "Goalkeeper"
    assert row["date_of_birth"] == "2000-07-11"
    assert row["height_cm"] == 187
    assert row["foot"] == "right"
    assert row["contract_until"] == "2030-06-30"
    assert row["market_value_eur"] == 15_000_000
    assert row["club_name"] == "West Ham United"
    assert row["competition_id"] == 3


def test_an_extra_column_before_height_does_not_shift_the_fields():
    # THE REGRESSION: positional parsing read blanks once a column moved.
    shifted = ["#", "Player", "Date of birth/Age", "Nat.", "Current club", "Height",
               "Foot", "Joined", "Signed from", "Contract", "Market value"]
    row = parse(shifted)[0]
    assert row["height_cm"] == 187
    assert row["foot"] == "right"
    assert row["contract_until"] == "2030-06-30"
    assert row["date_of_birth"] == "2000-07-11"


def test_headers_are_matched_case_insensitively_and_whitespace_tolerantly():
    noisy = ["#", " PLAYER ", "Date   of birth/Age", "Nat.", "height", "FOOT",
             "Joined", "Signed from", " contract ", "Market Value"]
    row = parse(noisy)[0]
    assert row["contract_until"] == "2030-06-30"
    assert row["height_cm"] == 187


def test_a_missing_required_header_raises_and_names_it():
    # The historic layout has no `Contract` column: fail loudly, never silently blank.
    with pytest.raises(ValueError) as excinfo:
        parse(HISTORIC_HEADERS)
    message = str(excinfo.value)
    assert "Contract" in message
    # The error must show what WAS found, so the layout change is diagnosable.
    assert "Current club" in message


def test_a_table_with_no_header_row_raises():
    html = ('<html><body><table class="items"><tbody><tr class="odd">'
            f'{"".join(CELL_HTML[h] for h in CURRENT_HEADERS)}'
            '</tr></tbody></table></body></html>')
    with pytest.raises(ValueError):
        parse_squad(html, "West Ham United", "GB2", 3)


def test_no_items_table_yields_no_rows():
    assert parse_squad("<html><body>nothing here</body></html>", "X", "GB2", 3) == []


# --------------------------------------------------------------------------
# D3 -- a degraded pull must abort rather than publish.
# --------------------------------------------------------------------------

def _rows(n: int, filled: int) -> list[dict]:
    """n scraped rows, `filled` of them carrying the bio fields."""
    return [{"contract_until": "2030-06-30" if i < filled else None,
             "height_cm": 187 if i < filled else None,
             "foot": "right" if i < filled else None,
             "market_value_eur": 1_000_000}
            for i in range(n)]


def test_degraded_fields_flags_a_zero_fill_contract_column():
    flagged = dict(degraded_fields(_rows(100, 0)))
    assert flagged["contract_until"] == 0.0
    assert set(flagged) == {"contract_until", "height_cm", "foot"}


def test_degraded_fields_passes_a_healthy_pull():
    assert degraded_fields(_rows(100, 90)) == []


def test_degraded_fields_boundary_is_twenty_percent():
    assert degraded_fields(_rows(100, 20)) == []
    assert [f for f, _ in degraded_fields(_rows(100, 19))] == \
        ["contract_until", "height_cm", "foot"]
    assert MIN_FILL_RATE == 0.20


def test_degraded_fields_treats_an_empty_scrape_as_degraded():
    assert [f for f, _ in degraded_fields([])] == ["contract_until", "height_cm", "foot"]


def _stub_scrape(monkeypatch, tmp_path, rows):
    """Point the scraper at tmp_path and replace every network call."""
    out = tmp_path / "efl_values.csv"
    backups = tmp_path / "backups"
    backups.mkdir()

    def no_network(*args, **kwargs):
        raise AssertionError("the test must not touch the network")

    monkeypatch.setattr(tm, "output_path", lambda: out)
    monkeypatch.setattr(tm, "backup_dir", lambda: backups)
    monkeypatch.setattr(tm, "LEAGUES", {"GB2": ("championship", 3)})
    monkeypatch.setattr(tm, "club_pages", lambda slug, code, season: [("Club", "url")])
    monkeypatch.setattr(tm, "squad_rows", lambda *a, **k: rows)
    monkeypatch.setattr(tm, "_fetch", no_network)
    return out, backups


def test_a_degraded_pull_leaves_the_existing_csv_untouched(monkeypatch, tmp_path, capsys):
    out, _ = _stub_scrape(monkeypatch, tmp_path, _rows(100, 0))
    out.write_text("good,data\n1,2\n")

    with pytest.raises(SystemExit) as excinfo:
        tm.main(["--force"])

    assert excinfo.value.code != 0
    assert out.read_text() == "good,data\n1,2\n"
    printed = capsys.readouterr().out
    assert "contract_until" in printed
    assert "0.0%" in printed or "0%" in printed


def test_allow_degraded_writes_anyway(monkeypatch, tmp_path, capsys):
    out, _ = _stub_scrape(monkeypatch, tmp_path, _rows(100, 0))
    out.write_text("good,data\n1,2\n")

    tm.main(["--force", "--allow-degraded"])

    assert "contract_until" in out.read_text().splitlines()[0]
    assert len(out.read_text().splitlines()) == 101
    assert "--allow-degraded" in capsys.readouterr().out


def test_a_healthy_pull_backs_up_the_previous_csv(monkeypatch, tmp_path):
    out, backups = _stub_scrape(monkeypatch, tmp_path, _rows(100, 95))
    out.write_text("previous,snapshot\n1,2\n")

    tm.main(["--force"])

    saved = list(backups.glob("efl_values-*.csv"))
    assert len(saved) == 1
    assert saved[0].read_text() == "previous,snapshot\n1,2\n"
    assert len(out.read_text().splitlines()) == 101


def test_an_empty_scrape_never_reaches_the_csv_even_with_allow_degraded(monkeypatch, tmp_path):
    out, _ = _stub_scrape(monkeypatch, tmp_path, [])
    out.write_text("good,data\n1,2\n")

    with pytest.raises(SystemExit):
        tm.main(["--force", "--allow-degraded"])

    assert out.read_text() == "good,data\n1,2\n"


def test_the_season_being_scraped_is_printed(monkeypatch, tmp_path, capsys):
    _stub_scrape(monkeypatch, tmp_path, _rows(10, 10))
    tm.main(["--force", "--season", "2026"])
    assert "2026" in capsys.readouterr().out


def test_an_explicit_season_overrides_the_derived_one(monkeypatch, tmp_path):
    seen = []
    _stub_scrape(monkeypatch, tmp_path, _rows(10, 10))
    monkeypatch.setattr(tm, "club_pages",
                        lambda slug, code, season: seen.append(season) or [("C", "url")])
    tm.main(["--force", "--season", "2019"])
    assert seen == [2019]


def test_the_default_season_is_the_current_one(monkeypatch, tmp_path):
    seen = []
    _stub_scrape(monkeypatch, tmp_path, _rows(10, 10))
    monkeypatch.setattr(tm, "club_pages",
                        lambda slug, code, season: seen.append(season) or [("C", "url")])
    tm.main(["--force"])
    assert seen == [current_tm_season()]
