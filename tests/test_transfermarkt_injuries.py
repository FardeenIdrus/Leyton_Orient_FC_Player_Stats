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
    """Point the module's file paths at a temporary directory.

    The sample paths are derived from `output_path()`, so redirecting that one
    redirects the smoke-test trio too. The backup directory is redirected as well:
    a test must never write into the real data/backups.
    """
    monkeypatch.setattr(tmi, "output_path", lambda: tmp_path / "injuries.csv")
    monkeypatch.setattr(tmi, "partial_path", lambda: tmp_path / "injuries.csv.partial")
    monkeypatch.setattr(tmi, "progress_path", lambda: tmp_path / "injuries.progress")
    monkeypatch.setattr(tmi, "backup_dir", lambda: tmp_path / "backups")


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


# --------------------------------------------------------------------------
# F3 -- player_ids(): the id list that drives the whole scrape.
# --------------------------------------------------------------------------

def _efl_values(tmp_path, rows: str):
    """Write an efl_values.csv into tmp_path and point the module's dir at it."""
    (tmp_path / "efl_values.csv").write_text("tm_player_id,player_name\n" + rows)
    return tmp_path


def test_player_ids_reads_distinct_sorted_ids(monkeypatch, tmp_path):
    _efl_values(tmp_path, "333,C\n111,A\n111,A again\n222,B\n")
    monkeypatch.setattr(tmi, "_tm_dir", lambda: tmp_path)
    assert tmi.player_ids() == [111, 222, 333]


def test_player_ids_skips_blank_transfermarkt_ids(monkeypatch, tmp_path):
    # A squad row with no TM id is an identity we do not have; it is not an error.
    _efl_values(tmp_path, "111,A\n,No Id\n  ,Whitespace Id\n222,B\n")
    monkeypatch.setattr(tmi, "_tm_dir", lambda: tmp_path)
    assert tmi.player_ids() == [111, 222]


def test_player_ids_raises_loudly_on_a_non_numeric_id(monkeypatch, tmp_path):
    # Silently dropping junk would shrink the id list, and a short id list is
    # precisely what publishes a truncated injuries.csv. Fail instead.
    _efl_values(tmp_path, "111,A\nnot-an-id,B\n")
    monkeypatch.setattr(tmi, "_tm_dir", lambda: tmp_path)
    with pytest.raises(ValueError) as excinfo:
        tmi.player_ids()
    assert "not-an-id" in str(excinfo.value)


# --------------------------------------------------------------------------
# F1 -- a limited (smoke-test) run must never be able to publish over the full
# CSV, and a full publish always backs up what it replaces.
# --------------------------------------------------------------------------

FULL_CSV = ("tm_player_id,season_label,injury_type_raw,injury_category,date_from,"
            "date_until,days_out,games_missed\n"
            + "1,25/26,Hamstring injury,hamstring,2025-08-18,2025-08-26,9,2\n" * 3930)


def _main_setup(monkeypatch, tmp_path, ids=(111, 222, 333)):
    """Redirect every path, stub the network and the id list."""
    _redirect_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(tmi, "player_ids", lambda: list(ids))
    monkeypatch.setattr(tmi, "fetch", lambda url: ONE_INJURY_HTML)
    return tmp_path / "injuries.csv"


def test_limit_with_force_cannot_touch_the_full_csv(monkeypatch, tmp_path, capsys):
    # THE INCIDENT: `--limit 5 --force` ended its truncated id list, which the module
    # treated as a complete run, and published a handful of rows over 3,930.
    out = _main_setup(monkeypatch, tmp_path)
    out.write_text(FULL_CSV)

    tmi.main(["--limit", "2", "--force"])

    assert out.read_text() == FULL_CSV                      # untouched
    sample = tmp_path / "injuries.sample.csv"
    assert sample.exists()
    with open(sample, newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert {r["tm_player_id"] for r in rows} == {"111", "222"}
    printed = capsys.readouterr().out
    assert "injuries.sample.csv" in printed


def test_a_limited_run_uses_its_own_progress_file(monkeypatch, tmp_path):
    # A smoke test must not leave progress markers that a later full run would
    # honour, or the full run would skip those players and publish without them.
    out = _main_setup(monkeypatch, tmp_path)
    out.write_text(FULL_CSV)

    tmi.main(["--limit", "2", "--force"])

    assert not tmp_path.joinpath("injuries.progress").exists()
    assert not tmp_path.joinpath("injuries.csv.partial").exists()


def test_limit_rejects_a_non_positive_value(monkeypatch, tmp_path):
    _main_setup(monkeypatch, tmp_path)
    with pytest.raises(SystemExit):
        tmi.main(["--limit", "0", "--force"])


def test_a_full_run_backs_up_the_csv_it_replaces(monkeypatch, tmp_path):
    out = _main_setup(monkeypatch, tmp_path)
    out.write_text(FULL_CSV)

    tmi.main(["--force"])

    saved = list((tmp_path / "backups").glob("injuries-*.csv"))
    assert len(saved) == 1
    assert saved[0].read_text() == FULL_CSV                 # the previous file, intact
    with open(out, newline="") as handle:
        assert {r["tm_player_id"] for r in csv.DictReader(handle)} == {"111", "222", "333"}


def test_backup_is_a_no_op_when_there_is_nothing_to_replace(monkeypatch, tmp_path):
    _redirect_paths(monkeypatch, tmp_path)
    assert tmi.backup_existing_csv(tmp_path / "injuries.csv") is None
    assert not (tmp_path / "backups").exists()


def test_main_skips_when_the_csv_is_present_and_force_is_absent(monkeypatch, tmp_path, capsys):
    out = _main_setup(monkeypatch, tmp_path)
    out.write_text(FULL_CSV)

    monkeypatch.setattr(tmi, "fetch", lambda url: (_ for _ in ()).throw(
        AssertionError("must not fetch when skipping")))
    tmi.main([])

    assert out.read_text() == FULL_CSV
    assert "already present" in capsys.readouterr().out


def test_main_writes_the_csv_on_a_first_ever_run(monkeypatch, tmp_path):
    out = _main_setup(monkeypatch, tmp_path)

    tmi.main([])

    with open(out, newline="") as handle:
        assert len(list(csv.DictReader(handle))) == 3
    assert list((tmp_path / "backups").glob("*.csv")) == []  # nothing to back up
