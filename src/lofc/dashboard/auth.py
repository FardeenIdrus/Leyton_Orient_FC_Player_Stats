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

import datetime
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


# Length is deliberately the ONLY rule. Composition requirements (a digit, a symbol, mixed
# case) measurably push users towards predictable mutations -- Passw0rd! -- and towards
# writing the result down, while a long passphrase is both stronger and easier to recall.
# NIST SP 800-63B says the same. Do not "strengthen" this by adding character classes.
PASSWORD_MIN_LENGTH = 12


def password_problems(password: str) -> list[str]:
    """Every reason `password` is unacceptable. An empty list means it is acceptable.

    Returns a list rather than a bool so a caller can show the user all of the problems at
    once instead of making them fix one, resubmit, and discover the next.
    """
    problems: list[str] = []
    if len(password) < PASSWORD_MIN_LENGTH:
        problems.append(f"must be at least {PASSWORD_MIN_LENGTH} characters")
    return problems


# scrypt already makes each guess cost ~50ms, which blunts online guessing but does not stop
# it: 5 attempts/second sustained overnight is still ~150k guesses. These bound it. The state
# lives on the users row rather than in process memory so it survives a Streamlit restart and
# is shared if the app is ever run with more than one worker.
MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15


def lockout_state(failed_logins: int, locked_until: "datetime.datetime | None",
                  now: "datetime.datetime") -> tuple[bool, int]:
    """Whether this account is currently locked, and for how many more seconds.

    `failed_logins` is accepted but deliberately not consulted: `locked_until` is the single
    source of truth for whether a lock is active, so a stale counter left behind by a partial
    write can never lock an account on its own.
    """
    if locked_until is None or locked_until <= now:
        return False, 0
    return True, int((locked_until - now).total_seconds())


def next_failure_state(failed_logins: int,
                       now: "datetime.datetime") -> tuple[int, "datetime.datetime | None"]:
    """The (count, locked_until) to store after one more failed attempt."""
    count = failed_logins + 1
    if count >= MAX_FAILED_LOGINS:
        return count, now + datetime.timedelta(minutes=LOCKOUT_MINUTES)
    return count, None


# 12 hours: long enough that nobody is re-authenticating during a working day, short enough
# that a browser left open on a shared training-ground machine does not stay logged in all week.
SESSION_TTL_MINUTES = 720


def session_expired(logged_in_at: "datetime.datetime | None",
                    now: "datetime.datetime") -> bool:
    """True if a session started at `logged_in_at` should no longer be trusted.

    A missing timestamp expires: an absent value means the session was never properly
    established, and defaulting that to 'still valid' would be the wrong direction to fail.
    """
    if logged_in_at is None:
        return True
    return now - logged_in_at > datetime.timedelta(minutes=SESSION_TTL_MINUTES)
