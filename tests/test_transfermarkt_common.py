"""Tests for the shared Transfermarkt HTTP client. No network."""

import pytest

from lofc.ingest import transfermarkt_common as tm


class _FakeResponse:
    def __init__(self, body: bytes = b"<html>ok</html>"):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def test_fetch_sends_browser_user_agent(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["ua"] = request.headers["User-agent"]
        return _FakeResponse()

    monkeypatch.setattr(tm.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(tm.time, "sleep", lambda seconds: None)

    assert tm.fetch("https://example.test/page") == "<html>ok</html>"
    assert "Mozilla" in captured["ua"]


def test_fetch_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(request, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError("transient")
        return _FakeResponse(b"recovered")

    monkeypatch.setattr(tm.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(tm.time, "sleep", lambda seconds: None)

    assert tm.fetch("https://example.test/page") == "recovered"
    assert calls["n"] == 3


def test_fetch_raises_after_exhausting_retries(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise OSError("down")

    monkeypatch.setattr(tm.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(tm.time, "sleep", lambda seconds: None)

    with pytest.raises(OSError):
        tm.fetch("https://example.test/page", retries=2)


def test_politeness_constants_are_not_weakened():
    assert tm.REQUEST_DELAY_S >= 2.5
