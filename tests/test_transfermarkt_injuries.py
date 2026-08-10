"""Parser tests for the Transfermarkt injury history page. Pure functions, no network."""

from lofc.ingest.transfermarkt_injuries import (
    parse_days,
    parse_games_missed,
    parse_injury_rows,
    parse_tm_date,
)

# A cut-down copy of the real page: a header row, two injuries, and an ongoing one
# with no end date and no games missed.
INJURY_HTML = """
<table class="items">
<tr><th>Season</th><th>Injury</th><th>from</th><th>until</th><th>Days</th><th>Games missed</th></tr>
<tr><td>25/26</td><td>muscular problems</td><td>18/08/2025</td><td>26/08/2025</td><td>9 days</td><td>2</td></tr>
<tr><td>24/25</td><td>Ligament injury</td><td>16/07/2024</td><td>12/09/2024</td><td>59 days</td><td>10</td></tr>
<tr><td>25/26</td><td>Rest</td><td>26/05/2026</td><td>-</td><td>12 days</td><td>-</td></tr>
</table>
"""


def test_parse_tm_date_formats():
    assert parse_tm_date("18/08/2025") == "2025-08-18"
    assert parse_tm_date(" 16/07/2024 ") == "2024-07-16"
    assert parse_tm_date("-") is None
    assert parse_tm_date("") is None


def test_parse_days():
    assert parse_days("9 days") == 9
    assert parse_days("59 days") == 59
    assert parse_days("-") == 0
    assert parse_days("") == 0


def test_parse_games_missed_treats_dash_as_zero():
    # A dash means the injury cost no matches, typically an off-season injury.
    assert parse_games_missed("2") == 2
    assert parse_games_missed("10") == 10
    assert parse_games_missed("-") == 0
    assert parse_games_missed("") == 0


def test_parse_injury_rows_extracts_all_injuries():
    rows = parse_injury_rows(INJURY_HTML)
    assert len(rows) == 3
    assert rows[0] == {
        "season_label": "25/26",
        "injury_type_raw": "muscular problems",
        "date_from": "2025-08-18",
        "date_until": "2025-08-26",
        "days_out": 9,
        "games_missed": 2,
    }


def test_parse_injury_rows_skips_the_header_row():
    rows = parse_injury_rows(INJURY_HTML)
    assert all(r["season_label"] != "Season" for r in rows)


def test_parse_injury_rows_handles_ongoing_injury():
    ongoing = parse_injury_rows(INJURY_HTML)[2]
    assert ongoing["date_until"] is None
    assert ongoing["games_missed"] == 0


def test_parse_injury_rows_returns_empty_for_a_player_with_no_injuries():
    # A clean player's page has no data rows. This is a valid result, not an error.
    assert parse_injury_rows("<table class='items'></table>") == []
