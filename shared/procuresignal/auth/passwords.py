"""Argon2id password hashing."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()

# Verified against when an account has no password, so "no such password" costs the same
# time as "wrong password". Without it, response timing tells an attacker which accounts
# are real. It is never a valid credential: see the `bool(stored_hash)` return below.
_DUMMY_PASSWORD = "procuresignal-timing-equalizer"
_DUMMY_HASH = _hasher.hash(_DUMMY_PASSWORD)


def hash_password(password: str) -> str:
    """Hash a password with argon2id and a fresh random salt."""

    return _hasher.hash(password)


def verify_password(password: str, stored_hash: str | None) -> bool:
    """Check a password, taking comparable time whether or not a hash exists.

    Placeholder users created by the identity backfill have no hash. They must never
    authenticate, but they also must not be distinguishable by how fast we say no.
    """

    try:
        _hasher.verify(stored_hash or _DUMMY_HASH, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    # Reached only when the comparison succeeded. If there was no stored hash, the match
    # was against the dummy, which is not a credential.
    return bool(stored_hash)
