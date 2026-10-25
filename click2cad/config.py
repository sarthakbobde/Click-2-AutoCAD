"""Paths and settings shared by the web server, the job runner and the CLI."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
JOBS_DIR = DATA_DIR / "jobs"
DB_PATH = DATA_DIR / "click2cad.db"
WEB_DIR = ROOT / "web"
ENV_FILE = ROOT / ".env"

PROVIDERS = {"claude": "AI Model"}  # label shown in the UI


def env(name: str, default: str = "") -> str:
    """A setting from .env, falling back to the process environment.

    .env is re-read on every call, so edits apply to the next job without restarting the server.
    """
    value = dotenv_values(ENV_FILE).get(name) if ENV_FILE.exists() else None
    if not (value or "").strip():
        value = os.environ.get(name, "")
    return value.strip() or default


def default_provider() -> str:
    return "claude"


def claude_mode() -> str:
    """live: Claude, in a Claude Code session next to the app, writes each script (click2cad/claude_session.py).
    api: the Anthropic API writes it (click2cad/claude.py, needs ANTHROPIC_API_KEY)."""
    mode = env("C2C_CLAUDE_MODE", "live").lower()
    return mode if mode in ("live", "api") else "live"


MAX_PARALLEL_JOBS = max(1, int(env("C2C_MAX_PARALLEL_JOBS", "2")))
JOB_TIMEOUT_SECONDS = int(env("C2C_JOB_TIMEOUT_SECONDS", "1800"))
