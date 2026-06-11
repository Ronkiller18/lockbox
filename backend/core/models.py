"""
backend/core/models.py — updated with tags support
"""

from datetime import datetime, timezone
from typing import Optional
import uuid

from pydantic import BaseModel, Field, field_validator


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PasswordEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    username: Optional[str] = None
    password: str
    url: Optional[str] = None
    notes: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("title must not be blank")
        return v.strip()

    @field_validator("password")
    @classmethod
    def password_not_blank(cls, v: str) -> str:
        if not v:
            raise ValueError("password must not be empty")
        return v

    def touch(self) -> None:
        self.updated_at = _utcnow()

    model_config = {"frozen": False}


class VaultData(BaseModel):
    version: int = 1
    created_at: datetime = Field(default_factory=_utcnow)
    entries: list[PasswordEntry] = Field(default_factory=list)