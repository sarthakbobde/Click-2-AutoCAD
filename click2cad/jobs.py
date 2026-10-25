"""Job records (SQLite) and per-job folders under data/jobs/<id>/.

Each job folder holds:
    inputs/          uploaded photo(s)
    thumb.jpg        small preview of the first photo
    job.json         what the pipeline needs: prompt, photo file names, provider (+ refine details)
    base_script.py   refinements only: the script being refined
    log.txt          worker output
    script.py        the bpy script the model wrote
    model.obj        the result (+ model.mtl)
"""

from __future__ import annotations

import io
import json
import re
import shutil
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from PIL import Image, ImageOps

from .config import DB_PATH, JOBS_DIR

STATUSES = ("queued", "running", "completed", "failed", "cancelled")
ACTIVE = ("queued", "running")

INPUTS = "inputs"
THUMB = "thumb.jpg"
SPEC = "job.json"
LOG = "log.txt"
SCRIPT = "script.py"
MODEL = "model.obj"
BASE_SCRIPT = "base_script.py"
OUTPUTS = (LOG, SCRIPT, MODEL, "model.mtl")

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    prompt      TEXT NOT NULL DEFAULT '',
    images      TEXT NOT NULL,             -- JSON list of file names in inputs/
    status      TEXT NOT NULL,             -- one of STATUSES
    stage       TEXT,                      -- progress while running: starting | asking | building | exporting
    error       TEXT,
    model       TEXT,                      -- model or deployment used
    attempts    INTEGER NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL,
    started_at  REAL,
    finished_at REAL
);
"""

# Columns added after the first version; existing databases get them on startup.
ADDED_COLUMNS = {
    "provider": "TEXT NOT NULL DEFAULT 'gemini'",  # azure | gemini; earlier jobs all used Gemini
    "parent_id": "TEXT",                           # refinements: the job whose script was refined
    "feedback": "TEXT",                            # refinements: what the user asked to change
}


def validate_image(data: bytes) -> None:
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
    except Exception as exc:
        raise ValueError("not a readable image") from exc


def safe_filename(name: str, index: int) -> str:
    path = Path(name)
    stem = re.sub(r"^\d{2}_", "", path.stem)  # photos copied from another job already carry a prefix
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._") or "photo"
    return f"{index + 1:02d}_{stem[:60]}{path.suffix.lower()}"


def make_thumbnail(src: Path, dest: Path, size: int = 320) -> None:
    with Image.open(src) as image:
        thumb = ImageOps.exif_transpose(image).convert("RGB")
        thumb.thumbnail((size, size))
        thumb.save(dest, "JPEG", quality=85)


class JobStore:
    def __init__(self, db_path: Path = DB_PATH, jobs_dir: Path = JOBS_DIR):
        self.jobs_dir = jobs_dir
        jobs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
        self._db.row_factory = sqlite3.Row
        with self._db:
            self._db.executescript(SCHEMA)
            existing = {row["name"] for row in self._db.execute("PRAGMA table_info(jobs)")}
            for column, ddl in ADDED_COLUMNS.items():
                if column not in existing:
                    self._db.execute(f"ALTER TABLE jobs ADD COLUMN {column} {ddl}")

    def job_dir(self, job_id: str) -> Path:
        return self.jobs_dir / job_id

    def create(
        self,
        name: str,
        prompt: str,
        images: list[tuple[str, bytes]],
        provider: str,
        model: str,
        *,
        status: str = "queued",
        created_at: float | None = None,
        parent_id: str | None = None,
        feedback: str | None = None,
        spec_extra: dict | None = None,
        files: dict[str, bytes] | None = None,
    ) -> dict:
        created_at = created_at or time.time()
        job_id = time.strftime("%Y%m%d-%H%M%S", time.localtime(created_at)) + "-" + uuid.uuid4().hex[:6]
        job_dir = self.job_dir(job_id)
        (job_dir / INPUTS).mkdir(parents=True)

        names = []
        for index, (original, data) in enumerate(images):
            filename = safe_filename(original, index)
            (job_dir / INPUTS / filename).write_bytes(data)
            names.append(filename)
        if names:
            make_thumbnail(job_dir / INPUTS / names[0], job_dir / THUMB)
        for filename, data in (files or {}).items():
            (job_dir / filename).write_bytes(data)
        spec = {"prompt": prompt, "images": names, "provider": provider, **(spec_extra or {})}
        (job_dir / SPEC).write_text(json.dumps(spec, indent=2), encoding="utf-8")

        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO jobs (id, name, prompt, images, status, provider, model, parent_id, feedback, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (job_id, name, prompt, json.dumps(names), status, provider, model, parent_id, feedback, created_at),
            )
        return self.get(job_id)

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _to_dict(row) if row else None

    def list(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
        return [_to_dict(row) for row in rows]

    def update(self, job_id: str, **fields) -> None:
        assignments = ", ".join(f"{column} = ?" for column in fields)
        with self._lock, self._db:
            self._db.execute(f"UPDATE jobs SET {assignments} WHERE id = ?", (*fields.values(), job_id))

    def claim_next(self) -> dict | None:
        """Atomically move the oldest queued job to running and return it."""
        with self._lock, self._db:
            row = self._db.execute(
                "SELECT id FROM jobs WHERE status = 'queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if not row:
                return None
            self._db.execute(
                "UPDATE jobs SET status = 'running', stage = 'starting', error = NULL,"
                " started_at = ?, finished_at = NULL, attempts = attempts + 1 WHERE id = ?",
                (time.time(), row["id"]),
            )
        return self.get(row["id"])

    def cancel_if_queued(self, job_id: str) -> bool:
        with self._lock, self._db:
            cursor = self._db.execute(
                "UPDATE jobs SET status = 'cancelled', stage = NULL, finished_at = ?"
                " WHERE id = ? AND status = 'queued'",
                (time.time(), job_id),
            )
        return cursor.rowcount == 1

    def requeue(self, job_id: str) -> None:
        job_dir = self.job_dir(job_id)
        for name in OUTPUTS:
            (job_dir / name).unlink(missing_ok=True)
        self.update(job_id, status="queued", stage=None, error=None, started_at=None, finished_at=None)

    def requeue_interrupted(self) -> int:
        """Jobs left 'running' by a stopped server go back in the queue."""
        with self._lock, self._db:
            cursor = self._db.execute(
                "UPDATE jobs SET status = 'queued', stage = NULL, started_at = NULL WHERE status = 'running'"
            )
        return cursor.rowcount

    def delete(self, job_id: str) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        shutil.rmtree(self.job_dir(job_id), ignore_errors=True)


def _to_dict(row: sqlite3.Row) -> dict:
    job = dict(row)
    job["images"] = json.loads(job["images"])
    return job
