"""Authentication and role permissions for the scout assessment system.

Passwords are hashed with hashlib.scrypt from the standard library -- deliberately no new
dependency. The stored form carries its own parameters:

    scrypt$<n>$<r>$<p>$<salt_hex>$<hash_hex>

so that a hash made under old parameters still verifies once the constants below change:
verify_password reads n/r/p from the stored string itself, never from the current constants.
`needs_rehash` tells a caller (a future login page) when a hash it just verified was made
under parameters other than today's, so it can be re-hashed and re-saved on that login.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

# scrypt cost for freshly hashed passwords. n must be a power of two.
_N, _R, _P = 2 ** 14, 8, 1
_DKLEN = 32

# Passed explicitly to hashlib.scrypt (both calls below) instead of relying on OpenSSL's
# default ~32 MiB maxmem, which would otherwise silently reject n=2**16 -- the top of the
# range below -- and cap any future rise of _N at the current value. 128 MiB comfortably
# covers n=2**16 at r=8 (~64 MiB), leaving 4x headroom over today's n=2**14 to raise _N into.
_MAXMEM = 128 * 1024 * 1024

# Bounds enforced on n/r/p READ BACK from a stored hash, before they are used to spend
# CPU/memory in hashlib.scrypt. Without this, a stored row with e.g. p=16000 turns one login
# attempt into ~13 minutes of pinned CPU -- raising maxmem above (needed so _N can grow) would
# otherwise remove the only thing currently limiting how large a stored p can be. The range
# for n brackets the constants above with the same headroom to raise _N later.
_N_MIN, _N_MAX = 2 ** 12, 2 ** 16
_R_MAX = 8
_P_MAX = 2


def _valid_cost(n: int, r: int, p: int) -> bool:
    is_power_of_two = n > 0 and (n & (n - 1)) == 0
    return is_power_of_two and _N_MIN <= n <= _N_MAX and 1 <= r <= _R_MAX and 1 <= p <= _P_MAX


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
                            n=_N, r=_R, p=_P, dklen=_DKLEN, maxmem=_MAXMEM)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """True if `password` produced `stored`. A malformed, unrecognised, or out-of-bounds
    stored value returns False rather than raising or spending unbounded CPU/memory -- a
    corrupt or tampered row must not crash a login page or become a denial-of-service lever."""
    try:
        scheme, n_s, r_s, p_s, salt_hex, digest_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        n, r, p = int(n_s), int(r_s), int(p_s)
        if not _valid_cost(n, r, p):
            return False
        expected = bytes.fromhex(digest_hex)
        if len(expected) != _DKLEN:
            return False
        salt = bytes.fromhex(salt_hex)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                                n=n, r=r, p=p, dklen=_DKLEN, maxmem=_MAXMEM)
    except (ValueError, TypeError, AttributeError):
        return False
    return hmac.compare_digest(actual, expected)


def needs_rehash(stored: str) -> bool:
    """True if `stored` was hashed under parameters other than today's _N/_R/_P (or is not a
    well-formed scrypt hash at all). Call this right after a successful verify_password; if
    True, hash the now-known-correct plaintext again with hash_password and save that instead."""
    try:
        scheme, n_s, r_s, p_s, _salt_hex, digest_hex = stored.split("$")
        if scheme != "scrypt":
            return True
        current = (int(n_s), int(r_s), int(p_s), len(bytes.fromhex(digest_hex)))
        return current != (_N, _R, _P, _DKLEN)
    except (ValueError, TypeError, AttributeError):
        return True


def can(role: str, action: str) -> bool:
    """Whether `role` may perform `action`. Unknown roles and actions are denied."""
    return action in _PERMISSIONS.get(role, frozenset())
