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


from lofc.ingest.transfermarkt_injuries import categorise_injury


def test_categorise_the_club_named_injuries():
    assert categorise_injury("Hamstring injury") == "hamstring"
    assert categorise_injury("Calf strain") == "calf"
    assert categorise_injury("Adductor pain") == "groin"
    assert categorise_injury("Cruciate ligament rupture") == "knee_ligament"
    assert categorise_injury("muscular problems") == "muscular"


def test_specific_joint_beats_the_generic_ligament_rule():
    # "Ankle ligament tear" must be ankle, not knee_ligament -- order matters.
    assert categorise_injury("Ankle ligament tear") == "ankle"


def test_unknown_phrasing_falls_back_to_other():
    assert categorise_injury("Rest") == "other"
    assert categorise_injury("Unknown injury") == "other"
    assert categorise_injury("") == "other"


def test_categorisation_is_case_insensitive():
    assert categorise_injury("HAMSTRING INJURY") == "hamstring"


import csv

from lofc.ingest import transfermarkt_injuries as tmi

ONE_INJURY_HTML = """
<table class="items">
<tr><th>Season</th><th>Injury</th><th>from</th><th>until</th><th>Days</th><th>Games missed</th></tr>
<tr><td>25/26</td><td>Hamstring injury</td><td>18/08/2025</td><td>26/08/2025</td><td>9 days</td><td>2</td></tr>
</table>
"""


def _redirect_paths(monkeypatch, tmp_path):
    """Point the module's three file paths at a temporary directory."""
    monkeypatch.setattr(tmi, "output_path", lambda: tmp_path / "injuries.csv")
    monkeypatch.setattr(tmi, "partial_path", lambda: tmp_path / "injuries.csv.partial")
    monkeypatch.setattr(tmi, "progress_path", lambda: tmp_path / "injuries.progress")


def test_injury_url_uses_the_id_not_the_slug():
    # Transfermarkt resolves the player from the id and ignores the name slug.
    assert tmi.injury_url(88755).endswith("/verletzungen/spieler/88755")


def test_scrape_writes_rows_with_id_and_category(monkeypatch, tmp_path):
    _redirect_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(tmi, "fetch", lambda url: ONE_INJURY_HTML)

    assert tmi.scrape([111]) == 1

    rows = list(csv.DictReader(open(tmp_path / "injuries.csv")))
    assert len(rows) == 1
    assert rows[0]["tm_player_id"] == "111"
    assert rows[0]["injury_category"] == "hamstring"
    assert rows[0]["games_missed"] == "2"


def test_player_with_no_injuries_is_recorded_as_done(monkeypatch, tmp_path):
    _redirect_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(tmi, "fetch", lambda url: "<table class='items'></table>")

    tmi.scrape([222])

    # No CSV rows, but the id must still be marked complete or a resume refetches him.
    assert 222 in tmi.load_progress()


def test_failed_player_is_skipped_and_not_marked_done(monkeypatch, tmp_path):
    _redirect_paths(monkeypatch, tmp_path)

    def flaky(url):
        if "999" in url:
            raise OSError("page failed")
        return ONE_INJURY_HTML

    monkeypatch.setattr(tmi, "fetch", flaky)

    tmi.scrape([111, 999])

    progress = tmi.load_progress()
    assert 111 in progress
    assert 999 not in progress   # so a resume retries him


def test_resume_skips_completed_ids_and_writes_one_header(monkeypatch, tmp_path):
    _redirect_paths(monkeypatch, tmp_path)

    calls = []

    def counting_fetch(url):
        calls.append(url)
        return ONE_INJURY_HTML

    monkeypatch.setattr(tmi, "fetch", counting_fetch)

    tmi.scrape([111])          # first run
    tmi.scrape([111, 222])     # resume: 111 already done

    assert len(calls) == 2     # 111 once, 222 once -- not three fetches

    text = (tmp_path / "injuries.csv").read_text()
    assert text.count("tm_player_id") == 1   # header written exactly once
