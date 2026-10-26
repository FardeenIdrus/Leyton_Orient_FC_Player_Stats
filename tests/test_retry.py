"""Retry/backoff around provider API calls (src/lofc/ingest/retry.py).

Nothing here touches the network: providers are monkeypatched and `sleep` is injected.
"""
from __future__ import annotations

import httpx
import pandas as pd
import pytest
import requests
from fitrequest.errors import HTTPStatusError as FitHTTPStatusError
from impectPy.helpers import ForbiddenError, HTTPError as ImpectHTTPError

from lofc.ingest import impect, impect_definitions, retry, skillcorner_api
from lofc.ingest.retry import is_transient, with_retries


class Boom(ConnectionError):
    pass


def _flaky(failures, exc, result="ok"):
    state = {"calls": 0}

    def fn():
        state["calls"] += 1
        if state["calls"] <= failures:
            raise exc
        return result
    return fn, state


# ---- with_retries behaviour ---------------------------------------------------------

def test_success_first_try_no_sleep():
    waits = []
    fn, st = _flaky(0, Boom())
    assert with_retries(fn, what="x", sleep=waits.append) == "ok"
    assert st["calls"] == 1 and waits == []


def test_transient_twice_then_success_backoff(capsys):
    waits = []
    fn, st = _flaky(2, Boom("net down"))
    assert with_retries(fn, what="impect averages", sleep=waits.append) == "ok"
    assert st["calls"] == 3
    assert 2.0 <= waits[0] <= 2.5 and 4.0 <= waits[1] <= 5.0  # base*2**(n-1) + <=25% jitter
    out = capsys.readouterr().out
    assert "impect averages" in out and "attempt 1 of 4" in out and "Boom" in out


def test_always_transient_reraises_original():
    waits = []
    exc = Boom("still down")
    fn, st = _flaky(99, exc)
    with pytest.raises(Boom) as ei:
        with_retries(fn, what="x", attempts=4, sleep=waits.append)
    assert ei.value is exc
    assert st["calls"] == 4 and len(waits) == 3


@pytest.mark.parametrize("exc", [ValueError("bad"), KeyError("k"), ForbiddenError("Received status code 403 (x)"),
                                 ImpectHTTPError("Received status code 401 (Invalid User Credentials).")])
def test_non_transient_fails_immediately(exc):
    waits = []
    fn, st = _flaky(99, exc)
    with pytest.raises(type(exc)) as ei:
        with_retries(fn, what="x", sleep=waits.append)
    assert ei.value is exc and st["calls"] == 1 and waits == []


def test_delay_capped_at_max_delay():
    waits = []
    fn, _ = _flaky(99, Boom())
    with pytest.raises(Boom):
        with_retries(fn, what="x", attempts=6, base_delay=10, max_delay=15, sleep=waits.append)
    assert len(waits) == 5 and all(w <= 15 for w in waits)


# ---- classification, built the way each library builds them ---------------------------

def _req_http_error(code):
    resp = requests.Response()
    resp.status_code = code
    return requests.HTTPError(f"{code} error", response=resp)


def _httpx_status_error(code):
    req = httpx.Request("GET", "https://example.test")
    return httpx.HTTPStatusError("err", request=req, response=httpx.Response(code, request=req))


@pytest.mark.parametrize("exc", [
    requests.ConnectionError("x"), requests.Timeout("x"), requests.exceptions.ChunkedEncodingError("x"),
    _req_http_error(429), _req_http_error(500), _req_http_error(503),
    httpx.ConnectError("x"), httpx.ReadTimeout("x"), httpx.RemoteProtocolError("x"),
    _httpx_status_error(429), _httpx_status_error(502),
    FitHTTPStatusError(status_code=503, content=b""), FitHTTPStatusError(status_code=429, content=b""),
    ImpectHTTPError("Received status code 429 (Rate Limit Exceeded), exceeded maximum number of 3 retries."),
    ImpectHTTPError("Received status code 503 (Unknown error). Request-ID: abc"),
    requests.exceptions.JSONDecodeError("Expecting value", "", 0),
    ConnectionResetError("x"), TimeoutError("x"),
])
def test_transient_classification(exc):
    assert is_transient(exc) is True


@pytest.mark.parametrize("exc", [
    _req_http_error(401), _req_http_error(403), _req_http_error(404), _req_http_error(400),
    _httpx_status_error(401), _httpx_status_error(404),
    FitHTTPStatusError(status_code=403, content=b""), FitHTTPStatusError(status_code=404, content=b""),
    ImpectHTTPError("Received status code 404 (Not found). Request-ID: abc"),
    ImpectHTTPError("Received status code 401 (Invalid User Credentials)."),
    ForbiddenError("Received status code 403 (You do not have access)."),
    ValueError("x"), KeyError("x"), TypeError("x"), RuntimeError("x"), Exception("returned no data/ an empty list."),
    FileNotFoundError("x"),
])
def test_non_transient_classification(exc):
    assert is_transient(exc) is False


# ---- call sites actually use the wrapper ------------------------------------------------

@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(retry.time, "sleep", lambda s: None)


def test_impect_pull_retries_fetch(no_sleep, tmp_path, monkeypatch):
    fn_calls = {"n": 0}

    def fetch():
        fn_calls["n"] += 1
        if fn_calls["n"] == 1:
            raise requests.ConnectionError("blip")
        return pd.DataFrame({"a": [1]})

    monkeypatch.setattr(impect, "write_parquet", lambda *a, **k: True)
    monkeypatch.setattr(impect, "is_live", lambda t: False)
    target = _impect_target()
    assert impect._pull(target, tmp_path / "x.parquet", fetch, "averages", force=True) is True
    assert fn_calls["n"] == 2


def _impect_target():
    from types import SimpleNamespace
    return SimpleNamespace(label="T", iteration_id=2, season_id=1)


def test_impect_pull_live_still_skipped_quietly_after_final_failure(no_sleep, tmp_path, monkeypatch):
    monkeypatch.setattr(impect, "is_live", lambda t: True)

    def fetch():
        raise ImpectHTTPError("Received status code 404 (Not found). Request-ID: a")
    assert impect._pull(_impect_target(), tmp_path / "none.parquet", fetch, "averages") is False


def test_impect_token_retries(no_sleep, monkeypatch):
    import impectPy
    calls = {"n": 0}

    def fake(user, pw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise requests.Timeout("slow")
        return "tok"
    monkeypatch.setattr(impectPy, "getAccessToken", fake)
    monkeypatch.setattr(impect.settings, "impect_username", "u", raising=False)
    monkeypatch.setattr(impect.settings, "impect_password", "p", raising=False)
    monkeypatch.setattr(type(impect.settings), "impect_authenticated", property(lambda s: True), raising=False)
    assert impect._token() == "tok" and calls["n"] == 2


def test_skillcorner_pull_edition_retries(no_sleep, tmp_path, monkeypatch):
    monkeypatch.setattr(skillcorner_api, "physical_path", lambda e: tmp_path / "p.parquet")
    monkeypatch.setattr(skillcorner_api, "is_live", lambda t: False)
    monkeypatch.setattr(skillcorner_api, "write_parquet", lambda *a, **k: True)

    class Client:
        n = 0

        def get_physical(self, params):
            Client.n += 1
            if Client.n == 1:
                raise FitHTTPStatusError(status_code=503, content=b"")
            return [{"player_id": 1}]
    target = SimpleNamespaceTarget()
    assert skillcorner_api.pull_edition(target, Client(), force=True) is True
    assert Client.n == 2


def SimpleNamespaceTarget():
    from types import SimpleNamespace
    return SimpleNamespace(label="T", edition_id=9, season_id=1)


def test_skillcorner_live_not_started_still_skipped(no_sleep, tmp_path, monkeypatch):
    monkeypatch.setattr(skillcorner_api, "physical_path", lambda e: tmp_path / "none.parquet")
    monkeypatch.setattr(skillcorner_api, "is_live", lambda t: True)

    class Client:
        def get_physical(self, params):
            raise FitHTTPStatusError(status_code=404, content=b"")
    assert skillcorner_api.pull_edition(SimpleNamespaceTarget(), Client(), force=True) is False


def test_definitions_pull_retries(no_sleep, tmp_path, monkeypatch):
    monkeypatch.setattr(impect_definitions, "definitions_raw_path", lambda: tmp_path / "d.json")
    written = {}
    monkeypatch.setattr(impect_definitions.landing, "write_json", lambda p, d, force=False: written.setdefault("d", d))
    state = {"n": 0}

    def fake_get(url, headers=None, timeout=None):
        state["n"] += 1
        resp = requests.Response()
        if state["n"] == 1:
            resp.status_code = 503
        else:
            resp.status_code = 200
            resp._content = b'{"data": [{"id": 1}]}'
        return resp
    monkeypatch.setattr(requests, "get", fake_get)
    assert impect_definitions.pull_definitions("tok", force=True) is True
    assert state["n"] == 2 and written["d"] == [{"id": 1}]
