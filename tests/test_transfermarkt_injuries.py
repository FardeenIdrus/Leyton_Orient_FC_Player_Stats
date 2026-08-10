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

import pytest

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

    with open(tmp_path / "injuries.csv", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["tm_player_id"] == "111"
    assert rows[0]["injury_category"] == "hamstring"
    assert rows[0]["games_missed"] == "2"


class _SimulatedCrash(BaseException):
    """Stands in for a real process interruption (killed, crashed, OOM). Like
    `KeyboardInterrupt` -- which it deliberately subclasses `BaseException` rather
    than `Exception` to resemble -- it must NOT be swallowed by scrape()'s
    `except Exception`, so it propagates out of scrape() before publish is reached.
    """


def test_player_with_no_injuries_is_recorded_as_done(monkeypatch, tmp_path):
    _redirect_paths(monkeypatch, tmp_path)

    def fetch_then_crash(url):
        if "222" in url:
            return "<table class='items'></table>"   # no injuries for this player
        raise _SimulatedCrash("process killed")         # crash before reaching 333

    monkeypatch.setattr(tmi, "fetch", fetch_then_crash)

    with pytest.raises(_SimulatedCrash):
        tmi.scrape([222, 333])

    # 222 was fully processed (zero rows) before the crash on 333. He must still be
    # marked complete in the surviving, unpublished progress file, or a resume would
    # refetch him even though he genuinely has nothing to report.
    assert 222 in tmi.load_progress()
    # And the crash means the run never reached publish.
    assert not tmp_path.joinpath("injuries.csv").exists()


def test_failed_player_is_skipped_and_not_marked_done(monkeypatch, tmp_path):
    _redirect_paths(monkeypatch, tmp_path)

    calls = []

    def flaky_then_crash(url):
        calls.append(url)
        if "999" in url:
            raise OSError("page failed")             # caught inside scrape(), logged
        if "333" in url:
            raise _SimulatedCrash("process killed")     # ends the run before publish
        return ONE_INJURY_HTML

    monkeypatch.setattr(tmi, "fetch", flaky_then_crash)

    with pytest.raises(_SimulatedCrash):
        tmi.scrape([111, 999, 333])

    # Mid-run state, inspected before any cleanup happens: 111 succeeded and is
    # marked done. 999's page was genuinely attempted and failed, so he must NOT be
    # marked done -- distinct from 333, who the crash means was never attempted at
    # all (both are absent from progress, but for different reasons).
    progress = tmi.load_progress()
    assert 111 in progress
    assert 999 not in progress
    assert 333 not in progress
    # All three were attempted -- 999's failure didn't stop the run, only the crash
    # on 333 did -- but only 111 succeeded and got marked done.
    assert calls == [tmi.injury_url(111), tmi.injury_url(999), tmi.injury_url(333)]

    # Resume: same id list, nothing crashes this time. 111 is skipped (already
    # done); 999 -- whose earlier attempt was never marked complete -- is retried,
    # and 333 (never reached before) is fetched for the first time.
    calls.clear()

    def healthy(url):
        calls.append(url)
        return ONE_INJURY_HTML

    monkeypatch.setattr(tmi, "fetch", healthy)
    tmi.scrape([111, 999, 333])

    assert calls == [tmi.injury_url(999), tmi.injury_url(333)]  # not 111


def test_resume_skips_completed_ids_and_writes_one_header(monkeypatch, tmp_path):
    _redirect_paths(monkeypatch, tmp_path)

    calls = []

    def crash_on_222(url):
        calls.append(url)
        if "222" in url:
            raise _SimulatedCrash("process killed")
        return ONE_INJURY_HTML

    monkeypatch.setattr(tmi, "fetch", crash_on_222)

    with pytest.raises(_SimulatedCrash):
        tmi.scrape([111, 222, 333])

    # The crash landed before publish: no injuries.csv yet (atomic publish -- an
    # interrupted run never leaves a half-written one), but the partial working
    # file already holds 111's row and the progress file already marks him done.
    assert not tmp_path.joinpath("injuries.csv").exists()
    assert tmp_path.joinpath("injuries.csv.partial").exists()
    assert 111 in tmi.load_progress()

    # Resume with a healthy fetch: 111 is skipped, 222 and 333 are (re)fetched.
    calls.clear()

    def healthy(url):
        calls.append(url)
        return ONE_INJURY_HTML

    monkeypatch.setattr(tmi, "fetch", healthy)
    tmi.scrape([111, 222, 333])

    assert calls == [tmi.injury_url(222), tmi.injury_url(333)]

    with open(tmp_path / "injuries.csv", newline="") as handle:
        text = handle.read()
        handle.seek(0)
        rows = list(csv.DictReader(handle))
    assert text.count("tm_player_id") == 1                        # header once
    assert {r["tm_player_id"] for r in rows} == {"111", "222", "333"}

    # Publish is atomic and consumes the working file: nothing is left to be
    # reopened (and duplicated into) by a later, unrelated run.
    assert not tmp_path.joinpath("injuries.csv.partial").exists()
