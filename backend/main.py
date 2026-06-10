"""
backend/main.py

LockBox FastAPI application entry point.

Run with:
    uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

--host 0.0.0.0  makes it reachable from Android on the same WiFi.
Your phone hits http://<your-linux-ip>:8000 in its browser.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from backend.api.routes import router

app = FastAPI(
    title="LockBox",
    description="Local AES-256 encrypted password manager",
    version="0.1.0",
)

# ── CORS ──────────────────────────────────────────────────────────────────────
# Allows the frontend (served from the same server or a different port during
# dev) to make API calls. Also covers Android browser on local WiFi.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # fine for local-only; tighten if you expose to internet
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API routes ────────────────────────────────────────────────────────────────
app.include_router(router, prefix="/api")

# ── Static frontend ───────────────────────────────────────────────────────────
# Serves your HTML/CSS/JS from the frontend/ directory.
# This must come AFTER the API router so /api/* routes take priority.
frontend_path = Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")