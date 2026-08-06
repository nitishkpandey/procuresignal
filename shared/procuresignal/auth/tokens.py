"""Access-token encoding and refresh-token minting."""

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256

import jwt

from procuresignal.config.secrets import get_secret

_ALGORITHM = "HS256"
_MINIMUM_SECRET_LENGTH = 32

ACCESS_TOKEN_TTL = timedelta(minutes=15)
REFRESH_TOKEN_TTL = timedelta(days=30)

_REQUIRED_CLAIMS = ("sub", "org", "role", "tv", "jti", "exp")


@dataclass(frozen=True)
class AccessClaims:
    """The identity an access token asserts."""

    subject: str
    organization: str
    role: str
    token_version: int
    jti: str


def _secret() -> str:
    # Through the resolver, so AUTH_SECRET_KEY_FILE and /run/secrets work. Reading
    # the environment directly meant the resolver existed and did nothing.
    secret = get_secret("AUTH_SECRET_KEY")
    if not secret or len(secret) < _MINIMUM_SECRET_LENGTH:
        raise RuntimeError(
            f"AUTH_SECRET_KEY must be set to at least {_MINIMUM_SECRET_LENGTH} characters"
        )
    return secret


def require_auth_secret() -> None:
    """Raise unless the signing secret is usable.

    One definition of "valid secret", shared by the startup check and every token
    operation, so the two cannot disagree.
    """

    _secret()


def encode_access_token(claims: AccessClaims, *, now: datetime | None = None) -> str:
    """Sign a short-lived access token."""

    issued = now or datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": claims.subject,
            "org": claims.organization,
            "role": claims.role,
            "tv": claims.token_version,
            "jti": claims.jti,
            "iat": issued,
            "exp": issued + ACCESS_TOKEN_TTL,
        },
        _secret(),
        algorithm=_ALGORITHM,
    )


def decode_access_token(token: str) -> AccessClaims:
    """Verify and decode an access token.

    Raises `jwt.InvalidTokenError` (or a subclass) for anything untrustworthy.
    """

    payload = jwt.decode(
        token,
        _secret(),
        # Pinned. Honouring the token's own `alg` header is the algorithm-confusion attack.
        algorithms=[_ALGORITHM],
        options={"require": list(_REQUIRED_CLAIMS)},
    )
    return AccessClaims(
        subject=payload["sub"],
        organization=payload["org"],
        role=payload["role"],
        token_version=int(payload["tv"]),
        jti=payload["jti"],
    )


def hash_refresh_token(plaintext: str) -> str:
    """Hash a refresh token for storage.

    A plain SHA-256 is right here, unlike for passwords: the input is 256 bits of
    randomness we generated, so there is nothing to brute-force and no salt to add.
    """

    return sha256(plaintext.encode("utf-8")).hexdigest()


def mint_refresh_token() -> tuple[str, str]:
    """Return `(plaintext, hash)`. Only the hash is ever persisted."""

    plaintext = secrets.token_urlsafe(32)
    return plaintext, hash_refresh_token(plaintext)


def refresh_token_expiry(*, now: datetime | None = None) -> datetime:
    """When a refresh token minted now should stop working."""

    return (now or datetime.utcnow()) + REFRESH_TOKEN_TTL
