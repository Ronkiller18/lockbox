"""
backend/core/crypto.py

Everything cryptographic in LockBox lives here.
Nothing else in the project touches raw crypto — only this file.

Rule: this module never reads from disk, never writes to disk.
It only takes bytes in and returns bytes out. Clean separation.
"""

import os
import hmac
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

from config import PBKDF2_ITER, SALT_SIZE, KEY_SIZE


# ── Salt ──────────────────────────────────────────────────────────────────────

def generate_salt() -> bytes:
    """
    Generate a cryptographically secure random salt.
    os.urandom() pulls from the OS entropy pool — never use random.randbytes()
    for security-sensitive code, it's not cryptographically secure.

    Called exactly once: when the vault is first created.
    Stored in plain text in vault.enc header — that's correct behaviour.
    """
    return os.urandom(SALT_SIZE)


# ── Key Derivation ────────────────────────────────────────────────────────────

def derive_key(master_password: str, salt: bytes) -> bytes:
    """
    Turn a human password into a 256-bit AES encryption key.

    Why not just SHA-256 the password? Too fast. A GPU can compute
    billions of SHA-256 hashes per second. PBKDF2 with 600k iterations
    stretches that to ~1 guess per 100ms on modern hardware.

    Returns: base64-encoded 32 bytes (Fernet's required format)
    The returned key is NEVER stored. Derived fresh on every unlock.
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KEY_SIZE,
        salt=salt,
        iterations=PBKDF2_ITER,
    )
    raw_key = kdf.derive(master_password.encode("utf-8"))
    return base64.urlsafe_b64encode(raw_key)


# ── Encrypt / Decrypt ─────────────────────────────────────────────────────────

def encrypt(data: bytes, key: bytes) -> bytes:
    """
    Encrypt bytes using AES-256-CBC + HMAC-SHA256 (Fernet standard).

    Fernet automatically:
    - Generates a random IV (initialization vector) per encryption
    - Appends an HMAC signature to detect tampering
    - Includes a timestamp (we ignore it but it's there)

    This means encrypting the same data twice gives different ciphertext.
    That's intentional and good — no pattern leakage.
    """
    return Fernet(key).encrypt(data)


def decrypt(token: bytes, key: bytes) -> bytes:
    """
    Decrypt a Fernet token back to the original bytes.

    Raises InvalidToken if:
    - The key is wrong (wrong master password)
    - The data was tampered with (HMAC verification fails)
    - The token is malformed

    We treat all three the same way: wrong password or corrupted vault.
    Never silently return garbage — fail loudly.
    """
    return Fernet(key).decrypt(token)


# ── Password Verification ─────────────────────────────────────────────────────

def create_verification_hash(master_password: str, salt: bytes) -> str:
    """
    Create a hash to verify the master password at login
    without storing the password itself.

    Why not just try decrypting the vault to verify?
    We could — but that's slow and wastes CPU on wrong passwords.
    This is a fast pre-check before the expensive vault decrypt.

    Uses a domain-separated salt (salt + b"lockbox-verify") so this hash
    is mathematically unrelated to the encryption key. Leaking this
    hash gives an attacker zero advantage against the encrypted vault.
    """
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        master_password.encode("utf-8"),
        salt + b"lockbox-verify",
        iterations=100_000,
    )
    return base64.urlsafe_b64encode(dk).decode("utf-8")


def verify_master_password(
    master_password: str,
    salt: bytes,
    stored_hash: str
) -> bool:
    """
    Verify the master password using constant-time comparison.

    Why constant-time? If we used == comparison, Python returns False
    the moment it finds the first mismatched character. An attacker
    measuring response times could guess the hash one character at a time.
    hmac.compare_digest() always takes the same time regardless of
    where the mismatch is.
    """
    candidate = create_verification_hash(master_password, salt)
    return hmac.compare_digest(
        candidate.encode("utf-8"),
        stored_hash.encode("utf-8")
    )