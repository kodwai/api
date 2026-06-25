from __future__ import annotations

import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def encrypt_api_key(plaintext_key: str, encryption_key: str) -> tuple[str, str]:
    """Encrypt an API key using AES-256-GCM.

    Args:
        plaintext_key: The raw API key to encrypt.
        encryption_key: Hex-encoded 32-byte encryption key.

    Returns:
        A tuple of (encrypted_hex, iv_hex).
    """
    key_bytes = bytes.fromhex(encryption_key)
    iv = os.urandom(12)  # 96-bit nonce for GCM
    aesgcm = AESGCM(key_bytes)
    ciphertext = aesgcm.encrypt(iv, plaintext_key.encode("utf-8"), None)
    return ciphertext.hex(), iv.hex()


def decrypt_api_key(encrypted_hex: str, iv_hex: str, encryption_key: str) -> str:
    """Decrypt an API key encrypted with AES-256-GCM.

    Args:
        encrypted_hex: Hex-encoded ciphertext (includes GCM auth tag).
        iv_hex: Hex-encoded initialization vector.
        encryption_key: Hex-encoded 32-byte encryption key.

    Returns:
        The original plaintext API key.
    """
    key_bytes = bytes.fromhex(encryption_key)
    iv = bytes.fromhex(iv_hex)
    ciphertext = bytes.fromhex(encrypted_hex)
    aesgcm = AESGCM(key_bytes)
    plaintext = aesgcm.decrypt(iv, ciphertext, None)
    return plaintext.decode("utf-8")
