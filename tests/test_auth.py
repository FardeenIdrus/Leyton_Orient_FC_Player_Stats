"""Password hashing and role permissions. No database, no network."""

import pytest

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
    stored = hash_password("hunter2")
    assert "hunter2" not in stored


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
