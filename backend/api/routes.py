"""
backend/api/routes.py — updated with tags support
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

_session: dict[str, bytes] = {}
SESSION_KEY = "key"


def _get_session_key() -> bytes:
    key = _session.get(SESSION_KEY)
    if key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Vault is locked. POST /api/unlock first.",
        )
    return key


# ── Request / Response models ─────────────────────────────────────────────

class PasswordRequest(BaseModel):
    master_password: str


class EntryCreate(BaseModel):
    title: str
    username: Optional[str] = None
    password: str
    url: Optional[str] = None
    notes: Optional[str] = None
    tags: list[str] = []


class EntryUpdate(BaseModel):
    title: str
    username: Optional[str] = None
    password: str
    url: Optional[str] = None
    notes: Optional[str] = None
    tags: list[str] = []


class StatusResponse(BaseModel):
    vault_exists: bool
    unlocked: bool


# ── Endpoints ─────────────────────────────────────────────────────────────

@router.get("/status", response_model=StatusResponse)
def get_status():
    return StatusResponse(
        vault_exists=vault_exists(VAULT_PATH),
        unlocked=SESSION_KEY in _session,
    )


@router.post("/init", status_code=status.HTTP_201_CREATED)
def init_vault(body: PasswordRequest):
    if vault_exists(VAULT_PATH):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Vault already exists.")
    try:
        initialize_vault(body.master_password, VAULT_PATH)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"message": "Vault created successfully."}


@router.post("/unlock")
def unlock_vault(body: PasswordRequest):
    try:
        vault = load_vault(body.master_password, VAULT_PATH)
    except WrongPasswordError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Wrong master password.")
    except VaultNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="No vault found. POST /api/init first.")
    except VaultCorruptedError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    from backend.core.vault import _read_vault_file
    salt, _ = _read_vault_file(VAULT_PATH)
    _session[SESSION_KEY] = derive_key(body.master_password, salt)
    return {"message": "Vault unlocked.", "entry_count": len(vault.entries)}


@router.post("/lock")
def lock_vault():
    _session.pop(SESSION_KEY, None)
    return {"message": "Vault locked."}


@router.get("/entries")
def list_entries():
    _get_session_key()
    try:
        vault = load_vault_with_key()
        return {"entries": [e.model_dump() for e in vault.entries]}
    except VaultCorruptedError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/entries", status_code=status.HTTP_201_CREATED)
def create_entry(body: EntryCreate):
    _get_session_key()
    entry = PasswordEntry(
        title=body.title,
        username=body.username,
        password=body.password,
        url=body.url,
        notes=body.notes,
        tags=body.tags,
    )
    try:
        saved = _add_entry_with_key(entry)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"entry": saved.model_dump()}


@router.put("/entries/{entry_id}")
def edit_entry(entry_id: str, body: EntryUpdate):
    _get_session_key()
    updated = PasswordEntry(
        title=body.title,
        username=body.username,
        password=body.password,
        url=body.url,
        notes=body.notes,
        tags=body.tags,
    )
    updated.id = entry_id
    found = _update_entry_with_key(updated)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"No entry with id {entry_id}.")
    return {"entry": updated.model_dump()}


@router.delete("/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_entry(entry_id: str):
    _get_session_key()
    found = _delete_entry_with_key(entry_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"No entry with id {entry_id}.")


# ── Helpers using cached session key ──────────────────────────────────────
from backend.core.crypto import encrypt, decrypt
from backend.core.vault import _read_vault_file, _write_vault_file
import json


def _load_vault_raw() -> tuple[bytes, VaultData]:
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