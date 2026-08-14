"""Password hashing and role permissions. No database, no network."""

import hashlib

from lofc.dashboard.auth import ROLES, can, hash_password, verify_password


def test_a_correct_password_verifies():
    stored = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", stored)


def test_a_wrong_password_does_not_verify():
    stored = hash_password("correct horse battery staple")
    assert not verify_password("Correct horse battery staple", stored)
    assert not verify_password("", stored)


def test_the_same_password_hashes_differently_each_time():
    # A per-user salt means two users with the same password do not share a hash.
    assert hash_password("same") != hash_password("same")


def test_the_stored_hash_never_contains_the_password():
    # A hex-only password: "hunter2" contains non-hex characters ('h', 'u', 't', ...) and
    # could never appear inside a hex-encoded digest regardless of what is actually stored,
    # so it would not catch a bug. "deadbeef" is valid hex, so this assertion can actually fail.
    stored = hash_password("deadbeef")
    assert "deadbeef" not in stored


def test_the_hash_carries_its_parameters_so_they_can_change_later():
    stored = hash_password("x")
    assert stored.startswith("scrypt$")
    assert len(stored.split("$")) == 6


def test_a_malformed_stored_hash_is_rejected_not_crashed():
    for bad in ("", "notahash", "scrypt$1$2", "bcrypt$a$b$c$d$e"):
        assert not verify_password("x", bad)


def test_roles_are_exactly_the_four_the_spec_defines():
    assert set(ROLES) == {"scout", "medical", "head_of_recruitment", "admin"}


def test_every_role_may_assess_both_dimensions():
    """Decision 16: the department is too small to split the dimensions by role.
    The role records WHO entered a band; it does not restrict which band they may enter."""
    for role in ROLES:
        assert can(role, "assess_psychological"), role
        assert can(role, "assess_medical"), role
        assert can(role, "enter_injury"), role


def test_sign_off_is_the_only_gated_assessment_action():
    assert can("head_of_recruitment", "sign_off")
    assert can("admin", "sign_off")
    assert not can("scout", "sign_off")
    assert not can("medical", "sign_off")


def test_only_admin_manages_users():
    assert can("admin", "manage_users")
    for role in ("scout", "medical", "head_of_recruitment"):
        assert not can(role, "manage_users"), role


def test_an_unknown_role_or_action_is_denied_not_crashed():
    assert not can("intern", "sign_off")
    assert not can("admin", "launch_missiles")


def test_a_hash_made_under_older_parameters_still_verifies():
    """The whole point of storing n/r/p alongside the hash: a password hashed years ago
    under weaker parameters still verifies today, without a migration. If verify_password
    silently substituted the current module constants instead of reading the stored ones,
    this would fail even though every other test in this file -- which all hash fresh with
    today's constants -- would keep passing."""
    n, r, p = 2 ** 12, 1, 1  # smallest parameters verify_password accepts
    salt = bytes.fromhex("00" * 16)
    digest = hashlib.scrypt(b"legacy password", salt=salt, n=n, r=r, p=p, dklen=32)
    legacy_stored = f"scrypt${n}${r}${p}${salt.hex()}${digest.hex()}"

    assert verify_password("legacy password", legacy_stored)
    assert not verify_password("wrong password", legacy_stored)
