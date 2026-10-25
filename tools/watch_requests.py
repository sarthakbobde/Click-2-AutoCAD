"""Live Claude mode: wait until a job is waiting for its script, print it, and exit.

Claude Code runs this in the background. When it exits, Claude answers the listed request(s) and
starts it again. With nothing to answer it exits after --max-minutes (default 9) so the watch can
be renewed.

usage: .venv311\\Scripts\\python.exe tools\\watch_requests.py [--max-minutes 9]
"""

from __future__ import annotations

import argparse
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "click2cad.db"
JOBS = ROOT / "data" / "jobs"


def pending() -> list[tuple[str, str]]:
    if not DB.exists():
        return []
    db = sqlite3.connect(DB, timeout=30)
    try:
        rows = db.execute("SELECT id, name FROM jobs WHERE status = 'running' ORDER BY created_at").fetchall()
    finally:
        db.close()
    return [(job_id, name) for job_id, name in rows
            if (JOBS / job_id / "request.md").exists() and not (JOBS / job_id / "answer.py").exists()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Wait for a live Claude request")
    parser.add_argument("--max-minutes", type=float, default=9)
    args = parser.parse_args()

    deadline = time.time() + args.max_minutes * 60
    while time.time() < deadline:
        found = pending()
        if found:
            for job_id, name in found:
                print(f"REQUEST {job_id} | {name} | {JOBS / job_id / 'request.md'}", flush=True)
            return 0
        time.sleep(2)
    print("NO REQUESTS (watch expired; start it again)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
