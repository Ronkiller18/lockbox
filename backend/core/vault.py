"""
backend/core/vault.py

Encrypted vault I/O for LockBox.

On-disk format (binary):
    [4 bytes big-endian uint32 = salt_length][salt_bytes][fernet_token]

Why store the salt in the file?
    The salt's only job is to make the PBKDF2 output unique per vault —
    it is NOT secret. Storing it alongside the ciphertext is the standard
    approach (same as what bcrypt, argon2, etc. do). An attacker who has
    your vault.enc still can't decrypt it without your master password.

Why the length prefix?
    Fernet tokens are base64url and can contain any byte value, so we
    can't use a delimiter. A 4-byte big-endian length prefix is simple,
    unambiguous, and language-agnostic.

Atomic writes:
    We write to vault.enc.tmp, then os.replace() it over vault.enc.
    os.replace() is atomic on POSIX — if the process dies mid-write,
    vault.enc is never corrupted.
"""

import json
import os
import struct
from pathlib import Path

from backend.config import VAULT_PATH
from backend.core.crypto import (
    decrypt,
    derive_key,
    encrypt,
    generate_salt,
    verify_master_password,
    create_verification_hash,
)
from backend.core.models import PasswordEntry, VaultData


# ── Exceptions ────────────────────────────────────────────────────────────────

class VaultNotFoundError(Exception):
    """Raised when vault.enc does not exist and you try to open it."""


class VaultCorruptedError(Exception):
    """Raised when the vault file cannot be parsed (truncated, tampered)."""


class WrongPasswordError(Exception):
    """Raised when the master password fails to decrypt the vault."""


# ── Low-level binary I/O ──────────────────────────────────────────────────────

def _write_vault_file(path: Path, salt: bytes, token: bytes) -> None:
    """
    Serialise [salt_len][salt][fernet_token] and write atomically.

    We write to a .tmp file first, then rename. On Linux, os.replace()
    is a single syscall (rename(2)) — atomic and crash-safe.
    """
    tmp_path = path.with_suffix(".enc.tmp")
    salt_len = struct.pack(">I", len(salt))   # 4 bytes, big-endian uint32

    with open(tmp_path, "wb") as f:
        f.write(salt_len)
        f.write(salt)
        f.write(token)

    os.replace(tmp_path, path)   # atomic rename


def _read_vault_file(path: Path) -> tuple[bytes, bytes]:
    """
    Read vault.enc and return (salt, fernet_token).

    Raises VaultNotFoundError or VaultCorruptedError on bad input.
    """
    if not path.exists():
        raise VaultNotFoundError(
            f"No vault found at {path}. "
            "Run initialize_vault() on first use."
        )

    with open(path, "rb") as f:
        raw = f.read()

    # Need at least 4 bytes for the length prefix
    if len(raw) < 4:
        raise VaultCorruptedError("Vault file is too short to be valid.")

    (salt_len,) = struct.unpack(">I", raw[:4])
    header_end = 4 + salt_len

    if len(raw) < header_end:
        raise VaultCorruptedError(
            f"Vault file claims salt length {salt_len} but file is truncated."
        )

    salt = raw[4:header_end]
    token = raw[header_end:]

    if not salt or not token:
        raise VaultCorruptedError("Vault file has empty salt or empty ciphertext.")

    return salt, token


# ── Public API ────────────────────────────────────────────────────────────────

def initialize_vault(master_password: str, path: Path = VAULT_PATH) -> None:
    """
    Create a brand-new vault on disk.

    Called once on first run. Generates a fresh salt, derives the key,
    encrypts an empty VaultData, and writes to disk.

    Raises FileExistsError if the vault already exists — we refuse to
    silently overwrite an existing vault.
    """
    if path.exists():
        raise FileExistsError(
            f"Vault already exists at {path}. "
            "Delete it manually to start over."
        )

    # Ensure the parent directory exists (e.g. ~/.lockbox/)
    path.parent.mkdir(parents=True, exist_ok=True)

    salt = generate_salt()
    key = derive_key(master_password, salt)

    empty_vault = VaultData()
    plaintext = empty_vault.model_dump_json(indent=2).encode("utf-8")
    token = encrypt(plaintext, key)

    _write_vault_file(path, salt, token)


def load_vault(master_password: str, path: Path = VAULT_PATH) -> VaultData:
    """
    Read and decrypt the vault from disk.

    Returns a VaultData instance ready to query or mutate.
    Raises WrongPasswordError if decryption fails (bad password or tampered file).
    """
    salt, token = _read_vault_file(path)
    key = derive_key(master_password, salt)

    try:
        plaintext = decrypt(token, key)
    except Exception as exc:
        # Fernet raises InvalidToken for bad key or tampered ciphertext —
        # surface it as a domain error so callers don't depend on cryptography internals.
        raise WrongPasswordError(
            "Failed to decrypt vault. Wrong master password or corrupted file."
        ) from exc

    try:
        data = json.loads(plaintext.decode("utf-8"))
        return VaultData(**data)
    except Exception as exc:
        raise VaultCorruptedError(
            "Vault decrypted but JSON is invalid. The file may be corrupted."
        ) from exc


def save_vault(
    vault: VaultData,
    master_password: str,
    path: Path = VAULT_PATH,
) -> None:
    """
    Encrypt and atomically write the vault back to disk.

    We re-derive the key from the *existing* salt (read from disk) so the
    same master password keeps working. The salt never changes after init.
    """
    salt, _ = _read_vault_file(path)
    key = derive_key(master_password, salt)

    plaintext = vault.model_dump_json(indent=2).encode("utf-8")
    token = encrypt(plaintext, key)

    _write_vault_file(path, salt, token)


def add_entry(
    entry: PasswordEntry,
    master_password: str,
    path: Path = VAULT_PATH,
) -> PasswordEntry:
    """
    Load the vault, append a new entry, save, and return the entry with its
    assigned id.

    This is the primary write path: load → mutate → save.
    """
    vault = load_vault(master_password, path)
    vault.entries.append(entry)
    save_vault(vault, master_password, path)
    return entry


def get_all_entries(
    master_password: str,
    path: Path = VAULT_PATH,
) -> list[PasswordEntry]:
    """
    Return all entries from the vault, decrypting once.

    Entries are returned in insertion order (list preserves order).
    """
    vault = load_vault(master_password, path)
    return vault.entries


def delete_entry(
    entry_id: str,
    master_password: str,
    path: Path = VAULT_PATH,
) -> bool:
    """
    Remove the entry with the given UUID from the vault.

    Returns True if deleted, False if no entry with that id existed.
    """
    vault = load_vault(master_password, path)
    original_count = len(vault.entries)
    vault.entries = [e for e in vault.entries if e.id != entry_id]

    if len(vault.entries) == original_count:
        return False  # nothing removed

    save_vault(vault, master_password, path)
    return True


def update_entry(
    updated_entry: PasswordEntry,
    master_password: str,
    path: Path = VAULT_PATH,
) -> bool:
    """
    Replace the vault entry matching updated_entry.id with the new data.

    Calls .touch() to update the timestamp. Returns True if found and
    updated, False if no entry with that id exists.
    """
    vault = load_vault(master_password, path)

    for i, entry in enumerate(vault.entries):
        if entry.id == updated_entry.id:
            updated_entry.touch()
            vault.entries[i] = updated_entry
            save_vault(vault, master_password, path)
            return True

    return False


def vault_exists(path: Path = VAULT_PATH) -> bool:
    """Simple check — does a vault file exist at the expected path?"""
    return path.exists()