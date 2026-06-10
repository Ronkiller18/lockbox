"""
tests/test_routes.py

Integration tests for the FastAPI routes.

Uses FastAPI's TestClient (wraps httpx) — no real server needed.
Each test gets a fresh tmp vault path via monkeypatching backend.config.VAULT_PATH.

Run with:
    pytest tests/test_routes.py -v
"""

import pytest
from pathlib import Path
from fastapi.testclient import TestClient

import backend.config as config_module
from backend.main import app

client = TestClient(app)
MASTER = "correct-horse-battery-staple"


@pytest.fixture(autouse=True)
def isolated_vault(tmp_path: Path, monkeypatch):
    """
    Point VAULT_PATH at a temp dir for every test.
    autouse=True means this runs automatically for every test in the file.
    Also clears the session so tests don't bleed into each other.
    """
    vault_file = tmp_path / "vault.enc"
    monkeypatch.setattr(config_module, "VAULT_PATH", vault_file)

    # Also patch the imported name inside each module that uses it
    import backend.api.routes as routes_module
    import backend.core.vault as vault_module
    monkeypatch.setattr(routes_module, "VAULT_PATH", vault_file)
    monkeypatch.setattr(vault_module, "VAULT_PATH", vault_file)

    # Clear session between tests
    from backend.api.routes import _session
    _session.clear()

    yield


def _init():
    return client.post("/api/init", json={"master_password": MASTER})


def _unlock():
    return client.post("/api/unlock", json={"master_password": MASTER})


def _init_and_unlock():
    _init()
    _unlock()


# ── /api/status ───────────────────────────────────────────────────────────────

def test_status_no_vault():
    r = client.get("/api/status")
    assert r.status_code == 200
    assert r.json() == {"vault_exists": False, "unlocked": False}


def test_status_after_init():
    _init()
    r = client.get("/api/status")
    assert r.json()["vault_exists"] is True
    assert r.json()["unlocked"] is False


def test_status_after_unlock():
    _init_and_unlock()
    r = client.get("/api/status")
    assert r.json()["unlocked"] is True


# ── /api/init ─────────────────────────────────────────────────────────────────

def test_init_creates_vault():
    r = _init()
    assert r.status_code == 201


def test_init_twice_returns_409():
    _init()
    r = _init()
    assert r.status_code == 409


# ── /api/unlock ───────────────────────────────────────────────────────────────

def test_unlock_correct_password():
    _init()
    r = _unlock()
    assert r.status_code == 200
    assert "entry_count" in r.json()


def test_unlock_wrong_password():
    _init()
    r = client.post("/api/unlock", json={"master_password": "wrong"})
    assert r.status_code == 401


def test_unlock_no_vault():
    r = _unlock()
    assert r.status_code == 404


# ── /api/lock ─────────────────────────────────────────────────────────────────

def test_lock_clears_session():
    _init_and_unlock()
    client.post("/api/lock")
    r = client.get("/api/status")
    assert r.json()["unlocked"] is False


# ── /api/entries GET ──────────────────────────────────────────────────────────

def test_get_entries_requires_unlock():
    _init()
    r = client.get("/api/entries")
    assert r.status_code == 401


def test_get_entries_empty():
    _init_and_unlock()
    r = client.get("/api/entries")
    assert r.status_code == 200
    assert r.json()["entries"] == []


# ── /api/entries POST ─────────────────────────────────────────────────────────

def test_create_entry():
    _init_and_unlock()
    r = client.post("/api/entries", json={
        "title": "GitHub",
        "username": "ron",
        "password": "gh_token",
        "url": "https://github.com",
        "notes": "",
    })
    assert r.status_code == 201
    entry = r.json()["entry"]
    assert entry["title"] == "GitHub"
    assert "id" in entry


def test_created_entry_persists():
    _init_and_unlock()
    client.post("/api/entries", json={"title": "AWS", "password": "secret"})
    r = client.get("/api/entries")
    assert len(r.json()["entries"]) == 1
    assert r.json()["entries"][0]["title"] == "AWS"


def test_create_entry_requires_unlock():
    _init()
    r = client.post("/api/entries", json={"title": "T", "password": "x"})
    assert r.status_code == 401


# ── /api/entries PUT ──────────────────────────────────────────────────────────

def test_update_entry():
    _init_and_unlock()
    create_r = client.post("/api/entries", json={"title": "Old", "password": "old"})
    entry_id = create_r.json()["entry"]["id"]

    r = client.put(f"/api/entries/{entry_id}", json={
        "title": "New", "password": "new"
    })
    assert r.status_code == 200
    assert r.json()["entry"]["title"] == "New"
    assert r.json()["entry"]["password"] == "new"


def test_update_nonexistent_returns_404():
    _init_and_unlock()
    r = client.put("/api/entries/fake-uuid", json={"title": "T", "password": "x"})
    assert r.status_code == 404


# ── /api/entries DELETE ───────────────────────────────────────────────────────

def test_delete_entry():
    _init_and_unlock()
    create_r = client.post("/api/entries", json={"title": "ToDelete", "password": "x"})
    entry_id = create_r.json()["entry"]["id"]

    r = client.delete(f"/api/entries/{entry_id}")
    assert r.status_code == 204

    entries = client.get("/api/entries").json()["entries"]
    assert entries == []


def test_delete_nonexistent_returns_404():
    _init_and_unlock()
    r = client.delete("/api/entries/fake-uuid")
    assert r.status_code == 404