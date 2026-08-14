"""Authentication and role permissions for the scout assessment system.

Passwords are hashed with hashlib.scrypt from the standard library -- deliberately no new
dependency. The stored form carries its own parameters:

    scrypt$<n>$<r>$<p>$<salt_hex>$<hash_hex>

so the cost can be raised later without invalidating existing users: verify with the
parameters in the stored string, and re-hash on the next successful login if they are stale.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

# scrypt cost. n must be a power of two. These are the interactive-login parameters from
# the Python docs; raising n is the way to make hashing more expensive later.
_N, _R, _P = 2 ** 14, 8, 1
_DKLEN = 32

ROLES: tuple[str, ...] = ("scout", "medical", "head_of_recruitment", "admin")

# Decision 16: EVERY role may assess both dimensions. The department is small enough that
# splitting them by role would block routine work, so the role is a RECORD of who entered a
# band -- displayed wherever the assessment appears -- rather than a restriction.
# Sign-off is the only gated assessment action. To tighten this later, narrow the sets below:
# no migration and no data change is needed, because the roles already recorded stay valid.
_ASSESSING = {"assess_psychological", "assess_medical", "enter_injury"}

_PERMISSIONS: dict[str, frozenset[str]] = {
    "scout": frozenset(_ASSESSING),
    "medical": frozenset(_ASSESSING),
    "head_of_recruitment": frozenset(_ASSESSING | {"sign_off"}),
    "admin": frozenset(_ASSESSING | {"sign_off", "manage_users"}),
}


def hash_password(password: str) -> str:
    """Hash a password for storage. A fresh random salt per call, so two users sharing a
    password do not share a hash."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                            n=_N, r=_R, p=_P, dklen=_DKLEN)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """True if `password` produced `stored`. A malformed or unrecognised stored value
    returns False rather than raising -- a corrupt row must not crash a login page."""
    try:
        scheme, n, r, p, salt_hex, digest_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
                                n=int(n), r=int(r), p=int(p), dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def can(role: str, action: str) -> bool:
    """Whether `role` may perform `action`. Unknown roles and actions are denied."""
    return action in _PERMISSIONS.get(role, frozenset())
