"""
tests/test_vault.py

Tests for backend/core/models.py and backend/core/vault.py.

Run from project root with:
    source venv/bin/activate
    pytest tests/test_vault.py -v

All tests use tmp_path (pytest's built-in temp directory fixture) so they
never touch your real vault.enc.
"""

import pytest
from pathlib import Path
from datetime import datetime

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

MASTER = "correct-horse-battery-staple"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def vault_path(tmp_path: Path) -> Path:
    """A path inside pytest's temp dir — isolated per test."""
    return tmp_path / "vault.enc"


@pytest.fixture
def initialized_vault(vault_path: Path) -> Path:
    """Create an initialized vault and return its path."""
    initialize_vault(MASTER, vault_path)
    return vault_path


# ── models.py tests ───────────────────────────────────────────────────────────

class TestPasswordEntry:
    def test_creates_with_required_fields(self):
        entry = PasswordEntry(title="GitHub", password="s3cr3t")
        assert entry.title == "GitHub"
        assert entry.password == "s3cr3t"
        assert entry.username is None
        assert entry.url is None

    def test_auto_generates_uuid(self):
        e1 = PasswordEntry(title="A", password="x")
        e2 = PasswordEntry(title="B", password="x")
        assert e1.id != e2.id
        assert len(e1.id) == 36  # UUID4 string length

    def test_blank_title_raises(self):
        with pytest.raises(ValueError, match="blank"):
            PasswordEntry(title="   ", password="x")

    def test_empty_password_raises(self):
        with pytest.raises(ValueError, match="empty"):
            PasswordEntry(title="Test", password="")

    def test_title_is_stripped(self):
        entry = PasswordEntry(title="  GitHub  ", password="x")
        assert entry.title == "GitHub"

    def test_touch_updates_updated_at(self):
        entry = PasswordEntry(title="T", password="x")
        before = entry.updated_at
        # Tiny sleep ensures clock advances — or just force assign
        entry.updated_at = entry.created_at  # set to same as created
        entry.touch()
        # updated_at should now be >= before
        assert entry.updated_at >= before

    def test_timestamps_are_utc(self):
        entry = PasswordEntry(title="T", password="x")
        assert entry.created_at.tzinfo is not None

    def test_optional_fields_accepted(self):
        entry = PasswordEntry(
            title="AWS",
            username="ron",
            password="pw",
            url="https://aws.amazon.com",
            notes="prod account",
        )
        assert entry.username == "ron"
        assert entry.url == "https://aws.amazon.com"
        assert entry.notes == "prod account"


class TestVaultData:
    def test_empty_vault_has_no_entries(self):
        v = VaultData()
        assert v.entries == []
        assert v.version == 1

    def test_vault_accepts_entries(self):
        entry = PasswordEntry(title="T", password="x")
        v = VaultData(entries=[entry])
        assert len(v.entries) == 1


# ── vault.py tests ────────────────────────────────────────────────────────────

class TestInitializeVault:
    def test_creates_file(self, vault_path):
        initialize_vault(MASTER, vault_path)
        assert vault_path.exists()

    def test_file_is_not_empty(self, vault_path):
        initialize_vault(MASTER, vault_path)
        assert vault_path.stat().st_size > 0

    def test_refuses_to_overwrite_existing(self, initialized_vault):
        with pytest.raises(FileExistsError):
            initialize_vault(MASTER, initialized_vault)

    def test_creates_parent_dirs(self, tmp_path):
        deep_path = tmp_path / "a" / "b" / "c" / "vault.enc"
        initialize_vault(MASTER, deep_path)
        assert deep_path.exists()


class TestLoadVault:
    def test_loads_empty_vault(self, initialized_vault):
        vault = load_vault(MASTER, initialized_vault)
        assert isinstance(vault, VaultData)
        assert vault.entries == []

    def test_wrong_password_raises(self, initialized_vault):
        with pytest.raises(WrongPasswordError):
            load_vault("wrong-password", initialized_vault)

    def test_missing_file_raises(self, vault_path):
        with pytest.raises(VaultNotFoundError):
            load_vault(MASTER, vault_path)

    def test_corrupted_file_raises(self, vault_path):
        vault_path.write_bytes(b"\x00\x00\x00\x10" + b"short")
        with pytest.raises((VaultCorruptedError, WrongPasswordError)):
            load_vault(MASTER, vault_path)


class TestAddAndGetEntries:
    def test_add_entry_persists(self, initialized_vault):
        entry = PasswordEntry(title="GitHub", password="gh_token")
        add_entry(entry, MASTER, initialized_vault)

        entries = get_all_entries(MASTER, initialized_vault)
        assert len(entries) == 1
        assert entries[0].title == "GitHub"

    def test_multiple_entries_preserved(self, initialized_vault):
        for name in ("GitHub", "AWS", "Gmail"):
            add_entry(PasswordEntry(title=name, password="x"), MASTER, initialized_vault)

        entries = get_all_entries(MASTER, initialized_vault)
        assert len(entries) == 3
        titles = [e.title for e in entries]
        assert "GitHub" in titles
        assert "AWS" in titles
        assert "Gmail" in titles

    def test_entry_roundtrip_preserves_fields(self, initialized_vault):
        entry = PasswordEntry(
            title="Test",
            username="ron",
            password="s3cr3t",
            url="https://example.com",
            notes="memo",
        )
        add_entry(entry, MASTER, initialized_vault)

        loaded = get_all_entries(MASTER, initialized_vault)[0]
        assert loaded.username == "ron"
        assert loaded.password == "s3cr3t"
        assert loaded.url == "https://example.com"
        assert loaded.notes == "memo"


class TestDeleteEntry:
    def test_delete_removes_entry(self, initialized_vault):
        entry = PasswordEntry(title="ToDelete", password="x")
        add_entry(entry, MASTER, initialized_vault)

        result = delete_entry(entry.id, MASTER, initialized_vault)
        assert result is True
        assert get_all_entries(MASTER, initialized_vault) == []

    def test_delete_nonexistent_returns_false(self, initialized_vault):
        result = delete_entry("fake-uuid", MASTER, initialized_vault)
        assert result is False

    def test_delete_only_removes_target(self, initialized_vault):
        e1 = PasswordEntry(title="Keep", password="x")
        e2 = PasswordEntry(title="Remove", password="x")
        add_entry(e1, MASTER, initialized_vault)
        add_entry(e2, MASTER, initialized_vault)

        delete_entry(e2.id, MASTER, initialized_vault)
        entries = get_all_entries(MASTER, initialized_vault)
        assert len(entries) == 1
        assert entries[0].title == "Keep"


class TestUpdateEntry:
    def test_update_changes_password(self, initialized_vault):
        entry = PasswordEntry(title="Service", password="old")
        add_entry(entry, MASTER, initialized_vault)

        entry.password = "new"
        result = update_entry(entry, MASTER, initialized_vault)
        assert result is True

        loaded = get_all_entries(MASTER, initialized_vault)[0]
        assert loaded.password == "new"

    def test_update_nonexistent_returns_false(self, initialized_vault):
        fake = PasswordEntry(title="Ghost", password="x")
        result = update_entry(fake, MASTER, initialized_vault)
        assert result is False


class TestVaultExists:
    def test_returns_false_when_missing(self, vault_path):
        assert vault_exists(vault_path) is False

    def test_returns_true_after_init(self, initialized_vault):
        assert vault_exists(initialized_vault) is True