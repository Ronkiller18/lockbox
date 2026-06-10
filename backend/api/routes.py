"""
backend/api/routes.py

All HTTP endpoints for LockBox.

Session design:
    After POST /api/unlock succeeds, the derived AES key is stored in the
    module-level `_session` dict. Every subsequent request reads from there.
    No key ever leaves the server. The frontend only ever sends the master
    password once (at unlock time).

    On server restart the key is wiped — user must unlock again. Correct.

Endpoints:
    POST   /api/init          — first-run: create vault
    POST   /api/unlock        — derive key, store in session
    POST   /api/lock          — clear session key
    GET    /api/status        — is vault initialised? is session unlocked?
    GET    /api/entries       — list all entries (requires unlock)
    POST   /api/entries       — add entry (requires unlock)
    PUT    /api/entries/{id}  — update entry (requires unlock)
    DELETE /api/entries/{id}  — delete entry (requires unlock)
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Optional

from backend.config import VAULT_PATH
from backend.core.crypto import derive_key
from backend.core.models import PasswordEntry, VaultData
from backend.core.vault import (
    initialize_vault,
    load_vault,
    save_vault,
    add_entry,
    get_all_entries,
    delete_entry,
    update_entry,
    vault_exists,
    VaultNotFoundError,
    VaultCorruptedError,
    WrongPasswordError,
)

router = APIRouter()

# ── In-memory session ─────────────────────────────────────────────────────────
# Stores the derived key after a successful unlock.
# Dict so we can extend to multi-user later without changing the interface.
_session: dict[str, bytes] = {}
SESSION_KEY = "key"


def _get_session_key() -> bytes:
    """Return the current session key or raise 401."""
    key = _session.get(SESSION_KEY)
    if key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Vault is locked. POST /api/unlock first.",
        )
    return key


# ── Request / Response models ─────────────────────────────────────────────────

class PasswordRequest(BaseModel):
    master_password: str


class EntryCreate(BaseModel):
    title: str
    username: Optional[str] = None
    password: str
    url: Optional[str] = None
    notes: Optional[str] = None


class EntryUpdate(BaseModel):
    title: str
    username: Optional[str] = None
    password: str
    url: Optional[str] = None
    notes: Optional[str] = None


class StatusResponse(BaseModel):
    vault_exists: bool
    unlocked: bool


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/status", response_model=StatusResponse)
def get_status():
    """
    Returns whether the vault file exists and whether it's currently unlocked.
    The frontend uses this on page load to decide which screen to show:
      - no vault    → show Setup screen
      - vault + locked   → show Unlock screen
      - vault + unlocked → show Entries screen
    """
    return StatusResponse(
        vault_exists=vault_exists(VAULT_PATH),
        unlocked=SESSION_KEY in _session,
    )


@router.post("/init", status_code=status.HTTP_201_CREATED)
def init_vault(body: PasswordRequest):
    """
    First-run: create a new encrypted vault with the given master password.
    Returns 409 if a vault already exists.
    """
    if vault_exists(VAULT_PATH):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Vault already exists. Delete vault.enc to start over.",
        )
    try:
        initialize_vault(body.master_password, VAULT_PATH)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"message": "Vault created successfully."}


@router.post("/unlock")
def unlock_vault(body: PasswordRequest):
    """
    Derive the AES key from the master password and store it in the session.
    Returns 401 if the password is wrong.

    We call load_vault() here — it attempts decryption, which proves the
    password is correct before we cache the key.
    """
    try:
        # load_vault decrypts; if it succeeds the password is correct
        vault = load_vault(body.master_password, VAULT_PATH)
    except WrongPasswordError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Wrong master password.",
        )
    except VaultNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No vault found. POST /api/init first.",
        )
    except VaultCorruptedError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Re-read the salt and derive the key for caching
    # (load_vault already did this internally — we redo it so we have the key)
    from backend.core.vault import _read_vault_file
    salt, _ = _read_vault_file(VAULT_PATH)
    _session[SESSION_KEY] = derive_key(body.master_password, salt)

    return {"message": "Vault unlocked.", "entry_count": len(vault.entries)}


@router.post("/lock")
def lock_vault():
    """Clear the session key. Vault returns to locked state."""
    _session.pop(SESSION_KEY, None)
    return {"message": "Vault locked."}


@router.get("/entries")
def list_entries():
    """Return all vault entries. Requires unlock."""
    _get_session_key()   # 401 if locked

    try:
        vault = load_vault_with_key()
        return {"entries": [e.model_dump() for e in vault.entries]}
    except VaultCorruptedError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/entries", status_code=status.HTTP_201_CREATED)
def create_entry(body: EntryCreate):
    """Add a new entry to the vault. Requires unlock."""
    _get_session_key()

    entry = PasswordEntry(
        title=body.title,
        username=body.username,
        password=body.password,
        url=body.url,
        notes=body.notes,
    )

    try:
        saved = _add_entry_with_key(entry)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"entry": saved.model_dump()}


@router.put("/entries/{entry_id}")
def edit_entry(entry_id: str, body: EntryUpdate):
    """Update an existing entry by id. Requires unlock."""
    _get_session_key()

    updated = PasswordEntry(
        title=body.title,
        username=body.username,
        password=body.password,
        url=body.url,
        notes=body.notes,
    )
    # Preserve the original id
    updated.id = entry_id

    found = _update_entry_with_key(updated)
    if not found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No entry with id {entry_id}.",
        )

    return {"entry": updated.model_dump()}


@router.delete("/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_entry(entry_id: str):
    """Delete an entry by id. Requires unlock."""
    _get_session_key()

    found = _delete_entry_with_key(entry_id)
    if not found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No entry with id {entry_id}.",
        )


# ── Internal helpers (use cached key, skip re-deriving) ───────────────────────
# These bypass the master-password parameter in vault.py by using the
# cached key directly through a thin wrapper. This is the performance
# win — PBKDF2 runs once at unlock, not on every request.

from backend.core.crypto import encrypt, decrypt
from backend.core.vault import _read_vault_file, _write_vault_file
import json


def _load_vault_raw() -> tuple[bytes, VaultData]:
    """Read vault using the cached session key. Returns (salt, VaultData)."""
    key = _get_session_key()
    salt, token = _read_vault_file(VAULT_PATH)
    plaintext = decrypt(token, key)
    data = json.loads(plaintext.decode("utf-8"))
    return salt, VaultData(**data)


def load_vault_with_key() -> VaultData:
    _, vault = _load_vault_raw()
    return vault


def _save_vault_with_key(vault: VaultData) -> None:
    key = _get_session_key()
    salt, _ = _read_vault_file(VAULT_PATH)
    plaintext = vault.model_dump_json(indent=2).encode("utf-8")
    token = encrypt(plaintext, key)
    _write_vault_file(VAULT_PATH, salt, token)


def _add_entry_with_key(entry: PasswordEntry) -> PasswordEntry:
    vault = load_vault_with_key()
    vault.entries.append(entry)
    _save_vault_with_key(vault)
    return entry


def _delete_entry_with_key(entry_id: str) -> bool:
    vault = load_vault_with_key()
    original = len(vault.entries)
    vault.entries = [e for e in vault.entries if e.id != entry_id]
    if len(vault.entries) == original:
        return False
    _save_vault_with_key(vault)
    return True


def _update_entry_with_key(updated: PasswordEntry) -> bool:
    vault = load_vault_with_key()
    for i, entry in enumerate(vault.entries):
        if entry.id == updated.id:
            updated.touch()
            vault.entries[i] = updated
            _save_vault_with_key(vault)
            return True
    return False