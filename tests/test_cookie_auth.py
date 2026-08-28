"""The signed remembered-session cookie: sign/verify/decide, pure. No Streamlit, no browser,
no database -- mirrors how auth.py and session.py are already tested."""

import dataclasses
import datetime as dt

from lofc.dashboard import cookie_auth

NOW = dt.datetime(2026, 8, 14, 12, 0)
SECRET = "a-test-secret-not-used-anywhere-real"


def _stub_user(*, full_name="J. Smith", role="scout", is_active=True,
               must_change_password=False):
    @dataclasses.dataclass(frozen=True)
    class _Row:
        full_name: str
        role: str
        is_active: bool
        must_change_password: bool

    return _Row(full_name=full_name, role=role, is_active=is_active,
               must_change_password=must_change_password)


# --- issue_token / verify_token ------------------------------------------------------------


def test_a_freshly_issued_token_verifies():
    token = cookie_auth.issue_token(3, NOW, SECRET)
    payload = cookie_auth.verify_token(token, SECRET, NOW)
    assert payload == cookie_auth.TokenPayload(user_id=3, logged_in_at=NOW)


def test_a_token_anchored_at_a_timestamp_with_microseconds_still_verifies():
    """datetime.isoformat() puts a '.' before microseconds -- the SAME character as
    cookie_auth's own field separator. `datetime.datetime.now()` (what `require_login`
    actually anchors a token to) almost always has a nonzero microsecond component, unlike
    the whole-second NOW used elsewhere in this file, so this is the case that would have
    caught the parsing bug a whole-second fixture cannot expose."""
    with_micros = NOW.replace(microsecond=123456)
    token = cookie_auth.issue_token(3, with_micros, SECRET)
    assert with_micros.isoformat().count(".") >= 1, "fixture must actually exercise the '.'"
    payload = cookie_auth.verify_token(token, SECRET, with_micros)
    assert payload == cookie_auth.TokenPayload(user_id=3, logged_in_at=with_micros)


def test_a_tampered_payload_does_not_verify():
    token = cookie_auth.issue_token(3, NOW, SECRET)
    user_id_s, logged_in_at_s, sig = token.split(cookie_auth._SEP)
    tampered = f"{99}{cookie_auth._SEP}{logged_in_at_s}{cookie_auth._SEP}{sig}"
    assert cookie_auth.verify_token(tampered, SECRET, NOW) is None


def test_a_tampered_signature_does_not_verify():
    token = cookie_auth.issue_token(3, NOW, SECRET)
    tampered = token[:-1] + ("x" if token[-1] != "x" else "y")
    assert cookie_auth.verify_token(tampered, SECRET, NOW) is None


def test_a_token_signed_under_a_different_secret_does_not_verify():
    token = cookie_auth.issue_token(3, NOW, SECRET)
    assert cookie_auth.verify_token(token, "a-different-secret", NOW) is None


def test_an_expired_token_does_not_verify():
    """Reuses auth.SESSION_TTL_MINUTES -- the SAME rule an in-memory session already uses."""
    from lofc.dashboard import auth
    token = cookie_auth.issue_token(3, NOW, SECRET)
    later = NOW + dt.timedelta(minutes=auth.SESSION_TTL_MINUTES + 1)
    assert cookie_auth.verify_token(token, SECRET, later) is None


def test_a_token_just_inside_the_ttl_still_verifies():
    from lofc.dashboard import auth
    token = cookie_auth.issue_token(3, NOW, SECRET)
    later = NOW + dt.timedelta(minutes=auth.SESSION_TTL_MINUTES - 1)
    assert cookie_auth.verify_token(token, SECRET, later) is not None


def test_none_and_empty_and_malformed_tokens_do_not_verify():
    for bad in (None, "", "not-a-token", "1.2", "1.2.3.4"):
        assert cookie_auth.verify_token(bad, SECRET, NOW) is None


def test_a_non_integer_user_id_does_not_verify():
    # Hand-craft a token whose payload has a non-integer user id but a genuine signature.
    payload = f"not-an-int{cookie_auth._SEP}{NOW.isoformat()}"
    forged = f"{payload}{cookie_auth._SEP}{cookie_auth._sign(payload, SECRET)}"
    assert cookie_auth.verify_token(forged, SECRET, NOW) is None


# --- resolve_cookie_restore ------------------------------------------------------------------


def test_a_valid_token_and_an_active_user_restores():
    payload = cookie_auth.TokenPayload(user_id=3, logged_in_at=NOW)
    restored = cookie_auth.resolve_cookie_restore(payload, _stub_user())
    assert restored == cookie_auth.RestoredSession(
        user_id=3, full_name="J. Smith", role="scout", logged_in_at=NOW,
        must_change_password=False)


def test_no_token_never_restores():
    assert cookie_auth.resolve_cookie_restore(None, _stub_user()) is None


def test_a_missing_user_row_never_restores():
    """The account id in the token no longer exists at all."""
    payload = cookie_auth.TokenPayload(user_id=3, logged_in_at=NOW)
    assert cookie_auth.resolve_cookie_restore(payload, None) is None


def test_a_deactivated_user_does_not_restore():
    """A cookie issued before deactivation must not go on working after it -- is_active is
    re-checked against the LIVE row, never trusted from the cookie."""
    payload = cookie_auth.TokenPayload(user_id=3, logged_in_at=NOW)
    restored = cookie_auth.resolve_cookie_restore(payload, _stub_user(is_active=False))
    assert restored is None


def test_a_user_needing_a_password_change_still_restores_but_flags_it():
    """The restore succeeds -- the caller ends up signed in -- but must_change_password
    travels through, so the caller (session.require_login) still forces the change-password
    step exactly as it would for a fresh sign-in."""
    payload = cookie_auth.TokenPayload(user_id=3, logged_in_at=NOW)
    restored = cookie_auth.resolve_cookie_restore(
        payload, _stub_user(must_change_password=True))
    assert restored is not None
    assert restored.must_change_password is True


def test_the_restored_session_carries_no_password_or_hash():
    """RestoredSession only ever has the fields session_state already uses for a fresh
    login -- confirms nothing password-shaped can leak through this path."""
    payload = cookie_auth.TokenPayload(user_id=3, logged_in_at=NOW)
    restored = cookie_auth.resolve_cookie_restore(payload, _stub_user())
    fields = {f.name for f in dataclasses.fields(restored)}
    assert fields == {"user_id", "full_name", "role", "logged_in_at", "must_change_password"}


def test_the_token_itself_carries_no_password_or_role():
    """issue_token/verify_token's payload is a user id and a timestamp -- nothing else."""
    token = cookie_auth.issue_token(3, NOW, SECRET)
    payload = cookie_auth.verify_token(token, SECRET, NOW)
    fields = {f.name for f in dataclasses.fields(payload)}
    assert fields == {"user_id", "logged_in_at"}
