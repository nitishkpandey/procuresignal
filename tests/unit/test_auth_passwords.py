"""Tests for password hashing."""

from procuresignal.auth.passwords import hash_password, verify_password


def test_hash_is_argon2id_and_independently_salted() -> None:
    first = hash_password("correct horse battery staple")
    second = hash_password("correct horse battery staple")

    assert first.startswith("$argon2id$")
    assert first != second, "identical passwords must not produce identical hashes"


def test_correct_password_verifies_and_wrong_one_does_not() -> None:
    stored = hash_password("correct horse battery staple")

    assert verify_password("correct horse battery staple", stored) is True
    assert verify_password("Correct Horse Battery Staple", stored) is False
    assert verify_password("", stored) is False


def test_absent_password_never_verifies() -> None:
    """Placeholder users carry no password hash and must not be loggable-in."""
    assert verify_password("anything", None) is False
    assert verify_password("anything", "") is False


def test_dummy_hash_value_itself_does_not_authenticate_a_passwordless_user() -> None:
    """The timing equalizer must not become a backdoor password."""
    from procuresignal.auth.passwords import _DUMMY_PASSWORD

    assert verify_password(_DUMMY_PASSWORD, None) is False


def test_malformed_stored_hash_is_rejected_rather_than_raising() -> None:
    assert verify_password("anything", "not-a-real-argon2-hash") is False


def test_plaintext_never_appears_in_the_hash() -> None:
    secret = "unlikely-substring-9f2a"
    assert secret not in hash_password(secret)
