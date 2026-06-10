"""Parser tests for the EFL Transfermarkt scrape. Pure functions, no network."""

from lofc.ingest.transfermarkt_efl import parse_birth_date, parse_value


def test_parse_value_units():
    assert parse_value("€1.50m") == 1_500_000
    assert parse_value("€900k") == 900_000
    assert parse_value("€32.00m") == 32_000_000
    assert parse_value("-") is None
    assert parse_value("") is None


def test_parse_birth_date_formats():
    # Transfermarkt serves either format depending on locale negotiation.
    assert parse_birth_date("17/05/2003 (23)") == "2003-05-17"
    assert parse_birth_date("May 17, 2003 (23)") == "2003-05-17"
    assert parse_birth_date("Jan 28, 2000 (26)") == "2000-01-28"
    assert parse_birth_date("unknown") is None
