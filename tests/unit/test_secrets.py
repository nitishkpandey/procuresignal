"""Tests for the secret resolver.

.env does not survive contact with more than one host. A concrete cloud backend cannot
be chosen before hosting is, so what lands now is the seam plus Docker secrets, which
work anywhere compose does.
"""

import pytest
from procuresignal.config.secrets import (
    DOCKER_SECRETS_DIR,
    MissingSecretError,
    get_secret,
    require_secret,
)


def test_environment_variables_still_work(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOME_TOKEN", "from-env")

    assert get_secret("SOME_TOKEN") == "from-env"


def test_a_docker_secret_file_is_read(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """The _FILE convention compose and swarm already use."""
    secret = tmp_path / "token"
    secret.write_text("from-file\n")
    monkeypatch.setenv("SOME_TOKEN_FILE", str(secret))
    monkeypatch.delenv("SOME_TOKEN", raising=False)

    assert get_secret("SOME_TOKEN") == "from-file"


def test_the_file_wins_over_the_variable(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """A mounted secret is the more deliberate of the two, and the one that is not
    visible in `docker inspect`."""
    secret = tmp_path / "token"
    secret.write_text("from-file")
    monkeypatch.setenv("SOME_TOKEN", "from-env")
    monkeypatch.setenv("SOME_TOKEN_FILE", str(secret))

    assert get_secret("SOME_TOKEN") == "from-file"


def test_the_conventional_mount_point_is_searched(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr("procuresignal.config.secrets.DOCKER_SECRETS_DIR", tmp_path)
    (tmp_path / "some_token").write_text("from-mount")
    monkeypatch.delenv("SOME_TOKEN", raising=False)

    assert get_secret("SOME_TOKEN") == "from-mount"


def test_trailing_whitespace_is_stripped(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """A file written by an editor gains a newline, and a token with a newline fails
    authentication in a way that is genuinely hard to see."""
    secret = tmp_path / "token"
    secret.write_text("  value\n\n")
    monkeypatch.setenv("SOME_TOKEN_FILE", str(secret))

    assert get_secret("SOME_TOKEN") == "value"


def test_a_missing_secret_returns_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ABSENT", raising=False)

    assert get_secret("ABSENT", default="fallback") == "fallback"
    assert get_secret("ABSENT") is None


def test_requiring_a_missing_secret_names_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ABSENT", raising=False)

    with pytest.raises(MissingSecretError, match="ABSENT"):
        require_secret("ABSENT")


def test_an_unreadable_file_does_not_crash(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("SOME_TOKEN_FILE", str(tmp_path / "does-not-exist"))
    monkeypatch.setenv("SOME_TOKEN", "from-env")

    assert get_secret("SOME_TOKEN") == "from-env"


def test_the_conventional_directory_is_the_docker_one() -> None:
    assert str(DOCKER_SECRETS_DIR) == "/run/secrets"


def test_every_real_secret_consumer_uses_the_resolver() -> None:
    """The resolver existed with no callers, so _FILE and /run/secrets did nothing."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    consumers = {
        "shared/procuresignal/auth/tokens.py": "AUTH_SECRET_KEY",
        "shared/procuresignal/enrichment/openai_client.py": "OPENAI_API_KEY",
    }

    for relative, name in consumers.items():
        source = (root / relative).read_text()
        assert f'os.getenv("{name}")' not in source, f"{relative} still bypasses the resolver"
        assert "get_secret" in source, f"{relative} does not use the resolver"


def test_the_auth_secret_can_come_from_a_file(monkeypatch, tmp_path) -> None:
    """End to end through the code that actually signs tokens."""
    from procuresignal.auth.tokens import AccessClaims, encode_access_token

    secret = tmp_path / "auth"
    secret.write_text("a-secret-key-long-enough-for-hs256\n")
    monkeypatch.delenv("AUTH_SECRET_KEY", raising=False)
    monkeypatch.setenv("AUTH_SECRET_KEY_FILE", str(secret))

    token = encode_access_token(
        AccessClaims(subject="u", organization="o", role="member", token_version=0, jti="j")
    )
    assert token
