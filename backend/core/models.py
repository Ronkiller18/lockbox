"""
backend/core/models.py

Data models for LockBox vault entries.

Why Pydantic?
- Automatic validation: wrong types raise clear errors, not silent bugs
- Serialization: .model_dump() gives clean dicts for JSON storage
- IDE support: full type hints everywhere
- v2 is ~5-17x faster than v1, ships with FastAPI by default
"""

from datetime import datetime, timezone
from typing import Optional
import uuid

from pydantic import BaseModel, Field, field_validator


def _utcnow() -> datetime:
    """Return current UTC time. Centralised so tests can monkeypatch it."""
    return datetime.now(timezone.utc)


class PasswordEntry(BaseModel):
    """
    A single credential record stored in the vault.

    All fields except `title` and `password` are optional — forcing users
    to fill in URL/notes/username for every entry is annoying and wrong.

    `id` is a UUID4 string (not a UUID object) so it round-trips through
    JSON without a custom serialiser.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    username: Optional[str] = None
    password: str
    url: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, v: str) -> str:
        """Title must not be an empty / whitespace-only string."""
        if not v.strip():
            raise ValueError("title must not be blank")
        return v.strip()

    @field_validator("password")
    @classmethod
    def password_not_blank(cls, v: str) -> str:
        """Password field must not be empty."""
        if not v:
            raise ValueError("password must not be empty")
        return v

    def touch(self) -> None:
        """Update `updated_at` to now. Call this before saving an edit."""
        self.updated_at = _utcnow()

    model_config = {"frozen": False}  # allow .touch() mutations


class VaultData(BaseModel):
    """
    The full decrypted vault: metadata + list of entries.

    This is what gets serialised to JSON, encrypted, and written to disk.
    `version` lets us migrate the schema in future without breaking existing
    vaults (e.g., add a `totp` field in v2).
    """

    version: int = 1
    created_at: datetime = Field(default_factory=_utcnow)
    entries: list[PasswordEntry] = Field(default_factory=list)