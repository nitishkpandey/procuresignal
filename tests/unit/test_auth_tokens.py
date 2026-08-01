"""Tests for access-token encoding and refresh-token minting."""

import base64
import json
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from shared.procuresignal.auth.tokens import (
    AccessClaims,
    decode_access_token,
    encode_access_token,
    hash_refresh_token,
    mint_refresh_token,
    refresh_token_expiry,
)

SECRET = "test-secret-key-that-is-long-enough-32"
CLAIMS = AccessClaims(
    subject="user-public-id",
    organization="org-public-id",
    role="member",
    token_version=3,
    jti="token-id-1",
)


@pytest.fixture(autouse=True)
def _auth_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_SECRET_KEY", SECRET)


def test_access_token_round_trips() -> None:
    assert decode_access_token(encode_access_token(CLAIMS)) == CLAIMS


def test_rejects_token_signed_with_a_different_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    token = encode_access_token(CLAIMS)
    monkeypatch.setenv("AUTH_SECRET_KEY", "a-completely-different-secret-key-32ch")

    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token)


def test_rejects_unsigned_alg_none_token() -> None:
    """A token claiming alg=none must never be accepted, however it was assembled."""

    def segment(payload: dict) -> str:
        raw = json.dumps(payload, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    forged = "{}.{}.".format(
        segment({"alg": "none", "typ": "JWT"}),
        segment({"sub": "attacker", "org": "o", "role": "owner", "tv": 0, "jti": "x"}),
    )

    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(forged)


def test_rejects_expired_token() -> None:
    stale = datetime.now(timezone.utc) - timedelta(hours=2)

    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(encode_access_token(CLAIMS, now=stale))


def test_rejects_token_missing_required_claims() -> None:
    partial = jwt.encode(
        {"sub": "u", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        SECRET,
        algorithm="HS256",
    )

    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(partial)


def test_access_token_carries_the_token_version() -> None:
    """Revocation depends on this claim surviving the round trip."""
    payload = jwt.decode(encode_access_token(CLAIMS), SECRET, algorithms=["HS256"])
    assert payload["tv"] == 3


def test_refresh_token_is_stored_only_as_a_hash() -> None:
    plaintext, digest = mint_refresh_token()

    assert len(plaintext) >= 43, "expected at least 256 bits of entropy"
    assert digest == hash_refresh_token(plaintext)
    assert plaintext not in digest
    assert len(digest) == 64


def test_refresh_tokens_are_unique() -> None:
    assert len({mint_refresh_token()[0] for _ in range(200)}) == 200


def test_refresh_expiry_is_in_the_future() -> None:
    issued = datetime(2026, 8, 1, 12, 0)
    assert refresh_token_expiry(now=issued) > issued


def test_missing_secret_is_refused() -> None:
    with pytest.MonkeyPatch.context() as patch:
        patch.delenv("AUTH_SECRET_KEY", raising=False)
        with pytest.raises(RuntimeError, match="AUTH_SECRET_KEY"):
            encode_access_token(CLAIMS)


def test_short_secret_is_refused() -> None:
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("AUTH_SECRET_KEY", "too-short")
        with pytest.raises(RuntimeError, match="AUTH_SECRET_KEY"):
            encode_access_token(CLAIMS)
