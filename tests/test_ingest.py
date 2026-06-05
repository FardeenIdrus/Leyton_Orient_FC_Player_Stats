"""Tests for the raw-data landing layer. No network or database needed."""

from lofc.ingest import landing


def test_write_json_is_idempotent(tmp_path):
    path = tmp_path / "events" / "123.json"
    payload = [{"id": "a", "type": "Pass"}]

    assert landing.write_json(path, payload) is True       # first write happens
    assert landing.write_json(path, payload) is False      # second write is skipped
    assert landing.read_json(path) == payload              # content intact


def test_force_overwrites(tmp_path):
    path = tmp_path / "m.json"
    landing.write_json(path, {"v": 1})
    assert landing.write_json(path, {"v": 2}, force=True) is True
    assert landing.read_json(path) == {"v": 2}


def test_empty_file_is_not_counted_as_landed(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text("")
    assert landing.exists(path) is False


def test_path_layout(tmp_path, monkeypatch):
    # raw paths hang off the configured raw_data_dir.
    monkeypatch.setattr(landing.settings, "raw_data_dir", str(tmp_path))
    assert landing.events_path(2, 27, 999) == tmp_path / "2" / "27" / "events" / "999.json"
    assert landing.lineups_path(2, 27, 999) == tmp_path / "2" / "27" / "lineups" / "999.json"
    assert landing.matches_path(2, 27) == tmp_path / "2" / "27" / "matches.json"
