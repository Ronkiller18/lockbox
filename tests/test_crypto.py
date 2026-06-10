"""
tests/test_crypto.py

Run from the lockbox/ root with:
    python -m pytest tests/ -v
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import pytest
from cryptography.fernet import InvalidToken
from core.crypto import (
    generate_salt,
    derive_key,
    encrypt,
    decrypt,
    create_verification_hash,
    verify_master_password,
)


def test_salt_uniqueness():
    """Every salt must be different — if they match, something is very wrong."""
    assert generate_salt() != generate_salt()

def test_salt_length():
    """Salt must be exactly 32 bytes."""
    assert len(generate_salt()) == 32

def test_key_derivation_is_deterministic():
    """Same password + same salt must always produce the same key."""
    salt = generate_salt()
    assert derive_key("Password1!", salt) == derive_key("Password1!", salt)

def test_different_salts_produce_different_keys():
    """Same password, different salt → completely different key."""
    pw = "Password1!"
    assert derive_key(pw, generate_salt()) != derive_key(pw, generate_salt())

def test_encrypt_decrypt_roundtrip():
    """Decrypt(Encrypt(data)) must equal the original data."""
    key = derive_key("Password1!", generate_salt())
    data = b"my secret password: hunter2"
    assert decrypt(encrypt(data, key), key) == data

def test_wrong_password_cannot_decrypt():
    """Decrypting with the wrong key must raise — never silently corrupt."""
    salt = generate_salt()
    right_key = derive_key("CorrectPassword", salt)
    wrong_key  = derive_key("WrongPassword",  salt)
    token = encrypt(b"secret", right_key)
    with pytest.raises(InvalidToken):
        decrypt(token, wrong_key)

def test_tampered_vault_is_rejected():
    """Flipping even one byte must make decryption fail — HMAC catches it."""
    key   = derive_key("Password1!", generate_salt())
    token = bytearray(encrypt(b"secret data", key))
    token[10] ^= 0xFF                          # flip bits in the middle
    with pytest.raises(InvalidToken):
        decrypt(bytes(token), key)

def test_verify_correct_password():
    """Correct password must pass verification."""
    salt = generate_salt()
    h    = create_verification_hash("MyPassword", salt)
    assert verify_master_password("MyPassword", salt, h) is True

def test_verify_wrong_password():
    """Wrong password must fail verification."""
    salt = generate_salt()
    h    = create_verification_hash("MyPassword", salt)
    assert verify_master_password("WrongPassword", salt, h) is False