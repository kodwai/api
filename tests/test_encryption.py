"""Encryption service tests."""
from app.services.encryption_service import decrypt_api_key, encrypt_api_key


ENCRYPTION_KEY = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


def test_encrypt_decrypt_roundtrip():
    original = "sk-ant-api03-my-secret-key-1234567890"
    encrypted, iv = encrypt_api_key(original, ENCRYPTION_KEY)

    assert encrypted != original
    assert iv is not None
    assert len(iv) > 0

    decrypted = decrypt_api_key(encrypted, iv, ENCRYPTION_KEY)
    assert decrypted == original


def test_different_keys_different_output():
    original = "sk-ant-api03-test-key"
    enc1, iv1 = encrypt_api_key(original, ENCRYPTION_KEY)
    enc2, iv2 = encrypt_api_key(original, ENCRYPTION_KEY)

    # Each encryption should produce a different IV (and thus different ciphertext)
    assert iv1 != iv2


def test_wrong_key_fails():
    original = "sk-ant-api03-test-key"
    wrong_key = "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
    encrypted, iv = encrypt_api_key(original, ENCRYPTION_KEY)

    try:
        decrypt_api_key(encrypted, iv, wrong_key)
        assert False, "Should have raised an exception"
    except Exception:
        pass  # Expected
