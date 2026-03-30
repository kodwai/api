"""Security module tests."""
from app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
    verify_token,
)


def test_hash_and_verify_password():
    hashed = hash_password("mypassword")
    assert hashed != "mypassword"
    assert verify_password("mypassword", hashed) is True
    assert verify_password("wrongpassword", hashed) is False


def test_hash_is_unique():
    h1 = hash_password("same")
    h2 = hash_password("same")
    assert h1 != h2  # Different salts


def test_create_and_verify_token():
    token = create_access_token({"sub": "user123"})
    payload = verify_token(token)
    assert payload is not None
    assert payload["sub"] == "user123"
    assert "exp" in payload


def test_verify_invalid_token():
    assert verify_token("garbage.token.here") is None


def test_verify_tampered_token():
    token = create_access_token({"sub": "user123"})
    tampered = token[:-5] + "XXXXX"
    assert verify_token(tampered) is None
